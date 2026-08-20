"""Dashboard metrics.

Phase 1 has no feedback responses yet, so this deliberately reports on what
does exist and is genuinely useful on day one: tenant health, directory
coverage, and activity. Inventing placeholder scores would make the dashboard
look finished while teaching the user nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.audit import AuditLog
from app.models.catalog import Contact, FeedbackTarget, FeedbackTemplate
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    CycleAudience,
    CycleStatus,
    OrgStatus,
    ProposalStage,
    Relationship,
    TargetType,
    UserRole,
    UserStatus,
)
from app.models.organization import Organization
from app.models.proposal import Proposal
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(session: DbSession, actor: CurrentUser) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=13)

    async def scalar(stmt) -> int:
        return int((await session.execute(stmt)).scalar_one() or 0)

    total_users = await scalar(
        select(func.count()).select_from(User).where(User.status != UserStatus.DELETED)
    )
    active_users = await scalar(
        select(func.count()).select_from(User).where(User.status == UserStatus.ACTIVE)
    )
    pending_users = await scalar(
        select(func.count()).select_from(User).where(User.status == UserStatus.INVITED)
    )
    contacts = await scalar(select(func.count()).select_from(Contact))
    templates = await scalar(select(func.count()).select_from(FeedbackTemplate))

    # Coverage across the feedback graph. This is the view no single-domain
    # competitor can render, because their employee and customer data live in
    # different products.
    coverage_rows = (
        await session.execute(
            select(FeedbackTarget.target_type, func.count())
            .group_by(FeedbackTarget.target_type)
        )
    ).all()
    coverage_map = {str(row[0]): row[1] for row in coverage_rows}
    coverage = [
        {
            "target_type": target.value,
            "label": target.value.replace("_", " ").title(),
            "count": coverage_map.get(target.value, 0),
            "domain": (
                "internal"
                if target in {TargetType.EMPLOYEE, TargetType.MANAGER,
                              TargetType.TEAM, TargetType.DEPARTMENT}
                else "external"
            ),
        }
        for target in TargetType
    ]

    activity_rows = (
        await session.execute(
            select(
                func.date_trunc("day", AuditLog.occurred_at).label("day"),
                func.count().label("n"),
            )
            .where(AuditLog.occurred_at >= since)
            .group_by("day")
            .order_by("day")
        )
    ).all()
    activity_map = {row.day.date().isoformat(): row.n for row in activity_rows}
    activity = [
        {
            "date": (since + timedelta(days=offset)).date().isoformat(),
            "count": activity_map.get((since + timedelta(days=offset)).date().isoformat(), 0),
        }
        for offset in range(14)
    ]

    recent = (
        await session.execute(
            select(AuditLog)
            .order_by(AuditLog.occurred_at.desc())
            .limit(8)
        )
    ).scalars().all()

    # A short, actionable list of what actually needs a human decision right
    # now. This replaces a generic "activity over time" chart with counts a
    # reader can act on directly — each one routes straight to the screen that
    # resolves it.
    # Client Admin and Super Admin see the whole org's open work. A Manager's
    # dashboard is scoped to what they themselves are running — same
    # ownership boundary as the cycles/campaigns list endpoints — so this
    # never shows a manager a colleague manager's (or the Client Admin's)
    # counts.
    is_manager_only = actor.role == UserRole.MANAGER
    attention: dict[str, Any] = {}
    if not actor.is_super_admin:
        soon = now + timedelta(days=7)
        owner_clause = (
            (ReviewCycle.created_by_id == actor.user.id,) if is_manager_only else ()
        )
        attention["open_cycles"] = await scalar(
            select(func.count())
            .select_from(ReviewCycle)
            .where(
                ReviewCycle.status == CycleStatus.OPEN,
                ReviewCycle.audience != CycleAudience.EXTERNAL,
                *owner_clause,
            )
        )
        attention["open_campaigns"] = await scalar(
            select(func.count())
            .select_from(ReviewCycle)
            .where(
                ReviewCycle.status == CycleStatus.OPEN,
                ReviewCycle.audience == CycleAudience.EXTERNAL,
                *owner_clause,
            )
        )
        attention["closing_soon"] = await scalar(
            select(func.count())
            .select_from(ReviewCycle)
            .where(
                ReviewCycle.status == CycleStatus.OPEN,
                ReviewCycle.closes_at.isnot(None),
                ReviewCycle.closes_at <= soon,
                *owner_clause,
            )
        )
        # Proposals are not "owned" by whoever created them the way a cycle
        # or campaign is, so there is no meaningful per-manager scope for
        # this one — it is an org-wide pipeline concern, shown only to the
        # roles that actually manage that pipeline.
        if not is_manager_only:
            attention["proposals_awaiting_outcome"] = await scalar(
                select(func.count())
                .select_from(Proposal)
                .where(
                    Proposal.stage.in_([ProposalStage.SUBMITTED, ProposalStage.SHORTLISTED])
                )
            )

    # What this specific person has open right now — the numbers an Employee's
    # narrower dashboard actually needs, since they never see org-wide metrics.
    my_pending_feedback = await scalar(
        select(func.count())
        .select_from(FeedbackAssignment)
        .where(
            FeedbackAssignment.reviewer_user_id == actor.user.id,
            FeedbackAssignment.status == AssignmentStatus.PENDING,
        )
    )
    my_results = await scalar(
        select(func.count())
        .select_from(FeedbackResponse)
        .join(FeedbackTarget, FeedbackTarget.id == FeedbackResponse.target_id)
        .where(
            FeedbackTarget.subject_user_id == actor.user.id,
            FeedbackResponse.relationship_type != Relationship.SELF,
        )
    )

    payload: dict[str, Any] = {
        "scope": "platform" if actor.is_super_admin else "organization",
        "organization": (
            {"id": str(actor.org.id), "name": actor.org.name, "timezone": actor.org.timezone}
            if actor.org
            else None
        ),
        "metrics": {
            "users_total": total_users,
            "users_active": active_users,
            "users_pending": pending_users,
            "contacts": contacts,
            "templates": templates,
            "my_pending_feedback": my_pending_feedback,
            "my_results": my_results,
        },
        "coverage": coverage,
        "activity_14d": activity,
        "attention": attention,
        "recent_activity": [
            {
                "id": str(entry.id),
                "action": entry.action,
                "severity": str(entry.severity),
                "summary": entry.summary,
                "actor_name": entry.actor_name,
                "occurred_at": entry.occurred_at,
            }
            for entry in recent
        ],
    }

    if actor.is_super_admin:
        payload["platform"] = {
            "orgs_total": await scalar(select(func.count()).select_from(Organization)),
            "orgs_pending": await scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.status == OrgStatus.PENDING)
            ),
            "orgs_active": await scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.status == OrgStatus.ACTIVE)
            ),
            "orgs_suspended": await scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.status == OrgStatus.SUSPENDED)
            ),
            "client_admins": await scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.CLIENT_ADMIN)
            ),
        }

    return payload