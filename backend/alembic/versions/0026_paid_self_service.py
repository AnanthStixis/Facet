"""Add paid_self_service to org_registration_source.

The counterpart to self-registration that lands in `pending` — this one
marks an organization that went live immediately through the (not yet
payment-gated) instant self-registration endpoint. Additive only, same
pattern as 0014_target_type_client.

Revision ID: 0026_paid_self_service
Revises: 0025_org_plan
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision = "0026_paid_self_service"
down_revision = "0025_org_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that
    # later uses the new value (and, on older Postgres, cannot run inside an
    # explicit transaction block at all) — autocommit_block() steps outside
    # Alembic's normal transactional DDL wrapper for just this statement.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE org_registration_source ADD VALUE IF NOT EXISTS 'paid_self_service'"
        )


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Removing a value would
    # require rebuilding the enum type and is not attempted here — this
    # migration is additive-only by design.
    pass