"""Add 'deleted' to the user_status enum.

app/models/enums.py's UserStatus already carries a DELETED member (used
throughout dashboard.py, orgs.py, and users.py to filter out soft-deleted
users), but no prior migration ever added the matching label to the
Postgres user_status enum type created in 0001_initial_schema. Any query
that filters `User.status != UserStatus.DELETED` fails at the database
with "invalid input value for enum user_status: deleted" until this runs.

Revision ID: 0029_user_status_deleted
Revises: 0028_response_own_view
"""

from __future__ import annotations

from alembic import op

revision = "0029_user_status_deleted"
down_revision = "0028_response_own_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the transaction Alembic
    # normally wraps migrations in, so this one opts out of it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'deleted'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum label
    # requires rebuilding the type, which isn't worth doing for a value
    # that's additive and harmless to leave in place.
    pass
