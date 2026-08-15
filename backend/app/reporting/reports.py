"""Concrete report definitions.

Each one declares its columns and a single query used for both the screen and
every export format.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.audit import AuditLog
from app.models.campaign import CampaignRecipient
from app.models.catalog import Contact, FeedbackTarget
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.proposal import Proposal
from app.models.user import User
from app.reporting.filters import escape_like, resolve_window
from app.reporting.registry import Column, ReportDefinition, ReportPage, register
from app.schemas.common import FilterState


def _apply_pagination(stmt: Select, filters: FilterState, paginate: bool) -> Select:
    if not paginate:
        return stmt
    return stmt.offset((filters.page - 1) * filters.page_size).limit(filters.page_size)


async def _count(session: AsyncSession, stmt: Select) -> int:
    subquery = stmt.order_by(None).subquery()
    return int(
        (await session.execute(select(func.count()).select_from(subquery))).scalar_one()
    )


# --- Audit trail ------------------------------------------------------------

AUDIT_COLUMNS = [
    Column("occurred_at", "When", width=18, kind="datetime"),
    Column("actor_name", "Who", width=22),
    Column("actor_email", "Email", width=26, detail_only=True),
    Column("actor_role", "Role", width=14),
    Column("action", "Action", width=22, kind="badge"),
    Column("severity", "Severity", width=11, kind="badge"),
    Column("summary", "Detail", width=42),
    Column("target_label", "Target", width=24),
    Column("organization", "Organization", width=22),
    Column("ip_address", "IP address", width=16, detail_only=True),
]


async def _query_audit(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    stmt = (
        select(
            AuditLog.occurred_at,
            AuditLog.actor_name,
            AuditLog.actor_email,
            AuditLog.actor_role,
            AuditLog.action,
            AuditLog.severity,
            AuditLog.summary,
            AuditLog.target_label,
            # host() renders inet as plain text. Postgres INET maps to a Python
            # ipaddress object, which neither JSON nor the export renderers
            # know how to handle.
            func.host(AuditLog.ip_address).label("ip_address"),
            Organization.name.label("organization"),
        )
        .select_from(AuditLog)
        .join(Organization, Organization.id == AuditLog.org_id, isouter=True)
        .where(
            AuditLog.occurred_at >= window.start_at,
            AuditLog.occurred_at < window.end_at,
        )
    )

    # No explicit org filter for a Client Admin: row level security already
    # constrains this to their tenant. Adding a redundant WHERE here would
    # invite the belief that the WHERE is what protects the data.
    if actor.is_super_admin and filters.org_ids:
        stmt = stmt.where(AuditLog.org_id.in_(filters.org_ids))
    if filters.actor_ids:
        stmt = stmt.where(AuditLog.actor_id.in_(filters.actor_ids))
    if filters.actions:
        stmt = stmt.where(AuditLog.action.in_(filters.actions))
    if filters.severities:
        stmt = stmt.where(AuditLog.severity.in_(filters.severities))
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                AuditLog.summary.ilike(term),
                AuditLog.actor_name.ilike(term),
                AuditLog.actor_email.ilike(term),
                AuditLog.target_label.ilike(term),
            )
        )

    total = await _count(session, stmt)
    direction = AuditLog.occurred_at.desc() if filters.sort_dir == "desc" else AuditLog.occurred_at.asc()
    stmt = stmt.order_by(direction, AuditLog.id.desc())
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()

    return ReportPage(rows=[dict(row) for row in rows], total=total, window=window)


AUDIT_REPORT = register(
    ReportDefinition(
        key="audit_trail",
        title="Audit trail",
        description=(
            "Every recorded action, scoped to your organization. Entries are "
            "append-only and cannot be edited or deleted by any role."
        ),
        columns=AUDIT_COLUMNS,
        query=_query_audit,
        min_role=UserRole.CLIENT_ADMIN,
        default_sort="occurred_at",
        filters_supported=["search", "date_range", "actors", "actions", "severities", "orgs"],
    )
)


# --- Directory --------------------------------------------------------------

USER_COLUMNS = [
    Column("full_name", "Name", width=24),
    Column("email", "Email", width=30),
    Column("job_title", "Job title", width=22),
    Column("department", "Department", width=20),
    Column("role", "Role", width=14, kind="badge"),
    Column("status", "Status", width=12, kind="badge"),
    Column("last_login_at", "Last sign-in", width=18, kind="datetime"),
    Column("organization", "Organization", width=22),
]


async def _query_users(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    stmt = (
        select(
            User.id,
            User.full_name,
            User.email,
            User.job_title,
            User.department,
            User.role,
            User.status,
            User.last_login_at,
            User.created_at,
            Organization.name.label("organization"),
        )
        .select_from(User)
        .join(Organization, Organization.id == User.org_id, isouter=True)
    )

    if actor.is_super_admin and filters.org_ids:
        stmt = stmt.where(User.org_id.in_(filters.org_ids))
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(term),
                User.email.ilike(term),
                User.department.ilike(term),
            )
        )

    total = await _count(session, stmt)
    stmt = stmt.order_by(User.full_name.asc())
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()
    return ReportPage(rows=[dict(row) for row in rows], total=total, window=window)


USER_REPORT = register(
    ReportDefinition(
        key="user_directory",
        title="User directory",
        description="People with access to the platform and their roles.",
        columns=USER_COLUMNS,
        query=_query_users,
        min_role=UserRole.CLIENT_ADMIN,
        default_sort="full_name",
        filters_supported=["search", "orgs"],
    )
)


# --- Tenants (Super Admin) --------------------------------------------------

ORG_COLUMNS = [
    Column("name", "Organization", width=26),
    Column("slug", "Slug", width=18),
    Column("status", "Status", width=12, kind="badge"),
    Column("registration_source", "Onboarded via", width=16),
    Column("contact_name", "Primary contact", width=22),
    Column("contact_email", "Contact email", width=28, detail_only=True),
    Column("user_count", "Users", width=9, kind="number"),
    Column("country", "Country", width=9),
    Column("created_at", "Registered", width=18, kind="datetime"),
    Column("approved_at", "Approved", width=18, kind="datetime"),
]


async def _query_orgs(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    window = resolve_window(filters.date_range, "UTC")
    user_counts = (
        select(User.org_id, func.count().label("user_count"))
        .group_by(User.org_id)
        .subquery()
    )
    stmt = (
        select(
            Organization.id,
            Organization.name,
            Organization.slug,
            Organization.status,
            Organization.registration_source,
            Organization.contact_name,
            Organization.contact_email,
            Organization.country,
            Organization.created_at,
            Organization.approved_at,
            func.coalesce(user_counts.c.user_count, 0).label("user_count"),
        )
        .select_from(Organization)
        .join(user_counts, user_counts.c.org_id == Organization.id, isouter=True)
    )
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                Organization.name.ilike(term),
                Organization.slug.ilike(term),
                Organization.contact_email.ilike(term),
            )
        )
    if filters.severities:  # reused as a status filter on this report
        stmt = stmt.where(Organization.status.in_(filters.severities))

    total = await _count(session, stmt)
    stmt = stmt.order_by(Organization.created_at.desc())
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()
    return ReportPage(rows=[dict(row) for row in rows], total=total, window=window)


ORG_REPORT = register(
    ReportDefinition(
        key="organizations",
        title="Organizations",
        description="Every tenant on the platform, its onboarding route, and its size.",
        columns=ORG_COLUMNS,
        query=_query_orgs,
        min_role=UserRole.SUPER_ADMIN,
        default_sort="created_at",
        filters_supported=["search", "statuses"],
    )
)


# --- Cycle completion (Module A) -------------------------------------------

COMPLETION_COLUMNS = [
    Column("cycle", "Cycle", width=24),
    Column("reviewer", "Reviewer", width=24),
    Column("reviewer_email", "Reviewer email", width=28, detail_only=True),
    Column("target", "About", width=24),
    Column("relationship", "Direction", width=14, kind="badge"),
    Column("status", "Status", width=13, kind="badge"),
    Column("due_at", "Due", width=18, kind="datetime"),
    Column("submitted_at", "Submitted", width=18, kind="datetime"),
]


async def _query_completion(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    """Who has and has not responded.

    Deliberately contains no answers. Chasing completion is an administrative
    need; reading what someone said is not, and in an anonymous cycle the data
    to answer it does not exist.
    """
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    reviewer = aliased(User)
    stmt = (
        select(
            ReviewCycle.name.label("cycle"),
            reviewer.full_name.label("reviewer"),
            reviewer.email.label("reviewer_email"),
            FeedbackTarget.label.label("target"),
            FeedbackAssignment.relationship_type.label("relationship"),
            FeedbackAssignment.status,
            FeedbackAssignment.due_at,
            FeedbackAssignment.submitted_at,
        )
        .select_from(FeedbackAssignment)
        .join(ReviewCycle, ReviewCycle.id == FeedbackAssignment.cycle_id)
        .join(FeedbackTarget, FeedbackTarget.id == FeedbackAssignment.target_id)
        .join(reviewer, reviewer.id == FeedbackAssignment.reviewer_user_id, isouter=True)
    )
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                ReviewCycle.name.ilike(term),
                reviewer.full_name.ilike(term),
                FeedbackTarget.label.ilike(term),
            )
        )
    if filters.severities:  # reused as an assignment-status filter here
        stmt = stmt.where(FeedbackAssignment.status.in_(filters.severities))

    total = await _count(session, stmt)
    stmt = stmt.order_by(ReviewCycle.name, FeedbackTarget.label, reviewer.full_name)
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()
    return ReportPage(rows=[dict(row) for row in rows], total=total, window=window)


COMPLETION_REPORT = register(
    ReportDefinition(
        key="cycle_completion",
        title="Cycle completion",
        description=(
            "Who has been asked for feedback and who has responded. Contains no "
            "answers, so it is safe to circulate while a cycle is still open."
        ),
        columns=COMPLETION_COLUMNS,
        query=_query_completion,
        min_role=UserRole.MANAGER,
        default_sort="cycle",
        filters_supported=["search", "severities"],
    )
)


# --- Feedback results (Module A) -------------------------------------------

RESULT_COLUMNS = [
    Column("cycle", "Cycle", width=24),
    Column("target", "About", width=26),
    Column("target_type", "Type", width=13, kind="badge"),
    Column("responses", "Responses", width=11, kind="number"),
    Column("overall_average", "Average", width=11, kind="number"),
    Column("self_average", "Self", width=10, kind="number"),
    Column("status", "Visibility", width=22),
]


async def _query_results(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    """Aggregated scores per target, with the same suppression as the screen.

    Exports are the classic way an anonymity guarantee gets bypassed — the UI
    hides a two-response average and the spreadsheet cheerfully prints it. The
    threshold is applied here, in the query, so no renderer can leak past it.
    """
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    aggregates = (
        select(
            FeedbackResponse.cycle_id,
            FeedbackResponse.target_id,
            func.count()
            .filter(FeedbackResponse.relationship_type != "self")
            .label("responses"),
            func.avg(FeedbackResponse.overall_score)
            .filter(FeedbackResponse.relationship_type != "self")
            .label("overall_average"),
            func.avg(FeedbackResponse.overall_score)
            .filter(FeedbackResponse.relationship_type == "self")
            .label("self_average"),
        )
        .group_by(FeedbackResponse.cycle_id, FeedbackResponse.target_id)
        .subquery()
    )

    stmt = (
        select(
            ReviewCycle.name.label("cycle"),
            FeedbackTarget.label.label("target"),
            FeedbackTarget.target_type,
            aggregates.c.responses,
            aggregates.c.overall_average,
            aggregates.c.self_average,
            ReviewCycle.is_anonymous,
            ReviewCycle.min_responses_to_reveal,
        )
        .select_from(aggregates)
        .join(ReviewCycle, ReviewCycle.id == aggregates.c.cycle_id)
        .join(FeedbackTarget, FeedbackTarget.id == aggregates.c.target_id)
    )
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(ReviewCycle.name.ilike(term), FeedbackTarget.label.ilike(term))
        )

    total = await _count(session, stmt)
    stmt = stmt.order_by(ReviewCycle.name, FeedbackTarget.label)
    raw = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()

    rows: list[dict[str, Any]] = []
    for row in raw:
        # Suppression removed at the org's explicit request — matches
        # app/services/results.py, so an export never disagrees with what
        # the app itself shows.
        rows.append(
            {
                "cycle": row["cycle"],
                "target": row["target"],
                "target_type": str(row["target_type"]),
                "responses": row["responses"] or 0,
                "overall_average": (
                    round(float(row["overall_average"]), 2)
                    if row["overall_average"] is not None
                    else None
                ),
                "self_average": (
                    round(float(row["self_average"]), 2)
                    if row["self_average"] is not None
                    else None
                ),
                "status": "Visible",
            }
        )

    return ReportPage(rows=rows, total=total, window=window)


SCORECARD_COLUMNS = [
    Column("reference", "Reference", width=14),
    Column("title", "Proposal", width=30),
    Column("client_name", "Client", width=20),
    Column("author", "Author", width=20),
    Column("stage", "Outcome", width=12, kind="badge"),
    Column("value_amount", "Proposed", width=13, kind="number"),
    Column("won_amount", "Signed", width=13, kind="number"),
    Column("loss_reason", "Lost because", width=16, kind="badge"),
    Column("competitor", "Lost to", width=18, detail_only=True),
    Column("responses", "Responses", width=10, kind="number"),
    Column("feedback_average", "Prospect score", width=13, kind="number"),
    Column("submitted_at", "Submitted", width=18, kind="datetime"),
]


async def _query_scorecard(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    """Proposal feedback next to what actually happened.

    This is the report the whole three-domain model exists to make possible.
    Every competitor can tell you a proposal scored 4.2. None of them can put
    that number beside the outcome, because the outcome lives in a CRM they do
    not read and the score lives in a survey tool the CRM does not read.

    Here both are columns in the same query.
    """
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    scores = (
        select(
            FeedbackResponse.target_id,
            func.count().label("responses"),
            func.avg(FeedbackResponse.overall_score).label("feedback_average"),
        )
        .group_by(FeedbackResponse.target_id)
        .subquery()
    )

    author = aliased(User)
    stmt = (
        select(
            Proposal.reference,
            Proposal.title,
            Proposal.client_name,
            author.full_name.label("author"),
            Proposal.stage,
            Proposal.value_amount,
            Proposal.won_amount,
            Proposal.loss_reason,
            Proposal.competitor,
            func.coalesce(scores.c.responses, 0).label("responses"),
            func.round(scores.c.feedback_average, 2).label("feedback_average"),
            Proposal.submitted_at,
        )
        .select_from(Proposal)
        .join(author, author.id == Proposal.author_id, isouter=True)
        .join(scores, scores.c.target_id == Proposal.target_id, isouter=True)
        .where(Proposal.stage != "draft")
    )

    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                Proposal.title.ilike(term),
                Proposal.client_name.ilike(term),
                Proposal.reference.ilike(term),
            )
        )
    if filters.severities:  # reused as a stage filter here
        stmt = stmt.where(Proposal.stage.in_(filters.severities))

    total = await _count(session, stmt)
    stmt = stmt.order_by(Proposal.submitted_at.desc().nullslast())
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()

    return ReportPage(
        rows=[
            {
                **dict(row),
                "stage": str(row["stage"]),
                "loss_reason": str(row["loss_reason"]) if row["loss_reason"] else None,
                "feedback_average": (
                    float(row["feedback_average"])
                    if row["feedback_average"] is not None
                    else None
                ),
            }
            for row in rows
        ],
        total=total,
        window=window,
    )


SCORECARD_REPORT = register(
    ReportDefinition(
        key="proposal_scorecard",
        title="Proposal scorecard",
        description=(
            "Every submitted proposal with the prospect's rating beside the "
            "actual outcome — so you can see whether the proposals that score "
            "well are the ones that win."
        ),
        columns=SCORECARD_COLUMNS,
        query=_query_scorecard,
        min_role=UserRole.MANAGER,
        default_sort="submitted_at",
        filters_supported=["search", "severities"],
    )
)


DELIVERY_COLUMNS = [
    Column("campaign", "Campaign", width=24),
    Column("contact_name", "Recipient", width=22),
    Column("contact_email", "Email", width=28, detail_only=True),
    Column("company", "Company", width=20),
    Column("subject", "About", width=22),
    Column("status", "Status", width=13, kind="badge"),
    Column("sent_at", "Sent", width=18, kind="datetime"),
    Column("first_opened_at", "Opened", width=18, kind="datetime"),
    Column("submitted_at", "Submitted", width=18, kind="datetime"),
    Column("open_count", "Opens", width=8, kind="number"),
]


async def _query_delivery(
    session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
) -> ReportPage:
    """Who was invited to an external campaign and how far they got.

    Contains no answers. Chasing a non-responder is an operational need; the
    contents of what they said belongs on the results report, behind the
    anonymity threshold.
    """
    timezone_name = actor.org.timezone if actor.org else "UTC"
    window = resolve_window(filters.date_range, timezone_name)

    stmt = (
        select(
            ReviewCycle.name.label("campaign"),
            Contact.full_name.label("contact_name"),
            Contact.email.label("contact_email"),
            Contact.company,
            FeedbackTarget.label.label("subject"),
            CampaignRecipient.status,
            CampaignRecipient.sent_at,
            CampaignRecipient.first_opened_at,
            CampaignRecipient.submitted_at,
            CampaignRecipient.open_count,
        )
        .select_from(CampaignRecipient)
        .join(ReviewCycle, ReviewCycle.id == CampaignRecipient.cycle_id)
        .join(Contact, Contact.id == CampaignRecipient.contact_id)
        .join(FeedbackTarget, FeedbackTarget.id == CampaignRecipient.target_id)
    )
    if filters.search:
        term = f"%{escape_like(filters.search)}%"
        stmt = stmt.where(
            or_(
                ReviewCycle.name.ilike(term),
                Contact.full_name.ilike(term),
                Contact.company.ilike(term),
                FeedbackTarget.label.ilike(term),
            )
        )
    if filters.severities:  # reused as a recipient-status filter here
        stmt = stmt.where(CampaignRecipient.status.in_(filters.severities))

    total = await _count(session, stmt)
    stmt = stmt.order_by(ReviewCycle.name, Contact.full_name)
    rows = (await session.execute(_apply_pagination(stmt, filters, paginate))).mappings().all()
    return ReportPage(rows=[dict(row) for row in rows], total=total, window=window)


DELIVERY_REPORT = register(
    ReportDefinition(
        key="campaign_delivery",
        title="Campaign delivery",
        description=(
            "Every external invitation: sent, opened, and submitted. Contains "
            "no answers, so it is safe to share with whoever is chasing "
            "responses."
        ),
        columns=DELIVERY_COLUMNS,
        query=_query_delivery,
        min_role=UserRole.MANAGER,
        default_sort="campaign",
        filters_supported=["search", "severities"],
    )
)


RESULTS_REPORT = register(
    ReportDefinition(
        key="feedback_results",
        title="Feedback results",
        description=(
            "Aggregated scores per person or item, per cycle. Averages are "
            "withheld until the anonymity threshold is met — in the file exactly "
            "as on the screen."
        ),
        columns=RESULT_COLUMNS,
        query=_query_results,
        min_role=UserRole.CLIENT_ADMIN,
        anonymity_sensitive=True,
        default_sort="cycle",
        filters_supported=["search"],
    )
)
