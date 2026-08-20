"""The unified "Create Feedback" flow: one call, no intermediate steps.

Cycles and campaigns already share one lifecycle (`ReviewCycle` with an
`audience`), one assignment/recipient model, and one results pipeline — the
existing UI just made a client walk through 3-4 separate calls (create,
assign/add-recipients, open, send) to use that. `create_and_send` collapses
that into the single atomic action the client asked for: pick a kind, pick a
template, pick who it's about, click once.

Every branch below reuses the exact same building blocks `Cycles.tsx` and
`Campaigns.tsx` already call from the frontend (`generate_assignments`,
`ensure_person_target`, `add_recipients`, `send_pending`) — this module is
purely an orchestrator, not a new source of truth for any of that logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.config import settings
from app.models.campaign import CampaignRecipient
from app.models.catalog import (
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.cycle import FeedbackAssignment, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    CycleAudience,
    CycleStatus,
    Relationship,
    TargetType,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.user import User
from app.services import campaigns as campaign_service
from app.services import cycles as cycle_service
from app.services import email as email_service
from app.core import security

FeedbackKind = Literal[
    "client", "employee", "management", "product", "service", "proposal"
]

INTERNAL_KINDS = {"employee", "management"}
EXTERNAL_KINDS = {"client", "product", "service", "proposal"}

# What TargetType a kind's template must be written for. "client" can go
# either to a named client relationship (find-or-create by label, like
# product/service/proposal) or, when about_user_id is set, to that person's
# own target (still TargetType.CLIENT — the person just also has one).
KIND_TARGET_TYPE: dict[str, TargetType] = {
    "client": TargetType.CLIENT,
    "employee": TargetType.EMPLOYEE,
    "management": TargetType.MANAGER,
    "product": TargetType.PRODUCT,
    "service": TargetType.SERVICE,
    "proposal": TargetType.PROPOSAL,
}


@dataclass(slots=True)
class CreateAndSendResult:
    cycle: ReviewCycle
    warnings: list[str]


async def _load_published_template(
    session: AsyncSession, *, template_id: uuid.UUID, expect_type: TargetType
) -> tuple[FeedbackTemplate, FeedbackTemplateVersion]:
    template = (
        await session.execute(
            select(FeedbackTemplate).where(FeedbackTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if template is None:
        raise NotFound("That template does not exist.")
    if str(template.target_type) != str(expect_type):
        raise ValidationFailed(
            f"'{template.name}' is written for {template.target_type} feedback, "
            f"which does not match this feedback type."
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
        raise Conflict("That template has no published version yet. Publish it first.")
    return template, version


async def _find_or_create_labeled_target(
    session: AsyncSession, *, org_id: uuid.UUID, target_type: TargetType, label: str
) -> FeedbackTarget:
    """Same find-or-create-by-label pattern as `campaigns.py::create_campaign`."""
    clean = label.strip()
    target = (
        await session.execute(
            select(FeedbackTarget).where(
                FeedbackTarget.org_id == org_id,
                FeedbackTarget.target_type == target_type,
                func.lower(FeedbackTarget.label) == clean.lower(),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        target = FeedbackTarget(
            org_id=org_id,
            target_type=target_type,
            label=clean,
            reference=f"{target_type}:{uuid.uuid4().hex[:10]}",
        )
        session.add(target)
        await session.flush()
    return target


def _org_branding(org: Organization) -> email_service.Branding:
    """Same branding-construction shape as everywhere else email gets sent
    (see `api/v1/users.py::invite_user`) — kept as one function here since
    both internal-delivery branches below need it."""
    return email_service.Branding(
        org_name=org.name,
        accent_color=org.branding.accent_color if org.branding else "#B4633A",
        logo_url=(
            f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
            if org.branding and org.branding.logo_path
            else None
        ),
        footer_note=org.branding.email_footer_note if org.branding else None,
    )


async def _notify_new_assignments(
    session: AsyncSession,
    *,
    org: Organization,
    cycle: ReviewCycle,
    assignments: list[FeedbackAssignment],
    subject_label: str,
) -> list[str]:
    """One "you have been asked" email per assignment, additional to — never
    instead of — the "My feedback" queue entry each one already has the
    moment its `FeedbackAssignment` row exists.

    Each assignment gets its own single-use token here, the same
    generate_token()/hash_token() pair used for invitations and password
    resets — only the raw token is ever put in the email; the row stores
    the hash. This is what lets the link work without login, the same
    security property `campaign_recipients.token_hash` already gives
    external respondents, rather than trusting the assignment's plain
    database id to be secret.
    """
    if not assignments:
        return []
    reviewer_ids = {a.reviewer_user_id for a in assignments}
    reviewers = {
        user.id: user
        for user in (
            (await session.execute(select(User).where(User.id.in_(reviewer_ids))))
            .scalars()
            .all()
        )
    }
    branding = _org_branding(org)
    warnings: list[str] = []
    for assignment in assignments:
        reviewer = reviewers.get(assignment.reviewer_user_id)
        if reviewer is None:
            continue
        raw_token = security.generate_token()
        assignment.token_hash = security.hash_token(raw_token)
        sent = await email_service.send_assignment_notice(
            to=reviewer.email,
            full_name=reviewer.full_name,
            org_name=org.name,
            subject_label=subject_label,
            cycle_name=cycle.name,
            link=f"{settings.public_app_url}/give-feedback/{raw_token}",
            due_at=cycle.closes_at,
            branding=branding,
        )
        if not sent:
            warnings.append(f"Could not email {reviewer.full_name}.")
    await session.flush()
    return warnings


async def create_and_send(
    session: AsyncSession,
    *,
    org: Organization,
    actor: User,
    kind: FeedbackKind,
    template_id: uuid.UUID,
    name: str,
    closes_at: datetime | None = None,
    reviewee_user_id: uuid.UUID | None = None,
    about_user_id: uuid.UUID | None = None,
    contact_ids: list[uuid.UUID] | None = None,
    target_label: str | None = None,
    manager_ids: list[uuid.UUID] | None = None,
    audience: Literal["external", "internal"] = "external",
    recipient_user_ids: list[uuid.UUID] | None = None,
) -> CreateAndSendResult:
    """Create a cycle for one of the 6 kinds and send it in one call.

    - employee / management: internal, org-chart-driven, opened immediately
      (no separate "send" step — an open internal cycle already puts the
      assignment in each reviewer's "My feedback" queue).
    - client / product / service / proposal: external, contact-based, opens
      and sends invitations to `contact_ids` in the same call.
    - client with `about_user_id` set: additionally targets that employee's
      own person-target (via `ensure_person_target`), so their answers also
      show up on that person's own results — the cross-linking the client
      specifically asked for.
    - employee with `manager_ids` set: narrows which of the reviewee's
      managers actually get an assignment to the checked subset, instead of
      every manager on record.
    - product/service with `audience="internal"`: same external-typed
      target (a Product or Service), but delivered to a directly-chosen set
      of internal staff instead of external client contacts — each gets a
      direct `FeedbackAssignment` in their own "My feedback" queue, the same
      delivery mechanism employee/management use, rather than an emailed
      one-time link. Validated one layer up in `FeedbackCreateRequest`, so
      by the time this runs `audience="internal"` only ever arrives for
      `kind` in `{"product", "service"}`. Nothing below is kind-specific —
      it reads `expect_type` off `kind` the same as every other branch — so
      no other change was needed here to extend this from product to
      service.
    """
    if org.id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")

    expect_type = KIND_TARGET_TYPE[kind]
    template, version = await _load_published_template(
        session, template_id=template_id, expect_type=expect_type
    )

    clean_name = name.strip()
    if not clean_name:
        raise ValidationFailed("Give this round a name.")

    warnings: list[str] = []

    # --- Internal kinds: employee, management --------------------------
    if kind in INTERNAL_KINDS:
        if reviewee_user_id is None:
            raise ValidationFailed("Choose who this feedback is about.")

        reviewee = (
            await session.execute(select(User).where(User.id == reviewee_user_id))
        ).scalar_one_or_none()
        if reviewee is None or reviewee.org_id != org.id:
            raise NotFound("That person does not exist.")

        cycle = ReviewCycle(
            org_id=org.id,
            name=clean_name,
            template_version_id=version.id,
            status=CycleStatus.DRAFT,
            audience=CycleAudience.INTERNAL,
            is_anonymous=template.is_anonymous,
            min_responses_to_reveal=template.min_responses_to_reveal,
            closes_at=closes_at,
            created_by_id=actor.id,
        )
        session.add(cycle)
        await session.flush()

        if kind == "employee":
            plan = cycle_service.GenerationPlan(
                include_self=True,
                include_manager=True,
                include_upward=False,
                include_peers=True,
            )
        else:  # management
            plan = cycle_service.GenerationPlan(
                include_self=False,
                include_manager=False,
                include_upward=True,
                include_peers=False,
            )

        result = await cycle_service.generate_assignments(
            session,
            cycle=cycle,
            reviewee_ids=[reviewee_user_id],
            plan=plan,
            due_at=closes_at,
            manager_ids=manager_ids if kind == "employee" else None,
        )
        warnings.extend(result.warnings)

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
            raise Conflict(
                "No reviewers could be generated for this person "
                "(check they have a manager/direct reports on record)."
            )

        cycle.status = CycleStatus.OPEN
        cycle.opened_at = datetime.now(UTC)
        await session.flush()
        if result.created_assignments:
            warnings.extend(
                await _notify_new_assignments(
                    session,
                    org=org,
                    cycle=cycle,
                    assignments=result.created_assignments,
                    subject_label=reviewee.full_name,
                )
            )

        return CreateAndSendResult(cycle=cycle, warnings=warnings)

    # --- External-typed kind delivered internally: Product review sent to
    # chosen staff, not external contacts -------------------------------
    if audience == "internal":
        if not recipient_user_ids:
            raise ValidationFailed("Choose at least one internal recipient.")

        label = (target_label or "").strip()
        if not label:
            raise ValidationFailed("Say what this feedback is about.")
        target = await _find_or_create_labeled_target(
            session, org_id=org.id, target_type=expect_type, label=label
        )

        reviewers = (
            (
                await session.execute(
                    select(User).where(
                        User.id.in_(recipient_user_ids), User.org_id == org.id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not reviewers:
            raise Conflict("None of the selected recipients could be found.")
        missing = len(set(recipient_user_ids)) - len(reviewers)
        if missing > 0:
            warnings.append(f"{missing} selected recipient(s) were not found.")

        now = datetime.now(UTC)
        cycle = ReviewCycle(
            org_id=org.id,
            name=clean_name,
            template_version_id=version.id,
            status=CycleStatus.OPEN,
            audience=CycleAudience.INTERNAL,
            is_anonymous=template.is_anonymous,
            min_responses_to_reveal=template.min_responses_to_reveal,
            target_id=target.id,
            opens_at=now,
            opened_at=now,
            closes_at=closes_at,
            created_by_id=actor.id,
        )
        session.add(cycle)
        await session.flush()

        new_assignments: list[FeedbackAssignment] = []
        for reviewer in reviewers:
            assignment = FeedbackAssignment(
                org_id=org.id,
                cycle_id=cycle.id,
                target_id=target.id,
                reviewer_user_id=reviewer.id,
                relationship_type=Relationship.PEER,
                status=AssignmentStatus.PENDING,
                due_at=closes_at,
            )
            session.add(assignment)
            new_assignments.append(assignment)
        await session.flush()

        warnings.extend(
            await _notify_new_assignments(
                session, org=org, cycle=cycle, assignments=new_assignments, subject_label=label
            )
        )

        return CreateAndSendResult(cycle=cycle, warnings=warnings)

    # --- External kinds: client, product, service, proposal ------------
    if not contact_ids:
        raise ValidationFailed("Select at least one recipient.")

    about_user: User | None = None
    if kind == "client" and about_user_id is not None:
        about_user = (
            await session.execute(select(User).where(User.id == about_user_id))
        ).scalar_one_or_none()
        if about_user is None or about_user.org_id != org.id:
            raise NotFound("That person does not exist.")
        # This is what makes a Client Review's answers also show up on the
        # employee's own results — the same find-or-create a person-target
        # already uses internally, just pointed at externally-collected
        # answers instead of internal ones.
        target = await cycle_service.ensure_person_target(
            session, org_id=org.id, user=about_user
        )
        # A person's target is normally EMPLOYEE/MANAGER (set by
        # ensure_person_target based on role) — a Client Review about them
        # still needs a CLIENT-typed template, so the target itself is
        # re-typed to CLIENT the first time this happens. If the person
        # already has an EMPLOYEE/MANAGER target from internal cycles, this
        # would collide with those cycles' own target-type expectations, so
        # instead we find-or-create a *separate* CLIENT target scoped to the
        # same person via the label, rather than mutating their existing one.
        if target.target_type != TargetType.CLIENT:
            target = await _find_or_create_labeled_target(
                session,
                org_id=org.id,
                target_type=TargetType.CLIENT,
                label=f"{about_user.full_name}",
            )
            target.subject_user_id = about_user.id
            await session.flush()
    else:
        label = (target_label or "").strip()
        if not label:
            raise ValidationFailed("Say what this feedback is about.")
        target = await _find_or_create_labeled_target(
            session, org_id=org.id, target_type=expect_type, label=label
        )

    cycle = ReviewCycle(
        org_id=org.id,
        name=clean_name,
        template_version_id=version.id,
        status=CycleStatus.DRAFT,
        audience=CycleAudience.EXTERNAL,
        is_anonymous=template.is_anonymous,
        min_responses_to_reveal=template.min_responses_to_reveal,
        target_id=target.id,
        closes_at=closes_at,
        created_by_id=actor.id,
    )
    session.add(cycle)
    await session.flush()

    add_result = await campaign_service.add_recipients(
        session, cycle=cycle, target_id=target.id, contact_ids=contact_ids
    )
    warnings.extend(add_result.warnings)

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
        raise Conflict("None of the selected recipients could be added.")

    cycle.status = CycleStatus.OPEN
    cycle.opened_at = datetime.now(UTC)
    await session.flush()

    send_result = await campaign_service.send_pending(session, cycle=cycle, org=org)
    if send_result.errors:
        warnings.append(
            f"{send_result.failed} invitation(s) failed to send: "
            f"{', '.join(send_result.errors[:5])}"
        )

    return CreateAndSendResult(cycle=cycle, warnings=warnings)