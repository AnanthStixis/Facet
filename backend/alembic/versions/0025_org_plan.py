"""Add plan to organizations.

Determines seat caps and whether external review types (Client/Product/
Service/Proposal) are available — see PLAN_LIMITS in app/core/plans.py for
the actual numbers. No payment gateway exists yet, so this is set manually
by a Super Admin for now.

Existing organizations back-fill as Enterprise (unlimited) so turning this
feature on never suddenly caps an org already using the platform. New
organizations default to Starter going forward, matching that intent at the
column level too.

Revision ID: 0025_org_plan
Revises: 0024_assignment_tokens
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_org_plan"
down_revision = "0024_assignment_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("starter", "growth", "enterprise", name="org_plan").create(
        bind, checkfirst=True
    )
    op.add_column(
        "organizations",
        sa.Column(
            "plan",
            postgresql.ENUM(name="org_plan", create_type=False),
            nullable=False,
            server_default="enterprise",
        ),
    )
    op.alter_column("organizations", "plan", server_default="starter")


def downgrade() -> None:
    op.drop_column("organizations", "plan")
    op.execute("DROP TYPE org_plan")