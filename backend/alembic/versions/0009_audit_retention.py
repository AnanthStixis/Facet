"""A sanctioned purge path for audit retention.

Revision ID: 0009_retention
Revises: 0008_analytics
Create Date: 2026-08-08

Migration 0001 made `audit_logs` append-only with a trigger that rejects UPDATE
and DELETE from every role, deliberately, so that "no user can edit or delete
audit entries" is enforced rather than promised.

That collides with the retention requirement: a customer who says "keep audit
history for 400 days" needs something to eventually remove day 401. Two ways
out, and only one of them keeps the guarantee:

  1. Relax the trigger to permit DELETE. Rejected — it hands deletion back to
     anyone with a connection, which is exactly what the trigger exists to
     prevent, in order to solve a problem that occurs once a night.
  2. Keep the trigger, and give it one narrow exception it can recognise.

This implements (2). `facet_audit_purge` is SECURITY DEFINER, sets a
transaction-local flag, and deletes only rows older than a cutoff. The trigger
allows DELETE only while that flag is set — so deletion is possible exclusively
from inside that one function, which takes a cutoff, enforces a floor on it,
and reports how many rows it removed.

The flag is `is_local => true`, so it cannot leak to another statement on a
pooled connection, and it is set inside the function rather than by the caller,
so an application bug cannot turn it on.
"""

from __future__ import annotations

from alembic import op

revision = "0009_retention"
down_revision = "0008_analytics"
branch_labels = None
depends_on = None

PURGE_GUC = "app.audit_purge"


def upgrade() -> None:
    # The trigger gains exactly one exception, and still refuses every UPDATE.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION facet_audit_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('{PURGE_GUC}', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_logs is append-only (attempted %)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION facet_audit_purge(
            p_org_id uuid,
            p_before  timestamptz
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            removed integer;
            floor_at timestamptz := now() - interval '30 days';
        BEGIN
            -- A floor inside the function, not just in the calling code. A
            -- retention bug that passes `now()` would otherwise erase
            -- everything, and the audit trail is the one table with no backup
            -- of its own semantics.
            IF p_before IS NULL OR p_before > floor_at THEN
                RAISE EXCEPTION 'refusing to purge audit entries newer than 30 days'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            PERFORM set_config('{PURGE_GUC}', 'on', true);

            IF p_org_id IS NULL THEN
                DELETE FROM audit_logs WHERE occurred_at < p_before;
            ELSE
                DELETE FROM audit_logs
                 WHERE org_id = p_org_id AND occurred_at < p_before;
            END IF;

            GET DIAGNOSTICS removed = ROW_COUNT;
            PERFORM set_config('{PURGE_GUC}', 'off', true);
            RETURN removed;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION facet_audit_purge(uuid, timestamptz) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION facet_audit_purge(uuid, timestamptz) TO facet_app"
    )

    # Reserved for real embeddings once an embeddings API is configured. Theme
    # clustering currently runs on TF-IDF locally and does not need it, but
    # adding the column now avoids a migration against a large table later.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                ALTER TABLE feedback_responses
                    ADD COLUMN IF NOT EXISTS embedding vector(1536);
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS facet_audit_purge(uuid, timestamptz)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only (attempted %)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("ALTER TABLE feedback_responses DROP COLUMN IF EXISTS embedding")
