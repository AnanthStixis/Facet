"""Store a campaign's subject directly on the cycle.

An external campaign's "subject" (the product/service/proposal it is about)
was only ever derivable by joining through campaign_recipients — which means
a freshly created campaign with zero recipients had no queryable target at
all. The recipients UI required that target_id to add the first recipient,
so nobody could ever add one: a straight chicken-and-egg 422. This adds the
column so the campaign's subject is set once, at creation, and read directly.

Revision ID: 0011_cycle_target
Revises: 0010_password_reset
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_cycle_target"
down_revision = "0010_password_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_cycles",
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_review_cycles_target_id",
        "review_cycles",
        "feedback_targets",
        ["target_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_review_cycles_target_id", "review_cycles", ["target_id"])

    # Backfill existing external campaigns from whatever their recipients
    # already point at, so nothing already sent loses its subject.
    op.execute(
        """
        UPDATE review_cycles
        SET target_id = sub.target_id
        FROM (
            SELECT DISTINCT ON (cycle_id) cycle_id, target_id
            FROM campaign_recipients
            ORDER BY cycle_id, created_at
        ) AS sub
        WHERE review_cycles.id = sub.cycle_id
          AND review_cycles.target_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_review_cycles_target_id", table_name="review_cycles")
    op.drop_constraint("fk_review_cycles_target_id", "review_cycles", type_="foreignkey")
    op.drop_column("review_cycles", "target_id")
