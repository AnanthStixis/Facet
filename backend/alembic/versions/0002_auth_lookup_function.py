"""Pre-authentication user lookup.

Revision ID: 0002_auth_lookup
Revises: 0001_initial
Create Date: 2026-08-07

Authentication has a bootstrapping problem. Row level security on `users`
filters by the tenant bound to the transaction, but at the moment a login
request arrives there is no tenant yet - working out which tenant the caller
belongs to is precisely what the lookup is for.

There are three ways out and only one of them is good:

  1. Turn RLS off for `users`. Rejected: it removes the guarantee everywhere
     else in the app, to solve a problem that exists on one code path.
  2. Have the login path set `app.is_super_admin = on` for its transaction.
     Rejected: that is a bypass switch living in application code, and any
     future bug that leaves it set is a full cross-tenant read.
  3. Expose one SECURITY DEFINER function that returns only the columns
     authentication actually needs, for exactly one user at a time.

This migration implements (3). The function is owned by the table owner, so it
runs with rights to read the table, but it cannot be used to enumerate: it
takes an exact id or an exact lowercased email and returns at most one row.
Password hashes are returned because verification happens in the application;
nothing else sensitive is.
"""

from __future__ import annotations

from alembic import op

revision = "0002_auth_lookup"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
            mfa_enabled          boolean,
            mfa_secret_encrypted varchar,
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
                u.mfa_enabled, u.mfa_secret_encrypted,
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
    # Revoke from PUBLIC first: SECURITY DEFINER functions are executable by
    # everyone by default, which would hand the bypass to any future role.
    op.execute("REVOKE ALL ON FUNCTION facet_auth_principal(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION facet_auth_principal(uuid, text) TO facet_app")

    # Counter updates on the login path have the same bootstrapping problem:
    # they must happen before a tenant is bound. Scoped to exactly the columns
    # that lockout needs, so it cannot be repurposed to edit a user.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_auth_record_attempt(
            p_user_id      uuid,
            p_succeeded    boolean,
            p_lock_seconds integer,
            p_max_attempts integer
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF p_succeeded THEN
                UPDATE users
                   SET failed_login_count = 0,
                       locked_until       = NULL,
                       last_login_at      = now()
                 WHERE id = p_user_id;
            ELSE
                UPDATE users
                   SET failed_login_count = failed_login_count + 1,
                       locked_until = CASE
                           WHEN failed_login_count + 1 >= p_max_attempts
                           THEN now() + make_interval(secs => p_lock_seconds)
                           ELSE locked_until
                       END
                 WHERE id = p_user_id;
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION facet_auth_record_attempt(uuid, boolean, integer, integer) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION facet_auth_record_attempt(uuid, boolean, integer, integer) "
        "TO facet_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS facet_auth_record_attempt(uuid, boolean, integer, integer)"
    )
    op.execute("DROP FUNCTION IF EXISTS facet_auth_principal(uuid, text)")
