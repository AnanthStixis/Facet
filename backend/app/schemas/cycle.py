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


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    is_enabled: bool | None = None


class TemplateCloneRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    category_id: uuid.UUID
    target_type: TargetType
    description: str | None = Field(default=None, max_length=2000)
    is_anonymous: bool = False
    # 0 is a deliberate choice, not an oversight: it disables suppression
    # entirely, and an org that wants that (small team, non-anonymous intent)
    # is asking for it explicitly rather than tripping over a hidden floor.
    min_responses_to_reveal: int = Field(default=4, ge=0, le=50)


class TemplateDraftRequest(BaseModel):
    definition: dict[str, Any]
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_anonymous: bool | None = None
    min_responses_to_reveal: int | None = Field(default=None, ge=0, le=50)