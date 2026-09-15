"""Org- or vendor-authored copy for the feedback-request invite email.

A Super Admin's row (`scope=GLOBAL`, `org_id=NULL`) is the platform default
for a review kind — exactly one per kind. An org may author any number of
its own (`scope=ORG`) templates for a kind — a library, not a single
override — but at most one of them may be `is_active` at a time
(`uq_email_templates_org_kind_active`, added 0031); a send uses that active
row, or the global default if the org has none active for the kind (see
app/services/email_templates.py). Activating one row is what deactivates
whichever other org row for the same kind was active, enforced by the
partial unique index rather than trusted to the API layer alone.

Only the subject, heading, and message body are stored and editable here.
The CTA button/link, expiry line, and footer/legal notice are never part of
this row — `app/services/email.py` always renders those itself, so an org
can personalize the pitch without ever being able to break the link or drop
required legal text.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import EmailTemplateKind, TemplateScope


class EmailTemplate(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "email_templates"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[EmailTemplateKind] = mapped_column(
        pg_enum(EmailTemplateKind, "email_template_kind"), nullable=False
    )
    scope: Mapped[TemplateScope] = mapped_column(
        pg_enum(TemplateScope, "template_scope", create_type=False),
        nullable=False,
        default=TemplateScope.ORG,
    )

    # Set when an org's row started life as a copy of the global default for
    # this kind, so we can tell customization from an independently-written
    # row (not that anything currently branches on it — kept for the same
    # reason FeedbackTemplate.cloned_from_id is, so it isn't a follow-up
    # migration the day someone wants to know).
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="SET NULL")
    )

    # What an admin sees in the list to tell rows for the same kind apart —
    # required for an org's own rows (the create form requires it); a global
    # row's name is just its kind's label.
    name: Mapped[str] = mapped_column(String(150), nullable=False, default="")

    subject_template: Mapped[str] = mapped_column(String(200), nullable=False)
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # For an org row: whether this is the one a send actually uses (see
    # module docstring — enforced as "at most one" by a DB index, not just
    # this flag). Meaningless for a global row, which has no sibling to
    # compete with; left `True` there for no reason beyond schema symmetry.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index(
            "uq_email_templates_global_kind",
            "kind",
            unique=True,
            postgresql_where="org_id IS NULL",
        ),
        Index(
            "uq_email_templates_org_kind_active",
            "org_id",
            "kind",
            unique=True,
            postgresql_where="org_id IS NOT NULL AND is_active",
        ),
        CheckConstraint(
            "(scope = 'global' AND org_id IS NULL) "
            "OR (scope = 'org' AND org_id IS NOT NULL)",
            name="email_template_scope_matches_org",
        ),
    )
