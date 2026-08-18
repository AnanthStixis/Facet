"""Phase 2 seed: an org chart, a completed review cycle, and real responses.

Separate from `app.seed` so the Phase 1 seed stays a clean minimum. Run after it:

    python -m app.seed_cycle

Idempotent. Generates responses from a fixed random seed, so the dashboard
shows the same numbers on every machine and a screenshot stays reproducible.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
from app.models.catalog import FeedbackTemplate, FeedbackTemplateVersion
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    CycleStatus,
    Relationship,
    TemplateStatus,
    UserRole,
)
from app.models.organization import Organization
from app.models.user import User
from app.services import managers as managers_service
from app.services.cycles import GenerationPlan, generate_assignments
from app.services.forms import validate_definition

CYCLE_NAME = "H1 2026 Manager Effectiveness"

# Fixed seed: reproducible demo data beats novel-but-different-every-run.
RNG = random.Random(360)

COMMENTS = [
    "Clear about priorities and quick to unblock people. Would like more notice before scope changes.",
    "Consistently makes time for one-to-ones even in a busy delivery week.",
    "Decisions are well reasoned but the reasoning does not always reach the wider team.",
    "Gives credit publicly and handles difficult conversations privately, which builds a lot of trust.",
    "Would benefit from delegating more; a few decisions bottleneck unnecessarily.",
    "Feedback is specific and actionable rather than generic praise.",
    "Very approachable. I have never hesitated to raise a problem early.",
]


async def seed_cycle() -> None:
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

        org = (
            await session.execute(
                select(Organization).where(Organization.slug == "northwind-logistics")
            )
        ).scalar_one_or_none()
        if org is None:
            print("Run `python -m app.seed` first.")
            return

        people = {
            user.email: user
            for user in (
                await session.execute(select(User).where(User.org_id == org.id))
            )
            .scalars()
            .all()
        }

        # --- Org chart -----------------------------------------------------
        # Assignment generation reads manager relationships, so the chart has to
        # exist before a 360 can mean anything.
        chart = {
            "arun.k@northwind.example": ["priya.raman@northwind.example"],
            "sneha.d@northwind.example": ["priya.raman@northwind.example"],
            # Two managers on purpose — this is the one person in the seed
            # data the Employee Review manager checkbox list actually has
            # more than a single row to show.
            "vikram.s@northwind.example": [
                "sneha.d@northwind.example",
                "arun.k@northwind.example",
            ],
            "rahul.n@northwind.example": ["sneha.d@northwind.example"],
            "meera.j@northwind.example": ["arun.k@northwind.example"],
        }
        changed = 0
        for email, manager_emails in chart.items():
            person = people.get(email)
            if person is None:
                continue
            manager_ids = [people[m].id for m in manager_emails if m in people]
            if not manager_ids:
                continue
            current = await managers_service.get_manager_ids(session, person.id)
            if set(current) != set(manager_ids):
                await managers_service.set_managers(
                    session, org_id=org.id, employee_id=person.id, manager_ids=manager_ids
                )
                changed += 1
        await session.flush()

        # --- Cycle ---------------------------------------------------------
        cycle = (
            await session.execute(
                select(ReviewCycle).where(
                    ReviewCycle.org_id == org.id, ReviewCycle.name == CYCLE_NAME
                )
            )
        ).scalar_one_or_none()

        if cycle is not None:
            print(f"Cycle '{CYCLE_NAME}' already exists. Org chart links updated: {changed}.")
            await session.commit()
            return

        row = (
            await session.execute(
                select(FeedbackTemplate, FeedbackTemplateVersion)
                .join(
                    FeedbackTemplateVersion,
                    FeedbackTemplateVersion.template_id == FeedbackTemplate.id,
                )
                .where(
                    FeedbackTemplate.name == "Manager effectiveness (upward feedback)",
                    FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED,
                )
                .limit(1)
            )
        ).first()
        if row is None:
            print("The manager effectiveness template is missing. Run `python -m app.seed`.")
            return
        template, version = row

        now = datetime.now(UTC)
        cycle = ReviewCycle(
            org_id=org.id,
            name=CYCLE_NAME,
            description=(
                "Upward and peer feedback on the management team for the first "
                "half of 2026."
            ),
            template_version_id=version.id,
            status=CycleStatus.OPEN,
            is_anonymous=template.is_anonymous,
            min_responses_to_reveal=template.min_responses_to_reveal,
            opens_at=now - timedelta(days=10),
            closes_at=now + timedelta(days=11),
            opened_at=now - timedelta(days=10),
            created_by_id=people["priya.raman@northwind.example"].id,
        )
        session.add(cycle)
        await session.flush()

        managers = [
            person
            for person in people.values()
            if person.role in {UserRole.MANAGER, UserRole.CLIENT_ADMIN}
        ]
        result = await generate_assignments(
            session,
            cycle=cycle,
            reviewee_ids=[manager.id for manager in managers],
            plan=GenerationPlan(max_peers=4),
        )
        await session.flush()

        # --- Responses -----------------------------------------------------
        form = validate_definition(version.definition)
        scored_keys = form.scored_keys

        assignments = (
            (
                await session.execute(
                    select(FeedbackAssignment).where(
                        FeedbackAssignment.cycle_id == cycle.id
                    )
                )
            )
            .scalars()
            .all()
        )

        # Deliberately not 100%. A cycle at 78% completion is what the product
        # actually looks like in use, and it exercises the "chase the stragglers"
        # path that a fully complete demo would hide.
        responded = 0
        for assignment in assignments:
            if RNG.random() > 0.78:
                continue

            # Self-assessments skew high; upward feedback is more spread. Making
            # the demo data behave like real data means the self-awareness gap
            # on the results page shows something worth looking at.
            if assignment.relationship_type == Relationship.SELF:
                centre = 4.3
            elif assignment.relationship_type == Relationship.UPWARD:
                centre = 3.8
            else:
                centre = 4.0

            answers: dict[str, int] = {}
            for key in scored_keys:
                value = round(RNG.gauss(centre, 0.7))
                answers[key] = max(form.scale_min, min(form.scale_max, value))

            scores = list(answers.values())
            anonymous = (
                cycle.is_anonymous and assignment.relationship_type != Relationship.SELF
            )

            session.add(
                FeedbackResponse(
                    org_id=org.id,
                    cycle_id=cycle.id,
                    target_id=assignment.target_id,
                    template_version_id=version.id,
                    assignment_id=None if anonymous else assignment.id,
                    reviewer_user_id=None if anonymous else assignment.reviewer_user_id,
                    is_anonymous=anonymous,
                    relationship_type=assignment.relationship_type,
                    answers=answers,
                    comment=RNG.choice(COMMENTS) if RNG.random() > 0.45 else None,
                    overall_score=round(sum(scores) / len(scores), 2),
                    answered_count=len(answers),
                    submitted_at=now - timedelta(days=RNG.randint(1, 8)),
                )
            )
            assignment.status = AssignmentStatus.SUBMITTED
            assignment.submitted_at = now - timedelta(days=RNG.randint(1, 8))
            responded += 1

        await session.commit()

        print(f"Cycle '{CYCLE_NAME}' created.")
        print(f"  org chart links set   : {changed}")
        print(f"  reviewees             : {len(managers)}")
        print(f"  assignments generated : {result.created}")
        print(f"  responses submitted   : {responded}")
        print(f"  anonymous             : {cycle.is_anonymous} "
              f"(hidden below {cycle.min_responses_to_reveal} responses)")
        for warning in result.warnings:
            print(f"  note: {warning}")


if __name__ == "__main__":
    asyncio.run(seed_cycle())