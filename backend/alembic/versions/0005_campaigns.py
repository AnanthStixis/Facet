"""External campaigns: audience, recipients, and the public link resolver.

Revision ID: 0005_campaigns
Revises: 0004_cycles
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_campaigns"
down_revision = "0004_cycles"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"

TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)


def upgrade() -> None:
    bind = op.get_bind()

    for name, values in {
        "cycle_audience": ("internal", "external", "mixed"),
        "recipient_status": (
            "pending", "sent", "opened", "submitted",
            "bounced", "unsubscribed", "expired", "revoked",
        ),
    }.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.add_column(
        "review_cycles",
        sa.Column(
            "audience",
            postgresql.ENUM(name="cycle_audience", create_type=False),
            nullable=False,
            server_default="internal",
        ),
    )
    op.create_index("ix_review_cycles_audience", "review_cycles", ["audience"])

    # --- campaign_recipients ---------------------------------------------
    op.create_table(
        "campaign_recipients",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="recipient_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("batch", sa.String(80)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("first_opened_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_ip", postgresql.INET()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_recipients"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_campaign_recipients_org_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["review_cycles.id"],
            name="fk_campaign_recipients_cycle_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["feedback_targets.id"],
            name="fk_campaign_recipients_target_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            name="fk_campaign_recipients_contact_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_campaign_recipients_token_hash"),
        sa.UniqueConstraint(
            "cycle_id", "target_id", "contact_id", name="uq_recipient_unique"
        ),
    )
    op.create_index("ix_campaign_recipients_org_id", "campaign_recipients", ["org_id"])
    op.create_index("ix_campaign_recipients_cycle_id", "campaign_recipients", ["cycle_id"])
    op.create_index("ix_campaign_recipients_target_id", "campaign_recipients", ["target_id"])
    op.create_index("ix_campaign_recipients_contact_id", "campaign_recipients", ["contact_id"])
    op.create_index("ix_recipients_cycle_status", "campaign_recipients", ["cycle_id", "status"])
    op.create_index("ix_recipients_token", "campaign_recipients", ["token_hash"])

    # --- responses gain an external provenance column ---------------------
    op.add_column(
        "feedback_responses",
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_feedback_responses_recipient_id",
        "feedback_responses",
        "campaign_recipients",
        ["recipient_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_feedback_responses_recipient_id", "feedback_responses", ["recipient_id"]
    )

    # Extend the anonymity guarantee to cover the external path. Without this,
    # an anonymous external response would still be joinable back to the
    # contact it was sent to, which is precisely the leak the internal design
    # went to trouble to prevent.
    op.drop_constraint(
        "ck_feedback_responses_anonymous_has_no_reviewer_link",
        "feedback_responses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_feedback_responses_anonymous_has_no_reviewer_link",
        "feedback_responses",
        "(is_anonymous AND assignment_id IS NULL AND reviewer_user_id IS NULL "
        " AND recipient_id IS NULL) OR (NOT is_anonymous)",
    )

    # --- RLS ---------------------------------------------------------------
    op.execute("ALTER TABLE campaign_recipients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaign_recipients FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY campaign_recipients_tenant_isolation ON campaign_recipients "
        f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
    )

    # --- Public link resolution -------------------------------------------
    # The respondent endpoint is unauthenticated and internet-facing, so it has
    # the same bootstrapping problem as login: it must find a tenant-scoped row
    # before any tenant is bound.
    #
    # The resolution is the same as for authentication. One SECURITY DEFINER
    # function returns the minimum needed to identify the link's tenant, and
    # nothing else. The endpoint then binds *that* organization and does all
    # remaining work under ordinary row level security — so a bug in the public
    # handler can only ever touch the one tenant the token already belonged to.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_public_link(p_token_hash text)
        RETURNS TABLE (
            recipient_id uuid,
            org_id       uuid,
            cycle_id     uuid,
            target_id    uuid,
            contact_id   uuid,
            status       recipient_status,
            expires_at   timestamptz,
            cycle_status cycle_status
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        STABLE
        AS $$
            SELECT r.id, r.org_id, r.cycle_id, r.target_id, r.contact_id,
                   r.status, r.expires_at, c.status
            FROM campaign_recipients r
            JOIN review_cycles c ON c.id = r.cycle_id
            WHERE r.token_hash = p_token_hash
            LIMIT 1;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION facet_public_link(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_public_link(text) TO facet_app")

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS facet_public_link(text)")
    op.drop_constraint(
        "ck_feedback_responses_anonymous_has_no_reviewer_link",
        "feedback_responses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_feedback_responses_anonymous_has_no_reviewer_link",
        "feedback_responses",
        "(is_anonymous AND assignment_id IS NULL AND reviewer_user_id IS NULL) "
        "OR (NOT is_anonymous)",
    )
    op.drop_constraint(
        "uq_feedback_responses_recipient_id", "feedback_responses", type_="unique"
    )
    op.drop_constraint(
        "fk_feedback_responses_recipient_id", "feedback_responses", type_="foreignkey"
    )
    op.drop_column("feedback_responses", "recipient_id")
    op.execute("DROP TABLE IF EXISTS campaign_recipients CASCADE")
    op.drop_index("ix_review_cycles_audience", table_name="review_cycles")
    op.drop_column("review_cycles", "audience")
    for name in ["recipient_status", "cycle_audience"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
