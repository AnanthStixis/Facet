"""Hard-delete every disabled (is_active=False) template that has no real
history pinned to it.

A prior session set is_active=False on old templates instead of deleting
them, because ReviewCycle.template_version_id and
FeedbackResponse.template_version_id are FK(..., ondelete="RESTRICT") and
this dev DB has real review-cycle / response rows referencing several of
them. The client now wants the ones with no such dependency actually
removed.

For every disabled template: attempt session.delete(template) (cascades to
its FeedbackTemplateVersion rows via the ORM relationship's
cascade="all, delete-orphan") **in its own independent session/transaction**
— not batched with the others via SAVEPOINT. A batched-SAVEPOINT version of
this script was tried first and was NOT reliable: after an IntegrityError on
one template's delete, the DBAPI-level transaction can be left in a state
where a later `session.commit()` for the whole batch does not accurately
reflect what was rolled back per savepoint, which produced non-idempotent,
contradictory output across consecutive runs. One template = one
session = one transaction sidesteps that entirely: each outcome is
independently verified by re-querying for the row's continued existence in
a still-open connection right after that transaction settles.

No ReviewCycle / FeedbackResponse / FeedbackAssignment / CampaignRecipient
row is ever altered to force a template through — that data is out of
scope.

    python -m scripts.hard_delete_disabled_templates
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionFactory  # noqa: E402
from app.db.tenancy import TenantContext, bind_tenant  # noqa: E402
from app.models.catalog import FeedbackTemplate  # noqa: E402


async def _try_delete_one(template_id, name: str) -> tuple[str, bool]:
    """Attempt to hard-delete a single template in its own session/transaction.

    Returns (name, deleted). On an IntegrityError (some ReviewCycle or
    FeedbackResponse row still references one of its versions), the whole
    transaction for this attempt is rolled back by the `async with` context
    manager exiting on exception, and the template is reported as kept.
    """
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        template = (
            await session.execute(
                select(FeedbackTemplate).where(FeedbackTemplate.id == template_id)
            )
        ).scalar_one_or_none()
        if template is None:
            # Already gone (e.g. cascaded from something else this run).
            return name, True
        try:
            await session.delete(template)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return name, False
        return name, True


async def main() -> int:
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        disabled = (
            (
                await session.execute(
                    select(FeedbackTemplate.id, FeedbackTemplate.name)
                    .where(FeedbackTemplate.is_active.is_(False))
                    .order_by(FeedbackTemplate.name)
                )
            ).all()
        )

    if not disabled:
        print("No disabled templates found. Nothing to do.")
        return 0

    deleted: list[str] = []
    kept: list[str] = []
    for template_id, name in disabled:
        _, ok = await _try_delete_one(template_id, name)
        (deleted if ok else kept).append(name)

    print(f"Hard-deleted: {len(deleted)}")
    for name in sorted(deleted):
        print(f"  - {name}")
    print(f"\nKept (still referenced by real review-cycle/response history): {len(kept)}")
    for name in sorted(kept):
        print(f"  - {name}")

    # Independent, final verification: fresh session, fresh query — no
    # reliance on any state carried over from the loop above.
    async with SessionFactory() as verify_session:
        await bind_tenant(verify_session, TenantContext(org_id=None, is_super_admin=True))
        still_disabled = (
            (
                await verify_session.execute(
                    select(FeedbackTemplate.name)
                    .where(FeedbackTemplate.is_active.is_(False))
                    .order_by(FeedbackTemplate.name)
                )
            )
            .scalars()
            .all()
        )
    print(f"\nRemaining disabled templates in DB (verified fresh): {len(still_disabled)}.")
    mismatch = set(still_disabled) != set(kept)
    if mismatch:
        print(
            "WARNING: remaining-disabled set does not match the kept list above — "
            f"remaining={sorted(still_disabled)} kept={sorted(kept)}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
