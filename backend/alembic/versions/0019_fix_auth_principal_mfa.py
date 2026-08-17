"""Fix facet_auth_principal() to stop selecting the columns 0018 dropped.

0018_drop_mfa dropped users.mfa_enabled / mfa_secret_encrypted but never
updated this SECURITY DEFINER function (from 0002_auth_lookup), which
selects them by name — every login started failing with
`UndefinedColumnError: column u.mfa_enabled does not exist` as a result.
This is the fix, forward-only: re-create the function without those two
columns, matching what app/services/auth.py's Principal/load_principal()
have actually expected since MFA was removed from the app.

Revision ID: 0019_fix_auth_principal_mfa
Revises: 0018_drop_mfa
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision = "0019_fix_auth_principal_mfa"
down_revision = "0018_drop_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres refuses a plain CREATE OR REPLACE when the OUT-parameter row
    # type changes (here: two fewer columns) — the function must be dropped
    # first.
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
    # DROP FUNCTION above also drops any grants on the old object — a
    # function is a distinct catalog entry after DROP+CREATE, even with the
    # identical name, so the permissions from 0002_auth_lookup have to be
    # re-applied rather than assumed to carry over.
    op.execute("REVOKE ALL ON FUNCTION facet_auth_principal(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_auth_principal(uuid, text) TO facet_app")


def downgrade() -> None:
    # Not a real restoration to the pre-0019 function: at this exact point in
    # a downgrade sequence (0019 -> 0018), 0018's downgrade() — which
    # restores the mfa_* columns — has not run yet, so a version of this
    # function that selects them would fail immediately, the same way
    # upgrading originally did. There is no valid intermediate state to go
    # back to here; downgrading all the way to 0017 (where this function was
    # last genuinely correct) requires continuing on to 0018's downgrade
    # right after this one.
    pass
