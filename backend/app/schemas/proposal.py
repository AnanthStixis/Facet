"""Proposal payloads."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import LossReason, ProposalStage


class ProposalCreateRequest(BaseModel):
    reference: str | None = Field(default=None, max_length=60)
    title: str = Field(min_length=3, max_length=250)
    client_name: str = Field(min_length=2, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    prospect_contact_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    value_amount: Decimal | None = Field(default=None, ge=0, le=10**11)
    estimated_effort_days: int | None = Field(default=None, ge=0, le=100_000)
    decision_due_on: date | None = None


class ProposalUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=250)
    client_name: str | None = Field(default=None, min_length=2, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    prospect_contact_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    value_amount: Decimal | None = Field(default=None, ge=0, le=10**11)
    estimated_effort_days: int | None = Field(default=None, ge=0, le=100_000)
    decision_due_on: date | None = None


class ProposalOutcomeRequest(BaseModel):
    stage: ProposalStage
    loss_reason: LossReason | None = None
    won_amount: Decimal | None = Field(default=None, ge=0, le=10**11)
    competitor: str | None = Field(default=None, max_length=200)
    outcome_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _coherent(self) -> "ProposalOutcomeRequest":
        if self.stage not in {
            ProposalStage.WON,
            ProposalStage.LOST,
            ProposalStage.WITHDRAWN,
        }:
            raise ValueError("Only won, lost or withdrawn can be recorded as an outcome.")
        # A loss reason on a win, or a won amount on a loss, corrupts every
        # breakdown built on those fields later.
        if self.stage == ProposalStage.LOST and self.loss_reason is None:
            raise ValueError("Record why the proposal was lost.")
        if self.stage != ProposalStage.LOST and self.loss_reason is not None:
            raise ValueError("A loss reason only applies to a lost proposal.")
        if self.stage != ProposalStage.WON and self.won_amount is not None:
            raise ValueError("A signed value only applies to a won proposal.")
        return self


class FeedbackRequestRequest(BaseModel):
    template_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    closes_in_days: int = Field(default=21, ge=1, le=180)


class ProposalDetail(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    client_name: str
    summary: str | None
    stage: str
    currency: str
    value_amount: Decimal | None
    won_amount: Decimal | None
    value_variance: Decimal | None = None
    estimated_effort_days: int | None
    prospect_contact_id: uuid.UUID | None
    prospect_contact_name: str | None = None
    author_id: uuid.UUID | None
    author_name: str | None = None
    submitted_at: datetime | None
    decision_due_on: date | None
    decided_at: datetime | None
    loss_reason: str | None
    competitor: str | None
    outcome_note: str | None
    target_id: uuid.UUID | None
    created_at: datetime

    # Feedback state, joined in so the pipeline view can show at a glance
    # which proposals have been asked about and which have answers.
    feedback_requested: bool = False
    feedback_responses: int = 0
    feedback_average: float | None = None
    feedback_cycle_id: uuid.UUID | None = None


class PipelineSummary(BaseModel):
    total: int
    open_value: Decimal
    won_value: Decimal
    by_stage: dict[str, int]
    win_rate_pct: int
    feedback_coverage_pct: int
