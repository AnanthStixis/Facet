"""Categories, feedback templates, and the feedback target graph.

This module is where the product's differentiation actually lives.

Every competitor examined during design (Culture Amp, Lattice, 15Five on the
employee side; Qualtrics and Sprinklr on the customer side) models employee
review and customer survey as separate subsystems with separate data stores.
Facet models them as one graph: a `FeedbackTarget` can be a person, a team, a
product, a service, or a proposal, and a template can be pointed at any of them.

That single decision is what makes the cross-domain question answerable -
"do the teams that score well on internal collaboration also produce the
proposals prospects rate highest?" - and no separated-subsystem product can
answer it without an export and a spreadsheet.
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import TargetType, TemplateScope, TemplateStatus


class Category(UUIDPrimaryKey, Timestamped, Base):
    """A family of feedback, e.g. "Annual 360", "Post-delivery CSAT".

    Vendor-authored categories have org_id NULL and are visible to every
    tenant; a tenant may also define its own. The RLS policy allows a row when
    org_id matches the caller's tenant OR org_id is NULL, which is why this
    table gets a bespoke policy rather than the standard one.
    """

    __tablename__ = "categories"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )

    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    icon: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Nullable: existing rows predate this column and have no known author.
    # SET NULL on delete rather than RESTRICT — a category must never become
    # undeletable just because the user who made it was later removed.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("uq_categories_global_key", "key", unique=True,
              postgresql_where="org_id IS NULL"),
        Index("uq_categories_org_key", "org_id", "key", unique=True,
              postgresql_where="org_id IS NOT NULL"),
    )


class FeedbackTemplate(UUIDPrimaryKey, Timestamped, Base):
    """A reusable questionnaire definition.

    Templates are versioned and immutable once published. A campaign pins a
    specific `FeedbackTemplateVersion`, never the template itself, so editing a
    template next quarter cannot retroactively change what a respondent was
    asked last quarter. Getting this wrong silently corrupts trend reporting,
    and it is close to impossible to repair after the fact.
    """

    __tablename__ = "feedback_templates"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    scope: Mapped[TemplateScope] = mapped_column(
        pg_enum(TemplateScope, "template_scope"),
        nullable=False,
        default=TemplateScope.ORG,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[TargetType] = mapped_column(
        pg_enum(TargetType, "target_type"), nullable=False
    )

    # Set when a tenant clones a vendor template, so we can tell how the
    # library is actually used and which defaults are worth improving.
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feedback_templates.id", ondelete="SET NULL")
    )

    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Below this many responses, individual results and AI summaries are
    # withheld. Anonymity that leaks under aggregation is not anonymity.
    min_responses_to_reveal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4
    )

    # Independent of draft/published status: an admin can take a template out
    # of circulation (it stops appearing in CreateFeedback.tsx's dropdown)
    # without touching its version history. Additive column, defaults true so
    # every existing template stays selectable after this migration.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Nullable for the same reason as Category.created_by_id above: existing
    # rows predate this column.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    versions: Mapped[list["FeedbackTemplateVersion"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="FeedbackTemplateVersion.version.desc()",
    )

    __table_args__ = (
        Index("ix_feedback_templates_org_category", "org_id", "category_id"),
        Index(
            "ix_feedback_templates_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        CheckConstraint(
            "(scope = 'global' AND org_id IS NULL) "
            "OR (scope = 'org' AND org_id IS NOT NULL)",
            name="template_scope_matches_org",
        ),
    )


class FeedbackTemplateVersion(UUIDPrimaryKey, Timestamped, Base):
    """An immutable published snapshot of a template's questions."""

    __tablename__ = "feedback_template_versions"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[TemplateStatus] = mapped_column(
        pg_enum(TemplateStatus, "template_status"),
        nullable=False,
        default=TemplateStatus.DRAFT,
    )

    # The questionnaire itself: sections, questions, scale definitions, and
    # conditional logic. JSONB rather than an EAV question table because every
    # read is "give me the whole form", and because EAV makes the reporting
    # queries that this product is sold on genuinely painful to write.
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    template: Mapped[FeedbackTemplate] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_template_version"),
        Index("ix_template_versions_status", "template_id", "status"),
    )


class FeedbackTarget(UUIDPrimaryKey, Timestamped, Base):
    """Anything feedback can be about.

    One row per reviewable entity, regardless of what kind of entity it is.
    `subject_user_id` is populated for people; `attributes` carries the
    type-specific detail (proposal value and author for a proposal, SKU for a
    product) without forcing a table per type.
    """

    __tablename__ = "feedback_targets"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[TargetType] = mapped_column(
        pg_enum(TargetType, "target_type", create_type=False),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(250), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))

    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_feedback_targets_org_type", "org_id", "target_type"),
        Index(
            "ix_feedback_targets_label_trgm",
            "label",
            postgresql_using="gin",
            postgresql_ops={"label": "gin_trgm_ops"},
        ),
        UniqueConstraint(
            "org_id", "target_type", "reference", name="uq_target_org_type_reference"
        ),
    )


class Contact(UUIDPrimaryKey, Timestamped, Base):
    """An external respondent: client contact, customer, or prospect.

    Never a `User`. External respondents authenticate with a one-time link and
    have no credentials, no password reset flow, and no dormant account left
    behind when an engagement ends.
    """

    __tablename__ = "contacts"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_contacts_org_email"),
        Index(
            "ix_contacts_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
    )
