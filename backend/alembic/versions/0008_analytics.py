"""Fitted analytics models.

Revision ID: 0008_analytics
Revises: 0007_ai
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_analytics"
down_revision = "0007_ai"
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
        "model_kind": ("win_probability", "score_trend", "disengagement_risk"),
        "model_status": ("fitted", "insufficient_data", "failed"),
    }.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "analytics_models",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(name="model_kind", create_type=False), nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="model_status", create_type=False),
            nullable=False,
            server_default="insufficient_data",
        ),
        sa.Column("algorithm", sa.String(60), nullable=False, server_default="none"),
        sa.Column("reason", sa.Text()),
        sa.Column("n_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_positive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_features", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "feature_names", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "coefficients", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metrics", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("baseline_rate", sa.Numeric(5, 4)),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_models"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_analytics_models_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "kind", name="uq_analytics_model_kind"),
        # A fitted model must carry a reason-free, non-empty coefficient set;
        # a refusal must carry a reason. Neither state is allowed to be silent.
        sa.CheckConstraint(
            "(status = 'fitted' AND coefficients <> '{}'::jsonb) "
            "OR (status <> 'fitted' AND reason IS NOT NULL)",
            name="ck_analytics_models_state_is_explained",
        ),
    )
    op.create_index("ix_analytics_models_org_id", "analytics_models", ["org_id"])
    op.create_index("ix_analytics_models_trained_at", "analytics_models", ["trained_at"])
    op.create_index(
        "ix_analytics_models_org_kind", "analytics_models", ["org_id", "kind"]
    )

    op.execute("ALTER TABLE analytics_models ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE analytics_models FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY analytics_models_tenant_isolation ON analytics_models "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics_models CASCADE")
    for name in ["model_status", "model_kind"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
