"""Add is_active to feedback_templates.

A template needs an active/disabled state independent of its draft/published
version status — a disabled template stops appearing as selectable in
CreateFeedback.tsx's template dropdown, without archiving or deleting it.
Additive column, default true, so every existing template stays selectable.

Revision ID: 0016_template_active_flag
Revises: 0015_org_suspension_reason
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_template_active_flag"
down_revision = "0015_org_suspension_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback_templates",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("feedback_templates", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_column("feedback_templates", "is_active")
