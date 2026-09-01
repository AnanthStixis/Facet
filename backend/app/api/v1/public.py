"""The public respondent endpoint (Module B).

This is the only unauthenticated, internet-facing surface that touches tenant
data, so the rules it plays by are stricter than anywhere else in the app.

**Tenant binding.** Resolving the link has the same bootstrapping problem as
login: a tenant-scoped row must be found before any tenant is bound. It is
solved the same way — one SECURITY DEFINER function (`facet_public_link`,
migration 0005) returns only enough to identify the link's organization. The
handler then binds *that* organization and does everything else under ordinary
row level security. A bug in this file can therefore only ever reach the tenant
the presented token already belonged to.

**No enumeration.** Every failure — unknown token, expired link, already
submitted, campaign closed, revoked — returns the same 404 shape with a
deliberately unhelpful message. Distinguishing them would let anyone with a
list of guesses learn which tokens exist and which customers are running
campaigns.

**No account.** The respondent never authenticates, never sets a password, and
is never left holding a dormant credential when the engagement ends. That is
the product promise from the functional spec, and it is also the safest option:
credentials that do not exist cannot be reused or breached.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.ratelimit import Limit, limiter
from app.core.security import hash_token
from app.db.tenancy import TenantContext, bind_tenant
from app.models.campaign import CampaignRecipient
from app.models.catalog import Contact, FeedbackTarget, FeedbackTemplateVersion
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import AuditAction, CycleStatus, RecipientStatus, Relationship
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.cycle import SubmitResponseRequest
from app.services import audit
from app.services import email as email_service
from app.services.campaigns import maybe_auto_close
from app.services.forms import form_payload, validate_answers, validate_definition
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import AssignmentStatus, Relationship, TargetType
from app.services import cycles as cycle_service
from app.services.forms import form_payload, validate_answers, validate_definition
from app.services import cycles as cycle_service

log = get_logger("facet.public")

router = APIRouter(prefix="/public", tags=["public"])

# Tight limits. A legitimate respondent opens their link a handful of times;
# anything beyond that is someone walking the token space.
LINK_PER_IP = Limit(times=40, seconds=300)
LINK_PER_TOKEN = Limit(times=20, seconds=300)
SUBMIT_PER_IP = Limit(times=10, seconds=300)

# One message for every failure mode, so the endpoint reveals nothing about
# which tokens exist.
DEAD_LINK = (
    "This feedback link is no longer valid. It may have already been used, "
    "expired, or been withdrawn. Please ask your contact for a new one."
)


class _Link:
    __slots__ = ("recipient_id", "org_id", "cycle_id", "target_id", "contact_id")

    def __init__(self, row: Any) -> None:
        self.recipient_id: uuid.UUID = row["recipient_id"]
        self.org_id: uuid.UUID = row["org_id"]
        self.cycle_id: uuid.UUID = row["cycle_id"]
        self.target_id: uuid.UUID = row["target_id"]
        self.contact_id: uuid.UUID = row["contact_id"]


async def _resolve(session: DbSession, token: str, request: Request) -> _Link:
    """Turn a raw token into a bound tenant context, or raise a flat 404."""
    await limiter.hit(f"link:ip:{audit.client_ip(request) or 'unknown'}", LINK_PER_IP)

    if not token or len(token) < 20 or len(token) > 128:
        raise NotFound(DEAD_LINK)

    token_hash = hash_token(token)
    await limiter.hit(f"link:tok:{token_hash[:16]}", LINK_PER_TOKEN)

    row = (
        await session.execute(
            text("SELECT * FROM facet_public_link(:token_hash)"),
            {"token_hash": token_hash},
        )
    ).mappings().first()

    if row is None:
        raise NotFound(DEAD_LINK)

    now = datetime.now(UTC)
    status = RecipientStatus(row["status"])
    if (
        status
        in {
            RecipientStatus.SUBMITTED,
            RecipientStatus.REVOKED,
            RecipientStatus.EXPIRED,
            RecipientStatus.UNSUBSCRIBED,
        }
        or row["expires_at"] <= now
        or CycleStatus(row["cycle_status"]) != CycleStatus.OPEN
    ):
        raise NotFound(DEAD_LINK)

    # From here on the request behaves like any other: one tenant bound, RLS
    # doing the enforcing.
    await bind_tenant(
        session, TenantContext(org_id=row["org_id"], is_super_admin=False)
    )
    return _Link(row)


def _harden(response: Response) -> None:
    """Headers for a page that renders tenant-supplied text to strangers."""
    response.headers["x-robots-tag"] = "noindex, nofollow"
    response.headers["cache-control"] = "no-store"
    response.headers["referrer-policy"] = "no-referrer"


@router.get("/feedback/{token}")
async def open_link(
    token: str, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    """Render the branded form for a valid link."""
    link = await _resolve(session, token, request)
    _harden(response)

    recipient = (
        await session.execute(
            select(CampaignRecipient).where(CampaignRecipient.id == link.recipient_id)
        )
    ).scalar_one()
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == link.cycle_id))
    ).scalar_one()
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == link.target_id)
        )
    ).scalar_one()
    contact = (
        await session.execute(select(Contact).where(Contact.id == link.contact_id))
    ).scalar_one()
    org = (
        await session.execute(
            select(Organization).where(Organization.id == link.org_id)
        )
    ).scalar_one()
    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(
                FeedbackTemplateVersion.id == cycle.template_version_id
            )
        )
    ).scalar_one()

    now = datetime.now(UTC)
    if recipient.first_opened_at is None:
        recipient.first_opened_at = now
    recipient.open_count += 1
    recipient.last_ip = audit.client_ip(request)
    if recipient.status == RecipientStatus.SENT:
        recipient.status = RecipientStatus.OPENED
    await session.commit()

    form = validate_definition(version.definition)
    return {
        "organization": {
            "name": org.name,
            "accent_color": org.branding.accent_color if org.branding else "#B4633A",
            "logo_url": (
                f"{settings.public_api_url}/api/v1/public/logo/{token}"
                if org.branding and org.branding.logo_path
                else None
            ),
        },
        "recipient": {
            # Only the recipient's own details, so a leaked link exposes the
            # person who already had it and nobody else.
            "full_name": contact.full_name,
            "company": contact.company,
        },
        "subject": {"label": target.label, "type": str(target.target_type)},
        "campaign": {"name": cycle.name, "closes_at": cycle.closes_at},
        "is_anonymous": cycle.is_anonymous,
        "form": form_payload(form),
    }


@router.get("/logo/{token}")
async def branded_logo(
    token: str, request: Request, session: DbSession
) -> Response:
    """Serve the tenant logo to an unauthenticated respondent.

    Reached only by presenting a valid link, so it does not expose branding to
    anyone who was not already invited.
    """
    link = await _resolve(session, token, request)
    org = (
        await session.execute(
            select(Organization).where(Organization.id == link.org_id)
        )
    ).scalar_one()
    if org.branding is None or not org.branding.logo_path:
        raise NotFound("No logo.")

    from app.services import storage

    result = storage.read_logo(org.branding.logo_path)
    if result is None:
        raise NotFound("No logo.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "cache-control": "private, max-age=300",
            "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
            "x-content-type-options": "nosniff",
            "x-robots-tag": "noindex, nofollow",
        },
    )

@router.get("/assignment-logo/{token}")
async def branded_assignment_logo(
    token: str, request: Request, session: DbSession
) -> Response:
    """Serve the tenant logo to an internal reviewer on the assignment
    link flow — the counterpart to branded_logo above, resolving through
    an assignment token instead of a campaign recipient token, since the
    two are different token spaces validated by different SQL functions
    (facet_assignment_link vs facet_public_link).
    """
    link = await _resolve_assignment(session, token, request)
    org = (
        await session.execute(
            select(Organization).where(Organization.id == link.org_id)
        )
    ).scalar_one()
    if org.branding is None or not org.branding.logo_path:
        raise NotFound("No logo.")

    from app.services import storage

    result = storage.read_logo(org.branding.logo_path)
    if result is None:
        raise NotFound("No logo.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "cache-control": "private, max-age=300",
            "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
            "x-content-type-options": "nosniff",
            "x-robots-tag": "noindex, nofollow",
        },
    )


@router.post("/feedback/{token}", response_model=MessageResponse)
async def submit_link(
    token: str,
    payload: SubmitResponseRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> MessageResponse:
    """Accept one submission and burn the link."""
    await limiter.hit(
        f"submit:ip:{audit.client_ip(request) or 'unknown'}", SUBMIT_PER_IP
    )
    link = await _resolve(session, token, request)
    _harden(response)

    recipient = (
        await session.execute(
            select(CampaignRecipient).where(CampaignRecipient.id == link.recipient_id)
        )
    ).scalar_one()
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == link.cycle_id))
    ).scalar_one()
    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(
                FeedbackTemplateVersion.id == cycle.template_version_id
            )
        )
    ).scalar_one()

    form = validate_definition(version.definition)
    scored = validate_answers(form, payload.answers, payload.comment)

    now = datetime.now(UTC)
    session.add(
        FeedbackResponse(
            org_id=cycle.org_id,
            cycle_id=cycle.id,
            target_id=link.target_id,
            template_version_id=version.id,
            # Same rule as internal feedback: when the round is anonymous there
            # is no stored path back to the respondent, external or not.
            recipient_id=None if cycle.is_anonymous else recipient.id,
            assignment_id=None,
            reviewer_user_id=None,
            is_anonymous=cycle.is_anonymous,
            relationship_type=Relationship.EXTERNAL,
            answers=scored.answers,
            comment=scored.comment,
            overall_score=scored.overall_score,
            answered_count=scored.answered_count,
            submitted_at=now,
        )
    )

    # Burning the token is what makes the link single use. It happens in the
    # same transaction as the response, so a failure cannot leave a spent link
    # that still works or a burnt link with no answers behind it.
    recipient.status = RecipientStatus.SUBMITTED
    recipient.submitted_at = now
    recipient.token_hash = hash_token(uuid.uuid4().hex + uuid.uuid4().hex)
    await session.flush()
    await maybe_auto_close(session, cycle)

    await audit.record(
        session,
        action=AuditAction.EXTERNAL_RESPONSE,
        summary=f"An external response was received for '{cycle.name}'",
        org_id=cycle.org_id,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"anonymous": cycle.is_anonymous, "batch": recipient.batch},
        request=request,
    )
    # These reads must happen before commit: `bind_tenant` sets the tenant
    # GUC with `SET LOCAL`, which only lives for the current transaction.
    # Reading Contact/FeedbackTarget/Organization (all RLS-protected) after
    # `commit()` would run in a new, unbound transaction and silently return
    # nothing — exactly the bug that made this block never actually send.
    contact = (
        await session.execute(select(Contact).where(Contact.id == link.contact_id))
    ).scalar_one()
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == link.target_id)
        )
    ).scalar_one()
    org = (
        await session.execute(select(Organization).where(Organization.id == link.org_id))
    ).scalar_one()

    # The BCC recipient reads this instead of opening the app, so it carries
    # the actual answers, not a link to go look.
    answer_rows: list[tuple[str, str]] = []
    for question in form.questions:
        value = scored.answers.get(question.key)
        if value is None:
            continue
        if question.type == "scale":
            display = f"{value} / {form.scale_max}"
        elif question.type == "boolean":
            display = "Yes" if value else "No"
        else:
            display = str(value)
        answer_rows.append((question.text, display))

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

    await session.commit()

    # Best-effort from here: the response is already committed, so a mail
    # failure here must never surface as an error to the respondent — they
    # already got the "thank you" screen and that's the real contract.
    try:
        await email_service.send_thank_you(
            to=contact.email,
            full_name=contact.full_name,
            org_name=org.name,
            subject_label=target.label,
            branding=branding,
        )
        if settings.diagnostics_bcc_email:
            await email_service.send_response_notification(
                to=settings.diagnostics_bcc_email,
                org_name=org.name,
                subject_label=target.label,
                respondent_name=None if cycle.is_anonymous else contact.full_name,
                cycle_name=cycle.name,
                answers=answer_rows,
                overall_score=scored.overall_score,
                comment=scored.comment,
                branding=branding,
            )
    except Exception:  # noqa: BLE001 — never let a mail failure look like a broken submission
        log.warning("post_submit_email_failed", cycle_id=str(cycle.id))

    return MessageResponse(
        message="Thank you. Your feedback has been received."
    )


@router.post("/unsubscribe/{token}", response_model=MessageResponse)
async def unsubscribe(
    token: str, request: Request, session: DbSession
) -> MessageResponse:
    """Let a recipient opt out of future requests without contacting anyone.

    An opt-out that requires emailing a human is an opt-out that gets ignored,
    and eventually reported as spam.
    """
    link = await _resolve(session, token, request)
    contact = (
        await session.execute(select(Contact).where(Contact.id == link.contact_id))
    ).scalar_one()
    recipient = (
        await session.execute(
            select(CampaignRecipient).where(CampaignRecipient.id == link.recipient_id)
        )
    ).scalar_one()

    contact.unsubscribed_at = datetime.now(UTC)
    recipient.status = RecipientStatus.UNSUBSCRIBED

    await audit.record(
        session,
        action=AuditAction.CONTACT_UNSUBSCRIBED,
        summary=f"{contact.email} unsubscribed from feedback requests",
        org_id=link.org_id,
        target_type="contact",
        target_id=contact.id,
        target_label=contact.email,
        request=request,
    )
    await session.commit()
    return MessageResponse(
        message="You will not receive further feedback requests from this organization."
    )


class _AssignmentLink:
    __slots__ = ("assignment_id", "org_id", "cycle_id", "target_id", "reviewer_user_id")

    def __init__(self, row: Any) -> None:
        self.assignment_id: uuid.UUID = row["assignment_id"]
        self.org_id: uuid.UUID = row["org_id"]
        self.cycle_id: uuid.UUID = row["cycle_id"]
        self.target_id: uuid.UUID = row["target_id"]
        self.reviewer_user_id: uuid.UUID = row["reviewer_user_id"]


async def _resolve_assignment(
    session: DbSession, token: str, request: Request
) -> _AssignmentLink:
    """Same shape as `_resolve`, for an internal assignment's token instead
    of an external recipient's."""
    await limiter.hit(f"link:ip:{audit.client_ip(request) or 'unknown'}", LINK_PER_IP)

    if not token or len(token) < 20 or len(token) > 128:
        raise NotFound(DEAD_LINK)

    token_hash = hash_token(token)
    await limiter.hit(f"link:tok:{token_hash[:16]}", LINK_PER_TOKEN)

    row = (
        await session.execute(
            text("SELECT * FROM facet_assignment_link(:token_hash)"),
            {"token_hash": token_hash},
        )
    ).mappings().first()

    if row is None:
        raise NotFound(DEAD_LINK)

    status = AssignmentStatus(row["status"])
    if (
        status in {AssignmentStatus.SUBMITTED, AssignmentStatus.DECLINED}
        or CycleStatus(row["cycle_status"]) != CycleStatus.OPEN
    ):
        raise NotFound(DEAD_LINK)

    await bind_tenant(
        session, TenantContext(org_id=row["org_id"], is_super_admin=False)
    )
    return _AssignmentLink(row)


@router.get("/assignment/{token}")
async def open_assignment_link(
    token: str, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    """Render the branded form for a valid internal assignment link."""
    link = await _resolve_assignment(session, token, request)
    _harden(response)

    assignment = (
        await session.execute(
            select(FeedbackAssignment).where(FeedbackAssignment.id == link.assignment_id)
        )
    ).scalar_one()
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == link.cycle_id))
    ).scalar_one()
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == link.target_id)
        )
    ).scalar_one()
    org = (
        await session.execute(
            select(Organization).where(Organization.id == link.org_id)
        )
    ).scalar_one()
    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(
                FeedbackTemplateVersion.id == cycle.template_version_id
            )
        )
    ).scalar_one()

    if assignment.status == AssignmentStatus.PENDING:
        assignment.status = AssignmentStatus.IN_PROGRESS
        assignment.started_at = datetime.now(UTC)
        await session.commit()

    form = validate_definition(version.definition)
    return {
        "organization": {
            "name": org.name,
            "accent_color": org.branding.accent_color if org.branding else "#B4633A",
            "logo_url": (
                f"{settings.public_api_url}/api/v1/public/assignment-logo/{token}"
                if org.branding and org.branding.logo_path
                else None
            ),
        },
        "subject": {"label": target.label, "type": str(target.target_type)},
        "cycle": {"name": cycle.name, "closes_at": cycle.closes_at},
        "relationship": str(assignment.relationship_type),
        "is_anonymous": cycle.is_anonymous and assignment.relationship_type != Relationship.SELF,
        "form": form_payload(form),
    }


@router.post("/assignment/{token}/submit", response_model=MessageResponse)
async def submit_assignment_link(
    token: str,
    payload: SubmitResponseRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> MessageResponse:
    """Accept one submission and burn the token — same "answer, then the
    link stops working" contract as the external path, just for an
    internal reviewer who followed an emailed link instead of logging in.
    """
    await limiter.hit(
        f"submit:ip:{audit.client_ip(request) or 'unknown'}", SUBMIT_PER_IP
    )
    link = await _resolve_assignment(session, token, request)
    _harden(response)

    assignment = (
        await session.execute(
            select(FeedbackAssignment).where(FeedbackAssignment.id == link.assignment_id)
        )
    ).scalar_one()
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == link.cycle_id))
    ).scalar_one()
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == link.target_id)
        )
    ).scalar_one()
    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(
                FeedbackTemplateVersion.id == cycle.template_version_id
            )
        )
    ).scalar_one()

    form = validate_definition(version.definition)
    scored = validate_answers(form, payload.answers, payload.comment)

    # Same self-assessment exception as the authenticated submit path: a
    # self-review is always attributable, so it is never treated as
    # anonymous even on an anonymous cycle.
    anonymous = cycle.is_anonymous and assignment.relationship_type != Relationship.SELF

    session.add(
        FeedbackResponse(
            org_id=cycle.org_id,
            cycle_id=cycle.id,
            target_id=assignment.target_id,
            template_version_id=version.id,
            assignment_id=None if anonymous else assignment.id,
            reviewer_user_id=None if anonymous else link.reviewer_user_id,
            is_anonymous=anonymous,
            relationship_type=assignment.relationship_type,
            answers=scored.answers,
            comment=scored.comment,
            overall_score=scored.overall_score,
            answered_count=scored.answered_count,
            submitted_at=datetime.now(UTC),
        )
    )

    assignment.status = AssignmentStatus.SUBMITTED
    assignment.submitted_at = datetime.now(UTC)
    # Burn the token in the same transaction as the response, same reason
    # as the external path: a failure here can never leave a spent link
    # that still works or a burnt link with no answers behind it.
    assignment.token_hash = hash_token(uuid.uuid4().hex + uuid.uuid4().hex)
    await session.flush()
    await cycle_service.maybe_auto_close(session, cycle)

    await audit.record(
        session,
        action=AuditAction.RESPONSE_SUBMITTED,
        summary=f"A response was submitted in '{cycle.name}'",
        org_id=cycle.org_id,
        target_type="review_cycle",
        target_id=cycle.id,
        target_label=cycle.name,
        context={"anonymous": anonymous, "relationship": str(assignment.relationship_type)},
        request=request,
    )
    # These reads must happen before commit: `bind_tenant` sets the tenant
    # GUC with `SET LOCAL`, which only lives for the current transaction.
    # Reading User/Organization (both RLS-protected) after `commit()` would
    # run in a new, unbound transaction and silently return nothing —
    # same bug the external submit_link path above already had to avoid.
    reviewer = None
    org = None
    if target.target_type in {TargetType.EMPLOYEE, TargetType.MANAGER}:
        reviewer = (
            await session.execute(
                select(User).where(User.id == link.reviewer_user_id)
            )
        ).scalar_one_or_none()
        org = (
            await session.execute(
                select(Organization).where(Organization.id == link.org_id)
            )
        ).scalar_one()

    await session.commit()

    # Best-effort, same contract as submit_link above: the response is
    # already committed, so a mail failure here must never surface as an
    # error to the reviewer -- they already got the "thank you" screen.
    # Only Employee and Manager targets get this email; Team and
    # Department reviews are unchanged.
    if reviewer is not None and org is not None:
        try:
            await email_service.send_thank_you(
                to=reviewer.email,
                full_name=reviewer.full_name,
                org_name=org.name,
                subject_label=target.label,
                branding=email_service.Branding(
                    org_name=org.name,
                    accent_color=org.branding.accent_color if org.branding else "#B4633A",
                    logo_url=(
                        f"{settings.public_api_url}/api/v1/orgs/{org.id}/logo"
                        if org.branding and org.branding.logo_path
                        else None
                    ),
                    footer_note=org.branding.email_footer_note if org.branding else None,
                ),
                target_type=target.target_type,
            )
        except Exception:  # noqa: BLE001 -- never let a mail failure look like a broken submission
            log.warning("post_submit_email_failed", cycle_id=str(cycle.id))

    return MessageResponse(
        message="Thank you. Your feedback has been received."
    )