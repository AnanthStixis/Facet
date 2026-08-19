"""Single-use tokens for internal "you have been asked" email links.

Revision ID: 00XX_assignment_tokens
Revises: <PASTE YOUR CURRENT HEAD HERE>
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_assignment_tokens"
down_revision = "0023_user_managers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable and generated lazily — only an assignment that actually gets
    # emailed needs one; an assignment reached purely through the in-app
    # "My feedback" queue never needs a bearer secret at all.
    op.add_column(
        "feedback_assignments",
        sa.Column("token_hash", sa.String(64)),
    )
    op.create_unique_constraint(
        "uq_feedback_assignments_token_hash", "feedback_assignments", ["token_hash"]
    )
    op.create_index(
        "ix_feedback_assignments_token", "feedback_assignments", ["token_hash"]
    )

    # Same shape as facet_public_link (migration 0005_campaigns): one
    # SECURITY DEFINER function that identifies the token's tenant and
    # nothing else, so a bug in the handler can only ever touch the one
    # tenant the token already belonged to.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_assignment_link(p_token_hash text)
        RETURNS TABLE (
            assignment_id uuid,
            org_id        uuid,
            cycle_id      uuid,
            target_id     uuid,
            reviewer_user_id uuid,
            status        assignment_status,
            cycle_status  cycle_status
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        STABLE
        AS $$
            SELECT a.id, a.org_id, a.cycle_id, a.target_id, a.reviewer_user_id,
                   a.status, c.status
            FROM feedback_assignments a
            JOIN review_cycles c ON c.id = a.cycle_id
            WHERE a.token_hash = p_token_hash
            LIMIT 1;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION facet_assignment_link(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_assignment_link(text) TO facet_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS facet_assignment_link(text)")
    op.drop_index("ix_feedback_assignments_token", table_name="feedback_assignments")
    op.drop_constraint(
        "uq_feedback_assignments_token_hash", "feedback_assignments", type_="unique"
    )
    op.drop_column("feedback_assignments", "token_hash")