"""Email templates become a per-kind library, not a single override.

An org admin can now author more than one template for a review kind (e.g.
try two different pitches) and switch which one is live. `is_active` already
existed on `email_templates` (added 0030) but nothing enforced "at most one"
with it; this migration adds the enforcement and the `name` an admin needs
to tell rows apart in a list.

The old invariant — at most one *org* row per (org_id, kind), full stop — is
replaced by: at most one *active* org row per (org_id, kind). An org can
have any number of inactive drafts for a kind. The global row per kind is
untouched (still exactly one, per 0030) and is what a send falls back to
when an org has no active row for that kind — see
app/services/email_templates.py, which already filters on `is_active` and
needs no code change for this.

Revision ID: 0031_email_template_library
Revises: 0030_email_templates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_email_template_library"
down_revision = "0030_email_templates"
branch_labels = None
depends_on = None

_KIND_LABEL = {
    "client": "Client Review",
    "employee": "Employees Review",
    "management": "Management Review",
    "product": "Product Review",
    "service": "Service Review",
    "proposal": "Proposal Review",
}


def upgrade() -> None:
    op.add_column(
        "email_templates",
        sa.Column("name", sa.String(150), nullable=False, server_default=""),
    )

    # Backfill: a global row's name is just its kind's label; any pre-existing
    # org row (there shouldn't be many yet — this feature is brand new) was
    # that org's one-and-only override under the old model, so it was
    # necessarily the active one and is named generically.
    for kind, label in _KIND_LABEL.items():
        op.execute(
            sa.text(
                "UPDATE email_templates SET name = :label "
                "WHERE org_id IS NULL AND kind = CAST(:kind AS email_template_kind)"
            ).bindparams(label=f"{label} (platform default)", kind=kind)
        )
    op.execute(
        "UPDATE email_templates SET name = 'Custom', is_active = true "
        "WHERE org_id IS NOT NULL"
    )

    op.drop_index("uq_email_templates_org_kind", table_name="email_templates")
    op.create_index(
        "uq_email_templates_org_kind_active",
        "email_templates",
        ["org_id", "kind"],
        unique=True,
        postgresql_where=sa.text("org_id IS NOT NULL AND is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_email_templates_org_kind_active", table_name="email_templates")
    # An org that ended up with more than one row for a kind under the new
    # model has no single row to collapse back to a one-per-kind unique
    # index — keep only the active one (or, absent that, the most recently
    # updated) so the old constraint can be restored at all.
    op.execute(
        """
        DELETE FROM email_templates et
        WHERE et.org_id IS NOT NULL
          AND et.id NOT IN (
              SELECT DISTINCT ON (org_id, kind) id
              FROM email_templates
              WHERE org_id IS NOT NULL
              ORDER BY org_id, kind, is_active DESC, updated_at DESC
          )
        """
    )
    op.create_index(
        "uq_email_templates_org_kind",
        "email_templates",
        ["org_id", "kind"],
        unique=True,
        postgresql_where=sa.text("org_id IS NOT NULL"),
    )
    op.drop_column("email_templates", "name")
