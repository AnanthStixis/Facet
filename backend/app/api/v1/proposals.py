"""Proposals and statements of work (Module C).

The workflow is deliberately short: record a proposal, mark it submitted, ask
the prospect what they thought, record what actually happened. Everything
beyond that belongs in a CRM.

Asking for feedback creates an ordinary external campaign, so a proposal
survey shares the link security, delivery tracking, results aggregation and
exports built in Phase 3. No proposal-specific response handling exists,
because none is needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.api.deps import ActingOrg, DbSession, ManagerUser, rebind_tenant
from app.core.config import settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import generate_token, hash_token
from app.models.campaign import CampaignRecipient
from app.models.catalog import (
    Contact,
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import (
    AuditAction,
    CycleAudience,
    CycleStatus,
    ProposalStage,
    RecipientStatus,
    TargetType,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.proposal import Proposal
from app.models.user import User
from app.schemas.proposal import (
    FeedbackRequestRequest,
    PipelineSummary,
    ProposalCreateRequest,
    ProposalDetail,
    ProposalOutcomeRequest,
    ProposalUpdateRequest,
)
from app.services import audit, campaigns as campaign_service, email as email_service

router = APIRouter(prefix="/proposals", tags=["proposals"])


async def _next_reference(session: DbSession, org_id: uuid.UUID) -> str:
    year = datetime.now(UTC).year
    used = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Proposal)
                .where(
                    Proposal.org_id == org_id,
                    Proposal.reference.like(f"PRO-{year}-%"),
                )
            )
        ).scalar_one()
    )
    return f"PRO-{year}-{used + 1:03d}"


async def _load(session: DbSession, proposal_id: uuid.UUID) -> Proposal:
    proposal = (
        await session.execute(select(Proposal).where(Proposal.id == proposal_id))
    ).scalar_one_or_none()
    if proposal is None:
        raise NotFound("That proposal does not exist.")
    return proposal


async def _detail(session: DbSession, proposal: Proposal) -> ProposalDetail:
    contact_name = None
    if proposal.prospect_contact_id:
        contact_name = (
            await session.execute(
                select(Contact.full_name).where(
                    Contact.id == proposal.prospect_contact_id
                )
            )
        ).scalar_one_or_none()
    author_name = None
    if proposal.author_id:
        author_name = (
            await session.execute(
                select(User.full_name).where(User.id == proposal.author_id)
            )
        ).scalar_one_or_none()

    responses = 0
    average: float | None = None
    cycle_id: uuid.UUID | None = None
    if proposal.target_id:
        row = (
            await session.execute(
                select(
                    func.count(FeedbackResponse.id),
                    func.avg(FeedbackResponse.overall_score),
                ).where(FeedbackResponse.target_id == proposal.target_id)
            )
        ).first()
        if row:
            responses = int(row[0] or 0)
            average = round(float(row[1]), 2) if row[1] is not None else None

        # Postgres has no min() for uuid, so the round is located directly
        # rather than aggregated out of the response rows.
        cycle_id = (
            await session.execute(
                select(CampaignRecipient.cycle_id)
                .where(CampaignRecipient.target_id == proposal.target_id)
                .limit(1)
            )
        ).scalar_one_or_none()

    return ProposalDetail(
        id=proposal.id,
        reference=proposal.reference,
        title=proposal.title,
        client_name=proposal.client_name,
        summary=proposal.summary,
        stage=str(proposal.stage),
        currency=proposal.currency,
        value_amount=proposal.value_amount,
        won_amount=proposal.won_amount,
        value_variance=proposal.value_variance,
        estimated_effort_days=proposal.estimated_effort_days,
        prospect_contact_id=proposal.prospect_contact_id,
        prospect_contact_name=contact_name,
        author_id=proposal.author_id,
        author_name=author_name,
        submitted_at=proposal.submitted_at,
        decision_due_on=proposal.decision_due_on,
        decided_at=proposal.decided_at,
        loss_reason=str(proposal.loss_reason) if proposal.loss_reason else None,
        competitor=proposal.competitor,
        outcome_note=proposal.outcome_note,
        target_id=proposal.target_id,
        created_at=proposal.created_at,
        feedback_requested=cycle_id is not None,
        feedback_responses=responses,
        feedback_average=average,
        feedback_cycle_id=cycle_id,
    )


# --- Pipeline ---------------------------------------------------------------

@router.get("", response_model=list[ProposalDetail])
async def list_proposals(
    session: DbSession,
    actor: ManagerUser,
    acting: ActingOrg,
    stage: str | None = None,
    search: str | None = None,
) -> list[ProposalDetail]:
    stmt = select(Proposal).where(Proposal.org_id == acting.org_id)
    if stage:
        stmt = stmt.where(Proposal.stage == stage)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            Proposal.title.ilike(term)
            | Proposal.client_name.ilike(term)
            | Proposal.reference.ilike(term)
        )
    proposals = (
        (await session.execute(stmt.order_by(Proposal.created_at.desc()))).scalars().all()
    )
    return [await _detail(session, proposal) for proposal in proposals]


@router.get("/summary", response_model=PipelineSummary)
async def pipeline_summary(session: DbSession, actor: ManagerUser) -> PipelineSummary:
    rows = (
        await session.execute(select(Proposal.stage, func.count()).group_by(Proposal.stage))
    ).all()
    by_stage = {str(stage): count for stage, count in rows}
    total = sum(by_stage.values())

    open_value = (
        await session.execute(
            select(func.coalesce(func.sum(Proposal.value_amount), 0)).where(
                Proposal.stage.in_(
                    [
                        ProposalStage.SUBMITTED,
                        ProposalStage.SHORTLISTED,
                    ]
                )
            )
        )
    ).scalar_one()
    won_value = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(func.coalesce(Proposal.won_amount, Proposal.value_amount)), 0
                )
            ).where(Proposal.stage == ProposalStage.WON)
        )
    ).scalar_one()

    won = by_stage.get(str(ProposalStage.WON), 0)
    lost = by_stage.get(str(ProposalStage.LOST), 0)
    # Win rate is measured against decided proposals only. Counting proposals
    # still awaiting a decision as losses would make every pipeline look
    # terrible and the number meaningless.
    decided = won + lost

    with_feedback = int(
        (
            await session.execute(
                select(func.count(func.distinct(FeedbackResponse.target_id))).where(
                    FeedbackResponse.target_id.in_(
                        select(Proposal.target_id).where(Proposal.target_id.isnot(None))
                    )
                )
            )
        ).scalar_one()
    )
    submitted = total - by_stage.get(str(ProposalStage.DRAFT), 0)

    return PipelineSummary(
        total=total,
        open_value=Decimal(open_value),
        won_value=Decimal(won_value),
        by_stage=by_stage,
        win_rate_pct=round(100 * won / decided) if decided else 0,
        feedback_coverage_pct=round(100 * with_feedback / submitted) if submitted else 0,
    )


@router.post("", response_model=ProposalDetail, status_code=201)
async def create_proposal(
    payload: ProposalCreateRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
    acting: ActingOrg,
) -> ProposalDetail:
    reference = payload.reference or await _next_reference(session, acting.org_id)  
    if (
        await session.execute(
            select(Proposal.id).where(
                Proposal.org_id == acting.org_id, Proposal.reference == reference
            )
        )
    ).first() is not None:
        raise Conflict(f"Reference '{reference}' is already in use.")

    proposal = Proposal(
        org_id=acting.org_id,
        reference=reference,
        title=payload.title.strip(),
        client_name=payload.client_name.strip(),
        summary=payload.summary,
        prospect_contact_id=payload.prospect_contact_id,
        # Defaults to whoever recorded it, which is right far more often than
        # not and saves a field on the common path.
        author_id=payload.author_id or actor.id,
        currency=payload.currency.upper(),
        value_amount=payload.value_amount,
        estimated_effort_days=payload.estimated_effort_days,
        decision_due_on=payload.decision_due_on,
        stage=ProposalStage.DRAFT,
    )
    session.add(proposal)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.PROPOSAL_CREATED,
        summary=f"{actor.user.full_name} recorded proposal {reference}",
        org_id=acting.org_id,
        actor=actor.user,
        target_type="proposal",
        target_id=proposal.id,
        target_label=proposal.title,
        context={"client": proposal.client_name, "value": str(proposal.value_amount)},
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, proposal)


@router.patch("/{proposal_id}", response_model=ProposalDetail)
async def update_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalUpdateRequest,
    session: DbSession,
    actor: ManagerUser,
) -> ProposalDetail:
    proposal = await _load(session, proposal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(proposal, field, value)
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, proposal)


@router.post("/{proposal_id}/submit", response_model=ProposalDetail)
async def submit_proposal(
    proposal_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> ProposalDetail:
    """Mark a proposal as sent, and give it an identity in the feedback graph.

    The target is created here rather than at draft time, so a proposal that
    was never sent can never be surveyed.
    """
    proposal = await _load(session, proposal_id)
    if proposal.stage != ProposalStage.DRAFT:
        raise Conflict(f"This proposal is already {proposal.stage}.")

    proposal.stage = ProposalStage.SUBMITTED
    proposal.submitted_at = datetime.now(UTC)

    if proposal.target_id is None:
        target = FeedbackTarget(
            org_id=proposal.org_id,
            target_type=TargetType.PROPOSAL,
            label=f"{proposal.title} ({proposal.client_name})",
            reference=f"proposal:{proposal.reference}",
            attributes={
                "proposal_id": str(proposal.id),
                "client": proposal.client_name,
                "value": str(proposal.value_amount) if proposal.value_amount else None,
                "currency": proposal.currency,
            },
        )
        session.add(target)
        await session.flush()
        proposal.target_id = target.id

    await audit.record(
        session,
        action=AuditAction.PROPOSAL_SUBMITTED,
        summary=f"{actor.user.full_name} submitted {proposal.reference} to {proposal.client_name}",
        org_id=proposal.org_id,
        actor=actor.user,
        target_type="proposal",
        target_id=proposal.id,
        target_label=proposal.title,
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, proposal)


@router.post("/{proposal_id}/request-feedback", response_model=dict)
async def request_feedback(
    proposal_id: uuid.UUID,
    payload: FeedbackRequestRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> dict[str, Any]:
    """One click: create the campaign, invite the prospect, send the email."""
    proposal = await _load(session, proposal_id)
    if proposal.stage == ProposalStage.DRAFT:
        raise Conflict("Submit the proposal before asking for feedback on it.")
    if proposal.target_id is None:
        raise Conflict("This proposal has no feedback subject. Re-submit it.")

    contact_id = payload.contact_id or proposal.prospect_contact_id
    if contact_id is None:
        raise ValidationFailed(
            "Record the prospect's coordination contact before requesting feedback."
        )
    contact = (
        await session.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        raise NotFound("That contact does not exist.")
    if contact.unsubscribed_at is not None:
        raise Conflict(f"{contact.email} has unsubscribed from feedback requests.")

    # Pick the proposal-scoped template unless one is named.
    template_stmt = select(FeedbackTemplate).where(
        FeedbackTemplate.target_type == TargetType.PROPOSAL
    )
    if payload.template_id:
        template_stmt = template_stmt.where(FeedbackTemplate.id == payload.template_id)
    template = (await session.execute(template_stmt.limit(1))).scalar_one_or_none()
    if template is None:
        raise Conflict(
            "No proposal questionnaire is available. Publish one in Templates first."
        )

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
        raise Conflict("The proposal questionnaire has no published version.")

    existing = (
        await session.execute(
            select(ReviewCycle)
            .join(CampaignRecipient, CampaignRecipient.cycle_id == ReviewCycle.id)
            .where(CampaignRecipient.target_id == proposal.target_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict("Feedback has already been requested for this proposal.")

    now = datetime.now(UTC)
    cycle = ReviewCycle(
        org_id=proposal.org_id,
        name=f"Proposal feedback — {proposal.reference}",
        description=f"Prospect feedback on {proposal.title} for {proposal.client_name}.",
        template_version_id=version.id,
        status=CycleStatus.OPEN,
        audience=CycleAudience.EXTERNAL,
        is_anonymous=template.is_anonymous,
        min_responses_to_reveal=template.min_responses_to_reveal,
        opens_at=now,
        opened_at=now,
        closes_at=now + timedelta(days=payload.closes_in_days),
        created_by_id=actor.id,
    )
    session.add(cycle)
    await session.flush()

    await campaign_service.add_recipients(
        session,
        cycle=cycle,
        target_id=proposal.target_id,
        contact_ids=[contact.id],
        batch=proposal.reference,
    )
    await session.flush()

    org = (
        await session.execute(
            select(Organization).where(Organization.id == proposal.org_id)
        )
    ).scalar_one()

    # A proposal survey uses its own wording rather than the generic client
    # request: it must read as "help us improve", not as a nudge to buy while
    # a decision is still pending.
    recipient = (
        await session.execute(
            select(CampaignRecipient).where(CampaignRecipient.cycle_id == cycle.id)
        )
    ).scalar_one()

    raw_token = generate_token()
    recipient.token_hash = hash_token(raw_token)
    recipient.send_attempts += 1

    sent = await email_service.send_proposal_feedback_request(
        to=contact.email,
        full_name=contact.full_name,
        org_name=org.name,
        proposal_title=proposal.title,
        proposal_reference=proposal.reference,
        link=f"{settings.public_app_url}/f/{raw_token}",
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
    if sent:
        recipient.status = RecipientStatus.SENT
        recipient.sent_at = now

    await audit.record(
        session,
        action=AuditAction.PROPOSAL_FEEDBACK_REQUESTED,
        summary=(
            f"{actor.user.full_name} requested prospect feedback on "
            f"{proposal.reference}"
        ),
        org_id=proposal.org_id,
        actor=actor.user,
        target_type="proposal",
        target_id=proposal.id,
        target_label=proposal.title,
        context={"contact": contact.email, "cycle": str(cycle.id)},
        request=request,
    )
    await session.commit()

    return {
        "cycle_id": str(cycle.id),
        "sent": sent,
        "contact": contact.email,
        "closes_at": cycle.closes_at,
    }


@router.post("/{proposal_id}/outcome", response_model=ProposalDetail)
async def record_outcome(
    proposal_id: uuid.UUID,
    payload: ProposalOutcomeRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> ProposalDetail:
    """Record what actually happened.

    This is the field that makes the whole module worth building: without a
    real outcome next to the feedback, a proposal score is a number nobody can
    act on.
    """
    proposal = await _load(session, proposal_id)
    if proposal.stage == ProposalStage.DRAFT:
        raise Conflict("Submit the proposal before recording an outcome.")
    if proposal.stage.is_decided:
        raise Conflict(f"This proposal is already recorded as {proposal.stage}.")

    proposal.stage = payload.stage
    proposal.decided_at = datetime.now(UTC)
    proposal.loss_reason = payload.loss_reason
    proposal.won_amount = payload.won_amount
    proposal.competitor = payload.competitor
    proposal.outcome_note = payload.outcome_note

    await audit.record(
        session,
        action=AuditAction.PROPOSAL_DECIDED,
        summary=(
            f"{actor.user.full_name} recorded {proposal.reference} as {payload.stage}"
        ),
        org_id=proposal.org_id,
        actor=actor.user,
        target_type="proposal",
        target_id=proposal.id,
        target_label=proposal.title,
        context={
            "stage": str(payload.stage),
            "loss_reason": str(payload.loss_reason) if payload.loss_reason else None,
            "won_amount": str(payload.won_amount) if payload.won_amount else None,
            "competitor": payload.competitor,
        },
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)
    return await _detail(session, proposal)
