"""Append-only audit writer.

Revision ID: 0003_audit_append
Revises: 0002_auth_lookup
Create Date: 2026-08-07

Some audit entries are written before a tenant is known, and some belong to no
tenant at all:

  * a failed sign-in for an address that matches no account
  * a self-service organization registration, which happens anonymously
  * platform-level actions by a Super Admin, whose org_id is NULL

Row level security correctly refuses those inserts, because the transaction has
no tenant bound and a NULL org_id matches no policy. Loosening the policy to
permit NULL org_id inserts would let any tenant forge platform-level entries in
the one table the whole compliance story rests on.

Instead, writes go through this SECURITY DEFINER function. It can do exactly
one thing - append a row - and nothing else: it cannot read the table, cannot
update it, and cannot touch any other table. Reads still go through RLS, so a
Client Admin's audit page remains scoped to their own organization.

The append-only trigger from migration 0001 still applies, because triggers
fire regardless of definer rights. There is no path, for any role, that edits
or deletes an audit entry.
"""

from __future__ import annotations

from alembic import op

revision = "0003_audit_append"
down_revision = "0002_auth_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_audit_append(
            p_org_id       uuid,
            p_action       text,
            p_severity     audit_severity,
            p_actor_id     uuid,
            p_actor_email  text,
            p_actor_name   text,
            p_actor_role   text,
            p_target_type  text,
            p_target_id    uuid,
            p_target_label text,
            p_summary      text,
            p_context      jsonb,
            p_ip_address   inet,
            p_user_agent   text,
            p_request_id   text,
            p_occurred_at  timestamptz
        ) RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            INSERT INTO audit_logs (
                org_id, action, severity, actor_id, actor_email, actor_name,
                actor_role, target_type, target_id, target_label, summary,
                context, ip_address, user_agent, request_id, occurred_at
            ) VALUES (
                p_org_id, p_action, p_severity, p_actor_id, p_actor_email,
                p_actor_name, p_actor_role, p_target_type, p_target_id,
                p_target_label, p_summary, COALESCE(p_context, '{}'::jsonb),
                p_ip_address, p_user_agent, p_request_id,
                COALESCE(p_occurred_at, now())
            )
            RETURNING id;
        $$
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION facet_audit_append(
            uuid, text, audit_severity, uuid, text, text, text, text, uuid,
            text, text, jsonb, inet, text, text, timestamptz
        ) FROM PUBLIC
        """
    )
    op.execute(
        """
        GRANT EXECUTE ON FUNCTION facet_audit_append(
            uuid, text, audit_severity, uuid, text, text, text, text, uuid,
            text, text, jsonb, inet, text, text, timestamptz
        ) TO facet_app
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS facet_audit_append(
            uuid, text, audit_severity, uuid, text, text, text, text, uuid,
            text, text, jsonb, inet, text, text, timestamptz
        )
        """
    )
