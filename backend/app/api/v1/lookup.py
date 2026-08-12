"""Autocomplete lookup endpoints.

Every filter control in the product that accepts an entity is backed by one of
these. They return an id and a label and nothing more: a typeahead that returns
full records is a directory export for anyone who can type a letter.

Matching uses pg_trgm similarity with the GIN indexes created in migration
0001, so a partial match stays index-backed instead of degrading to a scan as
a tenant grows.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFound
from app.core.ratelimit import LOOKUP_PER_USER, limiter
from app.models.audit import AuditLog
from app.models.catalog import Contact, FeedbackTarget
from app.models.enums import AuditAction, AuditSeverity, UserRole, UserStatus
from app.models.organization import Organization
from app.models.user import User
from app.reporting.filters import escape_like
from app.schemas.common import LookupItem

router = APIRouter(prefix="/lookup", tags=["lookup"])

MAX_RESULTS = 20


@router.get("/{entity}", response_model=list[LookupItem])
async def lookup(
    entity: str,
    session: DbSession,
    actor: CurrentUser,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=MAX_RESULTS, ge=1, le=50),
) -> list[LookupItem]:
    await limiter.hit(f"lookup:{actor.id}", LOOKUP_PER_USER)
    term = f"%{escape_like(q.strip())}%" if q.strip() else None

    if entity == "users":
        # Active only, not just "not disabled" — an invited-but-not-yet-
        # activated person cannot log in to review anything, so offering them
        # here (as a reviewer, a manager, a recipient owner, etc.) across
        # cycles, campaigns, and every other picker built on this lookup
        # would let someone get assigned work they cannot see or do yet.
        stmt = select(User.id, User.full_name, User.email, User.job_title).where(
            User.status == UserStatus.ACTIVE
        )
        if term:
            stmt = stmt.where(or_(User.full_name.ilike(term), User.email.ilike(term)))
        stmt = stmt.order_by(User.full_name.asc()).limit(limit)
        return [
            LookupItem(id=row.id, label=row.full_name, sublabel=row.job_title or row.email)
            for row in (await session.execute(stmt)).all()
        ]

    if entity == "organizations":
        # Cross-tenant by nature, so this one is Super Admin only. RLS would
        # already reduce it to a single row for anyone else, but returning 403
        # is clearer than returning a list of one.
        if not actor.is_super_admin:
            raise NotFound("No such lookup.")
        stmt = select(Organization.id, Organization.name, Organization.slug)
        if term:
            stmt = stmt.where(
                or_(Organization.name.ilike(term), Organization.slug.ilike(term))
            )
        stmt = stmt.order_by(Organization.name.asc()).limit(limit)
        return [
            LookupItem(id=row.id, label=row.name, sublabel=row.slug)
            for row in (await session.execute(stmt)).all()
        ]

    if entity == "contacts":
        stmt = select(Contact.id, Contact.full_name, Contact.company, Contact.email)
        if term:
            stmt = stmt.where(
                or_(
                    Contact.full_name.ilike(term),
                    Contact.email.ilike(term),
                    Contact.company.ilike(term),
                )
            )
        stmt = stmt.order_by(Contact.full_name.asc()).limit(limit)
        return [
            LookupItem(id=row.id, label=row.full_name, sublabel=row.company or row.email)
            for row in (await session.execute(stmt)).all()
        ]

    if entity == "targets":
        stmt = select(
            FeedbackTarget.id, FeedbackTarget.label, FeedbackTarget.target_type
        ).where(FeedbackTarget.is_active.is_(True))
        if term:
            stmt = stmt.where(FeedbackTarget.label.ilike(term))
        stmt = stmt.order_by(FeedbackTarget.label.asc()).limit(limit)
        return [
            LookupItem(id=row.id, label=row.label, sublabel=str(row.target_type))
            for row in (await session.execute(stmt)).all()
        ]

    if entity == "actors":
        # People who actually appear in this tenant's audit log. Filtering by
        # the whole directory would offer names that can never match a row.
        stmt = (
            select(AuditLog.actor_id, AuditLog.actor_name, AuditLog.actor_email)
            .where(AuditLog.actor_id.isnot(None))
            .group_by(AuditLog.actor_id, AuditLog.actor_name, AuditLog.actor_email)
        )
        if term:
            stmt = stmt.where(
                or_(AuditLog.actor_name.ilike(term), AuditLog.actor_email.ilike(term))
            )
        stmt = stmt.order_by(func.min(AuditLog.actor_name)).limit(limit)
        return [
            LookupItem(
                id=row.actor_id, label=row.actor_name or row.actor_email or "Unknown",
                sublabel=row.actor_email,
            )
            for row in (await session.execute(stmt)).all()
        ]

    raise NotFound(f"No lookup named '{entity}'.")


@router.get("-static/{entity}", response_model=list[dict])
async def static_options(entity: str, actor: CurrentUser) -> list[dict]:
    """Enumerations for filter dropdowns, kept server-side as one source of truth."""
    if entity == "audit_actions":
        return [
            {"value": action.value, "label": action.value.split(".")[-1].replace("_", " ").title(),
             "group": action.value.split(".")[0].title()}
            for action in AuditAction
        ]
    if entity == "severities":
        return [{"value": s.value, "label": s.value.title()} for s in AuditSeverity]
    if entity == "roles":
        return [
            {"value": r.value, "label": r.value.replace("_", " ").title()}
            for r in UserRole
            if actor.is_super_admin or r != UserRole.SUPER_ADMIN
        ]
    raise NotFound(f"No option set named '{entity}'.")
