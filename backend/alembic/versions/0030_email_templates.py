"""Email templates: per-kind, org-overridable copy for the feedback-request
invite email.

New `email_templates` table following `feedback_templates`' own
global/org pattern (see 0001_initial_schema, catalog.py): a Super Admin's
row (`scope='global'`, `org_id NULL`) is the platform default for a review
kind; an org customizes by cloning that default into its own `scope='org'`
row. RLS mirrors `CATALOG_RLS_TABLES` — every tenant can *read* a global
row, but only a matching tenant (or a Super Admin acting platform-wide) can
write one.

Seeds the six global defaults with the exact copy `send_feedback_request`
already hardcodes today, so nothing about outbound email changes until an
admin actually edits a template through the new UI.

Revision ID: 0030_email_templates
Revises: 0029_user_status_deleted
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_email_templates"
down_revision = "0029_user_status_deleted"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"
TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)
CATALOG_READ_PREDICATE = f"(org_id IS NULL OR {TENANT_PREDICATE})"

_KINDS = ["client", "employee", "management", "product", "service", "proposal"]

# subject, heading, body_text — copied verbatim from
# app/services/email.py's send_feedback_request so the seeded defaults
# change nothing about what recipients receive today.
_SEED = {
    "employee": (
        "Feedback Request",
        "Share your feedback on {subject_label}",
        "Dear {first_name}, you have been asked to share feedback on your "
        "colleague, {subject_label}. Your input helps build a clear, "
        "well-rounded picture of how things are going and where there is "
        "room to grow.",
    ),
    "management": (
        "Feedback Request",
        "Share your feedback on {subject_label}",
        "Dear {first_name}, you have been asked to share feedback on your "
        "manager, {subject_label}. Your input helps build a clear, "
        "well-rounded picture of how things are going and where there is "
        "room to grow.",
    ),
    "client": (
        "Please Share Your Feedback",
        "",
        "Dear {first_name}, {org_name} values your feedback on "
        "{subject_label} and would appreciate a few minutes of your time to "
        "share your experience. Your responses help us understand what is "
        "working well and where we can improve.",
    ),
    "product": (
        "Please Share Your Feedback",
        "",
        "Dear {first_name}, {org_name} values your feedback on "
        "{subject_label} and would appreciate a few minutes of your time to "
        "share your experience. Your responses help us understand what is "
        "working well and where we can improve.",
    ),
    "service": (
        "Please Share Your Feedback",
        "",
        "Dear {first_name}, {org_name} values your feedback on "
        "{subject_label} and would appreciate a few minutes of your time to "
        "share your experience. Your responses help us understand what is "
        "working well and where we can improve.",
    ),
    "proposal": (
        "Please Share Your Feedback",
        "",
        "Dear {first_name}, {org_name} values your feedback on "
        "{subject_label} and would appreciate a few minutes of your time to "
        "share your experience. Your responses help us understand where we "
        "can improve.",
    ),
}


def upgrade() -> None:
    op.execute(
        "CREATE TYPE email_template_kind AS ENUM "
        "('client', 'employee', 'management', 'product', 'service', 'proposal')"
    )

    op.create_table(
        "email_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "kind",
            postgresql.ENUM(name="email_template_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "scope",
            postgresql.ENUM(name="template_scope", create_type=False),
            nullable=False,
            server_default="org",
        ),
        sa.Column("cloned_from_id", postgresql.UUID(as_uuid=True)),
        sa.Column("subject_template", sa.String(200), nullable=False),
        sa.Column("heading", sa.String(200), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_templates"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_email_templates_org_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cloned_from_id"], ["email_templates.id"],
            name="fk_email_templates_cloned_from_id_email_templates", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_email_templates_created_by_id_users", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND org_id IS NULL) "
            "OR (scope = 'org' AND org_id IS NOT NULL)",
            name="email_template_scope_matches_org",
        ),
    )
    op.create_index("ix_email_templates_org_id", "email_templates", ["org_id"])
    op.create_index(
        "uq_email_templates_global_kind", "email_templates", ["kind"],
        unique=True, postgresql_where=sa.text("org_id IS NULL"),
    )
    op.create_index(
        "uq_email_templates_org_kind", "email_templates", ["org_id", "kind"],
        unique=True, postgresql_where=sa.text("org_id IS NOT NULL"),
    )

    op.execute("ALTER TABLE email_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY email_templates_tenant_isolation ON email_templates "
        f"USING {CATALOG_READ_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    insert_stmt = sa.text(
        "INSERT INTO email_templates (kind, scope, subject_template, heading, body_text) "
        "VALUES (CAST(:kind AS email_template_kind), CAST(:scope AS template_scope), "
        ":subject_template, :heading, :body_text)"
    )
    for kind, (subject, heading, body) in _SEED.items():
        op.execute(
            insert_stmt.bindparams(
                kind=kind,
                scope="global",
                subject_template=subject,
                heading=heading,
                body_text=body,
            )
        )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS email_templates_tenant_isolation ON email_templates")
    op.drop_table("email_templates")
    op.execute("DROP TYPE IF EXISTS email_template_kind")
