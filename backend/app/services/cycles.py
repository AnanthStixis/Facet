"""Review cycle logic: assignment generation and completion accounting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationFailed
from app.models.catalog import FeedbackTarget
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    CycleStatus,
    Relationship,
    TargetType,
    UserRole,
    UserStatus,
)
from app.models.user import User
from app.services import managers as managers_service

# A 360 with thirty reviewers per person is a survey nobody finishes. Capping
# peers keeps the ask proportionate and the results comparable between people.
MAX_PEERS_PER_TARGET = 6


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    include_self: bool = True
    include_manager: bool = True
    include_upward: bool = True
    include_peers: bool = True
    max_peers: int = MAX_PEERS_PER_TARGET


@dataclass(slots=True)
class GenerationResult:
    created: int
    skipped_existing: int
    by_relationship: dict[str, int]
    warnings: list[str]


async def ensure_person_target(
    session: AsyncSession, *, org_id: uuid.UUID, user: User
) -> FeedbackTarget:
    """Find or create the feedback target that represents a person.

    People are targets like any product or proposal — that uniformity is what
    lets one aggregation path serve every domain instead of one per module.

    Scoped to the person's own EMPLOYEE/MANAGER target specifically: someone
    can also be the subject of a separate CLIENT-typed target (a Client
    Review "about" them, from the unified Create Feedback flow), and that is
    a distinct row on purpose — a template written for CLIENT feedback is not
    interchangeable with one written for internal EMPLOYEE/MANAGER feedback,
    so they cannot share a target without mixing incompatible questionnaires
    under one id. Filtering here is what keeps this call returning exactly
    one row instead of raising on multiple.
    """
    reference = f"user:{user.email}"
    existing = (
        await session.execute(
            select(FeedbackTarget).where(
                FeedbackTarget.org_id == org_id,
                FeedbackTarget.subject_user_id == user.id,
                FeedbackTarget.target_type.in_([TargetType.EMPLOYEE, TargetType.MANAGER]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    target = FeedbackTarget(
        org_id=org_id,
        target_type=(
            TargetType.MANAGER if user.role == UserRole.MANAGER else TargetType.EMPLOYEE
        ),
        label=user.full_name,
        reference=reference,
        subject_user_id=user.id,
    )
    session.add(target)
    await session.flush()
    return target


async def generate_assignments(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    reviewee_ids: list[uuid.UUID],
    plan: GenerationPlan,
    due_at: datetime | None = None,
    manager_ids: list[uuid.UUID] | None = None,
) -> GenerationResult:
    """Build the reviewer set for each reviewee from the org chart.

    Idempotent: re-running adds only what is missing. The unique constraint on
    (cycle, target, reviewer) is the backstop, but skipping in code keeps the
    result readable rather than surfacing as a constraint violation.

    `manager_ids`, when given, narrows a downward review (`plan.include_manager`)
    to just that subset of the reviewee's managers — the checked boxes on the
    Employee Review form. Left as None, every manager on record for the
    reviewee gets included, same as before an employee could have more than
    one. Only meaningful with a single reviewee; the bulk multi-reviewee path
    (the old Cycles.tsx flow) never passes this, so it keeps including every
    manager on record for each person, unchanged.
    """
    if cycle.status not in {CycleStatus.DRAFT, CycleStatus.OPEN}:
        raise Conflict("Assignments can only be generated for a draft or open cycle.")
    if not reviewee_ids:
        raise ValidationFailed("Select at least one person to be reviewed.")

    people = (
        (
            await session.execute(
                select(User).where(
                    User.org_id == cycle.org_id, User.status == UserStatus.ACTIVE
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {person.id: person for person in people}
    person_ids = list(by_id.keys())

    # manager_id -> employee_ids who report to them, and the reverse
    # employee_id -> manager_ids — both directions of the same many-to-many,
    # since a person with 2-3 managers has to show up under each of them for
    # "their direct reports"/"their peers" to be correct, and has to yield
    # all of their own managers for "their manager review" to be correct.
    reports_by_manager = await managers_service.get_reports_map(session, person_ids)
    managers_by_employee = await managers_service.get_manager_ids_map(session, person_ids)

    existing_pairs = {
        (row.target_id, row.reviewer_user_id)
        for row in (
            await session.execute(
                select(
                    FeedbackAssignment.target_id, FeedbackAssignment.reviewer_user_id
                ).where(FeedbackAssignment.cycle_id == cycle.id)
            )
        ).all()
    }

    created = 0
    skipped = 0
    counts: dict[str, int] = {}
    warnings: list[str] = []

    for reviewee_id in reviewee_ids:
        reviewee = by_id.get(reviewee_id)
        if reviewee is None:
            warnings.append("A selected person is not an active member of this organization.")
            continue

        target = await ensure_person_target(
            session, org_id=cycle.org_id, user=reviewee
        )

        pairs: list[tuple[User, Relationship]] = []

        if plan.include_self:
            pairs.append((reviewee, Relationship.SELF))

        if plan.include_manager:
            reviewee_manager_ids = managers_by_employee.get(reviewee.id, [])
            chosen_ids = (
                [m for m in manager_ids if m in reviewee_manager_ids]
                if manager_ids is not None
                else reviewee_manager_ids
            )
            if chosen_ids:
                for manager_id in chosen_ids:
                    manager = by_id.get(manager_id)
                    if manager is not None:
                        pairs.append((manager, Relationship.MANAGER))
            else:
                warnings.append(
                    f"{reviewee.full_name} has no manager on record, so no downward review was created."
                )

        if plan.include_upward:
            direct_reports = [
                by_id[employee_id]
                for employee_id in reports_by_manager.get(reviewee.id, [])
                if employee_id in by_id
            ]
            for report in direct_reports:
                pairs.append((report, Relationship.UPWARD))
            if not direct_reports and reviewee.role == UserRole.MANAGER:
                warnings.append(
                    f"{reviewee.full_name} is a manager with no direct reports recorded."
                )

        if plan.include_peers:
            sibling_ids: dict[uuid.UUID, User] = {}
            for manager_id in managers_by_employee.get(reviewee.id, []):
                for employee_id in reports_by_manager.get(manager_id, []):
                    if employee_id != reviewee.id and employee_id in by_id:
                        sibling_ids[employee_id] = by_id[employee_id]
            # Deterministic ordering, so re-running the generator does not pick
            # a different sample of peers and skew a comparison between cycles.
            siblings = sorted(sibling_ids.values(), key=lambda person: str(person.id))
            for sibling in siblings[: plan.max_peers]:
                pairs.append((sibling, Relationship.PEER))

        for reviewer, relationship in pairs:
            if (target.id, reviewer.id) in existing_pairs:
                skipped += 1
                continue
            existing_pairs.add((target.id, reviewer.id))
            session.add(
                FeedbackAssignment(
                    org_id=cycle.org_id,
                    cycle_id=cycle.id,
                    target_id=target.id,
                    reviewer_user_id=reviewer.id,
                    relationship_type=relationship,
                    status=AssignmentStatus.PENDING,
                    due_at=due_at or cycle.closes_at,
                )
            )
            created += 1
            counts[relationship.value] = counts.get(relationship.value, 0) + 1

    await session.flush()
    # Deduplicate while preserving order, so the caller sees each distinct
    # problem once rather than once per reviewee.
    seen: set[str] = set()
    unique_warnings = [w for w in warnings if not (w in seen or seen.add(w))]

    return GenerationResult(
        created=created,
        skipped_existing=skipped,
        by_relationship=counts,
        warnings=unique_warnings,
    )


async def cycle_progress(
    session: AsyncSession, cycle_id: uuid.UUID
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(FeedbackAssignment.status, func.count())
            .where(FeedbackAssignment.cycle_id == cycle_id)
            .group_by(FeedbackAssignment.status)
        )
    ).all()
    counts = {str(status): count for status, count in rows}
    total = sum(counts.values())
    submitted = counts.get(str(AssignmentStatus.SUBMITTED), 0)
    return {
        "total": total,
        "submitted": submitted,
        "pending": counts.get(str(AssignmentStatus.PENDING), 0),
        "in_progress": counts.get(str(AssignmentStatus.IN_PROGRESS), 0),
        "declined": counts.get(str(AssignmentStatus.DECLINED), 0),
        "completion_pct": round(100 * submitted / total) if total else 0,
    }


async def maybe_auto_close(session: AsyncSession, cycle: ReviewCycle) -> bool:
    """Close an open internal cycle once every reviewer has either submitted
    or declined — no one left who could still respond. Returns True if it
    closed the cycle.

    Deadline-based closing already happens in the `expire` scheduled task;
    this is the "everyone's done, don't make them wait for the deadline"
    counterpart, run inline right after a submission is recorded.
    """
    if cycle.status != CycleStatus.OPEN:
        return False
    progress = await cycle_progress(session, cycle.id)
    if progress["total"] == 0:
        return False
    if progress["pending"] or progress["in_progress"]:
        return False
    cycle.status = CycleStatus.CLOSED
    cycle.closed_at = datetime.now(UTC)
    return True


async def response_counts_by_target(
    session: AsyncSession, cycle_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    rows = (
        await session.execute(
            select(FeedbackResponse.target_id, func.count())
            .where(FeedbackResponse.cycle_id == cycle_id)
            .group_by(FeedbackResponse.target_id)
        )
    ).all()
    return {target_id: count for target_id, count in rows}