"""Shared request dependencies.

The ordering here is the security-critical part: a session is opened with no
tenant bound, the bearer token is verified, and only then is the tenant context
applied. Any route that forgets to depend on `CurrentUser` therefore operates
on a session that row level security has already closed off.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AuthenticationError,
    NotFound,
    OrganizationInactive,
    PermissionDenied,
    SessionExpired,
    ValidationFailed,
)
from app.core.security import TokenError, decode_access_token
from app.db.session import get_session
from app.db.tenancy import TenantContext, bind_tenant
from app.models.auth import SessionFamily
from app.models.enums import OrgStatus, UserRole, UserStatus
from app.models.organization import Organization
from app.models.user import User

DbSession = Annotated[AsyncSession, Depends(get_session)]


@dataclass(slots=True)
class Actor:
    """Everything a route needs to know about who is calling."""

    user: User
    org: Organization | None
    session_id: uuid.UUID
    scope: str

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def org_id(self) -> uuid.UUID | None:
        return self.user.org_id

    @property
    def role(self) -> UserRole:
        return self.user.role

    @property
    def is_super_admin(self) -> bool:
        return self.user.role == UserRole.SUPER_ADMIN

    def require_role(self, *allowed: UserRole) -> None:
        if self.user.role not in allowed:
            raise PermissionDenied()

    def require_at_least(self, minimum: UserRole) -> None:
        if not self.user.role.at_least(minimum):
            raise PermissionDenied()

    def assert_owns(self, created_by_id: uuid.UUID | None) -> None:
        """Ownership gate for a manager's own cycles/campaigns.

        Client Admin and Super Admin see and act on everything in the org, per
        policy. A Manager is scoped to what *they* run — not another
        manager's, not the Client Admin's — so this only bites for the
        Manager role; everyone above it is exempt. A record with no creator
        recorded (a pre-existing row, or one seeded before this existed) is
        treated as visible/actionable rather than orphaned and unreachable.
        """
        if self.user.role.at_least(UserRole.CLIENT_ADMIN):
            return
        if created_by_id is not None and created_by_id != self.id:
            raise PermissionDenied()

    def assert_can_reach_org(self, org_id: uuid.UUID) -> None:
        """Guard for routes that take an org id in the path.

        RLS already blocks the read, but failing here returns a clean 403
        instead of a confusing empty result, and it keeps the intent explicit
        at the call site.
        """
        if self.is_super_admin:
            return
        if self.org_id != org_id:
            raise PermissionDenied()


async def rebind_tenant(session: AsyncSession, actor: "Actor") -> None:
    """Re-apply the tenant context after a commit.

    The GUCs that drive row level security are set with `is_local => true`, so
    they are scoped to a transaction — which is exactly what stops them leaking
    onto the next request that borrows the same pooled connection. The
    consequence is that committing mid-handler drops the context, and any query
    afterwards silently returns zero rows.

    Any handler that commits and then keeps reading must call this. It is the
    one sharp edge of transaction-local tenancy, and it fails safe: the symptom
    is missing data, never another tenant's data.
    """
    await bind_tenant(
        session,
        TenantContext(org_id=actor.org_id, is_super_admin=actor.is_super_admin),
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError()
    return authorization.split(" ", 1)[1].strip()


async def get_actor(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Actor:
    try:
        claims = decode_access_token(_bearer_token(authorization))
    except TokenError as exc:
        raise SessionExpired() if str(exc) == "expired" else AuthenticationError() from exc

    # Bind the tenant before any ORM read, so every query below is already
    # constrained by the database rather than by the code that follows.
    await bind_tenant(
        session,
        TenantContext(
            org_id=claims.org_id,
            is_super_admin=claims.role == str(UserRole.SUPER_ADMIN),
        ),
    )

    # An access token stays valid for its full lifetime, but a revoked session
    # must not. Checking the family here caps the blast radius of a stolen
    # access token at the token TTL, which is why that TTL is 15 minutes.
    family = (
        await session.execute(
            select(SessionFamily).where(SessionFamily.id == claims.session_id)
        )
    ).scalar_one_or_none()
    if family is None or family.revoked_at is not None:
        raise SessionExpired()

    user = (
        await session.execute(select(User).where(User.id == claims.sub))
    ).scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        raise SessionExpired()

    org: Organization | None = None
    if user.org_id is not None:
        org = (
            await session.execute(
                select(Organization).where(Organization.id == user.org_id)
            )
        ).scalar_one_or_none()
        if org is None or org.status != OrgStatus.ACTIVE:
            raise OrganizationInactive()

    request.state.actor_id = str(user.id)
    request.state.org_id = str(user.org_id) if user.org_id else None
    return Actor(user=user, org=org, session_id=claims.session_id, scope=claims.scope)


async def get_current_user(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
    """Full-scope actor. Rejects a token still waiting on an MFA code."""
    if actor.scope != "full":
        raise AuthenticationError("Finish signing in before using this endpoint.")
    return actor


async def get_mfa_pending_user(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
    """Actor for the MFA challenge endpoints only."""
    return actor


CurrentUser = Annotated[Actor, Depends(get_current_user)]
MfaPendingUser = Annotated[Actor, Depends(get_mfa_pending_user)]


async def require_super_admin(actor: CurrentUser) -> Actor:
    actor.require_role(UserRole.SUPER_ADMIN)
    return actor


async def require_admin(actor: CurrentUser) -> Actor:
    """Super Admin or Client Admin."""
    actor.require_at_least(UserRole.CLIENT_ADMIN)
    return actor


async def require_manager(actor: CurrentUser) -> Actor:
    actor.require_at_least(UserRole.MANAGER)
    return actor


SuperAdmin = Annotated[Actor, Depends(require_super_admin)]
AdminUser = Annotated[Actor, Depends(require_admin)]
ManagerUser = Annotated[Actor, Depends(require_manager)]


# --- Acting organization -----------------------------------------------
#
# A Client Admin or Manager belongs to exactly one org — actor.org_id already
# names it, no choice involved. A Super Admin belongs to none (org_id is
# always NULL, enforced by ck_users_super_admin_has_no_org), so creating
# anything org-scoped — a cycle, a campaign, a proposal — has nothing to
# attach to unless they explicitly say which organization they mean.
#
# This is that explicit statement: the frontend's org selector sends
# X-Acting-Org-Id, and every route that creates or lists one of those
# org-scoped things should depend on ActingOrg instead of reading
# actor.org_id directly.


@dataclass(slots=True)
class ActingContext:
    """The organization an org-scoped operation actually applies to."""

    org_id: uuid.UUID
    org: Organization


async def get_acting_org(
    session: DbSession,
    actor: CurrentUser,
    x_acting_org_id: Annotated[str | None, Header()] = None,
) -> ActingContext:
    if not actor.is_super_admin:
        # get_actor() already loaded and validated this as ACTIVE.
        assert actor.org is not None
        return ActingContext(org_id=actor.org_id, org=actor.org)

    if not x_acting_org_id:
        raise ValidationFailed(
            "Select an organization to act within — a Super Admin has no "
            "organization of their own."
        )
    try:
        org_id = uuid.UUID(x_acting_org_id)
    except ValueError as exc:
        raise ValidationFailed("That is not a valid organization id.") from exc

    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None or org.status != OrgStatus.ACTIVE:
        raise NotFound("That organization does not exist or is not active.")

    # Rebind as though we genuinely were that org's own actor — not as a
    # super admin with an org_id set alongside. If is_super_admin stayed
    # 'on' here, the OR clause in every RLS policy would still let anything
    # through regardless of org_id, and the boundary would only be as
    # strong as this one query remembering to filter correctly. Rebinding
    # False means the database itself refuses a mistake here too, not just
    # this code.
    await bind_tenant(session, TenantContext(org_id=org.id, is_super_admin=False))
    return ActingContext(org_id=org.id, org=org)


ActingOrg = Annotated[ActingContext, Depends(get_acting_org)]