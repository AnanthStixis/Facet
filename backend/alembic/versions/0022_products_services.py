"""Product and Service master lists.

Additive only. Same pattern as departments/job_titles/cycle_names — a
simple org-scoped name list, picked from a dropdown on the Product/Service
review forms; not a foreign key from anywhere, so nothing about
ReviewCycle.target_label changes here.

Revision ID: 0022_products_services
Revises: 0021_contacts_phone_master_flag
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_products_services"
down_revision = "0021_contacts_phone_master_flag"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"
TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)

_TABLES = {
    "products": "uq_products_org_name",
    "services": "uq_services_org_name",
}


def upgrade() -> None:
    for table, uq_name in _TABLES.items():
        op.create_table(
            table,
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
        op.create_index(uq_name, table, ["org_id", "name"], unique=True)

        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
        )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.drop_table(table)
