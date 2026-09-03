"""Authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import (
    AuthenticationError,
    Conflict,
    InvalidCredentials,
    NotFound,
    SessionExpired,
    ValidationFailed,
)
from app.core.security import (
    generate_token,
    hash_token,
    verify_csrf,
    verify_password,
)
from app.db.tenancy import TenantContext, bind_tenant
from app.models.auth import SessionFamily
from app.models.enums import AuditAction, UserStatus
from app.models.organization import Organization
from app.models.user import Invitation, PasswordResetToken, User
from app.schemas.auth import (
    AcceptInviteRequest,
    ActiveSession,
    BrandingSummary,
    ForgotPasswordRequest,
    LoginRequest,
    OrgSummary,
    PasswordChangeRequest,
    PasswordResetCompleteRequest,
    SessionResponse,
    UserSummary,
)
from app.schemas.common import MessageResponse
from app.services import audit, auth as auth_service, email as email_service
from app.services.auth import CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Cookie plumbing --------------------------------------------------------

def _set_session_cookies(response: Response, issued: auth_service.IssuedSession) -> None:
    max_age = int(settings.refresh_token_ttl_seconds)
    common = {
        "max_age": max_age,
        "secure": settings.cookie_secure,
        # Strict rather than Lax: this cookie is only ever sent to our own
        # refresh endpoint by our own app, never as part of a top-level
        # navigation, so there is no usability cost to the stricter setting.
        "samesite": "strict",
        "path": "/",
    }
    if settings.cookie_domain:
        common["domain"] = settings.cookie_domain

    response.set_cookie(REFRESH_COOKIE, issued.refresh_token, httponly=True, **common)
    # Readable by JavaScript on purpose: the client must echo it back in a
    # header, which is the half of the double-submit check that a cross-site
    # attacker cannot perform.
    response.set_cookie(CSRF_COOKIE, issued.csrf_token, httponly=False, **common)


def _clear_session_cookies(response: Response) -> None:
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.cookie_domain or None,
            secure=settings.cookie_secure,
            samesite="strict",
        )


def _logo_url(org: Organization | None) -> str | None:
    if org is None or org.branding is None or not org.branding.logo_path:
        return None
    return f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"


def _org_summary(org: Organization | None) -> OrgSummary | None:
    if org is None:
        return None
    return OrgSummary(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=str(org.status),
        timezone=org.timezone,
        plan=str(org.plan),
        branding=BrandingSummary(
            accent_color=org.branding.accent_color if org.branding else "#B4633A",
            logo_url=_logo_url(org),
        ),
    )


# --- Sign in ----------------------------------------------------------------

@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> SessionResponse:
    principal = await auth_service.authenticate(
        session, email=payload.email, password=payload.password, request=request
    )

    issued = await auth_service.start_session(session, principal, request=request)
    _set_session_cookies(response, issued)

    await bind_tenant(session, principal.tenant_context())
    user = (await session.execute(select(User).where(User.id == principal.id))).scalar_one()
    org = None
    if user.org_id:
        org = (
            await session.execute(
                select(Organization).where(Organization.id == user.org_id)
            )
        ).scalar_one_or_none()

    await audit.record(
        session,
        action=AuditAction.AUTH_LOGIN_SUCCEEDED,
        summary=f"{user.full_name} signed in",
        org_id=user.org_id,
        actor=user,
        context={"method": "password", "session_id": str(issued.session_id)},
        request=request,
    )
    await session.commit()

    return SessionResponse(
        access_token=issued.access_token,
        expires_at=issued.access_expires_at,
        csrf_token=issued.csrf_token,
        user=UserSummary.model_validate(user),
        organization=_org_summary(org),
    )


@router.post("/refresh", response_model=SessionResponse)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
) -> SessionResponse:
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if not raw_refresh:
        raise SessionExpired()

    if not verify_csrf(request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)):
        raise AuthenticationError("Missing or invalid CSRF token.")

    principal, issued = await auth_service.rotate_session(
        session, raw_refresh=raw_refresh, request=request
    )
    _set_session_cookies(response, issued)

    await bind_tenant(session, principal.tenant_context())
    user = (await session.execute(select(User).where(User.id == principal.id))).scalar_one()
    org = None
    if user.org_id:
        org = (
            await session.execute(
                select(Organization).where(Organization.id == user.org_id)
            )
        ).scalar_one_or_none()
    await session.commit()

    return SessionResponse(
        access_token=issued.access_token,
        expires_at=issued.access_expires_at,
        csrf_token=issued.csrf_token,
        user=UserSummary.model_validate(user),
        organization=_org_summary(org),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    session: DbSession,
    actor: CurrentUser,
) -> MessageResponse:
    await auth_service.revoke_session(session, session_id=actor.session_id, reason="logout")
    await audit.record(
        session,
        action=AuditAction.AUTH_LOGOUT,
        summary=f"{actor.user.full_name} signed out",
        org_id=actor.org_id,
        actor=actor.user,
        request=request,
    )
    await session.commit()
    _clear_session_cookies(response)
    return MessageResponse(message="Signed out.")


# --- Current identity -------------------------------------------------------

@router.get("/me", response_model=SessionResponse)
async def me(actor: CurrentUser) -> SessionResponse:
    """Rehydrate the client after a page reload.

    Returns the profile only; a new access token comes from /refresh.
    """
    return SessionResponse(
        access_token="",
        expires_at=datetime.now(UTC),
        csrf_token="",
        user=UserSummary.model_validate(actor.user),
        organization=_org_summary(actor.org),
    )


@router.get("/sessions", response_model=list[ActiveSession])
async def list_sessions(session: DbSession, actor: CurrentUser) -> list[ActiveSession]:
    families = (
        (
            await session.execute(
                select(SessionFamily)
                .where(
                    SessionFamily.user_id == actor.id,
                    SessionFamily.revoked_at.is_(None),
                )
                .order_by(SessionFamily.last_used_at.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )
    return [
        ActiveSession(
            id=family.id,
            device_label=family.device_label,
            user_agent=family.user_agent,
            ip_address=str(family.ip_address) if family.ip_address else None,
            created_at=family.created_at,
            last_used_at=family.last_used_at,
            is_current=family.id == actor.session_id,
        )
        for family in families
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def revoke_one_session(
    session_id: str,
    request: Request,
    session: DbSession,
    actor: CurrentUser,
) -> MessageResponse:
    import uuid as _uuid

    target = _uuid.UUID(session_id)
    family = (
        await session.execute(
            select(SessionFamily).where(
                SessionFamily.id == target, SessionFamily.user_id == actor.id
            )
        )
    ).scalar_one_or_none()
    if family is None:
        raise NotFound("That session does not exist.")

    await auth_service.revoke_session(session, session_id=target, reason="user_revoked")
    await audit.record(
        session,
        action=AuditAction.AUTH_SESSION_REVOKED,
        summary=f"{actor.user.full_name} revoked a session",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="session_family",
        target_id=target,
        request=request,
    )
    await session.commit()
    return MessageResponse(message="Session revoked.")


# --- Password ---------------------------------------------------------------

@router.post("/password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    session: DbSession,
    actor: CurrentUser,
) -> MessageResponse:
    if not verify_password(payload.current_password, actor.user.password_hash):
        raise InvalidCredentials("Your current password is incorrect.")
    if payload.new_password == payload.current_password:
        raise ValidationFailed(
            "Your new password must be different from your current password.",
            password=["must be different from your current password"],
        )

    await auth_service.set_password(session, actor.user, new_password=payload.new_password)

    # Changing a password invalidates every other device. If the reason for the
    # change was a suspected compromise, leaving those sessions alive would
    # defeat the point of changing it.
    revoked = await auth_service.revoke_all_sessions(
        session, user_id=actor.id, reason="password_changed", except_id=actor.session_id
    )
    await audit.record(
        session,
        action=AuditAction.AUTH_PASSWORD_CHANGED,
        summary=f"{actor.user.full_name} changed their password",
        org_id=actor.org_id,
        actor=actor.user,
        context={"other_sessions_revoked": revoked},
        request=request,
    )
    await session.commit()
    return MessageResponse(
        message=f"Password updated. {revoked} other session(s) were signed out."
    )


@router.post("/accept-invite", response_model=MessageResponse)
async def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    session: DbSession,
) -> MessageResponse:
    """Complete an invitation by setting a password.

    Runs before authentication, so the invitation row is located by token hash
    with the super-admin context bound for exactly this lookup. The token is
    256 bits of entropy and single use, which is what makes that acceptable.
    """
    await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

    invite = (
        await session.execute(
            select(Invitation).where(Invitation.token_hash == hash_token(payload.token))
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if invite is None or not invite.is_open or invite.expires_at <= now:
        raise NotFound("That invitation link is no longer valid.")

    user = (
        await session.execute(
            select(User).where(User.org_id == invite.org_id, User.email == invite.email)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That invitation link is no longer valid.")
    if user.status == UserStatus.ACTIVE:
        raise Conflict("This invitation has already been used.")

    await auth_service.set_password(session, user, new_password=payload.password)
    if payload.full_name:
        user.full_name = payload.full_name
    user.status = UserStatus.ACTIVE
    invite.accepted_at = now

    await audit.record(
        session,
        action=AuditAction.USER_ACTIVATED,
        summary=f"{user.full_name} accepted their invitation",
        org_id=invite.org_id,
        actor=user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    await session.commit()
    return MessageResponse(message="Your account is ready. You can sign in now.")


@router.post("/reset-password", response_model=MessageResponse)
async def complete_password_reset(
    payload: PasswordResetCompleteRequest,
    request: Request,
    session: DbSession,
) -> MessageResponse:
    """Complete an admin-initiated password reset.

    Same before-authentication token lookup as accept-invite, and the same
    reasoning applies: 256 bits of entropy in a single-use, hashed, expiring
    token is what makes looking it up under a platform-context bind safe.
    """
    await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

    reset = (
        await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_token(payload.token)
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if reset is None or not reset.is_open or reset.expires_at <= now:
        raise NotFound("That password reset link is no longer valid.")

    user = (
        await session.execute(select(User).where(User.id == reset.user_id))
    ).scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotFound("That password reset link is no longer valid.")

    await auth_service.set_password(session, user, new_password=payload.password)
    reset.used_at = now
    # A reset already revokes sessions when requested; revoking again here is
    # a no-op for the common case and a correctness guard for the rare one
    # where a session was somehow re-established in between.
    await auth_service.revoke_all_sessions(
        session, user_id=user.id, reason="password_reset_completed"
    )

    await audit.record(
        session,
        action=AuditAction.USER_PASSWORD_RESET_COMPLETED,
        summary=f"{user.full_name} completed a password reset",
        org_id=reset.org_id,
        actor=user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    await session.commit()
    return MessageResponse(message="Your password has been reset. You can sign in now.")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
) -> MessageResponse:
    """Self-service equivalent of the admin "reset password" action.

    Always returns the same message whether or not the email matches an
    account — telling an anonymous caller "no such account" turns this into
    an account-enumeration tool, so the response is identical either way and
    the real signal (an email, or nothing) only ever reaches the mailbox.
    """
    await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

    user = (
        await session.execute(
            select(User).where(User.email == payload.email.lower())
        )
    ).scalar_one_or_none()

    if user is not None and user.status == UserStatus.ACTIVE:
        org = (
            await session.execute(select(Organization).where(Organization.id == user.org_id))
        ).scalar_one_or_none()
        raw_token = generate_token()
        ttl_hours = 4
        session.add(
            PasswordResetToken(
                org_id=user.org_id,
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
            )
        )
        await auth_service.revoke_all_sessions(
            session, user_id=user.id, reason="password_reset_requested"
        )
        await audit.record(
            session,
            action=AuditAction.USER_PASSWORD_RESET_REQUESTED,
            summary=f"{user.full_name} requested a password reset",
            org_id=user.org_id,
            actor=user,
            target_type="user",
            target_id=user.id,
            target_label=user.email,
            request=request,
        )
        await session.commit()

        reset_url = f"{settings.public_app_url}/reset-password?token={raw_token}"
        background_tasks.add_task(
            email_service.send_password_reset,
            to=user.email,
            full_name=user.full_name,
            org_name=org.name if org else "",
            reset_url=reset_url,
            expires_in_hours=ttl_hours,
            branding=email_service.Branding(
                org_name=org.name if org else settings.product_name,
                accent_color=org.branding.accent_color if org and org.branding else "#B4633A",
                logo_url=(
                    f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
                    if org and org.branding and org.branding.logo_path
                    else None
                ),
                footer_note=org.branding.email_footer_note if org and org.branding else None,
            ),
        )

    return MessageResponse(
        message="If that email matches an account, a reset link is on its way."
    )

