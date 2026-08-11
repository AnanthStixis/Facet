"""Scheduled maintenance jobs.

There is no container runtime here, so these run as commands rather than as
Celery beat entries. Point Windows Task Scheduler at them:

    python -m app.tasks reminders          send due reminders and escalations
    python -m app.tasks reminders --dry-run
    python -m app.tasks expire             mark lapsed links and assignments
    python -m app.tasks retain             purge audit history past retention
    python -m app.tasks all

Every job is idempotent and rate-limited internally, so running one twice by
accident, or more often than intended, does nothing harmful.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update

from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
from app.models.campaign import CampaignRecipient
from app.models.cycle import FeedbackAssignment, ReviewCycle
from app.models.enums import AssignmentStatus, CycleStatus, RecipientStatus
from app.models.organization import Organization
from app.schemas.settings import OrgSettings
from app.services.reminders import run_reminders


async def _reminders(dry_run: bool) -> int:
    async with SessionFactory() as session:
        # A maintenance job legitimately spans tenants; it runs from the
        # command line, not from a request, and touches no cross-tenant data
        # beyond dispatching each organization's own mail.
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        result = await run_reminders(session, dry_run=dry_run)
        if not dry_run:
            await session.commit()

    prefix = "Would send" if dry_run else "Sent"
    print(f"{prefix} {result.total} reminder(s).")
    print(f"  internal        : {result.internal_reminded}")
    print(f"  external        : {result.external_reminded}")
    print(f"  escalations     : {result.escalated}")
    print(f"  held (cooldown) : {result.skipped_cooldown}")
    print(f"  held (capped)   : {result.skipped_capped}")
    if result.failures:
        print(f"  delivery failures: {result.failures}")
    return 0


async def _expire() -> int:
    """Retire links and assignments that have run out of time.

    Expiry is already enforced on read — a lapsed link is refused whether or
    not this has run. This job exists so the *reporting* reflects reality
    rather than showing a queue of invitations that can no longer be used.
    """
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

        links = await session.execute(
            update(CampaignRecipient)
            .where(
                CampaignRecipient.expires_at <= now,
                CampaignRecipient.status.in_(
                    [
                        RecipientStatus.PENDING,
                        RecipientStatus.SENT,
                        RecipientStatus.OPENED,
                    ]
                ),
            )
            .values(status=RecipientStatus.EXPIRED)
        )

        closed = (
            await session.execute(
                update(ReviewCycle)
                .where(
                    ReviewCycle.status == CycleStatus.OPEN,
                    ReviewCycle.closes_at.isnot(None),
                    ReviewCycle.closes_at <= now,
                )
                .values(status=CycleStatus.CLOSED, closed_at=now)
                .returning(ReviewCycle.id)
            )
        ).all()

        assignments = await session.execute(
            update(FeedbackAssignment)
            .where(
                FeedbackAssignment.cycle_id.in_([row[0] for row in closed] or [None]),
                FeedbackAssignment.status.in_(
                    [AssignmentStatus.PENDING, AssignmentStatus.IN_PROGRESS]
                ),
            )
            .values(status=AssignmentStatus.EXPIRED)
        )
        await session.commit()

    print(f"Expired {links.rowcount} link(s).")
    print(f"Closed {len(closed)} round(s) past their closing date.")
    print(f"Expired {assignments.rowcount} outstanding assignment(s).")
    return 0


async def _retain() -> int:
    """Purge audit history past each organization's retention setting.

    Goes through `facet_audit_purge` (migration 0009), the one sanctioned hole
    in the append-only trigger. That function enforces its own 30-day floor
    independently of anything computed here, so a bug in this job's date
    arithmetic cannot turn into erasing recent history.

    An org with `retention_days = 0` (the default) is skipped entirely —
    "keep forever" is the safe default, and nothing is purged unless someone
    has explicitly set a value.
    """
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        orgs = (await session.execute(select(Organization))).scalars().all()

        purged_total = 0
        orgs_purged = 0
        for org in orgs:
            retention = OrgSettings.load(org.settings).audit.retention_days
            if retention <= 0:
                continue
            cutoff = datetime.now(UTC) - timedelta(days=retention)
            removed = (
                await session.execute(
                    text("SELECT facet_audit_purge(:org_id, :before)"),
                    {"org_id": org.id, "before": cutoff},
                )
            ).scalar_one()
            if removed:
                orgs_purged += 1
                purged_total += removed
                print(f"  {org.name}: removed {removed} row(s) older than {retention}d")

        await session.commit()

    print(f"Purged {purged_total} audit row(s) across {orgs_purged} organization(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.tasks", description=__doc__)
    parser.add_argument("job", choices=["reminders", "expire", "retain", "all"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be sent without sending anything.",
    )
    args = parser.parse_args()

    async def run() -> int:
        code = 0
        if args.job in {"reminders", "all"}:
            code |= await _reminders(args.dry_run)
        if args.job in {"expire", "all"}:
            if args.dry_run:
                print("Expiry has no dry-run mode; skipping.")
            else:
                code |= await _expire()
        if args.job in {"retain", "all"}:
            if args.dry_run:
                print("Retention has no dry-run mode; skipping.")
            else:
                code |= await _retain()
        return code

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
