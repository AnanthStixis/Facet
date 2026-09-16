"""Email templates gain an optional signature (sign-off) block.

Adds a `signature` column to `email_templates`. It is rendered by
app/services/email.py between the message body and the CTA button — a
per-template sign-off ("Regards, The Team") the author controls, distinct from
the fixed CTA/expiry/footer a template never controls. Optional; existing rows
default to an empty signature (no sign-off), so nothing about current outbound
email changes until an author adds one.

Revision ID: 0032_email_template_signature
Revises: 0031_email_template_library
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_email_template_signature"
down_revision = "0031_email_template_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_templates",
        sa.Column("signature", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("email_templates", "signature")