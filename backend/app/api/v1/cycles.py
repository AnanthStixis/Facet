"""Review cycles, assignments, responses, and results (Module A)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.api.deps import (
    ActingOrg,
    CurrentUser,
    DbSession,
    ManagerUser,
    rebind_tenant,
)
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.models.catalog import FeedbackTarget, FeedbackTemplate, FeedbackTemplateVersion
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.user import User
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    CycleAudience,
    CycleStatus,
    Relationship,
    TemplateStatus,
    UserRole,
)
from app.schemas.common import MessageResponse
from app.schemas.cycle import (
    AssignmentForm,
    AssignmentPlanRequest,
    AssignmentSummary,
    CycleCreateRequest,
    CycleDetail,
    DeclineRequest,
    GenerationSummary,
    SubmitResponseRequest,
)
from app.services import audit, cycles as cycle_service, results as results_service
from app.services.forms import form_payload, validate_answers, validate_definition

router = APIRouter(prefix="/cycles", tags=["cycles"])

# Assignments live under their own prefix rather than /cycles/assignments/...,
# because a literal segment declared after /cycles/{cycle_id} would be parsed
# as a UUID and 422 before it ever reached its handler.
assignments_router = APIRouter(prefix="/assignments", tags=["assignments"])
me_router = APIRouter(prefix="/me", tags=["me"])


async def _load_cycle(session: DbSession, cycle_id: uuid.UUID) -> ReviewCycle:
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id))
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFound("That review cycle does not exist.")
    return cycle


async def _detail(session: DbSession, cycle: ReviewCycle) -> CycleDetail:
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
    progress = await cycle_service.cycle_progress(session, cycle.id)
    creator_name = None
    if cycle.created_by_id is not None:
        creator = (
            await session.execute(select(User).where(User.id == cycle.created_by_id))
        ).scalar_one_or_none()
        creator_name = creator.full_name if creator else None
    return CycleDetail(
        id=cycle.id,
        name=cycle.name,
        description=cycle.description,
        status=str(cycle.status),
        is_anonymous=cycle.is_anonymous,
        min_responses_to_reveal=cycle.min_responses_to_reveal,
        template_version_id=cycle.template_version_id,
        template_name=version[1].name if version else None,
        template_version=version[0].version if version else None,
        opens_at=cycle.opens_at,
        closes_at=cycle.closes_at,
        opened_at=cycle.opened_at,
        closed_at=cycle.closed_at,
        created_at=cycle.created_at,
        created_by_id=cycle.created_by_id,
        created_by_name=creator_name,
        progress=progress,
    )


# --- Cycle lifecycle --------------------------------------------------------

@router.get("", response_model=list[CycleDetail])
async def list_cycles(session: DbSession, actor: ManagerUser, acting: ActingOrg) -> list[CycleDetail]:
    stmt = select(ReviewCycle).where(
        ReviewCycle.audience != CycleAudience.EXTERNAL,
        ReviewCycle.org_id == acting.org_id,
    )
    # Client Admin and Super Admin see everything in the org, per policy. A
    # Manager sees only what they themselves are running — not another
    # manager's cycle, not the Client Admin's — same as a Manager cannot open
    # another manager's cycle by guessing its id (see assert_owns below).
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN):
        stmt = stmt.where(ReviewCycle.created_by_id == actor.id)
    cycles = (
        (await session.execute(stmt.order_by(ReviewCycle.created_at.desc())))
        .scalars()
        .all()
    )
    return [await _detail(session, cycle) for cycle in cycles]


@router.post("", response_model=CycleDetail, status_code=201)
async def create_cycle(
    payload: CycleCreateRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
    acting: ActingOrg,
) -> CycleDetail:

    template = (
        await session.execute(
            select(FeedbackTemplate).where(FeedbackTemplate.id == payload.template_id)
        )
    ).scalar_one_or_none()
    if template is None:
        raise NotFound("That template does not exist.")

    # A cycle pins the newest *published* version. Draft versions are work in
    # progress and must never be what a respondent is asked.
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

    if payload.opens_at and payload.closes_at and payload.closes_at <= payload.opens_at:
        raise ValidationFailed("The closing date must be after the opening date.")

    cycle = ReviewCycle(
        org_id=acting.org_id,
        name=payload.name.strip(),
        description=payload.description,
        template_version_id=version.id,
        status=CycleStatus.DRAFT,
        # Snapshotted, so relaxing the template later cannot retroactively
        # de-anonymise feedback that was given under a promise.
        is_anonymous=template.is_anonymous,
        min_responses_to_reveal=template.min_responses_to_reveal,
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        created_by_id=actor.id,
    )
    session.add(cycle)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CYCLE_CREATED,
        summary=f"{actor.user.full_name} created the cycle '{cycle.name}'",
        org_id=acting.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={
            "template": template.name,
            "version": version.version,
            "anonymous": cycle.is_anonymous,
        },
        request=request,
    )
    await session.commit()
    # The commit ended the transaction the tenant GUC was local to, so it has
    # to be re-applied before _detail reads the assignment counts.
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.get("/{cycle_id}", response_model=CycleDetail)
async def get_cycle(
    cycle_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> CycleDetail:
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    return await _detail(session, cycle)


@router.post("/{cycle_id}/assignments", response_model=GenerationSummary)
async def generate(
    cycle_id: uuid.UUID,
    payload: AssignmentPlanRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> GenerationSummary:
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    result = await cycle_service.generate_assignments(
        session,
        cycle=cycle,
        reviewee_ids=payload.reviewee_ids,
        plan=cycle_service.GenerationPlan(
            include_self=payload.include_self,
            include_manager=payload.include_manager,
            include_upward=payload.include_upward,
            include_peers=payload.include_peers,
            max_peers=payload.max_peers,
        ),
    )
    await audit.record(
        session,
        action=AuditAction.ASSIGNMENTS_GENERATED,
        summary=(
            f"{actor.user.full_name} generated {result.created} assignment(s) "
            f"for '{cycle.name}'"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={
            "created": result.created,
            "skipped": result.skipped_existing,
            "by_relationship": result.by_relationship,
            "reviewees": len(payload.reviewee_ids),
        },
        request=request,
    )
    await session.commit()
    return GenerationSummary(
        created=result.created,
        skipped_existing=result.skipped_existing,
        by_relationship=result.by_relationship,
        warnings=result.warnings,
    )


@router.post("/{cycle_id}/open", response_model=CycleDetail)
async def open_cycle(
    cycle_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> CycleDetail:
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status != CycleStatus.DRAFT:
        raise Conflict(f"This cycle is already {cycle.status}.")

    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(FeedbackAssignment)
                .where(FeedbackAssignment.cycle_id == cycle.id)
            )
        ).scalar_one()
    )
    if total == 0:
        raise Conflict("Generate assignments before opening the cycle.")

    cycle.status = CycleStatus.OPEN
    cycle.opened_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.CYCLE_OPENED,
        summary=f"{actor.user.full_name} opened '{cycle.name}' to {total} reviewer(s)",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"assignments": total},
        request=request,
    )
    await session.commit()
    # The commit ended the transaction the tenant GUC was local to, so it has
    # to be re-applied before _detail reads the assignment counts.
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.post("/{cycle_id}/close", response_model=CycleDetail)
async def close_cycle(
    cycle_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> CycleDetail:
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status != CycleStatus.OPEN:
        raise Conflict("Only an open cycle can be closed.")

    cycle.status = CycleStatus.CLOSED
    cycle.closed_at = datetime.now(UTC)
    progress = await cycle_service.cycle_progress(session, cycle.id)

    await audit.record(
        session,
        action=AuditAction.CYCLE_CLOSED,
        summary=(
            f"{actor.user.full_name} closed '{cycle.name}' at "
            f"{progress['completion_pct']}% completion"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context=progress,
        request=request,
    )
    await session.commit()
    # The commit ended the transaction the tenant GUC was local to, so it has
    # to be re-applied before _detail reads the assignment counts.
    await rebind_tenant(session, actor)
    return await _detail(session, cycle)


@router.delete("/{cycle_id}", status_code=204, response_model=None)
async def delete_cycle(
    cycle_id: uuid.UUID, request: Request, session: DbSession, actor: ManagerUser
) -> None:
    """Delete a cycle nobody has responded to yet.

    Gated on responses, not status: a draft is always safe, and so is an
    opened cycle that has assignments but zero submissions — reviewers have
    something sitting in "My feedback" but haven't acted on it, so nothing is
    lost. Once even one response exists, deleting would destroy real
    feedback someone gave in confidence; close it instead.
    """
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    if cycle.status == CycleStatus.CLOSED:
        raise Conflict("A closed cycle is a historical record and cannot be deleted.")
    submitted = int(
        (
            await session.execute(
                select(func.count())
                .select_from(FeedbackAssignment)
                .where(
                    FeedbackAssignment.cycle_id == cycle.id,
                    FeedbackAssignment.status == AssignmentStatus.SUBMITTED,
                )
            )
        ).scalar_one()
    )
    if submitted > 0:
        raise Conflict(
            "This cycle already has responses — deleting it would destroy real "
            "feedback. Close it instead."
        )
    name = cycle.name
    await session.delete(cycle)
    await audit.record(
        session,
        action=AuditAction.CYCLE_DELETED,
        summary=f"{actor.user.full_name} deleted the cycle '{name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=cycle_id,
        target_label=name,
        request=request,
    )
    await session.commit()


# --- The reviewer's own queue ----------------------------------------------

def _assignment_summary(
    assignment: FeedbackAssignment,
    cycle: ReviewCycle,
    target: FeedbackTarget,
) -> AssignmentSummary:
    return AssignmentSummary(
        id=assignment.id,
        cycle_id=cycle.id,
        cycle_name=cycle.name,
        target_id=target.id,
        target_label=target.label,
        target_type=str(target.target_type),
        relationship=str(assignment.relationship_type),
        status=str(assignment.status),
        is_anonymous=cycle.is_anonymous,
        due_at=assignment.due_at,
        submitted_at=assignment.submitted_at,
    )


@assignments_router.get("/mine", response_model=list[AssignmentSummary])
async def my_assignments(
    session: DbSession, actor: CurrentUser, include_done: bool = False
) -> list[AssignmentSummary]:
    """Everything this person has been asked to complete.

    Restricted to open cycles: a draft cycle is still being built and a closed
    one is no longer accepting answers, so neither belongs in an inbox.
    """
    stmt = (
        select(FeedbackAssignment, ReviewCycle, FeedbackTarget)
        .join(ReviewCycle, ReviewCycle.id == FeedbackAssignment.cycle_id)
        .join(FeedbackTarget, FeedbackTarget.id == FeedbackAssignment.target_id)
        .where(
            FeedbackAssignment.reviewer_user_id == actor.id,
            ReviewCycle.status == CycleStatus.OPEN,
        )
        .order_by(FeedbackAssignment.due_at.asc().nullslast(), FeedbackTarget.label)
    )
    if not include_done:
        stmt = stmt.where(
            FeedbackAssignment.status.in_(
                [AssignmentStatus.PENDING, AssignmentStatus.IN_PROGRESS]
            )
        )
    rows = (await session.execute(stmt)).all()
    return [
        _assignment_summary(assignment, cycle, target)
        for assignment, cycle, target in rows
    ]


@assignments_router.get("/{assignment_id}", response_model=AssignmentForm)
async def get_assignment_form(
    assignment_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> AssignmentForm:
    row = (
        await session.execute(
            select(FeedbackAssignment, ReviewCycle, FeedbackTarget, FeedbackTemplateVersion)
            .join(ReviewCycle, ReviewCycle.id == FeedbackAssignment.cycle_id)
            .join(FeedbackTarget, FeedbackTarget.id == FeedbackAssignment.target_id)
            .join(
                FeedbackTemplateVersion,
                FeedbackTemplateVersion.id == ReviewCycle.template_version_id,
            )
            .where(FeedbackAssignment.id == assignment_id)
        )
    ).first()
    if row is None:
        raise NotFound("That assignment does not exist.")

    assignment, cycle, target, version = row
    # An assignment is personal. Not even a Client Admin gets to open someone
    # else's form, because doing so would let them see who was asked what and,
    # in an anonymous cycle, start narrowing down authorship.
    if assignment.reviewer_user_id != actor.id:
        raise PermissionDenied("This assignment belongs to someone else.")

    if assignment.status == AssignmentStatus.PENDING:
        assignment.status = AssignmentStatus.IN_PROGRESS
        assignment.started_at = datetime.now(UTC)
        await session.commit()

    form = validate_definition(version.definition)
    return AssignmentForm(
        assignment=_assignment_summary(assignment, cycle, target),
        form=form_payload(form),
    )


@assignments_router.post("/{assignment_id}/submit", response_model=MessageResponse)
async def submit_response(
    assignment_id: uuid.UUID,
    payload: SubmitResponseRequest,
    request: Request,
    session: DbSession,
    actor: CurrentUser,
) -> MessageResponse:
    row = (
        await session.execute(
            select(FeedbackAssignment, ReviewCycle, FeedbackTemplateVersion)
            .join(ReviewCycle, ReviewCycle.id == FeedbackAssignment.cycle_id)
            .join(
                FeedbackTemplateVersion,
                FeedbackTemplateVersion.id == ReviewCycle.template_version_id,
            )
            .where(FeedbackAssignment.id == assignment_id)
        )
    ).first()
    if row is None:
        raise NotFound("That assignment does not exist.")

    assignment, cycle, version = row
    if assignment.reviewer_user_id != actor.id:
        raise PermissionDenied("This assignment belongs to someone else.")
    if assignment.status == AssignmentStatus.SUBMITTED:
        raise Conflict("You have already submitted this feedback.")
    if not cycle.accepts_submissions:
        raise Conflict("This cycle is not accepting responses.")

    form = validate_definition(version.definition)
    scored = validate_answers(form, payload.answers, payload.comment)

    # A self-assessment is always attributable: it is the reviewee's own answer,
    # and hiding it from them would be nonsense.
    anonymous = cycle.is_anonymous and assignment.relationship_type != Relationship.SELF

    session.add(
        FeedbackResponse(
            org_id=cycle.org_id,
            cycle_id=cycle.id,
            target_id=assignment.target_id,
            template_version_id=version.id,
            # Both NULL for an anonymous response. This is the anonymity
            # guarantee: with no assignment_id and no reviewer_user_id there is
            # no join path from an answer back to the person who gave it.
            assignment_id=None if anonymous else assignment.id,
            reviewer_user_id=None if anonymous else actor.id,
            is_anonymous=anonymous,
            relationship_type=assignment.relationship_type,
            answers=scored.answers,
            comment=scored.comment,
            overall_score=scored.overall_score,
            answered_count=scored.answered_count,
            submitted_at=datetime.now(UTC),
        )
    )

    assignment.status = AssignmentStatus.SUBMITTED
    assignment.submitted_at = datetime.now(UTC)

    # The audit entry deliberately records *that* feedback was submitted and
    # never what it said or about whom, so the audit trail cannot be used to
    # reconstruct anonymous feedback.
    await audit.record(
        session,
        action=AuditAction.RESPONSE_SUBMITTED,
        summary=f"A response was submitted in '{cycle.name}'",
        org_id=cycle.org_id,
        actor=None if anonymous else actor.user,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"anonymous": anonymous, "relationship": str(assignment.relationship_type)},
        request=request,
    )
    await session.commit()

    return MessageResponse(
        message=(
            "Thank you. Your feedback was submitted anonymously and cannot be traced back to you."
            if anonymous
            else "Thank you. Your feedback was submitted."
        )
    )


@assignments_router.post("/{assignment_id}/decline", response_model=MessageResponse)
async def decline_assignment(
    assignment_id: uuid.UUID,
    payload: DeclineRequest,
    session: DbSession,
    actor: CurrentUser,
) -> MessageResponse:
    assignment = (
        await session.execute(
            select(FeedbackAssignment).where(FeedbackAssignment.id == assignment_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFound("That assignment does not exist.")
    if assignment.reviewer_user_id != actor.id:
        raise PermissionDenied("This assignment belongs to someone else.")
    if assignment.status == AssignmentStatus.SUBMITTED:
        raise Conflict("You have already submitted this feedback.")

    assignment.status = AssignmentStatus.DECLINED
    assignment.declined_reason = payload.reason
    await session.commit()
    return MessageResponse(message="Noted. You will not be reminded about this again.")


# --- Results ----------------------------------------------------------------

@router.get("/{cycle_id}/results")
async def cycle_results(
    cycle_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> dict[str, Any]:
    cycle = await _load_cycle(session, cycle_id)
    actor.assert_owns(cycle.created_by_id)
    return {
        "cycle": (await _detail(session, cycle)).model_dump(mode="json"),
        "rows": await results_service.cycle_overview(session, cycle=cycle),
    }


@router.get("/{cycle_id}/results/{target_id}")
async def target_results(
    cycle_id: uuid.UUID,
    target_id: uuid.UUID,
    session: DbSession,
    actor: CurrentUser,
) -> dict[str, Any]:
    """One person's results.

    Visible to an admin, to a manager, and to the reviewee themselves. Anyone
    else gets a 403 — and the suppression rules in the results service apply on
    top of that, so even a permitted viewer sees nothing until the threshold is
    met.
    """
    cycle = await _load_cycle(session, cycle_id)
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == target_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("That target does not exist.")

    is_admin = actor.role in {UserRole.SUPER_ADMIN, UserRole.CLIENT_ADMIN}
    # A manager only gets the manager-level view (which bypasses the
    # anonymity threshold the way an admin's does) on a cycle they themselves
    # ran — not on a colleague manager's, and not on the Client Admin's.
    owns_cycle = actor.role == UserRole.MANAGER and cycle.created_by_id == actor.id
    is_subject = target.subject_user_id == actor.id

    if not (is_admin or owns_cycle or is_subject):
        raise PermissionDenied("You cannot view these results.")

    return await results_service.target_results(
        session, cycle=cycle, target_id=target_id, viewer_is_admin=is_admin
    )


@me_router.get("/results")
async def my_results(session: DbSession, actor: CurrentUser) -> list[dict[str, Any]]:
    """Every closed cycle in which this person was reviewed."""
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.subject_user_id == actor.id)
        )
    ).scalar_one_or_none()
    if target is None:
        return []

    cycle_ids = (
        (
            await session.execute(
                select(FeedbackResponse.cycle_id)
                .where(FeedbackResponse.target_id == target.id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not cycle_ids:
        return []

    found = (
        (
            await session.execute(
                select(ReviewCycle)
                .where(ReviewCycle.id.in_(cycle_ids))
                .order_by(ReviewCycle.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return [
        await results_service.target_results(
            session, cycle=cycle, target_id=target.id, viewer_is_admin=False
        )
        for cycle in found
    ]
