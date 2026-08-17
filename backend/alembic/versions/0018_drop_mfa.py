"""Drop MFA columns and the recovery-code table.

Multi-factor auth was removed from the app this session — no code reads or
writes `users.mfa_enabled` / `mfa_secret_encrypted` / `mfa_confirmed_at`, and
`mfa_recovery_codes` has no code path left touching it at all. They were left
in place as harmless dead data at the time (same call as
`min_responses_to_reveal` before it), but since this is now shipping to QA as
a real schema change, drop them for real rather than carrying dead columns
forward indefinitely.

Irreversible in the sense that any MFA secrets/recovery codes still stored in
these columns are gone after this runs — but nothing in the app has read or
written them since MFA was removed, so there is nothing live depending on
them.

Revision ID: 0018_drop_mfa
Revises: 0017_catalog_created_by
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_drop_mfa"
down_revision = "0017_catalog_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("mfa_recovery_codes")
    op.drop_column("users", "mfa_confirmed_at")
    op.drop_column("users", "mfa_secret_encrypted")
    op.drop_column("users", "mfa_enabled")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("mfa_secret_encrypted", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("mfa_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_mfa_recovery_codes_user_id_users", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"]
    )
