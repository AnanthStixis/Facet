"""User management within an organization."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.security import generate_token, hash_token
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.organization import Organization
from app.models.user import Invitation, PasswordResetToken, User
from app.schemas.common import MessageResponse, Page
from app.schemas.org import InviteResult, UserCreateRequest, UserDetail, UserUpdateRequest
from app.schemas.settings import OrgSettings
from app.services import audit, auth as auth_service, email as email_service
from app.services.bulk_import import BulkRowError, parse_csv

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserDetail])
async def list_users(
    session: DbSession,
    actor: CurrentUser,
    search: str | None = None,
    role: UserRole | None = None,
    status: UserStatus | None = None,
    page: int = 1,
    page_size: int = 25,
) -> Page[UserDetail]:
    stmt = select(User)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            User.full_name.ilike(term)
            | User.email.ilike(term)
            | User.department.ilike(term)
        )
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
    )
    stmt = (
        stmt.order_by(User.full_name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = (await session.execute(stmt)).scalars().all()

    # A Client Admin only ever sees their own org's users (RLS), so the name
    # would just repeat on every row — not worth a query. A Super Admin's
    # list spans every tenant at once, and without this a Super Admin has no
    # way to tell whose employee a given row even is before, say, disabling
    # the wrong organization's account by mistake.
    org_names: dict[uuid.UUID, str] = {}
    if actor.is_super_admin:
        org_ids = {user.org_id for user in users if user.org_id is not None}
        if org_ids:
            rows = await session.execute(
                select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
            )
            org_names = dict(rows.all())

    items = []
    for user in users:
        detail = UserDetail.model_validate(user)
        detail.org_name = org_names.get(user.org_id) if user.org_id else None
        items.append(detail)

    return Page[UserDetail](items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=InviteResult, status_code=201)
async def invite_user(
    payload: UserCreateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> InviteResult:
    org_id = actor.org_id
    if org_id is None:
        raise ValidationFailed(
            "A Super Admin must act within an organization to invite a user."
        )

    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one()

    if org.seat_limit is not None:
        used = int(
            (
                await session.execute(
                    select(func.count()).select_from(User).where(User.org_id == org_id)
                )
            ).scalar_one()
        )
        if used >= org.seat_limit:
            raise Conflict(
                f"This organization has used all {org.seat_limit} of its seats."
            )

    email = payload.email.lower()
    if (
        await session.execute(
            select(User.id).where(User.org_id == org_id, User.email == email)
        )
    ).first() is not None:
        raise Conflict("Someone with that email already exists in this organization.")

    user = User(
        org_id=org_id,
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        job_title=payload.job_title,
        department=payload.department,
        manager_id=payload.manager_id,
        status=UserStatus.INVITED,
    )
    session.add(user)

    raw_token = generate_token()
    session.add(
        Invitation(
            org_id=org_id,
            email=email,
            full_name=user.full_name,
            role=payload.role,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.invite_token_ttl_hours),
            invited_by_id=actor.id,
        )
    )
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.USER_INVITED,
        summary=f"{actor.user.full_name} invited {user.email} as {payload.role}",
        org_id=org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        context={"role": str(payload.role)},
        request=request,
    )
    await session.commit()

    invite_url = f"{settings.public_app_url}/accept-invite?token={raw_token}"
    branding = email_service.Branding(
        org_name=org.name,
        accent_color=org.branding.accent_color if org.branding else "#B4633A",
        logo_url=(
            f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
            if org.branding and org.branding.logo_path
            else None
        ),
        footer_note=org.branding.email_footer_note if org.branding else None,
    )
    sent = await email_service.send_invitation(
        to=user.email,
        full_name=user.full_name,
        org_name=org.name,
        invite_url=invite_url,
        branding=branding,
        subject_template=OrgSettings.load(org.settings).email.invitation_subject,
    )

    return InviteResult(
        user=UserDetail.model_validate(user),
        # Returned only in non-production so an admin can complete onboarding
        # when no mail transport is configured. Never exposed in production,
        # where it would be a bearer credential sitting in an API response.
        invite_url=invite_url if not settings.is_production else None,
        email_sent=sent,
    )


@router.get("/bulk/template")
async def users_bulk_template(actor: AdminUser) -> StreamingResponse:
    """A starter CSV so the columns a bulk invite expects are never guessed."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["full_name", "email", "role", "job_title", "department"])
    writer.writerow(["Jane Doe", "jane.doe@example.com", "employee", "Engineer", "Product"])
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"content-disposition": "attachment; filename=user_invite_template.csv"},
    )


@router.post("/bulk")
async def bulk_invite_users(
    request: Request,
    session: DbSession,
    actor: AdminUser,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Invite many people at once from a CSV export of the directory.

    Each row is treated exactly like a single invite: same seat-limit check,
    same duplicate-email check, same audit entry, same invitation email. A row
    that cannot be invited is skipped with a reason rather than aborting the
    whole file, so one bad row in a 200-row sheet does not block the other 199.
    """
    if actor.org_id is None:
        raise ValidationFailed(
            "A Super Admin must act within an organization to invite users."
        )

    raw = await file.read()
    try:
        rows = parse_csv(raw, required=["full_name", "email"])
    except BulkRowError as exc:
        raise ValidationFailed(str(exc)) from exc

    org = (
        await session.execute(select(Organization).where(Organization.id == actor.org_id))
    ).scalar_one()
    invitation_subject = OrgSettings.load(org.settings).email.invitation_subject

    invited: list[str] = []
    skipped: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        email = row.get("email", "").lower()
        full_name = row.get("full_name", "")
        if not email or not full_name:
            skipped.append({"row": index, "reason": "Missing name or email"})
            continue

        role_raw = (row.get("role") or "employee").lower()
        try:
            role = UserRole(role_raw)
        except ValueError:
            skipped.append(
                {"row": index, "email": email, "reason": f"Unknown role '{role_raw}'"}
            )
            continue
        if role == UserRole.SUPER_ADMIN:
            skipped.append(
                {"row": index, "email": email, "reason": "Cannot bulk-invite a Super Admin"}
            )
            continue

        if org.seat_limit is not None:
            used = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(User)
                        .where(User.org_id == actor.org_id)
                    )
                ).scalar_one()
            )
            if used >= org.seat_limit:
                skipped.append({"row": index, "email": email, "reason": "Seat limit reached"})
                continue

        exists = (
            await session.execute(
                select(User.id).where(User.org_id == actor.org_id, User.email == email)
            )
        ).first()
        if exists is not None:
            skipped.append({"row": index, "email": email, "reason": "Already exists"})
            continue

        user = User(
            org_id=actor.org_id,
            email=email,
            full_name=full_name,
            role=role,
            job_title=row.get("job_title") or None,
            department=row.get("department") or None,
            status=UserStatus.INVITED,
        )
        session.add(user)

        raw_token = generate_token()
        session.add(
            Invitation(
                org_id=actor.org_id,
                email=email,
                full_name=full_name,
                role=role,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=settings.invite_token_ttl_hours),
                invited_by_id=actor.id,
            )
        )
        await session.flush()

        await audit.record(
            session,
            action=AuditAction.USER_INVITED,
            summary=f"{actor.user.full_name} bulk-invited {email} as {role}",
            org_id=actor.org_id,
            actor=actor.user,
            target_type="user",
            target_id=user.id,
            target_label=email,
            context={"role": str(role), "source": "bulk_csv"},
            request=request,
        )

        invite_url = f"{settings.public_app_url}/accept-invite?token={raw_token}"
        branding = email_service.Branding(
            org_name=org.name,
            accent_color=org.branding.accent_color if org.branding else "#B4633A",
            logo_url=(
                f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
                if org.branding and org.branding.logo_path
                else None
            ),
            footer_note=org.branding.email_footer_note if org.branding else None,
        )
        await email_service.send_invitation(
            to=email,
            full_name=full_name,
            org_name=org.name,
            invite_url=invite_url,
            branding=branding,
            subject_template=invitation_subject,
        )
        invited.append(email)

    await session.commit()
    return {"invited": len(invited), "skipped": skipped, "total_rows": len(rows)}


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> UserDetail:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That user does not exist.")

    changes: dict[str, list] = {}
    if payload.full_name is not None and payload.full_name != user.full_name:
        changes["full_name"] = [user.full_name, payload.full_name]
        user.full_name = payload.full_name
    if payload.job_title is not None:
        user.job_title = payload.job_title
    if payload.department is not None:
        user.department = payload.department
    if payload.manager_id is not None:
        if payload.manager_id == user.id:
            raise ValidationFailed("A person cannot be their own manager.")
        user.manager_id = payload.manager_id

    role_changed = payload.role is not None and payload.role != user.role
    if role_changed:
        if user.id == actor.id:
            # Otherwise the last Client Admin in a tenant can demote themselves
            # and leave the organization with nobody able to administer it.
            raise PermissionDenied("You cannot change your own role.")
        changes["role"] = [str(user.role), str(payload.role)]
        user.role = payload.role

    await audit.record(
        session,
        action=(
            AuditAction.USER_ROLE_CHANGED if role_changed else AuditAction.USER_INVITED
        ),
        summary=(
            f"{actor.user.full_name} changed {user.email}'s role to {user.role}"
            if role_changed
            else f"{actor.user.full_name} updated {user.email}"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        context={"changes": changes},
        request=request,
    )
    await session.commit()
    return UserDetail.model_validate(user)


@router.post("/{user_id}/disable", response_model=MessageResponse)
async def disable_user(
    user_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> MessageResponse:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That user does not exist.")
    if user.id == actor.id:
        raise PermissionDenied("You cannot disable your own account.")

    user.status = UserStatus.DISABLED
    # Disabling must end access immediately, not at token expiry.
    revoked = await auth_service.revoke_all_sessions(
        session, user_id=user.id, reason="user_disabled"
    )

    await audit.record(
        session,
        action=AuditAction.USER_DISABLED,
        summary=f"{actor.user.full_name} disabled {user.email}",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        context={"sessions_revoked": revoked},
        request=request,
    )
    await session.commit()
    return MessageResponse(message=f"{user.email} can no longer sign in.")


@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Send an existing user a single-use link to set a new password.

    Nobody with admin access ever learns or sets the new password itself —
    the same principle as the invitation flow. Existing sessions are revoked
    immediately, not when the link is used, since a reset is most often
    requested because the current credential is no longer trusted.
    """
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That user does not exist.")
    if user.status != UserStatus.ACTIVE:
        raise Conflict("Only an active user can be sent a password reset link.")

    # The target user's org, not the actor's — a Super Admin resetting a
    # password has no org of their own and is acting on someone else's.
    org = (
        await session.execute(select(Organization).where(Organization.id == user.org_id))
    ).scalar_one()

    raw_token = generate_token()
    ttl_hours = 4
    session.add(
        PasswordResetToken(
            org_id=user.org_id,
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
            requested_by_id=actor.id,
        )
    )
    revoked = await auth_service.revoke_all_sessions(
        session, user_id=user.id, reason="password_reset_requested"
    )

    await audit.record(
        session,
        action=AuditAction.USER_PASSWORD_RESET_REQUESTED,
        summary=f"{actor.user.full_name} sent {user.email} a password reset link",
        org_id=user.org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        context={"sessions_revoked": revoked},
        request=request,
    )
    await session.commit()

    reset_url = f"{settings.public_app_url}/reset-password?token={raw_token}"
    background_tasks.add_task(
        email_service.send_password_reset,
        to=user.email,
        full_name=user.full_name,
        org_name=org.name,
        reset_url=reset_url,
        expires_in_hours=ttl_hours,
        branding=email_service.Branding(
            org_name=org.name,
            accent_color=org.branding.accent_color if org.branding else "#B4633A",
            logo_url=(
                f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
                if org.branding and org.branding.logo_path
                else None
            ),
            footer_note=org.branding.email_footer_note if org.branding else None,
        ),
    )

    return {
        "message": f"A password reset link was sent to {user.email}.",
        # Dev-only fallback — see InviteResult.invite_url for why this is
        # withheld in production.
        "reset_url": reset_url if not settings.is_production else None,
    }
