"""Phase 4 seed: a proposal pipeline with feedback and real outcomes.

Run after the earlier seeds:

    python -m app.seed_proposals

Idempotent. The data is shaped so the scorecard shows something worth looking
at: proposals rated well on estimation accuracy mostly won, and the ones lost
on price are the ones prospects flagged as over-scoped. That is a synthetic
correlation, obviously — but it is the correlation the report exists to reveal,
and a demo where the numbers say nothing teaches nobody what the screen is for.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
from app.models.campaign import CampaignRecipient
from app.models.catalog import (
    Contact,
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import (
    CycleAudience,
    CycleStatus,
    LossReason,
    ProposalStage,
    RecipientStatus,
    Relationship,
    TargetType,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.proposal import Proposal
from app.models.user import User
from app.services.forms import validate_definition

RNG = random.Random(4004)

# (reference, title, client, contact email, value, effort, outcome, loss reason,
#  competitor, prospect rating band)
#
# The rating band drives the generated answers. "strong" proposals mostly win;
# "weak" ones mostly lose, and the loss reasons line up with what the prospect
# said. That is what makes the scorecard legible at a glance.
PROPOSALS = [
    ("PRO-2026-001", "Parata / NEXiA platform modernisation", "Parata",
     "agni.rao@parata.example", 480000, 640, ProposalStage.WON, None, None, "strong"),
    ("PRO-2026-002", "Gilbarco field service mobility SOW", "Gilbarco",
     "dana.f@gilbarco.example", 260000, 340, ProposalStage.WON, None, None, "strong"),
    ("PRO-2026-003", "BlueFleet telematics integration", "BlueFleet",
     "s.iyer@bluefleet.example", 195000, 250, ProposalStage.LOST,
     LossReason.PRICE, "Ardent Systems", "weak"),
    ("PRO-2026-004", "Harbour Freight warehouse analytics", "Harbour Freight",
     "m.oyelaran@harbourfreight.co", 320000, 410, ProposalStage.LOST,
     LossReason.SCOPE_MISMATCH, "Inhouse team", "weak"),
    ("PRO-2026-005", "Meridian Retail order orchestration", "Meridian Retail",
     "t.brennan@meridianretail.co", 410000, 520, ProposalStage.WON, None, None, "strong"),
    ("PRO-2026-006", "Sanko Logistics customs automation", "Sanko Logistics",
     "k.watanabe@sanko-logistics.co", 150000, 180, ProposalStage.LOST,
     LossReason.TIMELINE, "Kobayashi Digital", "mixed"),
    ("PRO-2026-007", "Vertex Parts supplier portal", "Vertex Parts",
     "a.silva@vertexparts.co", 225000, 290, ProposalStage.SUBMITTED, None, None, "mixed"),
    ("PRO-2026-008", "Dunlin Group network refresh", "Dunlin Group",
     None, 175000, 210, ProposalStage.DRAFT, None, None, None),
]

BANDS = {"strong": 4.4, "mixed": 3.5, "weak": 2.7}

COMMENTS = {
    "strong": [
        "Clearly the best-scoped response we received. The estimate matched our own internal figure closely.",
        "Technical approach was credible and the assumptions were stated openly rather than buried.",
    ],
    "mixed": [
        "Solid technically, but the timeline felt optimistic against our change freeze.",
        "Good proposal. Pricing structure was harder to compare against others than it needed to be.",
    ],
    "weak": [
        "The scope was considerably wider than we asked for, which made the price hard to justify internally.",
        "We did not feel the proposal engaged with the constraints we set out in the brief.",
    ],
}


async def seed_proposals() -> None:
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

        if (
            await session.execute(
                select(Proposal).where(Proposal.org_id == org.id).limit(1)
            )
        ).scalar_one_or_none() is not None:
            print("Proposals already seeded.")
            return

        row = (
            await session.execute(
                select(FeedbackTemplate, FeedbackTemplateVersion)
                .join(
                    FeedbackTemplateVersion,
                    FeedbackTemplateVersion.template_id == FeedbackTemplate.id,
                )
                .where(
                    FeedbackTemplate.target_type == TargetType.PROPOSAL,
                    FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED,
                )
                .limit(1)
            )
        ).first()
        if row is None:
            print("No published proposal template. Run `python -m app.seed`.")
            return
        template, version = row
        form = validate_definition(version.definition)
        scored_keys = form.scored_keys

        authors = (
            (
                await session.execute(
                    select(User).where(
                        User.org_id == org.id,
                        User.email.in_(
                            [
                                "arun.k@northwind.example",
                                "sneha.d@northwind.example",
                                "meera.j@northwind.example",
                            ]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

        contacts = {
            contact.email: contact
            for contact in (
                await session.execute(select(Contact).where(Contact.org_id == org.id))
            )
            .scalars()
            .all()
        }

        now = datetime.now(UTC)
        made = 0
        surveyed = 0
        responded = 0

        for index, (
            reference,
            title,
            client,
            contact_email,
            value,
            effort,
            stage,
            loss_reason,
            competitor,
            band,
        ) in enumerate(PROPOSALS):
            submitted_at = (
                None if stage == ProposalStage.DRAFT else now - timedelta(days=90 - index * 9)
            )
            decided_at = (
                now - timedelta(days=40 - index * 4) if stage.is_decided else None
            )
            won_amount = (
                Decimal(value) * Decimal("0.94") if stage == ProposalStage.WON else None
            )

            proposal = Proposal(
                org_id=org.id,
                reference=reference,
                title=title,
                client_name=client,
                summary=None,
                stage=stage,
                prospect_contact_id=(
                    contacts[contact_email].id if contact_email in contacts else None
                ),
                author_id=authors[index % len(authors)].id if authors else None,
                currency="USD",
                value_amount=Decimal(value),
                estimated_effort_days=effort,
                submitted_at=submitted_at,
                decided_at=decided_at,
                loss_reason=loss_reason,
                won_amount=won_amount,
                competitor=competitor,
                decision_due_on=(
                    (now + timedelta(days=18)).date()
                    if stage == ProposalStage.SUBMITTED
                    else None
                ),
            )
            session.add(proposal)
            await session.flush()
            made += 1

            if stage == ProposalStage.DRAFT:
                continue

            target = FeedbackTarget(
                org_id=org.id,
                target_type=TargetType.PROPOSAL,
                label=f"{title} ({client})",
                reference=f"proposal:{reference}",
                attributes={
                    "proposal_id": str(proposal.id),
                    "client": client,
                    "value": str(value),
                    "currency": "USD",
                },
            )
            session.add(target)
            await session.flush()
            proposal.target_id = target.id

            if band is None or contact_email not in contacts:
                continue

            cycle = ReviewCycle(
                org_id=org.id,
                name=f"Proposal feedback — {reference}",
                description=f"Prospect feedback on {title} for {client}.",
                template_version_id=version.id,
                status=CycleStatus.CLOSED if stage.is_decided else CycleStatus.OPEN,
                audience=CycleAudience.EXTERNAL,
                is_anonymous=template.is_anonymous,
                min_responses_to_reveal=template.min_responses_to_reveal,
                opens_at=submitted_at,
                opened_at=submitted_at,
                closes_at=(submitted_at or now) + timedelta(days=21),
                closed_at=decided_at,
            )
            session.add(cycle)
            await session.flush()

            recipient = CampaignRecipient(
                org_id=org.id,
                cycle_id=cycle.id,
                target_id=target.id,
                contact_id=contacts[contact_email].id,
                token_hash=f"seeded-{reference}-{RNG.random()}"[:64],
                status=RecipientStatus.SENT,
                batch=reference,
                expires_at=(submitted_at or now) + timedelta(days=21),
                sent_at=submitted_at,
            )
            session.add(recipient)
            await session.flush()
            surveyed += 1

            # Most, not all, prospects respond. A 100% response rate on a
            # cold proposal survey would be a fantasy.
            if RNG.random() > 0.82:
                continue

            centre = BANDS[band]
            answers = {
                key: max(form.scale_min, min(form.scale_max, round(RNG.gauss(centre, 0.5))))
                for key in scored_keys
            }
            scores = list(answers.values())
            session.add(
                FeedbackResponse(
                    org_id=org.id,
                    cycle_id=cycle.id,
                    target_id=target.id,
                    template_version_id=version.id,
                    recipient_id=None if cycle.is_anonymous else recipient.id,
                    is_anonymous=cycle.is_anonymous,
                    relationship_type=Relationship.EXTERNAL,
                    answers=answers,
                    comment=RNG.choice(COMMENTS[band]),
                    overall_score=round(sum(scores) / len(scores), 2),
                    answered_count=len(answers),
                    submitted_at=(submitted_at or now) + timedelta(days=6),
                )
            )
            recipient.status = RecipientStatus.SUBMITTED
            recipient.submitted_at = (submitted_at or now) + timedelta(days=6)
            responded += 1

        await session.commit()

        print("Proposal pipeline seeded.")
        print(f"  proposals recorded : {made}")
        print(f"  feedback requested : {surveyed}")
        print(f"  prospect responses : {responded}")
        print()
        print("Open Reports -> Proposal scorecard to see ratings beside outcomes.")


if __name__ == "__main__":
    asyncio.run(seed_proposals())
