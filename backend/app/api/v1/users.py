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
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.security import generate_token, hash_token
from app.models.catalog import FeedbackTarget, FeedbackTemplate, FeedbackTemplateVersion
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.organization import Organization
from app.models.user import Invitation, PasswordResetToken, User, UserManager
from app.schemas.common import LookupItem, MessageResponse, Page
from app.schemas.feedback import UserFeedbackItem
from app.schemas.org import InviteResult, UserCreateRequest, UserDetail, UserUpdateRequest
from app.schemas.settings import OrgSettings
from app.services import audit, auth as auth_service, email as email_service
from app.services import managers as managers_service
from app.services.bulk_import import BulkRowError, parse_csv

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserDetail])
async def list_users(
    session: DbSession,
    actor: CurrentUser,
    search: str | None = None,
    role: UserRole | None = None,
    status: UserStatus | None = None,
    org_id: uuid.UUID | None = None,
    department: str | None = None,
    is_manager: bool | None = None,
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
    else:
        # Soft-deleted people never show up unless someone explicitly asks
        # for them (a future ?status=deleted filter) — their historical
        # feedback and audit trail stay intact, but they no longer clutter
        # the everyday People list.
        stmt = stmt.where(User.status != UserStatus.DELETED)
    if department:
        stmt = stmt.where(User.department == department)
    if org_id:
        # Only meaningful for a Super Admin browsing across tenants — a
        # Client Admin's session is already RLS-scoped to their own org, so
        # this is a no-op filter for them rather than a privilege check.
        stmt = stmt.where(User.org_id == org_id)
    if is_manager:
        stmt = stmt.where(
            User.id.in_(select(UserManager.manager_id).distinct())
        )

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
    )
    stmt = (
        stmt.order_by(User.created_at.desc())
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

    # One grouped query for every row's feedback count, rather than one query
    # per row — the People page shows this on every row, so N+1 here would
    # mean N extra round-trips on every page load.
    user_ids = [user.id for user in users]
    feedback_counts: dict[uuid.UUID, int] = {}
    if user_ids:
        rows = await session.execute(
            select(FeedbackTarget.subject_user_id, func.count(FeedbackResponse.id))
            .join(FeedbackResponse, FeedbackResponse.target_id == FeedbackTarget.id)
            .where(FeedbackTarget.subject_user_id.in_(user_ids))
            .group_by(FeedbackTarget.subject_user_id)
        )
        feedback_counts = dict(rows.all())

    # Same batching reasoning as feedback_counts — one grouped query for
    # every row's managers instead of one query per row.
    manager_ids_by_user = await managers_service.get_manager_ids_map(session, user_ids)

    # manager_ids_by_user only carries raw ids — the People table displays
    # names, not ids, so those need resolving to LookupItems in one more
    # grouped query, same batching reasoning as everything above it.
    all_manager_ids = {mid for ids in manager_ids_by_user.values() for mid in ids}
    manager_lookup: dict[uuid.UUID, LookupItem] = {}
    if all_manager_ids:
        rows = await session.execute(
            select(User.id, User.full_name, User.job_title).where(User.id.in_(all_manager_ids))
        )
        manager_lookup = {
            row.id: LookupItem(id=row.id, label=row.full_name, sublabel=row.job_title)
            for row in rows.all()
        }

    items = []
    for user in users:
        detail = UserDetail.model_validate(user)
        detail.org_name = org_names.get(user.org_id) if user.org_id else None
        detail.feedback_count = feedback_counts.get(user.id, 0)
        detail.manager_ids = manager_ids_by_user.get(user.id, [])
        detail.managers = [
            manager_lookup[mid]
            for mid in manager_ids_by_user.get(user.id, [])
            if mid in manager_lookup
        ]
        items.append(detail)

    return Page[UserDetail](items=items, total=total, page=page, page_size=page_size)


@router.get("/{user_id}/feedback", response_model=list[UserFeedbackItem])
async def user_feedback(
    user_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> list[UserFeedbackItem]:
    """Every piece of feedback collected about this person, across every
    round they've ever been the subject of — the People-page popup and the
    "About" cross-link on a Client Review both read from here.
    """
    if actor.id != user_id:
        # Same "admin, owning manager, or the person themself" shape as
        # cycles.target_results — a plain employee cannot browse a
        # colleague's feedback history through this endpoint.
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFound("That person does not exist.")
        is_admin = actor.role in {UserRole.SUPER_ADMIN, UserRole.CLIENT_ADMIN}
        is_their_manager = actor.role == UserRole.MANAGER and actor.id in (
            await managers_service.get_manager_ids(session, user_id)
        )
        if not (is_admin or is_their_manager):
            raise PermissionDenied("You cannot view this person's feedback.")

    # A person can be the subject of more than one target: their normal
    # EMPLOYEE/MANAGER target from internal cycles, and separately a
    # CLIENT-typed target if a Client Review has ever named them via
    # about_user_id (see feedback_service.create_and_send). Both belong on
    # "everything about this person", so every target they're the subject of
    # is unioned here rather than assuming exactly one.
    target_rows = (
        (
            await session.execute(
                select(FeedbackTarget).where(FeedbackTarget.subject_user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    if not target_rows:
        return []
    targets_by_id = {t.id: t for t in target_rows}

    rows = (
        await session.execute(
            select(FeedbackResponse, ReviewCycle, FeedbackTemplate)
            .join(ReviewCycle, ReviewCycle.id == FeedbackResponse.cycle_id)
            .join(
                FeedbackTemplateVersion,
                FeedbackTemplateVersion.id == FeedbackResponse.template_version_id,
            )
            .join(FeedbackTemplate, FeedbackTemplate.id == FeedbackTemplateVersion.template_id)
            .where(FeedbackResponse.target_id.in_(targets_by_id.keys()))
            .order_by(FeedbackResponse.submitted_at.desc())
        )
    ).all()

    from app.api.v1.feedback import _kind_of  # local import avoids a cycle

    return [
        UserFeedbackItem(
            cycle_id=cycle.id,
            cycle_name=cycle.name,
            kind=_kind_of(cycle.audience, str(targets_by_id[response.target_id].target_type)),
            template_name=template.name,
            relationship=str(response.relationship_type),
            submitted_at=response.submitted_at,
            overall_score=(
                float(response.overall_score) if response.overall_score is not None else None
            ),
            comment=response.comment,
        )
        for response, cycle, template in rows
    ]


@router.get("/{user_id}/managers", response_model=list[LookupItem])
async def user_managers(
    user_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> list[LookupItem]:
    """This person's current managers — what the Employee Review form's
    manager checkbox list is built from once a reviewee is chosen.

    RLS already scopes `users` to the caller's org, so a manager_id pointing
    outside it can't happen; no extra org check needed here beyond that.
    """
    manager_ids = await managers_service.get_manager_ids(session, user_id)
    if not manager_ids:
        return []
    rows = (
        await session.execute(
            select(User.id, User.full_name, User.job_title).where(User.id.in_(manager_ids))
        )
    ).all()
    return [
        LookupItem(id=row.id, label=row.full_name, sublabel=row.job_title)
        for row in rows
    ]


@router.get("/{user_id}/reports", response_model=list[LookupItem])
async def user_reports(
    user_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> list[LookupItem]:
    """This person's current direct reports — what the Management Review
    form's "Reviewed by" side is built from once a manager is chosen, the
    reverse of user_managers above.
    """
    report_ids = await managers_service.get_report_ids(session, user_id)
    if not report_ids:
        return []
    rows = (
        await session.execute(
            select(User.id, User.full_name, User.job_title).where(User.id.in_(report_ids))
        )
    ).all()
    return [
        LookupItem(id=row.id, label=row.full_name, sublabel=row.job_title)
        for row in rows
    ]


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
                f"This organization has reached its seat limit "
                f"({org.seat_limit} seat{'' if org.seat_limit == 1 else 's'})."
            )

    # No pre-check SELECT here: RLS restricts this session to its own org's
    # rows, so a query scoped to org_id could never see a duplicate sitting
    # in a different organization. The platform-wide unique index on email
    # (migration 0013) is the real source of truth — this just turns its
    # violation into a clean error instead of a raw IntegrityError.
    email = payload.email.lower()

    user = User(
        org_id=org_id,
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        job_title=payload.job_title,
        department=payload.department,
        phone=payload.phone,
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
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_users_email" in str(exc.orig):
            raise Conflict(
                "Someone with that email already has an account on the platform."
            ) from exc
        raise

    # Only meaningful once the user has a real id, which the DB assigns on
    # insert — this is why it happens after the flush above, not inside the
    # User(...) construction alongside the other fields.
    if payload.manager_ids:
        await managers_service.set_managers(
            session, org_id=org_id, employee_id=user.id, manager_ids=payload.manager_ids
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

    max_rows = 100
    if len(rows) > max_rows:
        raise ValidationFailed(
            f"This file has {len(rows)} rows. Bulk invite is limited to "
            f"{max_rows} at a time — split it into smaller files."
        )

    org = (
        await session.execute(select(Organization).where(Organization.id == actor.org_id))
    ).scalar_one()
    invitation_subject = OrgSettings.load(org.settings).email.invitation_subject

    invited: list[str] = []
    skipped: list[dict[str, Any]] = []
    seen_in_file: set[str] = set()

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        email = row.get("email", "").lower()
        full_name = row.get("full_name", "")
        if not email or not full_name:
            skipped.append({"row": index, "reason": "Missing name or email"})
            continue
        if email in seen_in_file:
            skipped.append({"row": index, "email": email, "reason": "Duplicate in this file"})
            continue
        seen_in_file.add(email)

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

        # No pre-check SELECT: RLS restricts this session to its own org's
        # rows, so this could never see a duplicate sitting in a different
        # organization. The platform-wide unique index (migration 0013) is
        # the real source of truth. A savepoint here matters because this
        # runs per-row inside a loop — without one, a duplicate on row 40
        # would roll back every row already successfully invited before it,
        # not just row 40.
        try:
            async with session.begin_nested():
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
        except IntegrityError as exc:
            if "uq_users_email" in str(exc.orig):
                skipped.append({"row": index, "email": email, "reason": "Already exists"})
                continue
            raise

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
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.manager_ids is not None:
        await managers_service.set_managers(
            session, org_id=user.org_id, employee_id=user.id, manager_ids=payload.manager_ids
        )

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
    detail = UserDetail.model_validate(user)
    detail.manager_ids = await managers_service.get_manager_ids(session, user.id)
    return detail


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


@router.post("/{user_id}/enable", response_model=MessageResponse)
async def enable_user(
    user_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> MessageResponse:
    """Reverse a disable — the account was never deleted, just locked out."""
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That user does not exist.")
    if user.status != UserStatus.DISABLED:
        raise Conflict("Only a disabled account can be re-enabled.")

    user.status = UserStatus.ACTIVE

    await audit.record(
        session,
        action=AuditAction.USER_ENABLED,
        summary=f"{actor.user.full_name} re-enabled {user.email}",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        request=request,
    )
    await session.commit()
    return MessageResponse(message=f"{user.email} can sign in again.")


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

@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> MessageResponse:
    """Soft delete: the row stays — feedback history, audit trail, and
    manager/report relationships all reference it — but the person no
    longer appears in the default Users list (see list_users' status
    filter above) and can no longer sign in. Nothing here is destroyed,
    even though there is no "restore" UI yet.
    """
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("That user does not exist.")
    if user.id == actor.id:
        raise PermissionDenied("You cannot delete your own account.")

    user.status = UserStatus.DELETED
    revoked = await auth_service.revoke_all_sessions(
        session, user_id=user.id, reason="user_deleted"
    )

    await audit.record(
        session,
        action=AuditAction.USER_DELETED,
        summary=f"{actor.user.full_name} deleted {user.email}",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        context={"sessions_revoked": revoked},
        request=request,
    )
    await session.commit()
    return MessageResponse(message=f"{user.email} was removed.")