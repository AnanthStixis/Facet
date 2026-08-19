"""Review cycles, assignments, and responses (Module A).

The anonymity design is the important thing in this module, so it is recorded
here rather than in a ticket.

A template can be anonymous. "Anonymous" in most feedback products means the
reviewer's name is hidden in the UI while the database still holds a
`reviewer_id` column on the response row. That is not anonymity; it is a
promise that survives exactly as long as nobody runs a query.

Here, an anonymous response stores **no path back to the reviewer at all**:

  * `reviewer_user_id` is NULL
  * `assignment_id` is NULL, so it cannot be joined back to the assignment
    that names the reviewer
  * the assignment is marked submitted in the same transaction, so completion
    tracking and reminders still work

The result is that "has Vikram responded?" is answerable and "what did Vikram
say?" is not — not by an admin, not by a Super Admin, not by someone with psql
and the production password. That is the only version of the promise worth
making to the person being asked to be honest about their manager.

Attributable templates behave normally: both columns are populated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import (
    AssignmentStatus,
    CycleAudience,
    CycleStatus,
    Relationship,
)


class ReviewCycle(UUIDPrimaryKey, Timestamped, Base):
    """One round of feedback collection.

    Pins a specific `FeedbackTemplateVersion`, never a template. Publishing a
    new version of the template next quarter therefore cannot change what this
    cycle asked, which is what keeps trend reporting meaningful.
    """

    __tablename__ = "review_cycles"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    template_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[CycleStatus] = mapped_column(
        pg_enum(CycleStatus, "cycle_status"), nullable=False, default=CycleStatus.DRAFT
    )

    # Internal rounds reach people through assignments; external rounds reach
    # them through campaign_recipients and an emailed one-time link. Everything
    # downstream of the response is identical, which is the whole point.
    audience: Mapped[CycleAudience] = mapped_column(
        pg_enum(CycleAudience, "cycle_audience"),
        nullable=False,
        default=CycleAudience.INTERNAL,
    )

    # Snapshotted from the template when the cycle is created. If someone
    # relaxes the template later, an already-collected anonymous cycle must not
    # retroactively become attributable.
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_responses_to_reveal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4
    )

    # External campaigns only. Set once, at creation — recipients each carry
    # their own target_id too, but this is what lets the campaign be queried
    # (and its subject shown) before it has a single recipient yet.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feedback_targets.id", ondelete="SET NULL"), index=True
    )

    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set the first time non-responders are escalated to this round's owner, so
    # the escalation happens once rather than every night the job runs.
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    assignments: Mapped[list["FeedbackAssignment"]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_review_cycles_org_status", "org_id", "status"),
        Index(
            "ix_review_cycles_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    @property
    def accepts_submissions(self) -> bool:
        return self.status == CycleStatus.OPEN


class FeedbackAssignment(UUIDPrimaryKey, Timestamped, Base):
    """One reviewer asked to give feedback about one target in one cycle."""

    __tablename__ = "feedback_assignments"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL is reserved for external respondents in Phase 3, who are contacts
    # rather than users and reach the form through a one-time link.
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    relationship_type: Mapped[Relationship] = mapped_column(
        pg_enum(Relationship, "relationship_type"), nullable=False
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        pg_enum(AssignmentStatus, "assignment_status"),
        nullable=False,
        default=AssignmentStatus.PENDING,
    )

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_reason: Mapped[str | None] = mapped_column(Text)
    reminders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(String(64))

    cycle: Mapped[ReviewCycle] = relationship(back_populates="assignments")

    __table_args__ = (
    UniqueConstraint(
        "cycle_id", "target_id", "reviewer_user_id", name="uq_assignment_unique"
    ),
    UniqueConstraint("token_hash", name="uq_feedback_assignments_token_hash"),
    Index("ix_assignments_reviewer_status", "reviewer_user_id", "status"),
    Index("ix_assignments_cycle_status", "cycle_id", "status"),
    Index("ix_feedback_assignments_token", "token_hash"),
)


class FeedbackResponse(UUIDPrimaryKey, Timestamped, Base):
    """A submitted set of answers.

    See the module docstring for why `assignment_id` and `reviewer_user_id` are
    both nullable and are both NULL for anonymous cycles.
    """

    __tablename__ = "feedback_responses"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Both NULL when the cycle is anonymous. This is the anonymity guarantee,
    # and the check constraint below is what enforces it in the database rather
    # than trusting every future code path to remember.
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_assignments.id", ondelete="SET NULL"),
        unique=True,
    )
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # The external equivalent of assignment_id. Also NULL when anonymous, and
    # covered by the same check constraint, so an anonymous external response
    # is no more traceable than an anonymous internal one.
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campaign_recipients.id", ondelete="SET NULL"),
        unique=True,
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    relationship_type: Mapped[Relationship] = mapped_column(
        pg_enum(Relationship, "relationship_type", create_type=False), nullable=False
    )

    # {question_key: value}. Kept alongside the pinned template version, so a
    # response is always interpretable against the questions actually asked.
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)

    # Mean of the numeric answers, computed once on submit. Recomputing this on
    # every dashboard read is the kind of thing that is fine at 50 responses
    # and painful at 50,000.
    overall_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # --- Analysis (Module H) ---------------------------------------------
    # Stored on the response rather than in ai_insights because sentiment is
    # per-comment and high volume, and every aggregate wants to filter and
    # average it in SQL rather than unpack JSON.
    #
    # These columns are written after submission, which the immutability
    # trigger permits: it guards the answers, the comment and the reviewer
    # link, not derived analysis.
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    sentiment_label: Mapped[str | None] = mapped_column(String(20))
    sentiment_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    sentiment_aspects: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    sentiment_model: Mapped[str | None] = mapped_column(String(80))
    sentiment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(is_anonymous AND assignment_id IS NULL AND reviewer_user_id IS NULL "
            " AND recipient_id IS NULL) OR (NOT is_anonymous)",
            name="anonymous_has_no_reviewer_link",
        ),
        Index("ix_responses_target_cycle", "target_id", "cycle_id"),
        Index("ix_responses_cycle_relationship", "cycle_id", "relationship_type"),
        Index("ix_responses_answers", "answers", postgresql_using="gin"),
    )
