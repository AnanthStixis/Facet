"""Payloads for the unified Create Feedback / Results flow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import validate_closes_at_in_future

FeedbackKind = Literal["client", "employee", "management", "product", "service", "proposal"]


class FeedbackCreateRequest(BaseModel):
    kind: FeedbackKind
    template_id: uuid.UUID
    name: str = Field(min_length=3, max_length=200)
    closes_at: datetime | None = None

    _check_closes_at = field_validator("closes_at")(validate_closes_at_in_future)

    # employee only, optional — the checked managers on the Employee Review
    # form. Left unset, every manager on record for the reviewee is included,
    # the same as before an employee could have more than one.
    manager_ids: list[uuid.UUID] | None = None

    # employee / management
    reviewee_user_id: uuid.UUID | None = None

    # client only, optional
    about_user_id: uuid.UUID | None = None

    # client (no about_user_id) / product / service / proposal
    target_label: str | None = Field(default=None, max_length=200)

    # client / product / service / proposal
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)

    # product / service only — 'external' (client contacts, via contact_ids)
    # or 'internal' (org staff, via recipient_user_ids). Every other kind is
    # always 'external', and the frontend sends 'external' for those too, so
    # this can just default to it rather than needing kind-conditional logic
    # here.
    audience: Literal["external", "internal"] = "external"

    # product / service, only meaningful when audience == "internal" — the
    # internal staff this review goes to, instead of contact_ids. Same
    # shape and same lack of a non-empty requirement as contact_ids: the
    # frontend's own submit button is what actually enforces "pick at least
    # one," not this schema.
    recipient_user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def _check_shape(self) -> "FeedbackCreateRequest":
        if self.kind in {"employee", "management"} and self.reviewee_user_id is None:
            raise ValueError("Choose who this feedback is about.")
        if self.kind in {"product", "service", "proposal"} and not (
            self.target_label and self.target_label.strip()
        ):
            raise ValueError("Say what this feedback is about.")
        if self.kind == "client" and self.about_user_id is None and not (
            self.target_label and self.target_label.strip()
        ):
            raise ValueError(
                "Say what this Client Review is about, or choose who it's about."
            )
        return self


class FeedbackCreateResult(BaseModel):
    cycle_id: uuid.UUID
    status: str
    warnings: list[str] = Field(default_factory=list)


class FeedbackListItem(BaseModel):
    id: uuid.UUID
    kind: str
    audience: str
    target_id: uuid.UUID | None = None
    target_label: str | None = None
    target_type: str | None = None
    template_name: str | None = None
    name: str
    status: str
    is_anonymous: bool
    sent_at: datetime | None = None
    created_at: datetime
    closes_at: datetime | None = None
    total: int = 0
    responded: int = 0
    org_id: uuid.UUID | None = None
    org_name: str | None = None
    # The reviewing contact's own company — distinct from org_name, which is
    # the tenant and identical on every row. Only external rounds have a
    # contact behind them at all; internal ones leave this unset.
    client_name: str | None = None
    # Who the request actually went to — the external contacts for a
    # campaign, or the internal reviewers for a cycle. Distinct from
    # target_label, which is who/what the feedback is *about*, not who it
    # was sent to.
    recipients: list[str] = []


class FeedbackResponseAnswer(BaseModel):
    key: str
    text: str
    type: str
    value: Any = None


class FeedbackResponseItem(BaseModel):
    """One submitted response, for the Results detail popup.

    `respondent_name`/`respondent_email` are None whenever the response
    itself is anonymous — `FeedbackResponse.is_anonymous` is the single
    source of truth for that (enforced by a DB check constraint alongside
    it), so there's no separate secrecy decision made here.
    """

    id: uuid.UUID
    respondent_name: str | None = None
    respondent_email: str | None = None
    relationship: str
    is_anonymous: bool
    submitted_at: datetime
    overall_score: float | None = None
    comment: str | None = None
    answers: list[FeedbackResponseAnswer] = Field(default_factory=list)


class UserFeedbackItem(BaseModel):
    cycle_id: uuid.UUID
    cycle_name: str
    kind: str
    template_name: str | None = None
    relationship: str
    submitted_at: datetime
    overall_score: float | None = None
    comment: str | None = None