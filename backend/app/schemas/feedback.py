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

    # Only meaningful for kind="product" today: lets a Product review be
    # sent to a chosen set of internal staff instead of external client
    # contacts, reusing the same delivery mechanism as an Employee/
    # Management round (each recipient gets a direct assignment in their
    # "My feedback" queue) rather than emailed one-time links. The other
    # external-typed kinds (client/service/proposal) keep the
    # external-only behaviour they already had — the frontend does not
    # offer this toggle for them yet, and the validator below rejects it
    # rather than silently accepting a shape nothing acts on.
    audience: Literal["external", "internal"] = "external"
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
        if self.audience == "internal":
            if self.kind not in {"product", "service"}:
                raise ValueError(
                    "Internal delivery is only available for Product and "
                    "Service reviews right now."
                )
            if not self.recipient_user_ids:
                raise ValueError("Choose at least one internal recipient.")
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