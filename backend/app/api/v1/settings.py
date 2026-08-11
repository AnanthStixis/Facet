"""Per-organization settings and branding."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import AdminUser, CurrentUser, DbSession, rebind_tenant
from app.core.config import settings as platform
from app.core.errors import NotFound, ValidationFailed
from app.models.enums import AuditAction
from app.models.organization import Organization
from app.schemas.settings import OrgSettings, SettingsResponse, SettingsUpdateRequest
from app.services import audit, email as email_service

router = APIRouter(prefix="/settings", tags=["settings"])


async def _load_org(session: DbSession, actor) -> Organization:
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization.")
    org = (
        await session.execute(
            select(Organization).where(Organization.id == actor.org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("That organization does not exist.")
    return org


def _floors() -> dict[str, int]:
    return {
        "ai_min_responses_for_summary": platform.ai_min_responses_for_summary,
        "audit_retention_min_days": 30,
    }


@router.get("", response_model=SettingsResponse)
async def read_settings(session: DbSession, actor: CurrentUser) -> SettingsResponse:
    org = await _load_org(session, actor)
    return SettingsResponse(
        settings=OrgSettings.load(org.settings), platform_floors=_floors()
    )


@router.get("/email-preview")
async def preview_email(
    session: DbSession, actor: CurrentUser, kind: str = "feedback_request"
) -> dict[str, str]:
    """Render a sample email with the org's live branding so an admin can see
    exactly what recipients receive — logo, accent colour, footer note — before
    sending anything for real."""
    org = await _load_org(session, actor)
    current = OrgSettings.load(org.settings)
    subject_template = (
        current.email.invitation_subject
        if kind == "invitation"
        else current.email.feedback_request_subject
    )
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
    return email_service.render_preview(
        kind=kind, branding=branding, subject_template=subject_template
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> SettingsResponse:
    """Replace the supplied sections. Anything omitted is left alone."""
    org = await _load_org(session, actor)
    current = OrgSettings.load(org.settings)

    changed: list[str] = []
    for section in ("reminders", "anonymity", "ai", "audit", "email"):
        incoming = getattr(payload, section)
        if incoming is None:
            continue
        setattr(current, section, incoming)
        changed.append(section)

    if not changed:
        raise ValidationFailed("No settings were supplied.")

    org.settings = current.model_dump(mode="json")
    # JSONB reassignment on a mutable dict is not always seen by the unit of
    # work; flagging it explicitly avoids a silent no-op save.
    flag_modified(org, "settings")

    await audit.record(
        session,
        action=AuditAction.ORG_SETTINGS_UPDATED,
        summary=f"{actor.user.full_name} updated {', '.join(changed)} settings",
        org_id=org.id,
        actor=actor.user,
        target_type="organization",
        target_id=org.id,
        target_label=org.name,
        context={"sections": changed, "settings": org.settings},
        request=request,
    )
    await session.commit()
    await rebind_tenant(session, actor)

    return SettingsResponse(
        settings=OrgSettings.load(org.settings), platform_floors=_floors()
    )
