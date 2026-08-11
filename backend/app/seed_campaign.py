"""Phase 3 seed: an external client-feedback campaign with real responses.

Run after `app.seed` and `app.seed_cycle`:

    python -m app.seed_campaign

Idempotent. Creates a service-feedback campaign aimed at client contacts, sends
the invitations through the configured mail backend, and submits a realistic
subset so the delivery funnel and results pages have something to show.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

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
    RecipientStatus,
    Relationship,
    TargetType,
    TemplateStatus,
)
from app.models.organization import Organization
from app.services.campaigns import add_recipients, send_pending
from app.services.forms import validate_definition

CAMPAIGN_NAME = "Q3 2026 Client Experience"
RNG = random.Random(2026)

EXTRA_CONTACTS = [
    ("m.oyelaran@harbourfreight.co", "Modupe Oyelaran", "Harbour Freight", "COO"),
    ("t.brennan@meridianretail.co", "Tom Brennan", "Meridian Retail", "Head of Supply Chain"),
    ("k.watanabe@sanko-logistics.co", "Kenji Watanabe", "Sanko Logistics", "Director"),
    ("a.silva@vertexparts.co", "Ana Silva", "Vertex Parts", "Procurement Lead"),
    ("p.novak@dunlin.co", "Petra Novak", "Dunlin Group", "Operations Manager"),
]

COMMENTS = [
    "Delivery ran to schedule and the weekly updates were genuinely useful rather than box-ticking.",
    "Strong technical team. Commercial conversations took longer than they needed to.",
    "The handover documentation was the best we have received from any supplier this year.",
    "Responsive when things went wrong, which matters more than nothing ever going wrong.",
    "Would have liked earlier visibility of the resourcing changes mid-project.",
]


async def seed_campaign() -> None:
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

        existing = (
            await session.execute(
                select(ReviewCycle).where(
                    ReviewCycle.org_id == org.id, ReviewCycle.name == CAMPAIGN_NAME
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Campaign '{CAMPAIGN_NAME}' already exists.")
            return

        # --- Contacts -------------------------------------------------------
        added_contacts = 0
        for email, name, company, title in EXTRA_CONTACTS:
            found = (
                await session.execute(
                    select(Contact).where(
                        Contact.org_id == org.id, Contact.email == email
                    )
                )
            ).scalar_one_or_none()
            if found is None:
                session.add(
                    Contact(
                        org_id=org.id,
                        email=email,
                        full_name=name,
                        company=company,
                        job_title=title,
                        tags=["client"],
                    )
                )
                added_contacts += 1
        await session.flush()

        # One contact opts out, so the send path's unsubscribe handling is
        # visible in the seeded data rather than only in a test.
        opted_out = (
            await session.execute(
                select(Contact).where(
                    Contact.org_id == org.id,
                    Contact.email == "p.novak@dunlin.co",
                )
            )
        ).scalar_one_or_none()
        if opted_out and opted_out.unsubscribed_at is None:
            opted_out.unsubscribed_at = datetime.now(UTC) - timedelta(days=30)

        # --- Template and subject -------------------------------------------
        row = (
            await session.execute(
                select(FeedbackTemplate, FeedbackTemplateVersion)
                .join(
                    FeedbackTemplateVersion,
                    FeedbackTemplateVersion.template_id == FeedbackTemplate.id,
                )
                .where(
                    FeedbackTemplate.name == "Post-delivery client satisfaction",
                    FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED,
                )
                .limit(1)
            )
        ).first()
        if row is None:
            print("The client satisfaction template is missing. Run `python -m app.seed`.")
            return
        template, version = row

        target = (
            await session.execute(
                select(FeedbackTarget).where(
                    FeedbackTarget.org_id == org.id,
                    FeedbackTarget.target_type == TargetType.SERVICE,
                    FeedbackTarget.reference == "svc:integration",
                )
            )
        ).scalar_one()

        now = datetime.now(UTC)
        cycle = ReviewCycle(
            org_id=org.id,
            name=CAMPAIGN_NAME,
            description=(
                "Client satisfaction on the Managed Integration Service after "
                "the Q3 delivery milestone."
            ),
            template_version_id=version.id,
            status=CycleStatus.OPEN,
            audience=CycleAudience.EXTERNAL,
            is_anonymous=template.is_anonymous,
            min_responses_to_reveal=template.min_responses_to_reveal,
            opens_at=now - timedelta(days=6),
            opened_at=now - timedelta(days=6),
            closes_at=now + timedelta(days=15),
        )
        session.add(cycle)
        await session.flush()

        contacts = (
            (
                await session.execute(
                    select(Contact).where(Contact.org_id == org.id)
                )
            )
            .scalars()
            .all()
        )
        result = await add_recipients(
            session,
            cycle=cycle,
            target_id=target.id,
            contact_ids=[contact.id for contact in contacts],
            batch="cohort 1",
        )
        await session.flush()

        sent = await send_pending(session, cycle=cycle, org=org)
        await session.flush()

        # --- Responses ------------------------------------------------------
        form = validate_definition(version.definition)
        scored_keys = form.scored_keys

        recipients = (
            (
                await session.execute(
                    select(CampaignRecipient).where(
                        CampaignRecipient.cycle_id == cycle.id,
                        CampaignRecipient.status == RecipientStatus.SENT,
                    )
                )
            )
            .scalars()
            .all()
        )

        opened = 0
        submitted = 0
        for recipient in recipients:
            # A realistic external funnel: most invitations get opened, rather
            # fewer get completed. A seed that shows 100% would hide the
            # follow-up workflow this screen exists to support.
            if RNG.random() > 0.85:
                continue
            recipient.status = RecipientStatus.OPENED
            recipient.first_opened_at = now - timedelta(days=RNG.randint(1, 5))
            recipient.open_count = RNG.randint(1, 3)
            opened += 1

            if RNG.random() > 0.65:
                continue

            answers = {
                key: max(form.scale_min, min(form.scale_max, round(RNG.gauss(4.1, 0.7))))
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
                    comment=RNG.choice(COMMENTS) if RNG.random() > 0.4 else None,
                    overall_score=round(sum(scores) / len(scores), 2),
                    answered_count=len(answers),
                    submitted_at=now - timedelta(days=RNG.randint(0, 4)),
                )
            )
            recipient.status = RecipientStatus.SUBMITTED
            recipient.submitted_at = now - timedelta(days=RNG.randint(0, 4))
            submitted += 1

        await session.commit()

        print(f"Campaign '{CAMPAIGN_NAME}' created.")
        print(f"  contacts added     : {added_contacts}")
        print(f"  recipients         : {result.added}")
        print(f"  skipped unsubscribed: {result.skipped_unsubscribed}")
        print(f"  invitations sent   : {sent.sent}")
        print(f"  opened             : {opened}")
        print(f"  submitted          : {submitted}")
        print(f"  anonymous          : {cycle.is_anonymous}")
        print()
        print("Invitation emails were written to backend/var/outbox as .eml files.")


if __name__ == "__main__":
    asyncio.run(seed_campaign())
