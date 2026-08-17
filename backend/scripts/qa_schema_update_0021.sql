-- Schema changes to deploy to QA: contacts.phone, and is_active on the
-- Department/Job Title/Cycle Name master tables.
--
-- This is the SQL equivalent of Alembic migration
-- 0021_contacts_phone_master_flag
-- (backend/alembic/versions/0021_contacts_phone_master_flag.py). Additive
-- only — is_active backs the enable/disable toggle on master rows, phone
-- backs the new Client phone field.
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
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_schema_update_0021.sql
--
-- If you deploy by running `alembic upgrade head` on QA instead, you do not
-- need this file at all; it exists only for deploying the schema change
-- directly via psql without going through the app's migration tooling.

BEGIN;

ALTER TABLE contacts ADD COLUMN phone VARCHAR(30);

ALTER TABLE departments ADD COLUMN is_active BOOLEAN DEFAULT true NOT NULL;
ALTER TABLE job_titles ADD COLUMN is_active BOOLEAN DEFAULT true NOT NULL;
ALTER TABLE cycle_names ADD COLUMN is_active BOOLEAN DEFAULT true NOT NULL;

UPDATE alembic_version SET version_num = '0021_contacts_phone_master_flag'
WHERE version_num = '0020_masters_and_phone';

COMMIT;
