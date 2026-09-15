"""Email template payloads."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EmailTemplateKind, TemplateScope


class EmailTemplateOut(BaseModel):
    id: uuid.UUID
    kind: EmailTemplateKind
    scope: TemplateScope
    name: str
    subject_template: str
    heading: str
    body_text: str
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class EmailTemplateContent(BaseModel):
    """The editable fields shared by create and update — everything except
    identity (kind), which a create sets once and an update never changes."""

    name: str = Field(min_length=1, max_length=150)
    subject_template: str = Field(min_length=1, max_length=200)
    heading: str = Field(default="", max_length=200)
    body_text: str = Field(min_length=1, max_length=4000)


class EmailTemplateCreateRequest(EmailTemplateContent):
    kind: EmailTemplateKind


class EmailTemplatePreviewRequest(BaseModel):
    subject_template: str = Field(default="", max_length=200)
    heading: str = Field(default="", max_length=200)
    body_text: str = Field(default="", max_length=4000)


class EmailTemplateLibrary(BaseModel):
    """Everything the org-admin editor for one kind needs in a single call:
    the platform default (read-only for them) and every template — active or
    not — their own org has authored for that kind."""

    kind: EmailTemplateKind
    global_template: EmailTemplateOut
    org_templates: list[EmailTemplateOut]
