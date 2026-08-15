"""Add suspension_reason to organizations.

Suspend already recorded its reason in the audit log, but the org row itself
had nowhere to hold it — so the list page could show "Rejected: <reason>" but
had nothing to show for a suspended org. Mirrors rejection_reason.

Revision ID: 0015_org_suspension_reason
Revises: 0014_target_type_client
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_org_suspension_reason"
down_revision = "0014_target_type_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("suspension_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "suspension_reason")
