"""Email templates gain per-field content format (text | html).

Adds body_format and signature_format, each defaulting to 'text', so every
existing row keeps rendering exactly as before until an author switches a
field to HTML. Also widens body_text and signature to TEXT, because HTML
markup (tags, inline colour styles) makes them far larger than the old
plain-text varchar caps allowed.

Revision ID: 0033_email_template_content_format
Revises: 0032_email_template_signature
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_email_template_content_format"
down_revision = "0032_email_template_signature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_templates",
        sa.Column("body_format", sa.String(4), nullable=False, server_default="text"))
    op.add_column("email_templates",
        sa.Column("signature_format", sa.String(4), nullable=False, server_default="text"))
    op.alter_column("email_templates", "body_text", type_=sa.Text(), existing_nullable=False)
    op.alter_column("email_templates", "signature", type_=sa.Text(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("email_templates", "signature", type_=sa.String(500), existing_nullable=False)
    op.alter_column("email_templates", "body_text", type_=sa.String(4000), existing_nullable=False)
    op.drop_column("email_templates", "signature_format")
    op.drop_column("email_templates", "body_format")