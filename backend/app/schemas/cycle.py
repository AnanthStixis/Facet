"""Cycle, assignment, and response payloads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import TargetType
from app.schemas.common import ORMModel


class CycleCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    template_id: uuid.UUID
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class AssignmentPlanRequest(BaseModel):
    reviewee_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    include_self: bool = True
    include_manager: bool = True
    include_upward: bool = True
    include_peers: bool = True
    max_peers: int = Field(default=6, ge=1, le=20)


class GenerationSummary(BaseModel):
    created: int
    skipped_existing: int
    by_relationship: dict[str, int]
    warnings: list[str]


class CycleDetail(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    is_anonymous: bool
    min_responses_to_reveal: int
    template_version_id: uuid.UUID
    template_name: str | None = None
    template_version: int | None = None
    opens_at: datetime | None
    closes_at: datetime | None
    opened_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by_name: str | None = None
    progress: dict[str, int] = Field(default_factory=dict)


class AssignmentSummary(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    cycle_name: str
    target_id: uuid.UUID
    target_label: str
    target_type: str
    relationship: str
    status: str
    is_anonymous: bool
    due_at: datetime | None
    submitted_at: datetime | None


class AssignmentForm(BaseModel):
    assignment: AssignmentSummary
    form: dict[str, Any]


class SubmitResponseRequest(BaseModel):
    answers: dict[str, Any]
    # This is a technical ceiling, not the business rule: the real 5,000
    # character limit is enforced (and reported per-field) in
    # app.services.forms.validate_answers. Keeping this well above that
    # means Pydantic only ever rejects a genuinely oversized payload, and
    # never fires first with its own generic message ahead of the proper,
    # field-specific one.
    comment: str | None = Field(default=None, max_length=20000)


class DeclineRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CategoryCreateRequest(BaseModel):
    key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int = Field(default=100, ge=0, le=10_000)
    applies_to: list[TargetType] = Field(default_factory=list)


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    is_enabled: bool | None = None
    applies_to: list[TargetType] | None = None


class TemplateCloneRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    target_type: TargetType
    description: str | None = Field(default=None, max_length=2000)
    is_anonymous: bool = False
    # Optional on purpose: omitting it falls back to _default_category() so
    # existing callers (and the create flow before this field existed) keep
    # working unchanged. When given, it must be a category the caller can
    # actually see — checked in create_template, not here, since that check
    # needs a DB lookup.
    category_id: uuid.UUID | None = None
    # min_responses_to_reveal is no longer accepted from the client: results
    # already reveal at a single response (see results.py's threshold=0
    # comment), so the field is vestigial. The column stays on the model for
    # now (no migration dropping it) but every template is created at 0.


class TemplateDraftRequest(BaseModel):
    definition: dict[str, Any]
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_anonymous: bool | None = None