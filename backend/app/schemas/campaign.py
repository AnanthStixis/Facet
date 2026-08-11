"""Campaign, contact, and target payloads."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import TargetType
from app.schemas.common import ORMModel


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    template_id: uuid.UUID
    # Either reference an existing subject, or just say what this campaign is
    # about and let the server find-or-create it — a text field is a lot less
    # friction than "add a target, then come back and pick it from a list."
    target_id: uuid.UUID | None = None
    target_label: str | None = Field(default=None, min_length=1, max_length=200)
    closes_at: datetime | None = None


class RecipientAddRequest(BaseModel):
    target_id: uuid.UUID
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    batch: str | None = Field(default=None, max_length=80)


class SendRequest(BaseModel):
    # Re-sending regenerates the link, which invalidates the previous one. That
    # is the desired behaviour for a chase-up, but it is worth the caller
    # opting into it explicitly.
    resend: bool = False
    recipient_id: uuid.UUID | None = None


class CampaignDetail(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    audience: str
    is_anonymous: bool
    min_responses_to_reveal: int
    template_name: str | None = None
    template_version: int | None = None
    target_id: uuid.UUID | None = None
    target_label: str | None = None
    target_type: str | None = None
    closes_at: datetime | None
    created_at: datetime
    delivery: dict[str, int] = Field(default_factory=dict)


class RecipientDetail(BaseModel):
    id: uuid.UUID
    contact_name: str
    contact_email: str
    company: str | None
    target_label: str
    status: str
    batch: str | None
    sent_at: datetime | None
    first_opened_at: datetime | None
    submitted_at: datetime | None
    open_count: int
    expires_at: datetime


class AddSummary(BaseModel):
    added: int
    skipped_existing: int
    skipped_unsubscribed: int
    warnings: list[str]


class SendSummary(BaseModel):
    sent: int
    failed: int
    skipped: int
    errors: list[str]


class ContactCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    company: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=150)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ContactDetail(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    company: str | None
    job_title: str | None
    tags: list[str]
    unsubscribed_at: datetime | None
    created_at: datetime


class TargetCreateRequest(BaseModel):
    target_type: TargetType
    label: str = Field(min_length=2, max_length=250)
    reference: str | None = Field(default=None, max_length=120)
    attributes: dict = Field(default_factory=dict)


class TargetDetail(ORMModel):
    id: uuid.UUID
    target_type: str
    label: str
    reference: str | None
    is_active: bool
    created_at: datetime
