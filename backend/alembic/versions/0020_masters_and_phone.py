"""Department/Job Title/Cycle Name master lists, and users.phone.

Additive only. The three master tables are simple org-scoped name lists —
selecting a row just fills a text field (User.department, User.job_title,
ReviewCycle.name) the same as typing it would; none of those existing
columns become foreign keys, so nothing about them changes here.

Revision ID: 0020_masters_and_phone
Revises: 0019_fix_auth_principal_mfa
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_masters_and_phone"
down_revision = "0019_fix_auth_principal_mfa"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"
TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)

_TABLES = {
    "departments": "uq_departments_org_name",
    "job_titles": "uq_job_titles_org_name",
    "cycle_names": "uq_cycle_names_org_name",
}


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=30), nullable=True))

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
    op.drop_column("users", "phone")
