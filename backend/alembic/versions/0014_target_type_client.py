"""Add CLIENT to the target_type enum.

The simplified "Create Feedback" flow gives relationship-level client
feedback (feedback about the client relationship as a whole, not tied to a
specific product/service/proposal) its own place on the target-type axis,
distinct from product/service/proposal. Additive only — no data migration.

Revision ID: 0014_target_type_client
Revises: 0013_global_email_uniqueness
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op

revision = "0014_target_type_client"
down_revision = "0013_global_email_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that
    # later uses the new value (and, on older Postgres, cannot run inside an
    # explicit transaction block at all) — autocommit_block() steps outside
    # Alembic's normal transactional DDL wrapper for just this statement.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE target_type ADD VALUE IF NOT EXISTS 'client'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Removing a value would
    # require rebuilding the enum type and is not attempted here — this
    # migration is additive-only by design.
    pass
