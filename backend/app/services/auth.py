"""Authentication and session lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    AccountDisabled,
    AccountLocked,
    AuthenticationError,
    InvalidCredentials,
    OrganizationInactive,
    SessionExpired,
    TokenReuseDetected,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.ratelimit import (
    LOGIN_PER_ACCOUNT,
    LOGIN_PER_IP,
    limiter,
)
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.tenancy import TenantContext
from app.models.auth import LoginAttempt, RefreshToken, SessionFamily
from app.models.enums import AuditAction, OrgStatus, UserRole, UserStatus
from app.models.user import User
from app.services import audit

log = get_logger("facet.auth")

REFRESH_COOKIE = "facet_rt"
CSRF_COOKIE = "facet_csrf"
CSRF_HEADER = "x-facet-csrf"


@dataclass(slots=True)
class Principal:
    """The minimal identity resolved before a tenant is bound."""

    id: uuid.UUID
    org_id: uuid.UUID | None
    email: str
    full_name: str
    role: UserRole
    status: UserStatus
    password_hash: str | None
    must_change_password: bool
    failed_login_count: int
    locked_until: datetime | None
    org_status: OrgStatus | None

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    def tenant_context(self) -> TenantContext:
        return TenantContext(org_id=self.org_id, is_super_admin=self.is_super_admin)


@dataclass(slots=True)
class IssuedSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    csrf_token: str
    session_id: uuid.UUID


# --- Principal lookup -------------------------------------------------------

_PRINCIPAL_SQL = text(
    "SELECT * FROM facet_auth_principal(:user_id, :email)"
).bindparams()


async def load_principal(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
) -> Principal | None:
    """Resolve an identity without a tenant bound.

    Goes through the SECURITY DEFINER function documented in migration 0002,
    which is the only sanctioned way to read `users` outside a tenant context.
    """
    row = (
        await session.execute(
            _PRINCIPAL_SQL, {"user_id": user_id, "email": email}
        )
    ).mappings().first()
    if row is None:
        return None
    return Principal(
        id=row["id"],
        org_id=row["org_id"],
        email=row["email"],
        full_name=row["full_name"],
        role=UserRole(row["role"]),
        status=UserStatus(row["status"]),
        password_hash=row["password_hash"],
        must_change_password=row["must_change_password"],
        failed_login_count=row["failed_login_count"],
        locked_until=row["locked_until"],
        org_status=OrgStatus(row["org_status"]) if row["org_status"] else None,
    )


async def _record_attempt(
    session: AsyncSession,
    *,
    email: str,
    principal: Principal | None,
    succeeded: bool,
    reason: str | None,
    request: Request | None,
) -> None:
    session.add(
        LoginAttempt(
            email=email.lower(),
            user_id=principal.id if principal else None,
            succeeded=succeeded,
            failure_reason=reason,
            ip_address=audit.client_ip(request),
            user_agent=request.headers.get("user-agent") if request else None,
            occurred_at=datetime.now(UTC),
        )
    )
    if principal is not None:
        await session.execute(
            text(
                "SELECT facet_auth_record_attempt("
                ":user_id, :succeeded, :lock_seconds, :max_attempts)"
            ),
            {
                "user_id": principal.id,
                "succeeded": succeeded,
                "lock_seconds": settings.login_lockout_seconds,
                "max_attempts": settings.login_max_attempts,
            },
        )


# --- Password policy --------------------------------------------------------

_COMMON_SUBSTRINGS = ("password", "qwerty", "letmein", "welcome", "admin", "123456")


def validate_password_strength(password: str, *, email: str = "", name: str = "") -> None:
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"must be at least {settings.password_min_length} characters")
    lowered = password.lower()
    if any(token in lowered for token in _COMMON_SUBSTRINGS):
        problems.append("must not contain a common word such as 'password'")
    local_part = email.split("@")[0].lower() if email else ""
    if local_part and len(local_part) > 3 and local_part in lowered:
        problems.append("must not contain your email address")
    for part in (name or "").lower().split():
        if len(part) > 3 and part in lowered:
            problems.append("must not contain your name")
            break
    # Length beats character-class rules for real-world strength, so a long
    # passphrase is accepted without symbols. Short passwords must work harder.
    if len(password) < 16:
        classes = sum(
            [
                any(c.islower() for c in password),
                any(c.isupper() for c in password),
                any(c.isdigit() for c in password),
                any(not c.isalnum() for c in password),
            ]
        )
        if classes < 3:
            problems.append(
                "must mix upper case, lower case, digits or symbols "
                "(or simply be 16+ characters)"
            )
    if problems:
        raise ValidationFailed(
            "That password is not strong enough.", password=problems
        )


async def is_password_breached(password: str) -> bool:
    """k-anonymity check against Have I Been Pwned.

    Only the first five characters of the SHA-1 hash leave the server, so the
    password itself is never disclosed. Fails open: a third-party outage must
    not stop people setting a password.
    """
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={"Add-Padding": "true"},
            )
            response.raise_for_status()
    except Exception:  # noqa: BLE001 - availability must not block sign-up
        log.warning("hibp_check_unavailable")
        return False
    for line in response.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix and int(count or 0) > 0:
            return True
    return False


# --- Login ------------------------------------------------------------------

async def authenticate(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    request: Request | None = None,
) -> Principal:
    ip = audit.client_ip(request) or "unknown"
    await limiter.hit(f"login:ip:{ip}", LOGIN_PER_IP)
    await limiter.hit(f"login:acct:{email.lower()}", LOGIN_PER_ACCOUNT)

    principal = await load_principal(session, email=email)

    # Verify unconditionally, even for an unknown account, so the response time
    # does not reveal whether the email exists.
    password_ok = verify_password(
        password, principal.password_hash if principal else None
    )

    if principal is None or not password_ok:
        await _record_attempt(
            session,
            email=email,
            principal=principal,
            succeeded=False,
            reason="bad_password" if principal else "unknown_account",
            request=request,
        )
        await audit.record(
            session,
            action=AuditAction.AUTH_LOGIN_FAILED,
            summary=f"Failed sign-in for {email}",
            org_id=principal.org_id if principal else None,
            actor_email=email,
            request=request,
        )
        await session.commit()
        raise InvalidCredentials()

    now = datetime.now(UTC)
    if principal.locked_until and principal.locked_until > now:
        await _record_attempt(
            session, email=email, principal=principal,
            succeeded=False, reason="locked", request=request,
        )
        await session.commit()
        raise AccountLocked()

    if principal.status != UserStatus.ACTIVE:
        await _record_attempt(
            session, email=email, principal=principal,
            succeeded=False, reason=f"status_{principal.status}", request=request,
        )
        await session.commit()
        # The password already matched at this point, so telling a disabled
        # user their account is disabled (rather than the generic "email or
        # password is incorrect") does not create an account-enumeration
        # oracle — it only ever fires for someone who already knows the
        # correct password.
        if principal.status == UserStatus.DISABLED:
            raise AccountDisabled()
        raise InvalidCredentials()

    # A suspended or unapproved tenant must not be able to sign in, even with
    # correct credentials. Super Admins have no org and skip this check.
    if not principal.is_super_admin and principal.org_status != OrgStatus.ACTIVE:
        await _record_attempt(
            session, email=email, principal=principal,
            succeeded=False, reason=f"org_{principal.org_status}", request=request,
        )
        await session.commit()
        raise OrganizationInactive()

    await _record_attempt(
        session, email=email, principal=principal,
        succeeded=True, reason=None, request=request,
    )
    return principal


# --- Sessions ---------------------------------------------------------------

async def start_session(
    session: AsyncSession,
    principal: Principal,
    *,
    request: Request | None = None,
) -> IssuedSession:
    now = datetime.now(UTC)
    family = SessionFamily(
        user_id=principal.id,
        org_id=principal.org_id,
        user_agent=(request.headers.get("user-agent") if request else None),
        ip_address=audit.client_ip(request),
        # expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
        last_used_at=now,
    )
    session.add(family)
    await session.flush()

    raw_refresh = generate_token()
    session.add(
        RefreshToken(
            family_id=family.id,
            token_hash=hash_token(raw_refresh),
            generation=1,
            expires_at=family.expires_at,
        )
    )

    access, access_exp = create_access_token(
        user_id=principal.id,
        org_id=principal.org_id,
        role=str(principal.role),
        session_id=family.id,
        scope="full",
    )
    return IssuedSession(
        access_token=access,
        access_expires_at=access_exp,
        refresh_token=raw_refresh,
        csrf_token=generate_csrf_token(),
        session_id=family.id,
    )


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh: str,
    request: Request | None = None,
) -> tuple[Principal, IssuedSession]:
    """Exchange a refresh token for a new pair, detecting reuse.

    See the module docstring on models/auth.py for why reuse kills the family
    rather than merely rejecting the request.
    """
    token = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh))
        )
    ).scalar_one_or_none()

    if token is None:
        raise SessionExpired()

    family = (
        await session.execute(
            select(SessionFamily).where(SessionFamily.id == token.family_id)
        )
    ).scalar_one()

    now = datetime.now(UTC)

    if token.rotated_at is not None:
        # This token was already exchanged. A well-behaved client never does
        # this, so the token has been captured. Kill every generation in the
        # family: the attacker loses access and the victim is forced to sign
        # in again, which is the signal that something happened.
        await _revoke_family(session, family, reason="token_reuse")
        await audit.record(
            session,
            action=AuditAction.AUTH_TOKEN_REUSE_DETECTED,
            summary="Refresh token reuse detected; all sessions in the family revoked",
            org_id=family.org_id,
            target_type="session_family",
            target_id=family.id,
            context={"generation": token.generation},
            request=request,
        )
        await session.commit()
        raise TokenReuseDetected()

    if family.revoked_at is not None or family.expires_at <= now or token.expires_at <= now:
        raise SessionExpired()

    principal = await load_principal(session, user_id=family.user_id)
    if principal is None or principal.status != UserStatus.ACTIVE:
        await _revoke_family(session, family, reason="user_inactive")
        await session.commit()
        raise SessionExpired()
    if not principal.is_super_admin and principal.org_status != OrgStatus.ACTIVE:
        await _revoke_family(session, family, reason="org_inactive")
        await session.commit()
        raise OrganizationInactive()

    token.rotated_at = now
    token.used_at = now
    family.last_used_at = now

    raw_refresh_new = generate_token()
    session.add(
        RefreshToken(
            family_id=family.id,
            token_hash=hash_token(raw_refresh_new),
            generation=token.generation + 1,
            expires_at=family.expires_at,
        )
    )

    access, access_exp = create_access_token(
        user_id=principal.id,
        org_id=principal.org_id,
        role=str(principal.role),
        session_id=family.id,
        scope="full",
    )
    issued = IssuedSession(
        access_token=access,
        access_expires_at=access_exp,
        refresh_token=raw_refresh_new,
        csrf_token=generate_csrf_token(),
        session_id=family.id,
    )
    return principal, issued


async def _revoke_family(
    session: AsyncSession, family: SessionFamily, *, reason: str
) -> None:
    now = datetime.now(UTC)
    family.revoked_at = now
    family.revoked_reason = reason
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family.id, RefreshToken.rotated_at.is_(None))
        .values(rotated_at=now)
    )


async def revoke_session(
    session: AsyncSession, *, session_id: uuid.UUID, reason: str = "logout"
) -> None:
    family = (
        await session.execute(
            select(SessionFamily).where(SessionFamily.id == session_id)
        )
    ).scalar_one_or_none()
    if family and family.revoked_at is None:
        await _revoke_family(session, family, reason=reason)


async def revoke_all_sessions(
    session: AsyncSession, *, user_id: uuid.UUID, reason: str, except_id: uuid.UUID | None = None
) -> int:
    families = (
        (
            await session.execute(
                select(SessionFamily).where(
                    SessionFamily.user_id == user_id,
                    SessionFamily.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for family in families:
        if except_id and family.id == except_id:
            continue
        await _revoke_family(session, family, reason=reason)
        count += 1
    return count


async def set_password(
    session: AsyncSession,
    user: User,
    *,
    new_password: str,
    check_breach: bool = True,
) -> None:
    validate_password_strength(new_password, email=user.email, name=user.full_name)
    if check_breach and await is_password_breached(new_password):
        raise ValidationFailed(
            "That password has appeared in a known data breach. Choose a different one.",
            password=["appears in a public breach corpus"],
        )
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = False


def require_full_scope(scope: str) -> None:
    if scope != "full":
        raise AuthenticationError("Finish signing in before using this endpoint.")
