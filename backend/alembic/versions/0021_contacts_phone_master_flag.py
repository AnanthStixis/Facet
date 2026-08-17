"""contacts.phone, and is_active on the master lists.

Additive only. `is_active` backs a disable/enable toggle on Department/Job
Title/Cycle Name rows so an org can retire an entry without breaking past
records that already used it as free text (same reasoning as the master
tables themselves — nothing downstream is a foreign key to these).

Revision ID: 0021_contacts_phone_masters_active
Revises: 0020_masters_and_phone
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_contacts_phone_master_flag"
down_revision = "0020_masters_and_phone"
branch_labels = None
depends_on = None

_MASTER_TABLES = ["departments", "job_titles", "cycle_names"]


def upgrade() -> None:
    op.add_column("contacts", sa.Column("phone", sa.String(length=30), nullable=True))
    for table in _MASTER_TABLES:
        op.add_column(
            table,
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade() -> None:
    for table in _MASTER_TABLES:
        op.drop_column(table, "is_active")
    op.drop_column("contacts", "phone")
