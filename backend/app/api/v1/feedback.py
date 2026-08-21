"""The unified Create Feedback / Results flow (Module — simplified UX pass).

`POST /feedback` is the single-call "create and send" action described in
`app/services/feedback.py`. `GET /feedback` is the one list Results.tsx reads
from — internal and external rounds together, which is the whole point: the
client did not want to learn two different places to look.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DbSession, ManagerUser
from app.core.errors import NotFound, ValidationFailed
from app.models.campaign import CampaignRecipient
from app.models.catalog import Contact, FeedbackTarget, FeedbackTemplate, FeedbackTemplateVersion
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import AuditAction, CycleAudience, CycleStatus, TargetType, UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import Page
from app.schemas.feedback import (
    FeedbackCreateRequest,
    FeedbackCreateResult,
    FeedbackListItem,
    FeedbackResponseAnswer,
    FeedbackResponseItem,
)
from app.services import audit
from app.services import campaigns as campaign_service
from app.services import cycles as cycle_service
from app.services import feedback as feedback_service
from app.services.forms import validate_definition

router = APIRouter(prefix="/feedback", tags=["feedback"])

DateFilterPreset = Literal["all", "last_30_days", "last_6_months", "last_12_months", "custom"]


def _resolve_date_floor(preset: DateFilterPreset, start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Self-contained on purpose — this is a simple "sent on or after X" filter
    for one list view, not a report export, so it deliberately doesn't reach
    for the shared FilterState/resolve_window machinery in app/reporting/:
    that path resolves timezone-aware, org-local windows for numbers that get
    downloaded and audited, which is more machinery than a results list needs
    and not worth coupling this page to.
    """
    if preset == "all":
        return None, None
    if preset == "custom":
        if not start or not end:
            raise ValidationFailed("A custom range needs both a start and an end date.")
        if start > end:
            raise ValidationFailed("The start date must be on or before the end date.")
        floor = datetime.combine(start, time.min, tzinfo=UTC)
        ceiling = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
        return floor, ceiling
    today = datetime.now(UTC).date()
    days = {"last_30_days": 30, "last_6_months": 182, "last_12_months": 365}[preset]
    floor = datetime.combine(today - timedelta(days=days), time.min, tzinfo=UTC)
    return floor, None

# What kind a listed cycle is, derived from audience + target type rather than
# stored redundantly — a cycle already carries everything needed to know.
_INTERNAL_KIND_BY_TARGET_TYPE = {
    str(TargetType.EMPLOYEE): "employee",
    str(TargetType.MANAGER): "management",
}
_EXTERNAL_KIND_BY_TARGET_TYPE = {
    str(TargetType.CLIENT): "client",
    str(TargetType.PRODUCT): "product",
    str(TargetType.SERVICE): "service",
    str(TargetType.PROPOSAL): "proposal",
}


def _kind_of(audience: CycleAudience, target_type: str | None) -> str:
    table = (
        _INTERNAL_KIND_BY_TARGET_TYPE
        if audience == CycleAudience.INTERNAL
        else _EXTERNAL_KIND_BY_TARGET_TYPE
    )
    return table.get(target_type or "", str(target_type or "unknown"))


async def _resolve_targets(
    session: DbSession, cycles: list[ReviewCycle]
) -> dict[uuid.UUID, FeedbackTarget]:
    """cycle_id -> its resolved FeedbackTarget, wherever that target actually
    comes from. Shared by `list_feedback` and `list_feedback_kinds` so the
    two never classify the same cycle two different ways.

    Three sources, in priority order: the cycle's own target_id when it has
    one; its assignments' shared target when it's an internal cycle without
    one (target_id only exists for external campaigns); its campaign
    recipients' shared target when it's an older external cycle that
    predates target_id being set at creation.
    """
    target_ids = {c.target_id for c in cycles if c.target_id is not None}
    targets: dict[uuid.UUID, FeedbackTarget] = {}
    if target_ids:
        targets = {
            t.id: t
            for t in (
                await session.execute(
                    select(FeedbackTarget).where(FeedbackTarget.id.in_(target_ids))
                )
            )
            .scalars()
            .all()
        }

    internal_cycle_ids = [
        c.id for c in cycles if c.audience != CycleAudience.EXTERNAL and c.target_id is None
    ]
    internal_targets: dict[uuid.UUID, FeedbackTarget] = {}
    if internal_cycle_ids:
        assignment_rows = (
            await session.execute(
                select(FeedbackAssignment.cycle_id, FeedbackTarget)
                .join(FeedbackTarget, FeedbackTarget.id == FeedbackAssignment.target_id)
                .where(FeedbackAssignment.cycle_id.in_(internal_cycle_ids))
            )
        ).all()
        for cycle_id, target_row in assignment_rows:
            internal_targets.setdefault(cycle_id, target_row)

    external_cycle_ids = [
        c.id for c in cycles if c.audience == CycleAudience.EXTERNAL and c.target_id is None
    ]
    external_targets: dict[uuid.UUID, FeedbackTarget] = {}
    if external_cycle_ids:
        recipient_rows = (
            await session.execute(
                select(CampaignRecipient.cycle_id, FeedbackTarget)
                .join(FeedbackTarget, FeedbackTarget.id == CampaignRecipient.target_id)
                .where(CampaignRecipient.cycle_id.in_(external_cycle_ids))
            )
        ).all()
        for cycle_id, target_row in recipient_rows:
            external_targets.setdefault(cycle_id, target_row)

    resolved: dict[uuid.UUID, FeedbackTarget] = {}
    for cycle in cycles:
        target = (
            targets.get(cycle.target_id)
            if cycle.target_id
            else (internal_targets.get(cycle.id) or external_targets.get(cycle.id))
        )
        if target is not None:
            resolved[cycle.id] = target
    return resolved


@router.post("", response_model=FeedbackCreateResult, status_code=201)
async def create_feedback(
    payload: FeedbackCreateRequest,
    request: Request,
    session: DbSession,
    actor: ManagerUser,
) -> FeedbackCreateResult:
    if actor.org_id is None:
        raise NotFound("A Super Admin must act within an organization.")
    org = (
        await session.execute(select(Organization).where(Organization.id == actor.org_id))
    ).scalar_one()

    result = await feedback_service.create_and_send(
        session,
        org=org,
        actor=actor.user,
        kind=payload.kind,
        template_id=payload.template_id,
        name=payload.name,
        closes_at=payload.closes_at,
        reviewee_user_id=payload.reviewee_user_id,
        about_user_id=payload.about_user_id,
        contact_ids=payload.contact_ids or None,
        target_label=payload.target_label,
        manager_ids=payload.manager_ids,
        audience=payload.audience,
        recipient_user_ids=payload.recipient_user_ids or None,
    )

    await audit.record(
        session,
        action=AuditAction.CYCLE_CREATED,
        summary=(
            f"{actor.user.full_name} created and sent '{result.cycle.name}' "
            f"({payload.kind})"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="review_cycle",
        target_id=result.cycle.id,
        target_label=result.cycle.name,
        context={"kind": payload.kind, "warnings": result.warnings},
        request=request,
    )
    await session.commit()

    return FeedbackCreateResult(
        cycle_id=result.cycle.id,
        status=str(result.cycle.status),
        warnings=result.warnings,
    )


async def _build_feedback_items(
    session: DbSession,
    actor: ManagerUser,
    *,
    kind: str | None,
    status: str | None,
    org_id: uuid.UUID | None,
    client_name: str | None,
    cycle_name: str | None,
    q: str | None,
    date_floor: datetime | None,
    date_ceiling: datetime | None,
    closing_within_days: int | None = None,
) -> list[FeedbackListItem]:
    """Every feedback round, internal and external together, newest first.

    This is the one place the Results table is built — both `GET /feedback`
    (the screen) and the `results_overview` report definition (the Export
    button) call it with the same arguments, so the file a person downloads
    can never disagree with what they were looking at when they clicked
    Export.

    `kind` and the date window are derived/computed per row rather than
    stored columns, so filtering on them happens in Python after the rows are
    built below rather than as SQL `WHERE` clauses — organization-scale
    result-round counts make that entirely fine, and it avoids duplicating
    the same target-resolution logic in two places (a SQL version for
    filtering and this one for display).

    `q` — already lower-cased by the caller — is the free-text "Search" box
    on the Results page. It matches against nearly everything visible in
    the table: Cycle Name, Client, Type (both the internal slug and its
    display label, so typing either "employee" or "Employees" finds it),
    Reviewed by, Reviewed to, Sent on, Status. Progress is deliberately not
    included: it needs its own async query per cycle
    (`campaign_progress`/`cycle_progress` below), and running that for
    every row just to make a fraction like "0/6" searchable isn't a trade
    worth making for how rarely anyone would actually type that.

    `client_name` is the "Organisation Name" dropdown's separate,
    exact-match filter — matched against the raw company name
    (`client_names` below), not the richer "Contact - Company" text the
    Client Name *column* actually shows (`client_display` below); those two
    intentionally stay separate so reformatting the column never breaks
    what the filter matches against. When both are set, `q` only searches
    within whatever `client_name` already narrowed to, since both filters
    apply together in the same pass below rather than one replacing the
    other.
    """
    q_term = q

    stmt = select(ReviewCycle)
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN):
        stmt = stmt.where(ReviewCycle.created_by_id == actor.id)
    # Only a Super Admin's session spans more than one org (RLS already
    # scopes everyone else to their own), so this filter is a real narrowing
    # for them and a harmless no-op for anyone it doesn't apply to.
    if org_id is not None:
        stmt = stmt.where(ReviewCycle.org_id == org_id)
    if status:
        stmt = stmt.where(ReviewCycle.status == status)
    if cycle_name:
        stmt = stmt.where(ReviewCycle.name.ilike(f"%{cycle_name}%"))
    if closing_within_days is not None:
        # Same three conditions the Dashboard's own "Closing within 7 days"
        # tile counts by (dashboard.py) and the internal-only /cycles list
        # filter uses (api/v1/cycles.py) — kept in lockstep across all
        # three. Unlike the /cycles version, this one deliberately does not
        # exclude external rounds: Results is the one screen built to show
        # both kinds together, so a count meant to route here should too.
        deadline = datetime.now(UTC) + timedelta(days=closing_within_days)
        stmt = stmt.where(
            ReviewCycle.status == CycleStatus.OPEN,
            ReviewCycle.closes_at.is_not(None),
            ReviewCycle.closes_at <= deadline,
        )
    cycles = (
        (await session.execute(stmt.order_by(ReviewCycle.created_at.desc())))
        .scalars()
        .all()
    )
    if not cycles:
        return []

    # Client/org names — every actor sees these now (the Results table's
    # "Client" column isn't Super-Admin-only anymore), not just a Super
    # Admin narrowing across orgs. A single-org Client Admin just gets their
    # own org's name repeated on every row, which is harmless and lets `q`
    # match on it too.
    org_ids = {c.org_id for c in cycles}
    org_names: dict[uuid.UUID, str] = dict(
        (
            await session.execute(
                select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
            )
        ).all()
    )

    version_ids = {c.template_version_id for c in cycles}
    versions = dict(
        (
            await session.execute(
                select(FeedbackTemplateVersion.id, FeedbackTemplate.name)
                .join(
                    FeedbackTemplate,
                    FeedbackTemplate.id == FeedbackTemplateVersion.template_id,
                )
                .where(FeedbackTemplateVersion.id.in_(version_ids))
            )
        ).all()
    )

    resolved_targets = await _resolve_targets(session, cycles)

    # Who the request actually went to, for the "Reviewed by" / "Sent to"
    # columns — the external contacts for a campaign, or the internal
    # reviewers for a cycle. Batched up front, same as targets/versions
    # above, rather than a per-row query in the loop below.
    recipient_names: dict[uuid.UUID, list[str]] = {}
    external_ids = [c.id for c in cycles if c.audience == CycleAudience.EXTERNAL]
    if external_ids:
        rows = (
            await session.execute(
                select(CampaignRecipient.cycle_id, Contact.full_name, Contact.email)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(CampaignRecipient.cycle_id.in_(external_ids))
                .order_by(Contact.full_name)
            )
        ).all()
        for cycle_id, full_name, email in rows:
            recipient_names.setdefault(cycle_id, []).append(full_name or email)

    # The reviewing contact's own company — used for the Organisation Name
    # filter/search matching, not for display. Kept as the *raw* company
    # name specifically so it exactly matches what the filter dropdown's
    # options (from /contacts/companies) and the client_name query param
    # actually send — the richer "Contact - Company" text below would never
    # equal a plain company name, so the filter would silently stop
    # matching anything if this got repurposed for both.
    client_names: dict[uuid.UUID, str] = {}
    if external_ids:
        company_rows = (
            await session.execute(
                select(CampaignRecipient.cycle_id, Contact.company)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(CampaignRecipient.cycle_id.in_(external_ids))
                .where(Contact.company.isnot(None))
                .distinct()
            )
        ).all()
        companies_by_cycle: dict[uuid.UUID, set[str]] = {}
        for cycle_id, company in company_rows:
            companies_by_cycle.setdefault(cycle_id, set()).add(company)
        for cycle_id, companies in companies_by_cycle.items():
            client_names[cycle_id] = ", ".join(sorted(companies))

    # What the Client Name *column* actually shows — "Contact - Company" for
    # an external round (who reviewed, and which client they're with; a
    # richer answer than the plain company list above), or the tenant org
    # name for an internal round, which has no client contact to show at
    # all otherwise.
    client_display: dict[uuid.UUID, str] = {}
    if external_ids:
        contact_rows = (
            await session.execute(
                select(CampaignRecipient.cycle_id, Contact.full_name, Contact.company)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(CampaignRecipient.cycle_id.in_(external_ids))
                .order_by(Contact.full_name)
            )
        ).all()
        labels_by_cycle: dict[uuid.UUID, list[str]] = {}
        for cycle_id, full_name, company in contact_rows:
            label = f"{full_name} - {company}" if company else full_name
            labels_by_cycle.setdefault(cycle_id, []).append(label)
        for cycle_id, labels in labels_by_cycle.items():
            distinct = list(dict.fromkeys(labels))  # de-dupe, keep first-seen order
            client_display[cycle_id] = (
                distinct[0] if len(distinct) == 1 else f"{distinct[0]} +{len(distinct) - 1} more"
            )
    for cycle in cycles:
        if cycle.audience != CycleAudience.EXTERNAL:
            client_display[cycle.id] = org_names.get(cycle.org_id)

    internal_ids = [c.id for c in cycles if c.audience != CycleAudience.EXTERNAL]
    if internal_ids:
        rows = (
            await session.execute(
                select(FeedbackAssignment.cycle_id, User.full_name)
                .join(User, User.id == FeedbackAssignment.reviewer_user_id)
                .where(FeedbackAssignment.cycle_id.in_(internal_ids))
                .distinct()
                .order_by(User.full_name)
            )
        ).all()
        for cycle_id, full_name in rows:
            recipient_names.setdefault(cycle_id, []).append(full_name)

    items: list[FeedbackListItem] = []
    for cycle in cycles:
        target = resolved_targets.get(cycle.id)
        target_type = str(target.target_type) if target else None
        cycle_kind = _kind_of(cycle.audience, target_type)
        if kind and cycle_kind != kind:
            continue

        # Exact match, not a search — this comes from picking a name off the
        # "Organisation Name" dropdown (itself sourced from the same
        # distinct-companies list as the Client Organisation picker on the
        # create-feedback form), not typed freehand. An internal cycle
        # (nothing in client_names for it) never matches a real selected
        # name, so narrowing to one organisation correctly drops every
        # internal round too.
        if client_name and client_names.get(cycle.id) != client_name:
            continue

        if q_term:
            haystack_parts = [
                cycle.name,
                target.label if target else None,
                org_names.get(cycle.org_id),
                client_names.get(cycle.id),
                cycle_kind,
                # The internal kind slug alone ("employee") doesn't
                # necessarily match what's actually printed in the Type
                # column ("Employees") — this is what makes typing the
                # visible label work, not just the slug it's derived from.
                _KIND_LABEL.get(cycle_kind, cycle_kind),
                str(cycle.status),
                # Matches the M/D/YYYY shape the Sent on column renders
                # (toLocaleDateString() with no explicit locale), so typing
                # the date you see actually finds it.
                f"{(cycle.opened_at or cycle.created_at).month}/"
                f"{(cycle.opened_at or cycle.created_at).day}/"
                f"{(cycle.opened_at or cycle.created_at).year}",
                *recipient_names.get(cycle.id, []),
            ]
            haystack = " ".join(part for part in haystack_parts if part).lower()
            if q_term not in haystack:
                continue

        # "Sent" for filtering purposes: opened_at when it has one, otherwise
        # the cycle's own created_at — a still-draft round has no opened_at
        # but should not just vanish from a date-filtered view.
        sent_reference = cycle.opened_at or cycle.created_at
        if date_floor and sent_reference < date_floor:
            continue
        if date_ceiling and sent_reference >= date_ceiling:
            continue

        if cycle.audience == CycleAudience.EXTERNAL:
            progress = await campaign_service.campaign_progress(session, cycle.id)
            total, responded = progress["total"], progress["submitted"]
        else:
            progress = await cycle_service.cycle_progress(session, cycle.id)
            total, responded = progress["total"], progress["submitted"]

        items.append(
            FeedbackListItem(
                id=cycle.id,
                kind=cycle_kind,
                audience=str(cycle.audience),
                target_id=target.id if target else None,
                target_label=target.label if target else None,
                target_type=target_type,
                template_name=versions.get(cycle.template_version_id),
                name=cycle.name,
                status=str(cycle.status),
                is_anonymous=cycle.is_anonymous,
                sent_at=cycle.opened_at,
                created_at=cycle.created_at,
                closes_at=cycle.closes_at,
                total=total,
                responded=responded,
                org_id=cycle.org_id,
                org_name=org_names.get(cycle.org_id),
                client_name=client_display.get(cycle.id),
                recipients=recipient_names.get(cycle.id, []),
            )
        )

    return items


@router.get("", response_model=Page[FeedbackListItem])
async def list_feedback(
    session: DbSession,
    actor: ManagerUser,
    kind: str | None = None,
    status: str | None = None,
    org_id: uuid.UUID | None = None,
    client_name: str | None = None,
    cycle_name: str | None = None,
    q: str | None = None,
    date_preset: DateFilterPreset = "all",
    date_start: date | None = None,
    date_end: date | None = None,
    closing_within_days: int | None = None,
    page: int = 1,
    page_size: int = 15,
) -> Page[FeedbackListItem]:
    """The paginated screen the Results page reads from — see
    `_build_feedback_items` for the actual query and filtering."""
    date_floor, date_ceiling = _resolve_date_floor(date_preset, date_start, date_end)
    q_term = q.strip().lower() if q and q.strip() else None

    items = await _build_feedback_items(
        session,
        actor,
        kind=kind,
        status=status,
        org_id=org_id,
        client_name=client_name,
        cycle_name=cycle_name,
        q=q_term,
        date_floor=date_floor,
        date_ceiling=date_ceiling,
        closing_within_days=closing_within_days,
    )

    total_matching = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return Page(items=page_items, total=total_matching, page=page, page_size=page_size)


@router.get("/cycle-names", response_model=list[str])
async def list_feedback_cycle_names(
    session: DbSession,
    actor: ManagerUser,
    org_id: uuid.UUID | None = None,
    client_name: str | None = None,
) -> list[str]:
    """Distinct cycle names for the Results page's "Cycle name" filter dropdown.

    Scoped the same way `list_feedback` is (own cycles only below Client
    Admin, optional org narrowing for a Super Admin, optional client-company
    narrowing for everyone) so the dropdown never offers a name the person
    couldn't actually filter to.
    """
    stmt = select(ReviewCycle.name).distinct()
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN):
        stmt = stmt.where(ReviewCycle.created_by_id == actor.id)
    if org_id is not None:
        stmt = stmt.where(ReviewCycle.org_id == org_id)
    if client_name:
        stmt = stmt.where(
            ReviewCycle.id.in_(
                select(CampaignRecipient.cycle_id)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(Contact.company == client_name)
            )
        )
    stmt = stmt.order_by(ReviewCycle.name.asc())
    return [row[0] for row in (await session.execute(stmt)).all()]


# Canonical display order for the "Feedback type" dropdown — matches
# FEEDBACK_TYPES on the frontend, rather than however a Python set happens
# to iterate.
_KIND_ORDER = ["client", "employee", "management", "product", "service", "proposal"]

# Same source of truth, for the opposite direction — what each kind slug
# actually prints as in the Type column, so free-text search can match the
# label someone sees ("Employees") and not just the slug it's derived from
# ("employee"). Also mirrors FEEDBACK_TYPES on the frontend.
_KIND_LABEL = {
    "client": "Client",
    "employee": "Employees",
    "management": "Management",
    "product": "Product",
    "service": "Service",
    "proposal": "Proposal Review",
}


@router.get("/kinds", response_model=list[str])
async def list_feedback_kinds(
    session: DbSession,
    actor: ManagerUser,
    org_id: uuid.UUID | None = None,
    client_name: str | None = None,
) -> list[str]:
    """Distinct feedback kinds actually present for the current Organisation
    Name / Client filter, for the Results page's "Feedback type" dropdown —
    same idea as cycle-names above, for the other dropdown that was still
    listing every kind regardless of which organisation was selected.

    `kind` is computed, not a stored column (see `_kind_of`), so this reuses
    the same target-resolution helper `list_feedback` itself uses rather
    than guessing at kinds from `ReviewCycle` columns alone.
    """
    stmt = select(ReviewCycle)
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN):
        stmt = stmt.where(ReviewCycle.created_by_id == actor.id)
    if org_id is not None:
        stmt = stmt.where(ReviewCycle.org_id == org_id)
    if client_name:
        stmt = stmt.where(
            ReviewCycle.id.in_(
                select(CampaignRecipient.cycle_id)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(Contact.company == client_name)
            )
        )
    cycles = (await session.execute(stmt)).scalars().all()
    if not cycles:
        return []

    resolved_targets = await _resolve_targets(session, cycles)
    present: set[str] = set()
    for cycle in cycles:
        target = resolved_targets.get(cycle.id)
        target_type = str(target.target_type) if target else None
        present.add(_kind_of(cycle.audience, target_type))

    return [k for k in _KIND_ORDER if k in present]


@router.get("/{cycle_id}/responses", response_model=list[FeedbackResponseItem])
async def list_feedback_responses(
    cycle_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> list[FeedbackResponseItem]:
    """Every individual response to one round, for the Results detail popup.

    Identity is included only for responses that are not themselves
    anonymous — `FeedbackResponse.is_anonymous` (backed by a DB check
    constraint on the reviewer/recipient columns) is the one thing this
    trusts, not the cycle's `is_anonymous` default, since a response's own
    flag is what was actually enforced at submit time.
    """
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id))
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFound("That feedback round does not exist.")
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN) and cycle.created_by_id not in (
        None,
        actor.id,
    ):
        raise NotFound("That feedback round does not exist.")

    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(FeedbackTemplateVersion.id == cycle.template_version_id)
        )
    ).scalar_one()
    form = validate_definition(version.definition)
    by_key = {question.key: question for question in form.questions}

    responses = (
        (
            await session.execute(
                select(FeedbackResponse)
                .where(FeedbackResponse.cycle_id == cycle_id)
                .order_by(FeedbackResponse.submitted_at.desc())
            )
        )
        .scalars()
        .all()
    )

    reviewer_ids = {r.reviewer_user_id for r in responses if r.reviewer_user_id}
    users: dict[uuid.UUID, User] = {}
    if reviewer_ids:
        users = {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(reviewer_ids)))
            )
            .scalars()
            .all()
        }

    recipient_ids = {r.recipient_id for r in responses if r.recipient_id}
    recipients: dict[uuid.UUID, tuple[str, str]] = {}
    if recipient_ids:
        rows = (
            await session.execute(
                select(CampaignRecipient.id, Contact.full_name, Contact.email)
                .join(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(CampaignRecipient.id.in_(recipient_ids))
            )
        ).all()
        recipients = {rid: (name, email) for rid, name, email in rows}

    items: list[FeedbackResponseItem] = []
    for response in responses:
        name: str | None = None
        email: str | None = None
        if not response.is_anonymous:
            if response.reviewer_user_id and response.reviewer_user_id in users:
                user = users[response.reviewer_user_id]
                name, email = user.full_name, user.email
            elif response.recipient_id and response.recipient_id in recipients:
                name, email = recipients[response.recipient_id]

        answers: list[FeedbackResponseAnswer] = []
        for key, value in (response.answers or {}).items():
            question = by_key.get(key)
            if question is None:
                continue
            answers.append(
                FeedbackResponseAnswer(key=key, text=question.text, type=question.type, value=value)
            )

        items.append(
            FeedbackResponseItem(
                id=response.id,
                respondent_name=name,
                respondent_email=email,
                relationship=str(response.relationship_type),
                is_anonymous=response.is_anonymous,
                submitted_at=response.submitted_at,
                overall_score=float(response.overall_score) if response.overall_score is not None else None,
                comment=response.comment,
                answers=answers,
            )
        )
    return items


@router.get("/{cycle_id}/delivery")
async def feedback_delivery(
    cycle_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> dict[str, Any]:
    """Engagement funnel for one round, for the Results detail popup.

    This is what the old, separate Campaigns page used to show on each
    campaign card (sent/opened/responded, response rate) — folded into the
    unified Results view rather than living on its own page. An external
    round tracks delivery through email (sent/opened/responded); an internal
    one has no delivery step at all — reviewers are assigned directly — so it
    reports assignment progress instead (pending/in progress/submitted).
    """
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id))
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFound("That feedback round does not exist.")
    if not actor.user.role.at_least(UserRole.CLIENT_ADMIN) and cycle.created_by_id not in (
        None,
        actor.id,
    ):
        raise NotFound("That feedback round does not exist.")

    if cycle.audience == CycleAudience.EXTERNAL:
        progress = await campaign_service.campaign_progress(session, cycle_id)
        return {"audience": "external", **progress}
    progress = await cycle_service.cycle_progress(session, cycle_id)
    return {"audience": "internal", **progress}