"""Email templates: per-kind copy for the feedback-request invite email.

A Super Admin edits the six platform defaults (one per review kind, via the
`/{kind}` routes). An org admin instead keeps a *library* of its own
templates per kind (the `/item/{id}` and `/library` routes) — any number of
drafts, at most one of them active at a time. A send uses that org's active
row for the kind, or the platform default if it has none active. See
app/models/email_template.py for the storage model and
app/services/email_templates.py for how a send resolves which row to use.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.core.config import settings as platform
from app.core.errors import NotFound, ValidationFailed
from app.models.email_template import EmailTemplate
from app.models.enums import AuditAction, EmailTemplateKind, TemplateScope
from app.models.organization import Organization
from app.schemas.email_template import (
    EmailTemplateContent,
    EmailTemplateCreateRequest,
    EmailTemplateLibrary,
    EmailTemplateOut,
    EmailTemplatePreviewRequest,
)
from app.services import audit
from app.services import email as email_service

router = APIRouter(prefix="/email-templates", tags=["email-templates"])


def _require_platform(actor) -> None:
    if actor.org_id is not None:
        raise ValidationFailed("Only a Super Admin can edit the platform default.")


def _require_org(actor) -> uuid.UUID:
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin has no template library of its own.")
    return actor.org_id


async def _load_global(session: DbSession, kind: EmailTemplateKind) -> EmailTemplate:
    row = (
        await session.execute(
            select(EmailTemplate).where(EmailTemplate.org_id.is_(None), EmailTemplate.kind == kind)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("That review kind has no platform default yet.")
    return row


async def _load_own(session: DbSession, actor, template_id: uuid.UUID) -> EmailTemplate:
    org_id = _require_org(actor)
    row = (
        await session.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    ).scalar_one_or_none()
    if row is None or row.org_id != org_id:
        raise NotFound("That email template does not exist.")
    return row


@router.get("", response_model=list[EmailTemplateOut])
async def list_global_templates(session: DbSession, actor: AdminUser):
    """Super Admin only: the six platform defaults, one per kind."""
    _require_platform(actor)
    rows = (
        await session.execute(select(EmailTemplate).where(EmailTemplate.org_id.is_(None)))
    ).scalars().all()
    by_kind = {row.kind: row for row in rows}
    return [EmailTemplateOut.model_validate(by_kind[kind]) for kind in EmailTemplateKind if kind in by_kind]


@router.put("/{kind}", response_model=EmailTemplateOut)
async def update_global_template(
    kind: EmailTemplateKind,
    payload: EmailTemplateContent,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> EmailTemplateOut:
    """Super Admin only: edit the platform default for `kind`."""
    _require_platform(actor)
    row = await _load_global(session, kind)
    row.name = payload.name
    row.subject_template = payload.subject_template
    row.heading = payload.heading
    row.body_text = payload.body_text
    row.signature = payload.signature
    await session.flush()
    await session.refresh(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_UPDATED,
        summary=f"{actor.user.full_name} updated the platform default {kind.value} email template",
        org_id=None,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=kind.value,
        context={},
        request=request,
    )
    result = EmailTemplateOut.model_validate(row)
    await session.commit()
    return result


@router.get("/library", response_model=EmailTemplateLibrary)
async def get_library(
    session: DbSession, actor: AdminUser, kind: EmailTemplateKind = Query(...)
) -> EmailTemplateLibrary:
    """Org admin only: the platform default plus every template — active or
    not — this org has authored for `kind`."""
    org_id = _require_org(actor)
    global_row = await _load_global(session, kind)
    own_rows = (
        await session.execute(
            select(EmailTemplate)
            .where(EmailTemplate.org_id == org_id, EmailTemplate.kind == kind)
            .order_by(EmailTemplate.created_at)
        )
    ).scalars().all()
    return EmailTemplateLibrary(
        kind=kind,
        global_template=EmailTemplateOut.model_validate(global_row),
        org_templates=[EmailTemplateOut.model_validate(row) for row in own_rows],
    )


@router.post("", status_code=201, response_model=EmailTemplateOut)
async def create_org_template(
    payload: EmailTemplateCreateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> EmailTemplateOut:
    """Org admin only: add a new template for `payload.kind`. Starts
    inactive — a send keeps using whatever is already active (or the
    platform default) until this one is explicitly activated."""
    org_id = _require_org(actor)
    row = EmailTemplate(
        org_id=org_id,
        kind=payload.kind,
        scope=TemplateScope.ORG,
        name=payload.name,
        subject_template=payload.subject_template,
        heading=payload.heading,
        body_text=payload.body_text,
        signature=payload.signature, 
        is_active=False,
        created_by_id=actor.id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_UPDATED,
        summary=f"{actor.user.full_name} added a new {payload.kind.value} email template ('{payload.name}')",
        org_id=org_id,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=payload.name,
        context={},
        request=request,
    )
    result = EmailTemplateOut.model_validate(row)
    await session.commit()
    return result


@router.put("/item/{template_id}", response_model=EmailTemplateOut)
async def update_org_template(
    template_id: uuid.UUID,
    payload: EmailTemplateContent,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> EmailTemplateOut:
    """Org admin only: edit the name/content of one of the caller's own
    templates. Does not touch `is_active` — use activate/deactivate."""
    row = await _load_own(session, actor, template_id)
    row.name = payload.name
    row.subject_template = payload.subject_template
    row.heading = payload.heading
    row.body_text = payload.body_text
    row.signature = payload.signature
    await session.flush()
    await session.refresh(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_UPDATED,
        summary=f"{actor.user.full_name} updated the '{row.name}' {row.kind.value} email template",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=row.name,
        context={},
        request=request,
    )
    result = EmailTemplateOut.model_validate(row)
    await session.commit()
    return result


@router.post("/item/{template_id}/activate", response_model=EmailTemplateOut)
async def activate_org_template(
    template_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> EmailTemplateOut:
    """Org admin only: make this the one active template for its kind.

    Deactivates every other template this org has for the same kind first —
    there is never more than one active row per (org, kind); the DB's
    partial unique index is what actually guarantees that, this is just the
    ordering that keeps it from ever tripping.
    """
    row = await _load_own(session, actor, template_id)
    await session.execute(
        EmailTemplate.__table__.update()
        .where(
            EmailTemplate.org_id == actor.org_id,
            EmailTemplate.kind == row.kind,
            EmailTemplate.id != row.id,
        )
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    row.is_active = True
    await session.flush()
    await session.refresh(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_UPDATED,
        summary=f"{actor.user.full_name} activated the '{row.name}' {row.kind.value} email template",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=row.name,
        context={},
        request=request,
    )
    result = EmailTemplateOut.model_validate(row)
    await session.commit()
    return result


@router.post("/item/{template_id}/deactivate", response_model=EmailTemplateOut)
async def deactivate_org_template(
    template_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> EmailTemplateOut:
    """Org admin only: turn this template off. Sends for its kind fall back
    to the platform default until something is activated again."""
    row = await _load_own(session, actor, template_id)
    row.is_active = False
    await session.flush()
    await session.refresh(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_RESET,
        summary=f"{actor.user.full_name} deactivated the '{row.name}' {row.kind.value} email template",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=row.name,
        context={},
        request=request,
    )
    result = EmailTemplateOut.model_validate(row)
    await session.commit()
    return result


@router.delete("/item/{template_id}", status_code=204, response_model=None)
async def delete_org_template(
    template_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> None:
    """Org admin only: remove one of the caller's own drafts. Deleting the
    active one is allowed — the kind simply falls back to the platform
    default, same as an explicit deactivate."""
    row = await _load_own(session, actor, template_id)
    await session.delete(row)

    await audit.record(
        session,
        action=AuditAction.EMAIL_TEMPLATE_RESET,
        summary=f"{actor.user.full_name} deleted the '{row.name}' {row.kind.value} email template",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="email_template",
        target_id=row.id,
        target_label=row.name,
        context={},
        request=request,
    )
    await session.commit()


@router.post("/{kind}/preview")
async def preview_email_template(
    kind: EmailTemplateKind,
    payload: EmailTemplatePreviewRequest,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, str]:
    """Render `payload` (saved or not) with sample names, using the caller's
    own branding when they have an org, or the platform look otherwise."""
    if actor.org_id is not None:
        org = (
            await session.execute(select(Organization).where(Organization.id == actor.org_id))
        ).scalar_one_or_none()
        if org is None:
            raise NotFound("That organization does not exist.")
        branding = email_service.Branding(
            org_name=org.name,
            accent_color=org.branding.accent_color if org.branding else "#B4633A",
            logo_url=(
                f"{platform.public_api_url}/api/v1/orgs/{org.id}/logo"
                if org.branding and org.branding.logo_path
                else None
            ),
            footer_note=org.branding.email_footer_note if org.branding else None,
        )
    else:
        branding = email_service.Branding(org_name=platform.product_name)

    return email_service.render_email_template_preview(
        branding=branding,
        subject_template=payload.subject_template,
        heading=payload.heading,
        body_text=payload.body_text,
        signature=payload.signature,
    )