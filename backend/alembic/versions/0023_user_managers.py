"""Employee <-> Manager many-to-many.

`User.manager_id` is a single FK, and cannot represent someone who reports
to 2-3 managers at once. This adds `user_managers`, a proper junction
table, and backfills it with every existing single manager_id relationship
so day-one behaviour is unchanged. `users.manager_id` itself is left in
place, unused going forward, rather than dropped — a dormant column is a
far safer migration than a destructive one.

Revision ID: 0023_user_managers
Revises: 0022_products_services
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_user_managers"
down_revision = "0022_products_services"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"
TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)

TABLE = "user_managers"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(f"ix_{TABLE}_org_id", TABLE, ["org_id"])
    op.create_index(f"ix_{TABLE}_employee_id", TABLE, ["employee_id"])
    op.create_index(f"ix_{TABLE}_manager_id", TABLE, ["manager_id"])
    op.create_index(
        "uq_user_managers_employee_manager", TABLE, ["employee_id", "manager_id"], unique=True
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {TABLE}_tenant_isolation ON {TABLE} "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    # Backfill: every existing single manager_id relationship becomes one
    # row here, so upgrading changes nothing about who currently gets a
    # downward review — only the storage, not the behaviour.
    op.execute(
        f"""
        INSERT INTO {TABLE} (id, org_id, employee_id, manager_id, created_at, updated_at)
        SELECT gen_random_uuid(), org_id, id, manager_id, now(), now()
        FROM users
        WHERE manager_id IS NOT NULL
        """
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)