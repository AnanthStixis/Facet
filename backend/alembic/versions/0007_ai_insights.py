"""Sentiment fields and the AI insight cache.

Revision ID: 0007_ai
Revises: 0006_proposals
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_ai"
down_revision = "0006_proposals"
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
        "insight_kind": (
            "target_summary", "cycle_summary", "theme_cluster", "recommendation",
        ),
        "insight_status": ("ready", "suppressed", "failed", "stale"),
    }.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # --- Sentiment on responses -------------------------------------------
    # Per-comment and high volume, so these live on the response rather than in
    # ai_insights: every aggregate wants to average them in SQL.
    for column in (
        sa.Column("sentiment_score", sa.Numeric(4, 3)),
        sa.Column("sentiment_label", sa.String(20)),
        sa.Column("sentiment_confidence", sa.Numeric(4, 3)),
        sa.Column(
            "sentiment_aspects",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sentiment_model", sa.String(80)),
        sa.Column("sentiment_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("feedback_responses", column)

    op.create_index(
        "ix_responses_sentiment",
        "feedback_responses",
        ["cycle_id", "sentiment_label"],
    )

    # --- ai_insights -------------------------------------------------------
    op.create_table(
        "ai_insights",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(name="insight_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="insight_status", create_type=False),
            nullable=False,
            server_default="ready",
        ),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True)),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default="openai"),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_insights"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_ai_insights_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["review_cycles.id"], name="fk_ai_insights_cycle_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "kind", "subject_id", "cycle_id", name="uq_insight_subject_kind"
        ),
    )
    op.create_index("ix_ai_insights_org_id", "ai_insights", ["org_id"])
    op.create_index("ix_ai_insights_cycle_id", "ai_insights", ["cycle_id"])
    op.create_index("ix_ai_insights_generated_at", "ai_insights", ["generated_at"])
    op.create_index("ix_insights_org_kind", "ai_insights", ["org_id", "kind"])
    op.create_index("ix_insights_hash", "ai_insights", ["input_hash"])
    op.create_index("ix_insights_org_generated", "ai_insights", ["org_id", "generated_at"])

    op.execute("ALTER TABLE ai_insights ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_insights FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY ai_insights_tenant_isolation ON ai_insights "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_insights CASCADE")
    op.drop_index("ix_responses_sentiment", table_name="feedback_responses")
    for name in (
        "sentiment_at",
        "sentiment_model",
        "sentiment_aspects",
        "sentiment_confidence",
        "sentiment_label",
        "sentiment_score",
    ):
        op.execute(f"ALTER TABLE feedback_responses DROP COLUMN IF EXISTS {name}")
    for name in ["insight_status", "insight_kind"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
