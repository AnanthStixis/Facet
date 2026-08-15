"""Add created_by_id to categories and feedback_templates.

Additive, nullable columns — existing rows predate creator tracking and
render as "—" in the UI. Set going forward at creation time by
create_category/create_template/clone_template in catalog.py. ON DELETE
SET NULL: a category or template must never become undeletable, and a
user must never become un-removable, just because of this attribution
column.

Revision ID: 0017_catalog_created_by
Revises: 0016_template_active_flag
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_catalog_created_by"
down_revision = "0016_template_active_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_categories_created_by_id_users",
        "categories",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "feedback_templates",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_feedback_templates_created_by_id_users",
        "feedback_templates",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_feedback_templates_created_by_id_users", "feedback_templates", type_="foreignkey"
    )
    op.drop_column("feedback_templates", "created_by_id")

    op.drop_constraint("fk_categories_created_by_id_users", "categories", type_="foreignkey")
    op.drop_column("categories", "created_by_id")
