"""Reminders and escalation.

Chasing non-responders is what actually determines whether a feedback round
produces usable data. A 30% response rate is not a finding; it is a nudge that
never got sent.

Three rules, because an over-eager reminder system is worse than none:

  * **A cooldown.** Nobody is nudged more than once every `cooldown_days`, no
    matter how often this runs. That makes the job safe to schedule hourly and
    safe to run twice by accident.
  * **A cap.** At most `max_reminders` per person per round. Past that the
    silence is an answer, and continuing to email is how a sending domain ends
    up on a blocklist.
  * **Escalation, once.** When the cap is reached the round's owner gets a
    single digest naming who is outstanding. A human deciding whether to walk
    over and ask is more effective than a fourth email.

There is no container runtime here, so this runs as a command rather than a
Celery beat schedule:

    python -m app.tasks reminders

Point Windows Task Scheduler at that daily. The cooldown makes the cadence
forgiving — running it more often than needed simply does nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import generate_token, hash_token
from app.models.campaign import CampaignRecipient
from app.models.catalog import Contact, FeedbackTarget
from app.models.cycle import FeedbackAssignment, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    CycleAudience,
    CycleStatus,
    RecipientStatus,
)
from app.models.organization import Organization
from app.models.user import User
from app.schemas.settings import OrgSettings
from app.services import audit, email as email_service

log = get_logger("facet.reminders")

DEFAULT_COOLDOWN_DAYS = 3
DEFAULT_MAX_REMINDERS = 2
# Nothing is chased in its first day. A reminder that arrives before the person
# has plausibly had time to act reads as nagging and trains people to ignore
# the sender.
QUIET_PERIOD_HOURS = 24


@dataclass
class ReminderRun:
    internal_reminded: int = 0
    external_reminded: int = 0
    escalated: int = 0
    skipped_cooldown: int = 0
    skipped_capped: int = 0
    failures: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.internal_reminded + self.external_reminded


def _branding(org: Organization) -> email_service.Branding:
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


def _due(
    last_reminded_at: datetime | None,
    created_at: datetime,
    sent_count: int,
    *,
    now: datetime,
    cooldown_days: int,
    max_reminders: int,
) -> tuple[bool, str | None]:
    if sent_count >= max_reminders:
        return False, "capped"
    if created_at > now - timedelta(hours=QUIET_PERIOD_HOURS):
        return False, "quiet_period"
    if last_reminded_at and last_reminded_at > now - timedelta(days=cooldown_days):
        return False, "cooldown"
    return True, None


async def run_reminders(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    cooldown_days: int | None = None,
    max_reminders: int | None = None,
    dry_run: bool = False,
) -> ReminderRun:
    """Nudge everyone who is outstanding and due a nudge.

    Cadence comes from each organization's own settings unless the caller
    forces a value (verification does this, to get a deterministic cadence
    regardless of what a tenant has configured). An org with `reminders.enabled
    = false` is skipped entirely — respecting that flag here, not just in the
    UI, is what makes it a real setting rather than a suggestion.
    """
    now = datetime.now(UTC)
    result = ReminderRun()

    cycle_stmt = select(ReviewCycle).where(ReviewCycle.status == CycleStatus.OPEN)
    if org_id:
        cycle_stmt = cycle_stmt.where(ReviewCycle.org_id == org_id)
    cycles = (await session.execute(cycle_stmt)).scalars().all()

    orgs = {
        org.id: org
        for org in (
            await session.execute(
                select(Organization).where(
                    Organization.id.in_({c.org_id for c in cycles} or {uuid.uuid4()})
                )
            )
        )
        .scalars()
        .all()
    }

    for cycle in cycles:
        org = orgs.get(cycle.org_id)
        if org is None:
            continue

        org_reminders = OrgSettings.load(org.settings).reminders
        if not org_reminders.enabled:
            continue

        effective_cooldown = (
            cooldown_days if cooldown_days is not None else org_reminders.cooldown_days
        )
        effective_max = (
            max_reminders if max_reminders is not None else org_reminders.max_reminders
        )
        branding = _branding(org)

        if cycle.audience != CycleAudience.EXTERNAL:
            await _remind_internal(
                session,
                cycle=cycle,
                org=org,
                branding=branding,
                now=now,
                cooldown_days=effective_cooldown,
                max_reminders=effective_max,
                dry_run=dry_run,
                result=result,
                escalate=org_reminders.escalate_to_owner,
            )
        else:
            await _remind_external(
                session,
                cycle=cycle,
                org=org,
                branding=branding,
                now=now,
                cooldown_days=effective_cooldown,
                max_reminders=effective_max,
                dry_run=dry_run,
                result=result,
                escalate=org_reminders.escalate_to_owner,
            )

    if not dry_run and result.total:
        await audit.record(
            session,
            action=AuditAction.REMINDERS_SENT,
            summary=f"{result.total} reminder(s) sent across open rounds",
            org_id=org_id,
            context={
                "internal": result.internal_reminded,
                "external": result.external_reminded,
                "escalated": result.escalated,
            },
        )
    return result


async def _remind_internal(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    org: Organization,
    branding: email_service.Branding,
    now: datetime,
    cooldown_days: int,
    max_reminders: int,
    dry_run: bool,
    result: ReminderRun,
    escalate: bool = True,
) -> None:
    rows = (
        await session.execute(
            select(FeedbackAssignment, User, FeedbackTarget)
            .join(User, User.id == FeedbackAssignment.reviewer_user_id)
            .join(FeedbackTarget, FeedbackTarget.id == FeedbackAssignment.target_id)
            .where(
                FeedbackAssignment.cycle_id == cycle.id,
                FeedbackAssignment.status.in_(
                    [AssignmentStatus.PENDING, AssignmentStatus.IN_PROGRESS]
                ),
            )
        )
    ).all()

    outstanding: list[str] = []

    for assignment, reviewer, target in rows:
        outstanding.append(f"{reviewer.full_name} (about {target.label})")
        due, reason = _due(
            assignment.last_reminded_at,
            assignment.created_at,
            assignment.reminders_sent,
            now=now,
            cooldown_days=cooldown_days,
            max_reminders=max_reminders,
        )
        if not due:
            if reason == "cooldown":
                result.skipped_cooldown += 1
            elif reason == "capped":
                result.skipped_capped += 1
            continue

        if dry_run:
            result.internal_reminded += 1
            continue

        ok = await email_service.send_reminder(
            to=reviewer.email,
            full_name=reviewer.full_name,
            org_name=org.name,
            subject_label=target.label,
            cycle_name=cycle.name,
            link=f"{settings.public_app_url}/my-feedback",
            due_at=assignment.due_at or cycle.closes_at,
            branding=branding,
        )
        if ok:
            assignment.reminders_sent += 1
            assignment.last_reminded_at = now
            result.internal_reminded += 1
        else:
            result.failures += 1

    if escalate:
        await _escalate(
            session,
            cycle=cycle,
            org=org,
            branding=branding,
            outstanding=outstanding,
            rows_capped=[
                assignment
                for assignment, _, _ in rows
                if assignment.reminders_sent >= max_reminders
            ],
            now=now,
            dry_run=dry_run,
            result=result,
        )


async def _remind_external(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    org: Organization,
    branding: email_service.Branding,
    now: datetime,
    cooldown_days: int,
    max_reminders: int,
    dry_run: bool,
    result: ReminderRun,
    escalate: bool = True,
) -> None:
    rows = (
        await session.execute(
            select(CampaignRecipient, Contact, FeedbackTarget)
            .join(Contact, Contact.id == CampaignRecipient.contact_id)
            .join(FeedbackTarget, FeedbackTarget.id == CampaignRecipient.target_id)
            .where(
                CampaignRecipient.cycle_id == cycle.id,
                CampaignRecipient.status.in_(
                    [RecipientStatus.SENT, RecipientStatus.OPENED]
                ),
            )
        )
    ).all()

    outstanding: list[str] = []

    for recipient, contact, target in rows:
        outstanding.append(f"{contact.full_name} ({contact.company or contact.email})")

        # An unsubscribe outranks any reminder schedule.
        if contact.unsubscribed_at is not None:
            recipient.status = RecipientStatus.UNSUBSCRIBED
            continue

        due, reason = _due(
            recipient.last_reminded_at,
            recipient.sent_at or recipient.created_at,
            recipient.reminders_sent,
            now=now,
            cooldown_days=cooldown_days,
            max_reminders=max_reminders,
        )
        if not due:
            if reason == "cooldown":
                result.skipped_cooldown += 1
            elif reason == "capped":
                result.skipped_capped += 1
            continue

        if dry_run:
            result.external_reminded += 1
            continue

        # A reminder carries a fresh link, which invalidates the previous one.
        # Otherwise a recipient with two emails open has two live tokens, and
        # "single use" quietly stops being true.
        raw_token = generate_token()
        recipient.token_hash = hash_token(raw_token)

        ok = await email_service.send_reminder(
            to=contact.email,
            full_name=contact.full_name,
            org_name=org.name,
            subject_label=target.label,
            cycle_name=cycle.name,
            link=f"{settings.public_app_url}/f/{raw_token}",
            due_at=recipient.expires_at,
            branding=branding,
            external=True,
        )
        if ok:
            recipient.reminders_sent += 1
            recipient.last_reminded_at = now
            result.external_reminded += 1
        else:
            result.failures += 1

    if escalate:
        await _escalate(
            session,
            cycle=cycle,
            org=org,
            branding=branding,
            outstanding=outstanding,
            rows_capped=[
                recipient
                for recipient, _, _ in rows
                if recipient.reminders_sent >= max_reminders
            ],
            now=now,
            dry_run=dry_run,
            result=result,
        )


async def _escalate(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    org: Organization,
    branding: email_service.Branding,
    outstanding: list[str],
    rows_capped: list,
    now: datetime,
    dry_run: bool,
    result: ReminderRun,
) -> None:
    """Tell the round's owner once, when nudging has stopped working."""
    if not rows_capped or not outstanding or dry_run:
        return
    # Escalate only when everyone still outstanding has been chased to the cap.
    # Escalating while reminders are still in flight just adds noise.
    if len(rows_capped) < len(outstanding):
        return
    if cycle.created_by_id is None:
        return
    # Once only. A round that escalates every night is a round whose owner
    # filters the sender.
    if cycle.escalated_at is not None:
        return

    owner = (
        await session.execute(select(User).where(User.id == cycle.created_by_id))
    ).scalar_one_or_none()
    if owner is None:
        return

    ok = await email_service.send_escalation(
        to=owner.email,
        full_name=owner.full_name,
        org_name=org.name,
        cycle_name=cycle.name,
        outstanding=outstanding,
        link=f"{settings.public_app_url}/cycles",
        branding=branding,
    )
    if ok:
        cycle.escalated_at = now
        result.escalated += 1
        await audit.record(
            session,
            action=AuditAction.ESCALATION_SENT,
            summary=(
                f"{len(outstanding)} non-responder(s) in '{cycle.name}' escalated "
                f"to {owner.full_name}"
            ),
            org_id=cycle.org_id,
            target_type="review_cycle",
            target_id=cycle.id,
            target_label=cycle.name,
            context={"outstanding": len(outstanding)},
        )
