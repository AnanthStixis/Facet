"""Proposals and statements of work (Module C).

This is the table that makes the third domain worth having.

Feedback on a proposal is mildly interesting on its own: a prospect rates the
technical approach 4.2 and the estimate 3.1. It becomes valuable only when it
sits next to what actually happened — whether the work was won, at what value,
and if lost, why. That join is the question no employee-feedback tool and no
customer-experience tool can answer, because neither of them holds both halves:

    Do the proposals that prospects rate highly on estimation accuracy
    actually win, and are the ones we lose on price the ones they told us
    were over-scoped?

The scope here is deliberately narrow. This is not a CRM and must not grow into
one — it records only what is needed to ask for feedback at the right moment
and to correlate that feedback with the outcome.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import LossReason, ProposalStage


class Proposal(UUIDPrimaryKey, Timestamped, Base):
    """One proposal or SOW submitted to a prospect."""

    __tablename__ = "proposals"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human reference, e.g. PRO-2026-014. Unique per tenant so it can be quoted
    # in an email and found again.
    reference: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    stage: Mapped[ProposalStage] = mapped_column(
        pg_enum(ProposalStage, "proposal_stage"),
        nullable=False,
        default=ProposalStage.DRAFT,
    )

    # The prospect-side coordinator who receives the feedback request. The
    # functional spec's worked example — a sales lead at the client — is
    # exactly this person.
    prospect_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    # Who wrote it. Makes "which authors produce the best-rated proposals"
    # answerable, which is the internal half of the same question.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimated_effort_days: Mapped[int | None] = mapped_column(Integer)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_due_on: Mapped[date | None] = mapped_column(Date)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Outcome. `won_amount` is separate from `value_amount` on purpose: the gap
    # between what was proposed and what was signed is itself a signal about
    # estimation quality.
    loss_reason: Mapped[LossReason | None] = mapped_column(
        pg_enum(LossReason, "loss_reason")
    )
    won_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outcome_note: Mapped[str | None] = mapped_column(Text)
    competitor: Mapped[str | None] = mapped_column(String(200))

    # The proposal's identity in the feedback graph. Created when the proposal
    # is submitted, so a draft cannot accidentally be surveyed.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_targets.id", ondelete="SET NULL"),
        index=True,
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("org_id", "reference", name="uq_proposal_reference"),
        Index("ix_proposals_org_stage", "org_id", "stage"),
        Index("ix_proposals_submitted", "org_id", "submitted_at"),
        Index(
            "ix_proposals_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # A loss reason on a proposal that was not lost is a data-entry error
        # that would quietly corrupt every "why do we lose" breakdown.
        CheckConstraint(
            "(loss_reason IS NULL) OR (stage = 'lost')",
            name="loss_reason_only_when_lost",
        ),
        CheckConstraint(
            "(stage NOT IN ('won','lost','withdrawn')) OR (decided_at IS NOT NULL)",
            name="decided_stages_have_a_date",
        ),
    )

    @property
    def is_decided(self) -> bool:
        return self.stage.is_decided

    @property
    def value_variance(self) -> Decimal | None:
        """Signed difference between what was signed and what was proposed."""
        if self.won_amount is None or self.value_amount is None:
            return None
        return self.won_amount - self.value_amount
