"""External feedback campaigns, contacts, and targets (Module B).

A campaign is a `ReviewCycle` with `audience = external`. It shares the cycle
lifecycle, the pinned template version, the anonymity snapshot and the results
pipeline with internal 360s — only the delivery mechanism differs.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, ManagerUser, rebind_tenant
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.campaign import CampaignRecipient
from app.models.catalog import (
    Contact,
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.cycle import ReviewCycle
from app.models.enums import (
    AuditAction,
    CycleAudience,
    CycleStatus,
    RecipientStatus,
    TemplateStatus,
    UserRole,
)
from app.models.organization import Organization
from app.models.user import User
from app.schemas.campaign import (
    AddSummary,
    CampaignCreateRequest,
    CampaignDetail,
    ContactCreateRequest,
    ContactDetail,
    RecipientAddRequest,
    RecipientDetail,
    SendRequest,
    SendSummary,
    TargetCreateRequest,
    TargetDetail,
)
from app.schemas.common import MessageResponse, Page
from app.services import audit, campaigns as campaign_service
from app.services.bulk_import import BulkRowError, parse_csv

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
contacts_router = APIRouter(prefix="/contacts", tags=["contacts"])
targets_router = APIRouter(prefix="/targets", tags=["targets"])


async def _load(session: DbSession, campaign_id: uuid.UUID) -> ReviewCycle:
    cycle = (
        await session.execute(
            select(ReviewCycle).where(
                ReviewCycle.id == campaign_id,
                ReviewCycle.audience == CycleAudience.EXTERNAL,
            )
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFound("That campaign does not exist.")
    return cycle


async def _detail(session: DbSession, cycle: ReviewCycle) -> CampaignDetail:
    version = (
        await session.execute(
            select(FeedbackTemplateVersion, FeedbackTemplate)
            .join(
                FeedbackTemplate,
                FeedbackTemplate.id == FeedbackTemplateVersion.template_id,
            )
            .where(FeedbackTemplateVersion.id == cycle.template_version_id)
        )
    ).first()

    target = (
        (
            await session.execute(
                select(FeedbackTarget).where(FeedbackTarget.id == cycle.target_id)
            )
        ).scalar_one_or_none()
        if cycle.target_id is not None
        else None
    )

    creator_name = None
    if cycle.created_by_id is not None:
        creator = (
            await session.execute(select(User).where(User.id == cycle.created_by_id))
        ).scalar_one_or_none()
        creator_name = creator.full_name if creator else None

    return CampaignDetail(
        id=cycle.id,
        name=cycle.name,
        description=cycle.description,
        status=str(cycle.status),
        audience=str(cycle.audience),
        is_anonymous=cycle.is_anonymous,
        min_responses_to_reveal=cycle.min_responses_to_reveal,
        template_name=version[1].name if version else None,
        template_version=version[0].version if version else None,
        target_id=target.id if target else None,
        target_label=target.label if target else None,
        target_type=str(target.target_type) if target else None,
        closes_at=cycle.closes_at,
        created_at=cycle.created_at,
        created_by_id=cycle.created_by_id,
        created_by_name=creator_name,
        delivery=await campaign_service.campaign_progress(session, cycle.id),
    )


# --- Campaign lifecycle -----------------------------------------------------

@router.get("", response_model=list[CampaignDetail])
async def list_campaigns(session: DbSession, actor: ManagerUser) -> list[CampaignDetail]:
    stmt = select(ReviewCycle).where(ReviewCycle.audience == CycleAudience.EXTERNAL)
    # Same ownership scoping as review cycles: Client Admin/Super Admin see
    # every campaign in the org; a Manager sees only the ones they ran.
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN):
        stmt = stmt.where(ReviewCycle.created_by_id == actor.id)
    cycles = (
        (await session.execute(stmt.order_by(ReviewCycle.created_at.desc())))
        .scalars()
        .all()
    )
    return [await _detail(session, cycle) for cycle in cycles]


@router.post("", response_model=CampaignDetail, status_code=201)
async def create_campaign(
    payload: CampaignCreateRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> CampaignDetail:
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")

    template = (
        await session.execute(
            select(FeedbackTemplate).where(FeedbackTemplate.id == payload.template_id)
        )
    ).scalar_one_or_none()
    if template is None:
        raise NotFound("That template does not exist.")

    version = (
        await session.execute(
            select(FeedbackTemplateVersion)
            .where(
                FeedbackTemplateVersion.template_id == template.id,
                FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED,
            )
            .order_by(FeedbackTemplateVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise Conflict("That template has no published version yet. Publish it first.")

    target: FeedbackTarget | None = None
    if payload.target_id is not None:
        target = (
            await session.execute(
                select(FeedbackTarget).where(FeedbackTarget.id == payload.target_id)
            )
        ).scalar_one_or_none()
        if target is None:
            raise NotFound("That feedback target does not exist.")
    elif payload.target_label is not None:
        label = payload.target_label.strip()
        # Reuse an existing target with the same name and type rather than
        # minting a duplicate every time someone types the same subject in —
        # this is the "just type it in, no dropdown" flow's find-or-create.
        target = (
            await session.execute(
                select(FeedbackTarget).where(
                    FeedbackTarget.org_id == actor.org_id,
                    FeedbackTarget.target_type == template.target_type,
                    func.lower(FeedbackTarget.label) == label.lower(),
                )
            )
        ).scalar_one_or_none()
        if target is None:
            target = FeedbackTarget(
                org_id=actor.org_id,
                target_type=template.target_type,
                label=label,
                reference=f"{template.target_type}:{uuid.uuid4().hex[:10]}",
            )
            session.add(target)
            await session.flush()
    else:
        raise ValidationFailed("Say what this campaign is about.")

    # The template declares what it is written to assess. Asking a proposal
    # questionnaire about a person produces answers nobody can interpret.
    if str(target.target_type) != str(template.target_type):
        raise ValidationFailed(
            f"'{template.name}' is written for {template.target_type} feedback, "
            f"but '{target.label}' is a {target.target_type}."
        )

    cycle = ReviewCycle(
        org_id=actor.org_id,
        name=payload.name.strip(),
        description=payload.description,
        template_version_id=version.id,
        status=CycleStatus.DRAFT,
        audience=CycleAudience.EXTERNAL,
        is_anonymous=template.is_anonymous,
        min_responses_to_reveal=template.min_responses_to_reveal,
        target_id=target.id,
        closes_at=payload.closes_at,
        created_by_id=actor.id,
    )
    session.add(cycle)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CAMPAIGN_CREATED,
        summary=f"{actor.user.full_name} created the campaign '{cycle.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"template": template.name, "subject": target.label},
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.post("/{campaign_id}/recipients", response_model=AddSummary)
async def add_recipients(
    campaign_id: uuid.UUID,
    payload: RecipientAddRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> AddSummary:
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    result = await campaign_service.add_recipients(
        session,
        cycle=cycle,
        target_id=payload.target_id,
        contact_ids=payload.contact_ids,
        batch=payload.batch,
    )
    await audit.record(
        session,
        action=AuditAction.RECIPIENTS_ADDED,
        summary=(
            f"{actor.user.full_name} added {result.added} recipient(s) to "
            f"'{cycle.name}'"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={
            "added": result.added,
            "skipped_existing": result.skipped_existing,
            "skipped_unsubscribed": result.skipped_unsubscribed,
            "batch": payload.batch,
        },
        request=request,
    )
    await session.commit()
    return AddSummary(
        added=result.added,
        skipped_existing=result.skipped_existing,
        skipped_unsubscribed=result.skipped_unsubscribed,
        warnings=result.warnings,
    )


@router.post("/{campaign_id}/open", response_model=CampaignDetail)
async def open_campaign(
    campaign_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> CampaignDetail:
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status != CycleStatus.DRAFT:
        raise Conflict(f"This campaign is already {cycle.status}.")

    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(CampaignRecipient)
                .where(CampaignRecipient.cycle_id == cycle.id)
            )
        ).scalar_one()
    )
    if total == 0:
        raise Conflict("Add recipients before opening the campaign.")

    cycle.status = CycleStatus.OPEN
    cycle.opened_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.CAMPAIGN_LAUNCHED,
        summary=f"{actor.user.full_name} opened the campaign '{cycle.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"recipients": total},
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.post("/{campaign_id}/send", response_model=SendSummary)
async def send_invitations(
    campaign_id: uuid.UUID,
    payload: SendRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> SendSummary:
    """Send or re-send invitations. Single recipient or the whole list."""
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    org = (
        await session.execute(
            select(Organization).where(Organization.id == cycle.org_id)
        )
    ).scalar_one()

    result = await campaign_service.send_pending(
        session,
        cycle=cycle,
        org=org,
        only_recipient_id=payload.recipient_id,
        resend=payload.resend,
    )

    await audit.record(
        session,
        action=AuditAction.INVITATIONS_SENT,
        summary=(
            f"{actor.user.full_name} sent {result.sent} invitation(s) for "
            f"'{cycle.name}'"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={
            "sent": result.sent,
            "failed": result.failed,
            "skipped": result.skipped,
            "resend": payload.resend,
        },
        request=request,
    )
    await session.commit()
    return SendSummary(
        sent=result.sent,
        failed=result.failed,
        skipped=result.skipped,
        errors=result.errors,
    )


@router.post("/{campaign_id}/close", response_model=CampaignDetail)
async def close_campaign(
    campaign_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> CampaignDetail:
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status != CycleStatus.OPEN:
        raise Conflict("Only an open campaign can be closed.")

    cycle.status = CycleStatus.CLOSED
    cycle.closed_at = datetime.now(UTC)
    delivery = await campaign_service.campaign_progress(session, cycle.id)

    await audit.record(
        session,
        action=AuditAction.CYCLE_CLOSED,
        summary=(
            f"{actor.user.full_name} closed '{cycle.name}' at "
            f"{delivery['response_rate_pct']}% response rate"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context=delivery,
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.delete("/{campaign_id}", status_code=204, response_model=None)
async def delete_campaign(
    campaign_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> None:
    """Delete a campaign that never actually sent anything.

    Gated on delivery, not status: a draft is always safe to delete, and so
    is an *opened* campaign that has recipients added but nothing sent yet —
    "Create and open" makes that the common case, not an edge case, so tying
    delete to status alone meant almost nobody could ever use it. What is
    never safe is deleting after a real invitation went out: that would
    orphan a real person's one-time link and any response they already gave.
    Close it instead; closing is reversible in spirit (the record stays,
    just stops collecting) where deletion is not.
    """
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status == CycleStatus.CLOSED:
        raise Conflict("A closed campaign is a historical record and cannot be deleted.")
    sent = int(
        (
            await session.execute(
                select(func.count())
                .select_from(CampaignRecipient)
                .where(
                    CampaignRecipient.cycle_id == cycle.id,
                    CampaignRecipient.status != RecipientStatus.PENDING,
                )
            )
        ).scalar_one()
    )
    if sent > 0:
        raise Conflict(
            "This campaign has already sent invitations — deleting it would orphan "
            "real recipients' links. Close it instead."
        )
    name = cycle.name
    await session.delete(cycle)
    await audit.record(
        session,
        action=AuditAction.CAMPAIGN_DELETED,
        summary=f"{actor.user.full_name} deleted the draft campaign '{name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=campaign_id,
        target_label=name,
        request=request,
    )
    await session.commit()


@router.get("/{campaign_id}/recipients", response_model=list[RecipientDetail])
async def list_recipients(
    campaign_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> list[RecipientDetail]:
    """Delivery tracking.

    Shows who was invited and how far they got. It never shows what anyone
    said — for an anonymous campaign that link does not exist in the database,
    and for an attributable one it belongs on the results page.
    """
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    rows = (
        await session.execute(
            select(CampaignRecipient, Contact, FeedbackTarget)
            .join(Contact, Contact.id == CampaignRecipient.contact_id)
            .join(FeedbackTarget, FeedbackTarget.id == CampaignRecipient.target_id)
            .where(CampaignRecipient.cycle_id == cycle.id)
            .order_by(Contact.full_name)
        )
    ).all()
    return [
        RecipientDetail(
            id=recipient.id,
            contact_name=contact.full_name,
            contact_email=contact.email,
            company=contact.company,
            target_label=target.label,
            status=str(recipient.status),
            batch=recipient.batch,
            sent_at=recipient.sent_at,
            first_opened_at=recipient.first_opened_at,
            submitted_at=recipient.submitted_at,
            open_count=recipient.open_count,
            expires_at=recipient.expires_at,
        )
        for recipient, contact, target in rows
    ]


@router.post("/{campaign_id}/recipients/{recipient_id}/revoke", response_model=MessageResponse)
async def revoke_link(
    campaign_id: uuid.UUID,
    recipient_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> MessageResponse:
    """Kill one link, for a wrong address or a contact who has left."""
    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    recipient = (
        await session.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.id == recipient_id,
                CampaignRecipient.cycle_id == cycle.id,
            )
        )
    ).scalar_one_or_none()
    if recipient is None:
        raise NotFound("That recipient does not exist.")
    if recipient.status == RecipientStatus.SUBMITTED:
        raise Conflict("That person has already responded.")

    recipient.status = RecipientStatus.REVOKED
    recipient.revoked_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.LINK_REVOKED,
        summary=f"{actor.user.full_name} revoked a feedback link in '{cycle.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="campaign_recipient",
        target_id=recipient.id,
        request=request,
    )
    await session.commit()
    return MessageResponse(message="That link no longer works.")


# --- Contacts ---------------------------------------------------------------

@contacts_router.get("", response_model=Page[ContactDetail])
async def list_contacts(
    session: DbSession,
    actor: ManagerUser,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Page[ContactDetail]:
    stmt = select(Contact)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            Contact.full_name.ilike(term)
            | Contact.email.ilike(term)
            | Contact.company.ilike(term)
        )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
    )
    rows = (
        (
            await session.execute(
                stmt.order_by(Contact.full_name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return Page[ContactDetail](
        items=[ContactDetail.model_validate(contact) for contact in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@contacts_router.post("", response_model=ContactDetail, status_code=201)
async def create_contact(
    payload: ContactCreateRequest, session: DbSession, actor: ManagerUser
) -> ContactDetail:
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")
    email = payload.email.lower()
    if (
        await session.execute(
            select(Contact.id).where(
                Contact.org_id == actor.org_id, Contact.email == email
            )
        )
    ).first() is not None:
        raise Conflict("That contact already exists.")

    contact = Contact(
        org_id=actor.org_id,
        email=email,
        full_name=payload.full_name.strip(),
        company=payload.company,
        job_title=payload.job_title,
        tags=payload.tags,
    )
    session.add(contact)
    await session.commit()
    return ContactDetail.model_validate(contact)


@contacts_router.get("/bulk/template")
async def contacts_bulk_template(actor: ManagerUser) -> StreamingResponse:
    """A starter CSV so the columns a bulk import expects are never guessed."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["full_name", "email", "company", "job_title", "tags"])
    writer.writerow(["Jane Doe", "jane.doe@example.com", "Acme Inc", "Buyer", "vip;renewal"])
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"content-disposition": "attachment; filename=contact_import_template.csv"},
    )


@contacts_router.post("/bulk")
async def bulk_import_contacts(
    session: DbSession, actor: ManagerUser, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Import many contacts at once from a CSV export of a client list.

    Tags are semicolon-separated within the cell, since a plain comma is
    already the CSV field separator. A row whose email already exists in this
    organization is skipped with a reason rather than failing the file.
    """
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")

    raw = await file.read()
    try:
        rows = parse_csv(raw, required=["full_name", "email"])
    except BulkRowError as exc:
        raise ValidationFailed(str(exc)) from exc

    imported: list[str] = []
    skipped: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        email = row.get("email", "").lower()
        full_name = row.get("full_name", "")
        if not email or not full_name:
            skipped.append({"row": index, "reason": "Missing name or email"})
            continue

        exists = (
            await session.execute(
                select(Contact.id).where(
                    Contact.org_id == actor.org_id, Contact.email == email
                )
            )
        ).first()
        if exists is not None:
            skipped.append({"row": index, "email": email, "reason": "Already exists"})
            continue

        tags = [tag.strip() for tag in (row.get("tags") or "").split(";") if tag.strip()]
        session.add(
            Contact(
                org_id=actor.org_id,
                email=email,
                full_name=full_name,
                company=row.get("company") or None,
                job_title=row.get("job_title") or None,
                tags=tags,
            )
        )
        imported.append(email)

    await session.commit()
    return {"imported": len(imported), "skipped": skipped, "total_rows": len(rows)}


# --- Targets ----------------------------------------------------------------

@targets_router.get("", response_model=list[TargetDetail])
async def list_targets(
    session: DbSession, actor: CurrentUser, target_type: str | None = None
) -> list[TargetDetail]:
    stmt = select(FeedbackTarget).where(FeedbackTarget.is_active.is_(True))
    if target_type:
        stmt = stmt.where(FeedbackTarget.target_type == target_type)
    rows = (
        (await session.execute(stmt.order_by(FeedbackTarget.label))).scalars().all()
    )
    return [TargetDetail.model_validate(target) for target in rows]


@targets_router.post("", response_model=TargetDetail, status_code=201)
async def create_target(
    payload: TargetCreateRequest, session: DbSession, actor: ManagerUser
) -> TargetDetail:
    """Register something feedback can be about: a product, service or proposal."""
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")

    reference = payload.reference or f"{payload.target_type}:{uuid.uuid4().hex[:10]}"
    if (
        await session.execute(
            select(FeedbackTarget.id).where(
                FeedbackTarget.org_id == actor.org_id,
                FeedbackTarget.target_type == payload.target_type,
                FeedbackTarget.reference == reference,
            )
        )
    ).first() is not None:
        raise Conflict("A target with that reference already exists.")

    target = FeedbackTarget(
        org_id=actor.org_id,
        target_type=payload.target_type,
        label=payload.label.strip(),
        reference=reference,
        attributes=payload.attributes,
    )
    session.add(target)
    await session.commit()
    return TargetDetail.model_validate(target)


@router.get("/{campaign_id}/results")
async def campaign_results(
    campaign_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> dict[str, Any]:
    """Results for a campaign.

    Delegates to exactly the same aggregation and suppression used for internal
    360s — external feedback needed no separate results code, which is the
    payoff for modelling both as one cycle over one target graph.
    """
    from app.services import results as results_service

    cycle = await _load(session, campaign_id)
    actor.assert_owns(cycle.created_by_id)
    return {
        "campaign": (await _detail(session, cycle)).model_dump(mode="json"),
        "rows": await results_service.cycle_overview(session, cycle=cycle),
    }
