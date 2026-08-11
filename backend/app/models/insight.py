"""Generated AI insights (Module H).

Everything an LLM produces is stored here rather than recomputed on read, for
three reasons that all bite eventually:

  * **Cost.** Regenerating a summary every time someone opens a results page
    turns a fixed cost into a per-pageview one.
  * **Stability.** A manager who reads a summary, walks into a one-to-one and
    finds it has reworded itself stops trusting the feature.
  * **Auditability.** `model_id` and `prompt_version` are stored alongside the
    output, so when a summary changes there is an answer to "why".

`input_hash` is the cache key: a digest of exactly the material that went into
the prompt. Same inputs, same model, same prompt version means the stored
insight is reused. Change any of the three and a new one is generated, which is
also what makes a prompt change safely rolled out.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import InsightKind, InsightStatus


class AiInsight(UUIDPrimaryKey, Timestamped, Base):
    """One generated artefact about one subject."""

    __tablename__ = "ai_insights"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[InsightKind] = mapped_column(
        pg_enum(InsightKind, "insight_kind"), nullable=False
    )
    status: Mapped[InsightStatus] = mapped_column(
        pg_enum(InsightStatus, "insight_status"),
        nullable=False,
        default=InsightStatus.READY,
    )

    # What it is about. Polymorphic like the rest of the graph, so a summary of
    # a person, a service and a proposal are the same kind of row.
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        index=True,
    )

    # SHA-256 of the exact material that fed the prompt, plus the model and
    # prompt version. Regeneration is skipped when this matches.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="openai")

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # How many responses the insight was built from. Rendering this next to the
    # text is what stops a summary of four comments reading like a mandate.
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        # One current insight per kind per subject per round. Regeneration
        # replaces rather than accumulates, so there is never ambiguity about
        # which summary is the summary.
        UniqueConstraint(
            "kind", "subject_id", "cycle_id", name="uq_insight_subject_kind"
        ),
        Index("ix_insights_org_kind", "org_id", "kind"),
        Index("ix_insights_hash", "input_hash"),
        Index("ix_insights_org_generated", "org_id", "generated_at"),
    )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
