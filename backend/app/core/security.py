"""Cryptographic primitives: password hashing, tokens, JWTs.

Nothing in this module talks to the database or to FastAPI. Keeping it pure
means the security-critical code can be reasoned about, and unit tested,
without standing up an application.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# --- Password hashing -------------------------------------------------------

# OWASP-aligned argon2id parameters: 64 MiB memory, 3 passes, 4 lanes. Memory
# cost is what makes GPU cracking expensive, so it is the parameter to raise
# first if hardware improves.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# A real argon2 hash of a throwaway value. Verifying against this when the user
# does not exist keeps the failure path the same cost as the success path, so
# response timing does not reveal which email addresses are registered.
_DUMMY_HASH = _hasher.hash("facet-timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time password check that tolerates a missing hash."""
    if not password_hash:
        # Burn the same CPU we would have burned on a real verification.
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        return False
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than we now require."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --- Opaque tokens ----------------------------------------------------------

TOKEN_BYTES = 32  # 256 bits of entropy


def generate_token() -> str:
    """A URL-safe secret suitable for refresh tokens, invites, feedback links."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """SHA-256 of an opaque token.

    A fast hash is the right choice for high-entropy random tokens: there is no
    dictionary to attack, and these are verified on hot paths. Passwords, which
    are low entropy and human-chosen, use argon2 above.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --- JSON Web Tokens --------------------------------------------------------

ALGORITHM = "HS256"
ISSUER = "facet"


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    sub: uuid.UUID
    org_id: uuid.UUID | None
    role: str
    session_id: uuid.UUID
    jti: uuid.UUID
    expires_at: datetime
    scope: str


def create_access_token(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    role: str,
    session_id: uuid.UUID,
    scope: str = "full",
    ttl_minutes: int | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    expires_at = now + timedelta(minutes=ttl)
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "role": role,
        "sid": str(session_id),
        "scope": scope,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), expires_at


class TokenError(Exception):
    """Raised when an access token is absent, malformed, or expired."""


def decode_access_token(token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid") from exc

    org_raw = payload.get("org")
    return AccessTokenClaims(
        sub=uuid.UUID(payload["sub"]),
        org_id=uuid.UUID(org_raw) if org_raw else None,
        role=payload["role"],
        session_id=uuid.UUID(payload["sid"]),
        jti=uuid.UUID(payload["jti"]),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        scope=payload.get("scope", "full"),
    )


# --- CSRF -------------------------------------------------------------------

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def verify_csrf(header_value: str | None, cookie_value: str | None) -> bool:
    """Double-submit check.

    The refresh token lives in a SameSite=Strict httpOnly cookie, so a browser
    will not attach it to a cross-site request in the first place. This is the
    second layer, for the case where a future deployment has to relax SameSite
    for an embedded surface.
    """
    if not header_value or not cookie_value:
        return False
    return hmac.compare_digest(header_value, cookie_value)
