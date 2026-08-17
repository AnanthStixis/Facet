-- URGENT hotfix: fixes login, currently broken on QA.
--
-- Root cause: migration 0018_drop_mfa (applied via qa_migrate_0013_to_head.sql)
-- dropped users.mfa_enabled / mfa_secret_encrypted, but the
-- facet_auth_principal() SECURITY DEFINER function (from migration
-- 0002_auth_lookup) still explicitly selected those two columns by name.
-- Every login — the very first thing that function is used for — started
-- failing with:
--   UndefinedColumnError: column u.mfa_enabled does not exist
-- My mistake: I verified 0018 with an alembic upgrade/downgrade round-trip
-- but never actually re-tested a real login afterward, so this shipped to
-- QA without being caught first. It has now been reproduced and fixed on
-- local dev, and a real login (through the app's own facet_app role, not a
-- superuser) was tested and confirmed working before writing this file.
--
-- This is migration 0019_fix_auth_principal_mfa
-- (backend/alembic/versions/0019_fix_auth_principal_mfa.py), exported the
-- same way as qa_migrate_0013_to_head.sql — generated directly from the
-- real migration via `alembic upgrade 0018_drop_mfa:head --sql`, not
-- hand-written.
--
-- Purely a function replacement — no data is touched, nothing is dropped.
-- Safe to run immediately.
--
-- Needs a role with DDL privileges (same as every other script here — not
-- the app's normal facet_app runtime role).
--
-- The GRANT near the end assumes the app's runtime role is named
-- `facet_app`, matching local dev — check that's actually QA's role name
-- before running; if it's different, adjust that one line.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_hotfix_0019_login.sql

BEGIN;

DROP FUNCTION IF EXISTS facet_auth_principal(uuid, text);

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
$$;

REVOKE ALL ON FUNCTION facet_auth_principal(uuid, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION facet_auth_principal(uuid, text) TO facet_app;

UPDATE alembic_version SET version_num='0019_fix_auth_principal_mfa' WHERE alembic_version.version_num = '0018_drop_mfa';

COMMIT;

-- Sanity check — should print 0019_fix_auth_principal_mfa.
SELECT version_num FROM alembic_version;
