"""Category and template library (Module I).

Read-only in Phase 1. Cloning, the form builder, and publishing arrive with
campaigns in the next phase; the versioning model is already in the schema so
that work does not require a migration that rewrites history.
"""

from __future__ import annotations

from typing import Any

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, DbSession, ManagerUser
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.catalog import Category, FeedbackTemplate, FeedbackTemplateVersion
from app.models.enums import AuditAction, TemplateScope, TemplateStatus
from app.schemas.cycle import (
    CategoryCreateRequest,
    CategoryUpdateRequest,
    TemplateCloneRequest,
    TemplateCreateRequest,
    TemplateDraftRequest,
)
from app.services import audit
from app.services.forms import form_payload, normalise_definition, validate_definition

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _question_count(definition: dict[str, Any] | None) -> int:
    if not definition:
        return 0
    total = 0
    for section in definition.get("sections", []) or []:
        total += len(section.get("questions", []) or [])
        total += len(section.get("extra", []) or [])
    return total


@router.get("/categories")
async def list_categories(session: DbSession, actor: ManagerUser) -> list[dict[str, Any]]:
    """Categories visible to the caller, each with its templates.

    Row level security already returns vendor-authored rows (org_id NULL) plus
    the caller's own, so there is no scoping logic here - which is the point of
    putting the rule in the database.
    """
    categories = (
        (
            await session.execute(
                select(Category)
                .where(Category.is_enabled.is_(True))
                .order_by(Category.sort_order, Category.name)
            )
        )
        .scalars()
        .all()
    )

    templates = (
        (
            await session.execute(
                select(FeedbackTemplate).order_by(FeedbackTemplate.name)
            )
        )
        .scalars()
        .all()
    )

    # Latest version per template, preferring a published one over a draft.
    versions = (
        (
            await session.execute(
                select(FeedbackTemplateVersion).order_by(
                    FeedbackTemplateVersion.template_id,
                    FeedbackTemplateVersion.version.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[Any, FeedbackTemplateVersion] = {}
    for version in versions:
        current = latest.get(version.template_id)
        if current is None:
            latest[version.template_id] = version
        elif (
            current.status != TemplateStatus.PUBLISHED
            and version.status == TemplateStatus.PUBLISHED
        ):
            latest[version.template_id] = version

    by_category: dict[Any, list[dict[str, Any]]] = {}
    for template in templates:
        version = latest.get(template.id)
        by_category.setdefault(template.category_id, []).append(
            {
                "id": str(template.id),
                "name": template.name,
                "description": template.description,
                "target_type": str(template.target_type),
                "scope": str(template.scope),
                "is_anonymous": template.is_anonymous,
                "min_responses_to_reveal": template.min_responses_to_reveal,
                "version": version.version if version else None,
                "status": str(version.status) if version else None,
                "question_count": _question_count(version.definition if version else None),
            }
        )

    return [
        {
            "id": str(category.id),
            "key": category.key,
            "name": category.name,
            "description": category.description,
            "icon": category.icon,
            "is_global": category.org_id is None,
            "is_enabled": category.is_enabled,
            "templates": by_category.get(category.id, []),
        }
        for category in categories
    ]


@router.get("/categories/manage")
async def list_categories_for_management(
    session: DbSession, actor: AdminUser
) -> list[dict[str, Any]]:
    """Every category the caller may edit, enabled or not.

    A Client Admin manages only their own org's categories; a Super Admin
    manages the global (org_id NULL) ones. Disabled categories are included
    here — that is the whole point of a management view — unlike
    `/categories`, which only ever shows what a template author can pick from.
    """
    scope_org_id = actor.org_id  # None for a Super Admin -> global rows
    categories = (
        (
            await session.execute(
                select(Category)
                .where(Category.org_id.is_(scope_org_id) if scope_org_id is None else Category.org_id == scope_org_id)
                .order_by(Category.sort_order, Category.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(category.id),
            "key": category.key,
            "name": category.name,
            "description": category.description,
            "icon": category.icon,
            "sort_order": category.sort_order,
            "is_enabled": category.is_enabled,
            "is_global": category.org_id is None,
        }
        for category in categories
    ]


@router.post("/categories", status_code=201)
async def create_category(
    payload: CategoryCreateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Add a category a template can belong to.

    Scoped to the caller: a Super Admin (no org) creates a category every
    tenant sees; a Client Admin creates one visible only inside their own
    organization. There is no way to create a category for someone else's
    org through this endpoint — `org_id` is never taken from the request.
    """
    clash = (
        await session.execute(
            select(func.count())
            .select_from(Category)
            .where(
                Category.key == payload.key,
                Category.org_id.is_(None) if actor.org_id is None else Category.org_id == actor.org_id,
            )
        )
    ).scalar_one()
    if clash:
        raise Conflict("A category with that key already exists.")

    category = Category(
        org_id=actor.org_id,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        sort_order=payload.sort_order,
        is_enabled=True,
    )
    session.add(category)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.CATEGORY_CREATED,
        summary=f"{actor.user.full_name} created category '{category.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="category",
        target_id=category.id,
        target_label=category.name,
        context={},
        request=request,
    )
    await session.commit()
    return {"id": str(category.id), "name": category.name}


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    category = (
        await session.execute(select(Category).where(Category.id == category_id))
    ).scalar_one_or_none()
    if category is None:
        raise NotFound("That category does not exist.")
    # A Client Admin may only touch their own org's categories; a Super
    # Admin may only touch the global ones — neither can reach into the
    # other's scope even though RLS would let the row be read.
    if category.org_id != actor.org_id:
        raise NotFound("That category does not exist.")

    changes: dict[str, list] = {}
    for field in ("name", "description", "icon", "sort_order", "is_enabled"):
        new_value = getattr(payload, field)
        if new_value is None:
            continue
        old_value = getattr(category, field)
        if new_value != old_value:
            changes[field] = [old_value, new_value]
            setattr(category, field, new_value)

    if changes:
        await audit.record(
            session,
            action=AuditAction.CATEGORY_UPDATED,
            summary=f"{actor.user.full_name} updated category '{category.name}'",
            org_id=actor.org_id,
            actor=actor.user,
            target_type="category",
            target_id=category.id,
            target_label=category.name,
            context={"changes": changes},
            request=request,
        )
        await session.commit()

    return {
        "id": str(category.id),
        "name": category.name,
        "description": category.description,
        "icon": category.icon,
        "sort_order": category.sort_order,
        "is_enabled": category.is_enabled,
        "is_global": category.org_id is None,
    }


async def _load_template(session: DbSession, template_id: uuid.UUID) -> FeedbackTemplate:
    template = (
        await session.execute(
            select(FeedbackTemplate).where(FeedbackTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if template is None:
        raise NotFound("That template does not exist.")
    return template


async def _latest_version(
    session: DbSession, template_id: uuid.UUID
) -> FeedbackTemplateVersion | None:
    return (
        await session.execute(
            select(FeedbackTemplateVersion)
            .where(FeedbackTemplateVersion.template_id == template_id)
            .order_by(FeedbackTemplateVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/templates/{template_id}")
async def get_template(
    template_id: uuid.UUID, session: DbSession, actor: ManagerUser
) -> dict[str, Any]:
    """A template with its newest version, rendered as a form payload."""
    template = await _load_template(session, template_id)
    versions = (
        (
            await session.execute(
                select(FeedbackTemplateVersion)
                .where(FeedbackTemplateVersion.template_id == template.id)
                .order_by(FeedbackTemplateVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = versions[0] if versions else None
    return {
        "id": str(template.id),
        "name": template.name,
        "description": template.description,
        "scope": str(template.scope),
        "target_type": str(template.target_type),
        "is_anonymous": template.is_anonymous,
        "min_responses_to_reveal": template.min_responses_to_reveal,
        "editable": template.org_id is not None,
        "versions": [
            {
                "id": str(version.id),
                "version": version.version,
                "status": str(version.status),
                "published_at": version.published_at,
            }
            for version in versions
        ],
        "latest": (
            {
                "id": str(latest.id),
                "version": latest.version,
                "status": str(latest.status),
                "definition": latest.definition,
                "form": form_payload(validate_definition(latest.definition)),
            }
            if latest
            else None
        ),
    }


@router.delete("/templates/{template_id}", status_code=204, response_model=None)
async def delete_template(
    template_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> None:
    """Remove an org-owned template and every draft/published version of it.

    Provided (vendor-authored) templates can never be deleted through this
    endpoint — only a clone, which is org-owned, is. A version already pinned
    by a review cycle blocks the delete at the database level (a foreign key
    with `ON DELETE RESTRICT`), which this turns into a plain, actionable
    error instead of a 500: historical results must stay interpretable
    against the questions that were actually asked, so a template that has
    ever backed a cycle cannot be un-asked after the fact.
    """
    template = await _load_template(session, template_id)
    if template.org_id is None or template.org_id != actor.org_id:
        raise NotFound("That template does not exist.")

    name = template.name
    try:
        await session.delete(template)
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict(
            "This template has been used in a review cycle or campaign and "
            "cannot be deleted. Archive it instead by leaving it as a draft."
        ) from exc

    await audit.record(
        session,
        action=AuditAction.TEMPLATE_DELETED,
        summary=f"{actor.user.full_name} deleted '{name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="feedback_template",
        target_id=template_id,
        target_label=name,
        context={},
        request=request,
    )
    await session.commit()


@router.post("/templates", status_code=201)
async def create_template(
    payload: TemplateCreateRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Start a brand-new template from a blank single-question draft.

    Not a clone: this is for a questionnaire that has no vendor-authored
    starting point. The draft ships with one placeholder question so the
    definition is valid immediately — an empty section would fail
    `validate_definition` the moment the author tried to save it.
    """
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization to create a template.")

    category = (
        await session.execute(select(Category).where(Category.id == payload.category_id))
    ).scalar_one_or_none()
    if category is None:
        raise NotFound("That category does not exist.")

    clash = (
        await session.execute(
            select(func.count())
            .select_from(FeedbackTemplate)
            .where(
                FeedbackTemplate.org_id == actor.org_id, FeedbackTemplate.name == payload.name
            )
        )
    ).scalar_one()
    if clash:
        raise Conflict("A template with that name already exists in your organization.")

    template = FeedbackTemplate(
        org_id=actor.org_id,
        category_id=payload.category_id,
        scope=TemplateScope.ORG,
        name=payload.name,
        description=payload.description,
        target_type=payload.target_type,
        is_anonymous=payload.is_anonymous,
        min_responses_to_reveal=payload.min_responses_to_reveal,
    )
    session.add(template)
    await session.flush()

    session.add(
        FeedbackTemplateVersion(
            org_id=actor.org_id,
            template_id=template.id,
            version=1,
            status=TemplateStatus.DRAFT,
            definition={
                "intro": "",
                "scale": {"min": 1, "max": 5, "labels": {}},
                "sections": [
                    {
                        "key": "section_1",
                        "title": "General",
                        "questions": [
                            {
                                "key": "overall",
                                "text": "Overall, how would you rate this?",
                                "type": "scale",
                                "required": True,
                            }
                        ],
                    }
                ],
                "closing": {
                    "comment_prompt": "Anything else you would like to add?",
                    "comment_required": False,
                },
                "schema_version": 1,
            },
        )
    )

    await audit.record(
        session,
        action=AuditAction.TEMPLATE_DRAFT_SAVED,
        summary=f"{actor.user.full_name} created '{template.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="feedback_template",
        target_id=template.id,
        target_label=template.name,
        context={},
        request=request,
    )
    await session.commit()
    return {"id": str(template.id), "name": template.name}


@router.post("/templates/{template_id}/clone", status_code=201)
async def clone_template(
    template_id: uuid.UUID,
    payload: TemplateCloneRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Copy a template into this organization as an editable draft.

    Vendor-authored templates are read-only for tenants: they are shared by
    every customer, so letting one edit in place would change the library for
    everybody. Cloning is the supported way to customise.
    """
    if actor.org_id is None:
        raise ValidationFailed("A Super Admin must act within an organization to clone.")

    source = await _load_template(session, template_id)
    source_version = (
        await session.execute(
            select(FeedbackTemplateVersion)
            .where(
                FeedbackTemplateVersion.template_id == source.id,
                FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED,
            )
            .order_by(FeedbackTemplateVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or await _latest_version(session, source.id)
    if source_version is None:
        raise Conflict("That template has no content to copy.")

    name = (payload.name or f"{source.name} (copy)").strip()
    clash = (
        await session.execute(
            select(func.count())
            .select_from(FeedbackTemplate)
            .where(
                FeedbackTemplate.org_id == actor.org_id, FeedbackTemplate.name == name
            )
        )
    ).scalar_one()
    if clash:
        raise Conflict("A template with that name already exists in your organization.")

    clone = FeedbackTemplate(
        org_id=actor.org_id,
        category_id=source.category_id,
        scope=TemplateScope.ORG,
        name=name,
        description=source.description,
        target_type=source.target_type,
        cloned_from_id=source.id,
        is_anonymous=source.is_anonymous,
        min_responses_to_reveal=source.min_responses_to_reveal,
    )
    session.add(clone)
    await session.flush()

    session.add(
        FeedbackTemplateVersion(
            org_id=actor.org_id,
            template_id=clone.id,
            version=1,
            status=TemplateStatus.DRAFT,
            definition=source_version.definition,
        )
    )

    await audit.record(
        session,
        action=AuditAction.TEMPLATE_CLONED,
        summary=f"{actor.user.full_name} cloned '{source.name}' as '{name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="feedback_template",
        target_id=clone.id,
        target_label=name,
        context={"source_template": str(source.id)},
        request=request,
    )
    await session.commit()
    return {"id": str(clone.id), "name": clone.name}


@router.put("/templates/{template_id}/draft")
async def save_draft(
    template_id: uuid.UUID,
    payload: TemplateDraftRequest,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Create or update the draft version of an org-owned template."""
    template = await _load_template(session, template_id)
    if template.org_id is None:
        raise Conflict(
            "Provided templates cannot be edited. Clone it first, then edit the copy."
        )

    # Validated before it is stored, so an unusable questionnaire can never
    # reach a respondent halfway through a cycle.
    definition = normalise_definition(payload.definition)

    latest = await _latest_version(session, template.id)
    if latest is not None and latest.status == TemplateStatus.DRAFT:
        draft = latest
        draft.definition = definition
    else:
        # The newest version is published and immutable, so editing starts the
        # next version rather than rewriting history.
        draft = FeedbackTemplateVersion(
            org_id=template.org_id,
            template_id=template.id,
            version=(latest.version + 1) if latest else 1,
            status=TemplateStatus.DRAFT,
            definition=definition,
        )
        session.add(draft)

    if payload.name:
        template.name = payload.name.strip()
    if payload.description is not None:
        template.description = payload.description or None
    if payload.is_anonymous is not None:
        template.is_anonymous = payload.is_anonymous
    if payload.min_responses_to_reveal is not None:
        template.min_responses_to_reveal = payload.min_responses_to_reveal

    await session.flush()
    await audit.record(
        session,
        action=AuditAction.TEMPLATE_DRAFT_SAVED,
        summary=f"{actor.user.full_name} saved a draft of '{template.name}'",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="feedback_template",
        target_id=template.id,
        target_label=template.name,
        context={"version": draft.version},
        request=request,
    )
    await session.commit()
    return {"template_id": str(template.id), "version": draft.version, "status": "draft"}


@router.post("/templates/{template_id}/publish")
async def publish_template(
    template_id: uuid.UUID,
    request: Request,
    session: DbSession,
    actor: AdminUser,
) -> dict[str, Any]:
    """Publish the draft, making it immutable and usable by a cycle."""
    template = await _load_template(session, template_id)
    if template.org_id is None:
        raise Conflict("Provided templates are already published.")

    draft = await _latest_version(session, template.id)
    if draft is None or draft.status != TemplateStatus.DRAFT:
        raise Conflict("There is no draft to publish.")

    validate_definition(draft.definition)

    draft.status = TemplateStatus.PUBLISHED
    draft.published_at = datetime.now(UTC)
    draft.published_by_id = actor.id

    await audit.record(
        session,
        action=AuditAction.TEMPLATE_PUBLISHED,
        summary=(
            f"{actor.user.full_name} published version {draft.version} of "
            f"'{template.name}'"
        ),
        org_id=actor.org_id,
        actor=actor.user,
        target_type="feedback_template",
        target_id=template.id,
        target_label=template.name,
        context={"version": draft.version},
        request=request,
    )
    await session.commit()
    return {
        "template_id": str(template.id),
        "version": draft.version,
        "status": "published",
    }
