"""Add feedback_responses.submitted_by_user_id.

A narrow, deliberate exception to the anonymity guarantee described in
app/models/cycle.py's module docstring — added only so a reviewer can look
up their own past answers on an anonymous response later (My Reviews ->
Reviews Given -> View Review), which the existing anonymous-response design
otherwise makes structurally impossible (assignment_id and reviewer_user_id
are both NULL for those rows, on purpose).

This is intentionally a SEPARATE column from reviewer_user_id, not a relaxed
constraint on it: the existing check constraint (anonymous_has_no_reviewer_
link) is untouched, so an anonymous response still has no assignment_id,
reviewer_user_id, or recipient_id populated. Only this one column carries a
link, and only api/v1/cycles.py's submit_response (writer) and
get_my_response (reader) should ever touch it — no report, export, or other
endpoint should select it. See the model docstring for the full warning.

Revision ID: 0028_response_own_view
Revises: 0027_plan_expiration
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_response_own_view"
down_revision = "0027_plan_expiration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback_responses",
        sa.Column(
            "submitted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_responses_submitted_by_cycle_target",
        "feedback_responses",
        ["submitted_by_user_id", "cycle_id", "target_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_responses_submitted_by_cycle_target", table_name="feedback_responses")
    op.drop_column("feedback_responses", "submitted_by_user_id")