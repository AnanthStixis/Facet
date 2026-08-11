"""Fitted predictive models and their provenance (Module H.2).

A model row is a record of one training run, and it exists mainly so the
product can be honest about what it does and does not know.

The most important column is `status`. A run that did not have enough data to
be meaningful is stored as `insufficient_data` with a human-readable `reason`,
*not* silently discarded and not fitted anyway. That distinction is the whole
design:

    A win-probability model trained on eight proposals that confidently
    reports 73% is worse than no model. It launders noise into a number a
    salesperson will repeat in a meeting. Refusing, and saying why, is the
    only defensible behaviour until the data exists.

Coefficients are stored rather than a pickled estimator. Scoring a logistic
regression is a dot product, so keeping the maths in the database avoids a
binary artefact that has to be versioned against the library that produced it —
and makes the model inspectable, which matters when someone asks why a
particular proposal was rated the way it was.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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
from app.models.enums import ModelKind, ModelStatus


class AnalyticsModel(UUIDPrimaryKey, Timestamped, Base):
    """One fitted (or refused) model for one organization."""

    __tablename__ = "analytics_models"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ModelKind] = mapped_column(
        pg_enum(ModelKind, "model_kind"), nullable=False
    )
    status: Mapped[ModelStatus] = mapped_column(
        pg_enum(ModelStatus, "model_status"),
        nullable=False,
        default=ModelStatus.INSUFFICIENT_DATA,
    )

    algorithm: Mapped[str] = mapped_column(String(60), nullable=False, default="none")
    # Why the model refused, in words a user can act on. Populated whenever
    # status is not `fitted`.
    reason: Mapped[str | None] = mapped_column(Text)

    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_positive: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_features: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    feature_names: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    coefficients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Cross-validated, never in-sample. In-sample accuracy on a small dataset
    # is a measure of memorisation, and quoting it would misrepresent the model
    # exactly where the misrepresentation matters most.
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # A blunt honesty flag surfaced straight into the UI. Even a model that
    # clears the minimum sample count can be weak, and the reader is entitled
    # to know that before acting on it.
    baseline_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        # One current model per kind per tenant. Retraining replaces, so there
        # is never ambiguity about which model produced a number on screen.
        UniqueConstraint("org_id", "kind", name="uq_analytics_model_kind"),
        Index("ix_analytics_models_org_kind", "org_id", "kind"),
    )

    @property
    def is_usable(self) -> bool:
        return self.status == ModelStatus.FITTED
