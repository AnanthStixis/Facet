"""Admin-initiated password reset tokens.

Revision ID: 0010_password_reset
Revises: 0009_retention
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_password_reset"
down_revision = "0009_retention"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"

TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_password_reset_tokens_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], name="fk_password_reset_tokens_requested_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_org_id", "password_reset_tokens", ["org_id"])
    op.create_index("ix_password_reset_tokens_user", "password_reset_tokens", ["user_id"])

    op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY password_reset_tokens_tenant_isolation ON password_reset_tokens "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS password_reset_tokens_tenant_isolation ON password_reset_tokens"
    )
    op.drop_index("ix_password_reset_tokens_user", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_org_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
