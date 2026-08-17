"""External campaign logic: recipients, one-time links, and bulk send."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.security import generate_token, hash_token
from app.models.campaign import CampaignRecipient
from app.models.catalog import Contact, FeedbackTarget
from app.models.cycle import ReviewCycle
from app.models.enums import CycleStatus, RecipientStatus
from app.models.organization import Organization
from app.schemas.settings import OrgSettings
from app.services import email as email_service

log = get_logger("facet.campaigns")

# Bulk sends are chunked so one enormous cohort cannot monopolise a worker or
# trip a provider's per-connection limits.
SEND_CHUNK = 50


@dataclass(slots=True)
class AddResult:
    added: int
    skipped_existing: int
    skipped_unsubscribed: int
    warnings: list[str]


@dataclass(slots=True)
class SendResult:
    sent: int
    failed: int
    skipped: int
    errors: list[str]


def _link(raw_token: str) -> str:
    return f"{settings.public_app_url}/f/{raw_token}"


async def add_recipients(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    target_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
    batch: str | None = None,
) -> AddResult:
    """Generate a one-time link per contact.

    Idempotent against the unique constraint: re-running with an overlapping
    list adds only the contacts that do not already have a link for this
    target, rather than issuing a second link that would let one person answer
    twice.
    """
    if cycle.status not in {CycleStatus.DRAFT, CycleStatus.OPEN}:
        raise Conflict("Recipients can only be added to a draft or open campaign.")
    if not contact_ids:
        raise ValidationFailed("Select at least one recipient.")

    target = (
        await session.execute(
            select(FeedbackTarget).where(
                FeedbackTarget.id == target_id, FeedbackTarget.org_id == cycle.org_id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("That feedback target does not exist.")

    contacts = (
        (
            await session.execute(
                select(Contact).where(
                    Contact.org_id == cycle.org_id, Contact.id.in_(contact_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    existing = {
        row[0]
        for row in (
            await session.execute(
                select(CampaignRecipient.contact_id).where(
                    CampaignRecipient.cycle_id == cycle.id,
                    CampaignRecipient.target_id == target_id,
                )
            )
        ).all()
    }

    expires_at = cycle.closes_at or (
        datetime.now(UTC) + timedelta(days=settings.feedback_link_ttl_days)
    )

    added = 0
    skipped_existing = 0
    skipped_unsubscribed = 0
    warnings: list[str] = []

    for contact in contacts:
        if contact.id in existing:
            skipped_existing += 1
            continue
        if contact.unsubscribed_at is not None:
            # Honouring an unsubscribe is not optional, and quietly sending
            # anyway is how a domain's reputation gets destroyed.
            skipped_unsubscribed += 1
            warnings.append(f"{contact.email} has unsubscribed and was skipped.")
            continue

        # A placeholder hash. The real token is minted at send time, so a link
        # that was prepared but never delivered is never valid.
        session.add(
            CampaignRecipient(
                org_id=cycle.org_id,
                cycle_id=cycle.id,
                target_id=target_id,
                contact_id=contact.id,
                token_hash=hash_token(generate_token()),
                status=RecipientStatus.PENDING,
                batch=batch,
                expires_at=expires_at,
            )
        )
        added += 1

    missing = len(contact_ids) - len(contacts)
    if missing > 0:
        warnings.append(f"{missing} selected contact(s) were not found.")

    await session.flush()
    return AddResult(
        added=added,
        skipped_existing=skipped_existing,
        skipped_unsubscribed=skipped_unsubscribed,
        warnings=warnings,
    )


async def send_pending(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    org: Organization,
    only_recipient_id: uuid.UUID | None = None,
    resend: bool = False,
) -> SendResult:
    """Send invitations for every recipient that has not had one.

    Tokens are regenerated at send time. A link that was created but never
    delivered has no reason to stay valid, and reissuing means a send retry
    after a mail outage does not depend on a raw token nobody kept.
    """
    if cycle.status != CycleStatus.OPEN:
        raise Conflict("Open the campaign before sending invitations.")

    statuses = (
        [RecipientStatus.PENDING, RecipientStatus.SENT, RecipientStatus.OPENED]
        if resend
        else [RecipientStatus.PENDING]
    )
    # Unsubscribed recipients are always selected so they can be *reported* as
    # skipped. Omitting them from the query would suppress them silently, and
    # an admin chasing a missing response deserves to be told the reason is an
    # opt-out rather than left assuming the mail bounced.
    statuses.append(RecipientStatus.UNSUBSCRIBED)
    stmt = (
        select(CampaignRecipient, Contact, FeedbackTarget)
        .join(Contact, Contact.id == CampaignRecipient.contact_id)
        .join(FeedbackTarget, FeedbackTarget.id == CampaignRecipient.target_id)
        .where(
            CampaignRecipient.cycle_id == cycle.id,
            CampaignRecipient.status.in_(statuses),
        )
    )
    if only_recipient_id:
        stmt = stmt.where(CampaignRecipient.id == only_recipient_id)

    rows = (await session.execute(stmt)).all()

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
    feedback_request_subject = OrgSettings.load(org.settings).email.feedback_request_subject

    sent = 0
    failed = 0
    skipped = 0
    errors: list[str] = []
    now = datetime.now(UTC)

    for recipient, contact, target in rows:
        if (
            contact.unsubscribed_at is not None
            or recipient.status == RecipientStatus.UNSUBSCRIBED
        ):
            recipient.status = RecipientStatus.UNSUBSCRIBED
            skipped += 1
            continue

        raw_token = generate_token()
        recipient.token_hash = hash_token(raw_token)
        recipient.send_attempts += 1

        ok = await email_service.send_feedback_request(
            to=contact.email,
            full_name=contact.full_name,
            org_name=org.name,
            subject_label=target.label,
            link=_link(raw_token),
            expires_at=recipient.expires_at,
            branding=branding,
            subject_template=feedback_request_subject,
        )
        if ok:
            recipient.status = RecipientStatus.SENT
            recipient.sent_at = now
            recipient.last_error = None
            sent += 1
        else:
            recipient.last_error = "delivery failed"
            failed += 1
            errors.append(contact.email)

    await session.flush()
    return SendResult(sent=sent, failed=failed, skipped=skipped, errors=errors[:10])


async def campaign_progress(
    session: AsyncSession, cycle_id: uuid.UUID
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(CampaignRecipient.status, func.count())
            .where(CampaignRecipient.cycle_id == cycle_id)
            .group_by(CampaignRecipient.status)
        )
    ).all()
    counts = {str(status): count for status, count in rows}
    total = sum(counts.values())
    submitted = counts.get(str(RecipientStatus.SUBMITTED), 0)
    sent = (
        counts.get(str(RecipientStatus.SENT), 0)
        + counts.get(str(RecipientStatus.OPENED), 0)
        + submitted
    )
    opened = counts.get(str(RecipientStatus.OPENED), 0) + submitted
    return {
        "total": total,
        "pending": counts.get(str(RecipientStatus.PENDING), 0),
        "sent": sent,
        "opened": opened,
        "submitted": submitted,
        "unsubscribed": counts.get(str(RecipientStatus.UNSUBSCRIBED), 0),
        "revoked": counts.get(str(RecipientStatus.REVOKED), 0),
        # Response rate is measured against what was actually delivered, not
        # against everyone on the list. Counting undelivered invitations as
        # non-responses makes every campaign look worse than it was.
        "response_rate_pct": round(100 * submitted / sent) if sent else 0,
        "open_rate_pct": round(100 * opened / sent) if sent else 0,
    }


async def maybe_auto_close(session: AsyncSession, cycle: ReviewCycle) -> bool:
    """Close an open external campaign once no recipient could still respond
    — everyone has either submitted, unsubscribed, or had their link revoked.
    Returns True if it closed the cycle. Counterpart to cycles.py's version
    of the same idea for internal rounds."""
    if cycle.status != CycleStatus.OPEN:
        return False
    progress = await campaign_progress(session, cycle.id)
    if progress["total"] == 0:
        return False
    still_pending = progress["total"] - progress["submitted"] - progress["unsubscribed"] - progress["revoked"]
    if still_pending > 0:
        return False
    cycle.status = CycleStatus.CLOSED
    cycle.closed_at = datetime.now(UTC)
    return True
