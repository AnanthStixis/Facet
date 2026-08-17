-- Schema changes to deploy to QA: drop the MFA columns and the
-- mfa_recovery_codes table.
--
-- This is the SQL equivalent of Alembic migration 0018_drop_mfa
-- (backend/alembic/versions/0018_drop_mfa.py). Multi-factor auth was fully
-- removed from the application this session — nothing reads or writes these
-- columns/table anymore. They were left in place at the time as harmless
-- dead data, but this drops them for real now that the change is going
-- somewhere beyond local dev.
--
-- Tested end-to-end on local dev via `alembic upgrade head` /
-- `alembic downgrade -1` / `alembic upgrade head` before writing this file —
-- both directions apply cleanly.
--
-- IMPORTANT: run this with a role that owns these tables (the app's normal
-- runtime role does not have DDL privileges) — e.g. the same `postgres`
-- role used for migrations, not the `facet_app` role the API server
-- connects as.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_schema_update_0018.sql
--
-- If you deploy by running `alembic upgrade head` on QA instead (the normal
-- path — see backend/alembic/versions/0018_drop_mfa.py), you do not need
-- this file at all; it exists only for deploying the schema change directly
-- via psql without going through the app's migration tooling.

BEGIN;

DROP TABLE mfa_recovery_codes;

ALTER TABLE users DROP COLUMN mfa_confirmed_at;
ALTER TABLE users DROP COLUMN mfa_secret_encrypted;
ALTER TABLE users DROP COLUMN mfa_enabled;

-- Record this as applied, so a later `alembic upgrade head` on this same
-- database recognizes it's already done and doesn't try to re-run it.
UPDATE alembic_version SET version_num = '0018_drop_mfa' WHERE version_num = '0017_catalog_created_by';

COMMIT;

-- Sanity check — should show no mfa_* columns and no mfa_recovery_codes table.
SELECT column_name FROM information_schema.columns
WHERE table_name = 'users' AND column_name LIKE 'mfa%';
SELECT tablename FROM pg_tables WHERE tablename = 'mfa_recovery_codes';
