"""Phase 6 seed: synthetic history so the predictive models have something to fit.

    python -m app.seed_history

**This is fabricated demonstration data.** Every proposal it creates is marked
`synthetic: true` in `attributes` so it can be found and deleted, and so nobody
mistakes it for a real pipeline.

It exists because the sufficiency gate does its job: with the 8 seeded
proposals from Phase 4, the win-probability model correctly refuses to fit, and
a demo of a feature that refuses to run teaches nobody what the feature is.
This generates enough decided history to cross the threshold — which is also
the honest way to show the gate working, since you can watch it flip from
"declined" to "fitted" as the data arrives.

The generated relationship is deliberately real but noisy: prospect rating
genuinely influences the outcome, with enough randomness that the model lands
somewhere plausible rather than at a suspicious 100%.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
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
    Relationship,
    TargetType,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.proposal import Proposal
from app.models.user import User
from app.services.forms import validate_definition

RNG = random.Random(606)

CLIENTS = [
    "Ardent Systems", "Cobalt Freight", "Dunbar Retail", "Eastgate Foods",
    "Ferrous Mining", "Granite Health", "Halcyon Media", "Ironwood Timber",
    "Juniper Labs", "Kestrel Air", "Larkspur Bank", "Marrow Textiles",
    "Northbeam Energy", "Orchard Grocers", "Pinnacle Sports", "Quarry Cement",
    "Ridgeline Hotels", "Sable Logistics", "Thornbury Legal", "Umber Paints",
    "Vale Pharma", "Westcliff Marine", "Yarrow Farms", "Zephyr Telecom",
]

LOSS_REASONS = [
    LossReason.PRICE, LossReason.TIMELINE, LossReason.TECHNICAL_FIT,
    LossReason.SCOPE_MISMATCH, LossReason.INCUMBENT,
]

COMMENTS = {
    "high": [
        "Clear technical approach and the estimate matched our internal figure closely.",
        "Best-scoped response we received. Assumptions were stated openly.",
        "Strong understanding of our constraints and a realistic delivery plan.",
    ],
    "mid": [
        "Solid proposal, though the timeline looked optimistic against our change freeze.",
        "Good technically. Pricing was harder to compare than it needed to be.",
    ],
    "low": [
        "Scope was considerably wider than we asked for, which made the price hard to justify.",
        "The proposal did not really engage with the constraints in our brief.",
    ],
}

COUNT = 46


async def seed_history() -> None:
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

        already = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Proposal)
                    .where(
                        Proposal.org_id == org.id,
                        Proposal.attributes["synthetic"].astext == "true",
                    )
                )
            ).scalar_one()
        )
        if already:
            print(f"Synthetic history already present ({already} proposals).")
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

        authors = (
            (await session.execute(select(User).where(User.org_id == org.id)))
            .scalars()
            .all()
        )
        contact = (
            await session.execute(select(Contact).where(Contact.org_id == org.id).limit(1))
        ).scalar_one_or_none()

        now = datetime.now(UTC)
        won = 0
        lost = 0
        surveyed = 0

        for index in range(COUNT):
            client = CLIENTS[index % len(CLIENTS)]
            reference = f"PRO-2025-{index + 100:03d}"

            # The underlying relationship the model is meant to discover:
            # better-rated proposals win more often, but not deterministically.
            quality = RNG.random()
            band = "high" if quality > 0.62 else "mid" if quality > 0.32 else "low"
            centre = {"high": 4.4, "mid": 3.6, "low": 2.8}[band]

            win_chance = 0.18 + 0.62 * quality
            is_won = RNG.random() < win_chance

            value = RNG.choice([90, 140, 180, 240, 320, 410, 520]) * 1000
            effort = int(value / RNG.uniform(700, 1100))
            submitted_at = now - timedelta(days=RNG.randint(120, 640))
            decided_at = submitted_at + timedelta(days=RNG.randint(9, 70))

            proposal = Proposal(
                org_id=org.id,
                reference=reference,
                title=f"{client} engagement",
                client_name=client,
                stage=ProposalStage.WON if is_won else ProposalStage.LOST,
                prospect_contact_id=contact.id if contact else None,
                author_id=authors[index % len(authors)].id if authors else None,
                currency="USD",
                value_amount=Decimal(value),
                estimated_effort_days=effort,
                submitted_at=submitted_at,
                decided_at=decided_at,
                loss_reason=None if is_won else RNG.choice(LOSS_REASONS),
                won_amount=(
                    Decimal(int(value * RNG.uniform(0.88, 1.02))) if is_won else None
                ),
                attributes={"synthetic": "true", "generated_for": "phase 6 demo"},
            )
            session.add(proposal)
            await session.flush()
            won += int(is_won)
            lost += int(not is_won)

            target = FeedbackTarget(
                org_id=org.id,
                target_type=TargetType.PROPOSAL,
                label=f"{client} engagement",
                reference=f"proposal:{reference}",
                attributes={"synthetic": "true", "proposal_id": str(proposal.id)},
            )
            session.add(target)
            await session.flush()
            proposal.target_id = target.id

            # Most, not all, proposals were surveyed — so the model also learns
            # from rows where the prospect never replied.
            if RNG.random() > 0.78:
                continue

            cycle = ReviewCycle(
                org_id=org.id,
                name=f"Proposal feedback — {reference}",
                template_version_id=version.id,
                status=CycleStatus.CLOSED,
                audience=CycleAudience.EXTERNAL,
                is_anonymous=template.is_anonymous,
                min_responses_to_reveal=template.min_responses_to_reveal,
                opens_at=submitted_at,
                opened_at=submitted_at,
                closes_at=decided_at,
                closed_at=decided_at,
            )
            session.add(cycle)
            await session.flush()

            answers = {
                key: max(form.scale_min, min(form.scale_max, round(RNG.gauss(centre, 0.5))))
                for key in form.scored_keys
            }
            scores = list(answers.values())
            session.add(
                FeedbackResponse(
                    org_id=org.id,
                    cycle_id=cycle.id,
                    target_id=target.id,
                    template_version_id=version.id,
                    is_anonymous=cycle.is_anonymous,
                    relationship_type=Relationship.EXTERNAL,
                    answers=answers,
                    comment=RNG.choice(COMMENTS[band]),
                    overall_score=round(sum(scores) / len(scores), 2),
                    answered_count=len(answers),
                    submitted_at=submitted_at + timedelta(days=RNG.randint(3, 14)),
                )
            )
            surveyed += 1

        await session.commit()

        print("Synthetic proposal history seeded (demonstration data).")
        print(f"  proposals : {COUNT} ({won} won, {lost} lost)")
        print(f"  surveyed  : {surveyed}")
        print()
        print("All are tagged attributes->>'synthetic' = 'true'. Remove with:")
        print("  DELETE FROM proposals WHERE attributes->>'synthetic' = 'true';")
        print()
        print("Now train: POST /api/v1/insights/models/train")


if __name__ == "__main__":
    asyncio.run(seed_history())
