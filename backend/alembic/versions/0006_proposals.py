"""Proposals, outcomes, and reminder state.

Revision ID: 0006_proposals
Revises: 0005_campaigns
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_proposals"
down_revision = "0005_campaigns"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"

TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)


def upgrade() -> None:
    bind = op.get_bind()

    for name, values in {
        "proposal_stage": (
            "draft", "submitted", "shortlisted", "won", "lost", "withdrawn",
        ),
        "loss_reason": (
            "price", "timeline", "technical_fit", "relationship", "incumbent",
            "no_decision", "scope_mismatch", "other",
        ),
    }.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "proposals",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(60), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column(
            "stage",
            postgresql.ENUM(name="proposal_stage", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("prospect_contact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("author_id", postgresql.UUID(as_uuid=True)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("value_amount", sa.Numeric(14, 2)),
        sa.Column("estimated_effort_days", sa.Integer()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("decision_due_on", sa.Date()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("loss_reason", postgresql.ENUM(name="loss_reason", create_type=False)),
        sa.Column("won_amount", sa.Numeric(14, 2)),
        sa.Column("outcome_note", sa.Text()),
        sa.Column("competitor", sa.String(200)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_proposals"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_proposals_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prospect_contact_id"], ["contacts.id"],
            name="fk_proposals_prospect_contact_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_proposals_author_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["feedback_targets.id"], name="fk_proposals_target_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("org_id", "reference", name="uq_proposal_reference"),
        sa.CheckConstraint(
            "(loss_reason IS NULL) OR (stage = 'lost')",
            name="ck_proposals_loss_reason_only_when_lost",
        ),
        sa.CheckConstraint(
            "(stage NOT IN ('won','lost','withdrawn')) OR (decided_at IS NOT NULL)",
            name="ck_proposals_decided_stages_have_a_date",
        ),
    )
    op.create_index("ix_proposals_org_id", "proposals", ["org_id"])
    op.create_index("ix_proposals_author_id", "proposals", ["author_id"])
    op.create_index("ix_proposals_target_id", "proposals", ["target_id"])
    op.create_index("ix_proposals_org_stage", "proposals", ["org_id", "stage"])
    op.create_index("ix_proposals_submitted", "proposals", ["org_id", "submitted_at"])
    op.execute(
        "CREATE INDEX ix_proposals_title_trgm ON proposals USING gin (title gin_trgm_ops)"
    )

    # --- Reminder state ---------------------------------------------------
    op.add_column(
        "feedback_assignments",
        sa.Column("last_reminded_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("reminders_sent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("last_reminded_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "review_cycles",
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
    )

    op.execute("ALTER TABLE proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY proposals_tenant_isolation ON proposals "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    # IF EXISTS throughout: this revision was amended during development, so a
    # database may hold either shape.
    op.execute("ALTER TABLE review_cycles DROP COLUMN IF EXISTS escalated_at")
    op.execute("ALTER TABLE campaign_recipients DROP COLUMN IF EXISTS last_reminded_at")
    op.execute("ALTER TABLE campaign_recipients DROP COLUMN IF EXISTS reminders_sent")
    op.execute("ALTER TABLE feedback_assignments DROP COLUMN IF EXISTS last_reminded_at")
    op.execute("DROP TABLE IF EXISTS proposals CASCADE")
    for name in ["loss_reason", "proposal_stage"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
