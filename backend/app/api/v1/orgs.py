"""Organization onboarding, approval, and branding (Modules D and E)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, File, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, CurrentUser, DbSession, SuperAdmin
from app.core.config import settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ratelimit import REGISTRATION_PER_IP, limiter
from app.core.security import generate_token, hash_token
from app.db.tenancy import TenantContext, bind_tenant
from app.models.enums import (
    AuditAction,
    OrgRegistrationSource,
    OrgStatus,
    UserRole,
    UserStatus,
)
from app.models.organization import OrgBranding, Organization
from app.models.user import Invitation, User
from app.schemas.common import MessageResponse, Page
from app.schemas.org import (
    BrandingDetail,
    BrandingUpdateRequest,
    OrgApprovalRequest,
    OrgDetail,
    OrgInviteAdminRequest,
    OrgProvisionRequest,
    OrgReactivateRequest,
    OrgRegistrationRequest,
    OrgRejectionRequest,
    OrgStatusChangeRequest,
    OrgUpdateRequest,
)
from app.services import audit, email as email_service, storage

router = APIRouter(prefix="/orgs", tags=["organizations"])


@router.get("/check-email")
async def check_email(email: str, session: DbSession, actor: SuperAdmin) -> dict[str, bool]:
    """Field-level availability check for the client-admin email on the
    create/approve org forms — lets the UI flag a duplicate before submit
    rather than only after, given email is unique platform-wide (see
    migration 0013)."""
    taken = (
        await session.execute(select(User.id).where(func.lower(User.email) == email.strip().lower()))
    ).first() is not None
    return {"available": not taken}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "org")[:60]


async def _unique_slug(session: DbSession, desired: str) -> str:
    base = _slugify(desired)
    candidate = base
    suffix = 2
    while (
        await session.execute(select(Organization.id).where(Organization.slug == candidate))
    ).first() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _logo_url(org: Organization) -> str | None:
    if org.branding and org.branding.logo_path:
        version = (
            int(org.branding.logo_updated_at.timestamp())
            if org.branding.logo_updated_at
            else 0
        )
        return f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo?v={version}"
    return None


def _detail(org: Organization, user_count: int = 0) -> OrgDetail:
    return OrgDetail(
        id=org.id,
        name=org.name,
        slug=org.slug,
        legal_name=org.legal_name,
        primary_domain=org.primary_domain,
        status=str(org.status),
        registration_source=str(org.registration_source),
        contact_name=org.contact_name,
        contact_email=org.contact_email,
        contact_phone=org.contact_phone,
        country=org.country,
        timezone=org.timezone,
        seat_limit=org.seat_limit,
        approved_at=org.approved_at,
        rejection_reason=org.rejection_reason,
        suspension_reason=org.suspension_reason,
        created_at=org.created_at,
        user_count=user_count,
        branding=(
            BrandingDetail(
                accent_color=org.branding.accent_color,
                email_footer_note=org.branding.email_footer_note,
                logo_url=_logo_url(org),
                logo_updated_at=org.branding.logo_updated_at,
            )
            if org.branding
            else None
        ),
    )


async def _invite_admin(
    session: DbSession,
    *,
    org: Organization,
    full_name: str,
    email: str,
    role: UserRole,
    invited_by: User | None,
) -> tuple[User, str]:
    """Create an invited user and a single-use activation token.

    No pre-check SELECT here on purpose: RLS restricts this session to its
    own org's rows, so a query scoped to `org.id` could never see a
    duplicate sitting in a different organization anyway. The platform-wide
    unique index on email (migration 0013) is the actual source of truth —
    this just turns its violation into a clean error instead of a raw
    IntegrityError reaching the caller.
    """
    user = User(
        org_id=org.id,
        email=email.lower(),
        full_name=full_name,
        role=role,
        status=UserStatus.INVITED,
    )
    session.add(user)

    raw_token = generate_token()
    session.add(
        Invitation(
            org_id=org.id,
            email=email.lower(),
            full_name=full_name,
            role=role,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=settings.invite_token_ttl_hours),
            invited_by_id=invited_by.id if invited_by else None,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_users_email" in str(exc.orig):
            raise Conflict(
                "Someone with that email already has an account on the platform."
            ) from exc
        raise
    return user, raw_token


# --- Public self-registration ----------------------------------------------

@router.post("/register", response_model=MessageResponse, status_code=201)
async def self_register(
    payload: OrgRegistrationRequest,
    request: Request,
    session: DbSession,
) -> MessageResponse:
    """Anonymous tenant sign-up. Lands in `pending` awaiting Super Admin review.

    No user account is created here. Creating credentials before a human has
    approved the organization would mean an unreviewed stranger holds a working
    login on the platform.
    """
    await limiter.hit(
        f"register:{audit.client_ip(request) or 'unknown'}", REGISTRATION_PER_IP
    )
    await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

    existing_user = (
        await session.execute(
            select(User.id).where(func.lower(User.email) == payload.contact_email.lower())
        )
    ).first()
    if existing_user is not None:
        raise Conflict(
            "That email already has an account on the platform. Sign in "
            "instead, or use a different contact email for this registration."
        )

    org = Organization(
        name=payload.name.strip(),
        slug=await _unique_slug(session, payload.name),
        status=OrgStatus.PENDING,
        registration_source=OrgRegistrationSource.SELF_SERVICE,
        contact_name=payload.contact_name.strip(),
        contact_email=payload.contact_email.lower(),
        contact_phone=payload.contact_phone,
        country=payload.country.upper() if payload.country else None,
        timezone=payload.timezone or "UTC",
        primary_domain=payload.primary_domain,
    )
    session.add(org)
    await session.flush()
    session.add(OrgBranding(org_id=org.id))

    await audit.record(
        session,
        action=AuditAction.ORG_REGISTERED,
        summary=f"{org.name} registered and is awaiting approval",
        org_id=org.id,
        actor_email=org.contact_email,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"source": "self_service"},
        request=request,
    )
    await session.commit()

    return MessageResponse(
        message=(
            "Thank you. Your registration is with our team for review, and the "
            "primary contact will receive an email once it is approved."
        )
    )


# --- Super Admin: tenant lifecycle -----------------------------------------

@router.get("", response_model=Page[OrgDetail])
async def list_organizations(
    session: DbSession,
    actor: SuperAdmin,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> Page[OrgDetail]:
    counts = (
        select(User.org_id, func.count().label("n"))
        .where(User.status != UserStatus.DELETED)
        .group_by(User.org_id)
        .subquery()
    )
    stmt = (
        select(Organization, func.coalesce(counts.c.n, 0))
        .join(counts, counts.c.org_id == Organization.id, isouter=True)
    )
    if status:
        stmt = stmt.where(Organization.status == status)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(Organization.name.ilike(term) | Organization.slug.ilike(term))

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
    )
    stmt = (
        stmt.order_by(Organization.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).all()
    return Page[OrgDetail](
        items=[_detail(org, count) for org, count in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=OrgDetail, status_code=201)
async def provision_organization(
    payload: OrgProvisionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    """Super Admin direct provisioning: active immediately, no approval step.

    The organization has already been vetted by the person creating it, so a
    second approval by the same person would be theatre.
    """
    now = datetime.now(UTC)
    org = Organization(
        name=payload.name.strip(),
        slug=await _unique_slug(session, payload.slug or payload.name),
        status=OrgStatus.ACTIVE,
        registration_source=OrgRegistrationSource.PROVISIONED,
        contact_name=payload.contact_name.strip(),
        contact_email=payload.contact_email.lower(),
        contact_phone=payload.contact_phone,
        country=payload.country.upper() if payload.country else None,
        timezone=payload.timezone or "UTC",
        primary_domain=payload.primary_domain,
        seat_limit=payload.seat_limit,
        approved_at=now,
        approved_by_id=actor.id,
    )
    session.add(org)
    await session.flush()
    branding = OrgBranding(org_id=org.id)
    session.add(branding)
    org.branding = branding

    admin, raw_token = await _invite_admin(
        session,
        org=org,
        full_name=payload.admin_full_name,
        email=payload.admin_email,
        role=UserRole.CLIENT_ADMIN,
        invited_by=actor.user,
    )

    await audit.record(
        session,
        action=AuditAction.ORG_APPROVED,
        summary=f"{actor.user.full_name} provisioned {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"source": "provisioned", "admin_email": admin.email},
        request=request,
    )
    await session.commit()

    invite_url = f"{settings.public_app_url}/accept-invite?token={raw_token}"
    # Scheduled after commit, so the response returns as soon as the org
    # exists — a slow or unreachable SMTP server should never make the
    # person clicking "Provision" sit and wait for it.
    #
    # kind is left at its default ("invitation") here: the Super Admin
    # vetted and created this org directly, so the recipient never submitted
    # a request of their own — this is a plain "you've been given access"
    # email, not an approval of anything they asked for.
    background_tasks.add_task(
        email_service.send_invitation,
        to=admin.email,
        full_name=admin.full_name,
        org_name=org.name,
        invite_url=invite_url,
        branding=email_service.Branding(org_name=org.name),
    )
    # Never returned to the caller, in any environment: whoever is
    # provisioning this org must not be able to activate the new admin's
    # account themselves — only the person who actually receives the email
    # can. See InviteResult.invite_url for the same reasoning applied to
    # per-user invites.
    return _detail(org, user_count=1)


@router.get("/{org_id}", response_model=OrgDetail)
async def get_organization(
    org_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> OrgDetail:
    actor.assert_can_reach_org(org_id)
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    count = int(
        (
            await session.execute(
                                select(func.count()).select_from(User).where(
                    User.org_id == org_id, User.status != UserStatus.DELETED
                )
            )
        ).scalar_one()
    )
    return _detail(org, count)


@router.patch("/{org_id}", response_model=OrgDetail)
async def update_organization(
    org_id: uuid.UUID,
    payload: OrgUpdateRequest,
    request: Request,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    """Edit an organization's profile — name, contact details, timezone, seats.

    Super Admin only: a Client Admin edits their own org through branding and
    settings, neither of which touches these platform-recorded fields (they
    are what the Super Admin used to vet the tenant in the first place).
    """
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")

    changes: dict[str, list] = {}
    for field in ("name", "contact_name", "contact_phone", "country", "timezone"):
        new_value = getattr(payload, field)
        if field == "contact_phone":
            new_value = new_value or None
        if field == "country":
            new_value = new_value.upper() if new_value else None
        old_value = getattr(org, field)
        if new_value != old_value:
            changes[field] = [old_value, new_value]
            setattr(org, field, new_value)

    new_email = payload.contact_email.lower()
    if new_email != org.contact_email:
        changes["contact_email"] = [org.contact_email, new_email]
        org.contact_email = new_email

    if payload.seat_limit != org.seat_limit:
        changes["seat_limit"] = [org.seat_limit, payload.seat_limit]
        org.seat_limit = payload.seat_limit

    if changes:
        await audit.record(
            session,
            action=AuditAction.ORG_PROFILE_UPDATED,
            summary=f"{actor.user.full_name} updated {org.name}'s profile",
            org_id=org.id,
            actor=actor.user,
            target_type="organization",
            target_id=org.id,
            target_label=org.name,
            context={"changes": changes},
            request=request,
        )
        await session.commit()

    count = int(
        (
            await session.execute(
                select(func.count()).select_from(User).where(User.org_id == org_id)
            )
        ).scalar_one()
    )
    return _detail(org, count)


@router.post("/{org_id}/approve", response_model=OrgDetail)
async def approve_organization(
    org_id: uuid.UUID,
    payload: OrgApprovalRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    if org.status not in {OrgStatus.PENDING, OrgStatus.REJECTED}:
        raise Conflict(f"This organization is already {org.status}.")

    org.status = OrgStatus.ACTIVE
    org.approved_at = datetime.now(UTC)
    org.approved_by_id = actor.id
    org.rejection_reason = None
    if payload.seat_limit:
        org.seat_limit = payload.seat_limit

    admin, raw_token = await _invite_admin(
        session,
        org=org,
        full_name=payload.admin_full_name,
        email=payload.admin_email,
        role=UserRole.CLIENT_ADMIN,
        invited_by=actor.user,
    )

    await audit.record(
        session,
        action=AuditAction.ORG_APPROVED,
        summary=f"{actor.user.full_name} approved {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"admin_email": admin.email, "note": payload.note},
        request=request,
    )
    await session.commit()

    invite_url = f"{settings.public_app_url}/accept-invite?token={raw_token}"
    # This is the one path where the recipient initiated the request
    # themselves (the public "Request access" self-registration form) and a
    # Super Admin has now reviewed and approved it — so it gets the
    # "approval" copy rather than the default "you've been invited" one.
    background_tasks.add_task(
        email_service.send_invitation,
        to=admin.email,
        full_name=admin.full_name,
        org_name=org.name,
        invite_url=invite_url,
        branding=email_service.Branding(org_name=org.name),
        kind="approval",
    )
    # Never returned to the caller, in any environment — see the matching
    # comment in provision_organization above.
    return _detail(org, user_count=1)


@router.post("/{org_id}/reject", response_model=OrgDetail)
async def reject_organization(
    org_id: uuid.UUID,
    payload: OrgRejectionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    if org.status != OrgStatus.PENDING:
        raise Conflict("Only a pending organization can be rejected.")

    org.status = OrgStatus.REJECTED
    org.rejection_reason = payload.reason
    await audit.record(
        session,
        action=AuditAction.ORG_REJECTED,
        summary=f"{actor.user.full_name} rejected {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"reason": payload.reason},
        request=request,
    )
    await session.commit()

    # Scheduled after commit, same reasoning as approve_organization above:
    # the response should not wait on a slow or unreachable SMTP server.
    background_tasks.add_task(
        email_service.send_org_rejected,
        to=org.contact_email,
        org_name=org.name,
        contact_name=org.contact_name,
        rejection_reason=payload.reason,
        branding=email_service.Branding(org_name=org.name),
    )
    return _detail(org)


@router.post("/{org_id}/suspend", response_model=OrgDetail)
async def suspend_organization(
    org_id: uuid.UUID,
    payload: OrgStatusChangeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")

    org.status = OrgStatus.SUSPENDED
    org.suspension_reason = payload.reason

    from app.services.auth import revoke_all_sessions

    members = (
        (await session.execute(select(User.id).where(User.org_id == org_id)))
        .scalars()
        .all()
    )
    revoked = 0
    for member_id in members:
        revoked += await revoke_all_sessions(
            session, user_id=member_id, reason="org_suspended"
        )

    await audit.record(
        session,
        action=AuditAction.ORG_SUSPENDED,
        summary=f"{actor.user.full_name} suspended {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"reason": payload.reason, "sessions_revoked": revoked},
        request=request,
    )
    await session.commit()

    # Sessions are already revoked by this point, so the email correctly
    # describes something that has already happened, not something pending.
    background_tasks.add_task(
        email_service.send_org_suspended,
        to=org.contact_email,
        org_name=org.name,
        contact_name=org.contact_name,
        suspension_reason=payload.reason,
        branding=email_service.Branding(org_name=org.name),
    )
    return _detail(org)


@router.post("/{org_id}/reactivate", response_model=OrgDetail)
async def reactivate_organization(
    org_id: uuid.UUID,
    payload: OrgReactivateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    if org.status != OrgStatus.SUSPENDED:
        raise Conflict("Only a suspended organization can be reactivated.")

    org.status = OrgStatus.ACTIVE
    org.suspension_reason = None
    await audit.record(
        session,
        action=AuditAction.ORG_REACTIVATED,
        summary=f"{actor.user.full_name} reactivated {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"reason": payload.reason},
        request=request,
    )
    await session.commit()

    # Same after-commit background pattern as suspend_organization above:
    # the org is already active by this point, so the email correctly
    # describes something that has already happened.
    background_tasks.add_task(
        email_service.send_organization_reactivated,
        to=org.contact_email,
        org_name=org.name,
        contact_name=org.contact_name,
        branding=email_service.Branding(org_name=org.name),
    )
    return _detail(org)


@router.post("/{org_id}/invite-admin", response_model=OrgDetail, status_code=201)
async def invite_org_admin(
    org_id: uuid.UUID,
    payload: OrgInviteAdminRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: SuperAdmin,
) -> OrgDetail:
    """Add a new Client Admin to an already-active organization.

    The third path to a Client Admin, alongside approve_organization
    (pending -> active) and provision_organization (create-time admin
    fields) — this one is reachable only from an active org's Edit popup,
    never from the create-org flow, and can be used more than once (e.g. a
    second Client Admin for the same tenant). Reuses `_invite_admin`, the
    same helper the other two paths call, so the invitation email and audit
    shape are identical.
    """
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    if org.status != OrgStatus.ACTIVE:
        raise Conflict("Client Admins can only be added to an active organization.")

    admin, raw_token = await _invite_admin(
        session,
        org=org,
        full_name=payload.full_name,
        email=payload.email,
        role=UserRole.CLIENT_ADMIN,
        invited_by=actor.user,
    )

    await audit.record(
        session,
        action=AuditAction.ORG_APPROVED,
        summary=f"{actor.user.full_name} added Client Admin {admin.email} to {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"admin_email": admin.email, "source": "invite_admin_from_edit"},
        request=request,
    )
    await session.commit()

    invite_url = f"{settings.public_app_url}/accept-invite?token={raw_token}"
    # Default "invitation" copy: this is an existing org's admin adding a
    # colleague, not a self-registration being approved.
    background_tasks.add_task(
        email_service.send_invitation,
        to=admin.email,
        full_name=admin.full_name,
        org_name=org.name,
        invite_url=invite_url,
        branding=email_service.Branding(org_name=org.name),
    )

    count = int(
        (
            await session.execute(
                select(func.count()).select_from(User).where(User.org_id == org_id)
            )
        ).scalar_one()
    )
    return _detail(org, count)


# --- Branding (Module E) ----------------------------------------------------

@router.put("/{org_id}/branding", response_model=BrandingDetail)
async def update_branding(
    org_id: uuid.UUID,
    payload: BrandingUpdateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> BrandingDetail:
    actor.assert_can_reach_org(org_id)
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")

    branding = org.branding
    if branding is None:
        branding = OrgBranding(org_id=org.id)
        session.add(branding)
        org.branding = branding

    if payload.accent_color:
        branding.accent_color = payload.accent_color.upper()
    if payload.email_footer_note is not None:
        branding.email_footer_note = payload.email_footer_note or None

    await audit.record(
        session,
        action=AuditAction.ORG_BRANDING_UPDATED,
        summary=f"{actor.user.full_name} updated branding for {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"accent_color": branding.accent_color},
        request=request,
    )
    await session.commit()
    return BrandingDetail(
        accent_color=branding.accent_color,
        email_footer_note=branding.email_footer_note,
        logo_url=_logo_url(org),
        logo_updated_at=branding.logo_updated_at,
    )


@router.post("/{org_id}/logo", response_model=BrandingDetail)
async def upload_logo(
    org_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
    file: UploadFile = File(...),
) -> BrandingDetail:
    actor.assert_can_reach_org(org_id)
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")

    data = await file.read()
    if not data:
        raise ValidationFailed("The uploaded file is empty.")
    content_type = storage.validate_logo(data, file.content_type or "")
    relative = storage.store_logo(org.id, data, content_type)

    branding = org.branding
    if branding is None:
        branding = OrgBranding(org_id=org.id)
        session.add(branding)
        org.branding = branding
    branding.logo_path = relative
    branding.logo_content_type = content_type
    branding.logo_updated_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.ORG_BRANDING_UPDATED,
        summary=f"{actor.user.full_name} uploaded a new logo for {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"content_type": content_type, "bytes": len(data)},
        request=request,
    )
    await session.commit()

    return BrandingDetail(
        accent_color=branding.accent_color,
        email_footer_note=branding.email_footer_note,
        logo_url=_logo_url(org),
        logo_updated_at=branding.logo_updated_at,
    )


@router.delete("/{org_id}/logo", response_model=BrandingDetail)
async def remove_logo(
    org_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> BrandingDetail:
    actor.assert_can_reach_org(org_id)
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    if org.branding is None or not org.branding.logo_path:
        raise NotFound("This organization has no logo to remove.")

    storage.delete_logo(org.branding.logo_path)
    org.branding.logo_path = None
    org.branding.logo_content_type = None
    org.branding.logo_updated_at = None

    await audit.record(
        session,
        action=AuditAction.ORG_BRANDING_UPDATED,
        summary=f"{actor.user.full_name} removed the logo for {org.name}",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"removed": "logo"},
        request=request,
    )
    await session.commit()

    return BrandingDetail(
        accent_color=org.branding.accent_color,
        email_footer_note=org.branding.email_footer_note,
        logo_url=None,
        logo_updated_at=None,
    )


@router.get("/{org_id}/logo")
async def get_logo(org_id: uuid.UUID, session: DbSession) -> Response:
    """Deliberately unauthenticated.

    The same logo has to render on feedback forms for external respondents, who
    by design have no session at all. An <img> tag cannot send an Authorization
    header either. A company logo is public-facing material, so the only thing
    gained by gating it would be a broken image on every respondent form.
    """
    await bind_tenant(session, TenantContext(org_id=org_id, is_super_admin=False))
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None or org.branding is None or not org.branding.logo_path:
        raise NotFound("This organization has not uploaded a logo.")

    result = storage.read_logo(org.branding.logo_path)
    if result is None:
        raise NotFound("The logo file is missing.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "cache-control": "private, max-age=300",
            "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
            "x-content-type-options": "nosniff",
        },
    )