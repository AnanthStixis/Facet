"""Add plan_started_at to organizations, and return plan info from
facet_auth_principal() so login can check for expiration.

Existing organizations backfill plan_started_at to the moment this
migration runs, giving every current org a full period starting today
rather than retroactively expiring anyone. New organizations set it
explicitly at creation time (self_register_instant, provision_organization,
approve_organization), and it is reset whenever a Super Admin renews or
changes an org's plan (update_organization) — any explicit save there is
treated as a renewal, matching "upgrade or renew" from the login-blocked
message.

Revision ID: 0027_plan_expiration
Revises: 0026_paid_self_service
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_plan_expiration"
down_revision = "0026_paid_self_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "plan_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Postgres refuses a plain CREATE OR REPLACE when the OUT-parameter row
    # type changes (here: two more columns) — the function must be dropped
    # first, same constraint 0019 hit changing this same function before.
    op.execute("DROP FUNCTION IF EXISTS facet_auth_principal(uuid, text)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_auth_principal(
            p_user_id uuid DEFAULT NULL,
            p_email   text DEFAULT NULL
        )
        RETURNS TABLE (
            id                   uuid,
            org_id               uuid,
            email                varchar,
            full_name            varchar,
            role                 user_role,
            status               user_status,
            password_hash        varchar,
            must_change_password boolean,
            failed_login_count   integer,
            locked_until         timestamptz,
            org_status           org_status,
            org_plan             org_plan,
            org_plan_started_at  timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        STABLE
        AS $$
            SELECT
                u.id, u.org_id, u.email, u.full_name, u.role, u.status,
                u.password_hash, u.must_change_password,
                u.failed_login_count, u.locked_until,
                o.status, o.plan, o.plan_started_at
            FROM users u
            LEFT JOIN organizations o ON o.id = u.org_id
            WHERE (p_user_id IS NOT NULL AND u.id = p_user_id)
               OR (p_user_id IS NULL AND p_email IS NOT NULL
                   AND lower(u.email) = lower(p_email))
            LIMIT 1;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION facet_auth_principal(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_auth_principal(uuid, text) TO facet_app")


def downgrade() -> None:
    # Restore the pre-0027 function shape (matching 0019's definition)
    # before dropping the column it depends on.
    op.execute("DROP FUNCTION IF EXISTS facet_auth_principal(uuid, text)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_auth_principal(
            p_user_id uuid DEFAULT NULL,
            p_email   text DEFAULT NULL
        )
        RETURNS TABLE (
            id                   uuid,
            org_id               uuid,
            email                varchar,
            full_name            varchar,
            role                 user_role,
            status               user_status,
            password_hash        varchar,
            must_change_password boolean,
            failed_login_count   integer,
            locked_until         timestamptz,
            org_status           org_status
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        STABLE
        AS $$
            SELECT
                u.id, u.org_id, u.email, u.full_name, u.role, u.status,
                u.password_hash, u.must_change_password,
                u.failed_login_count, u.locked_until,
                o.status
            FROM users u
            LEFT JOIN organizations o ON o.id = u.org_id
            WHERE (p_user_id IS NOT NULL AND u.id = p_user_id)
               OR (p_user_id IS NULL AND p_email IS NOT NULL
                   AND lower(u.email) = lower(p_email))
            LIMIT 1;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION facet_auth_principal(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_auth_principal(uuid, text) TO facet_app")
    op.drop_column("organizations", "plan_started_at")