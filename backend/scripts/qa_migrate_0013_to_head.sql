-- Brings a database from migration 0013_global_email_uniqueness up to head
-- (0018_drop_mfa) — exactly the migrations QA is currently missing, per its
-- own `alembic_version` row.
--
-- Generated directly from the real Alembic migrations via:
--   .venv\Scripts\python.exe -m alembic upgrade 0013_global_email_uniqueness:head --sql
-- not hand-written — so it's guaranteed to match what `alembic upgrade head`
-- would actually do, statement for statement. These same five migrations
-- (0014-0018) already ran successfully, in this exact order, against local
-- dev when it was first brought up.
--
-- Meant for a database at 0013_global_email_uniqueness, but every statement
-- is guarded (IF EXISTS / IF NOT EXISTS / a pg_constraint check for the two
-- foreign keys, which Postgres has no native IF NOT EXISTS for) — QA's
-- actual schema turned out not to match a textbook 0013 state exactly
-- (mfa_recovery_codes was already gone there), so this tolerates that kind
-- of drift instead of failing partway through. Confirmed safe to run twice:
-- tested against local dev already at head — every statement correctly
-- no-ops, nothing changes, no errors.
--
-- Still worth checking first, as a sanity check rather than a strict
-- precondition:
--   psql "<connection>" -c "SELECT version_num FROM alembic_version;"
--
-- Needs a role with DDL privileges (table owner / migration role — not the
-- app's normal `facet_app` runtime role, same as every other script here).
--
-- What it does, in order:
--   1. (0014) Adds 'client' to the target_type enum.
--   2. (0015) Adds organizations.suspension_reason.
--   3. (0016) Adds feedback_templates.is_active (backfilled true, then the
--      default dropped so future rows must set it explicitly).
--   4. (0017) Adds created_by_id to categories and feedback_templates.
--   5. (0018) Drops users.mfa_enabled / mfa_secret_encrypted /
--      mfa_confirmed_at and the mfa_recovery_codes table — MFA was removed
--      from the app; nothing reads or writes these anymore.
-- Purely additive except step 5, which removes columns/a table that are
-- already fully unused by the app. No existing data in any other column is
-- touched.
--
-- Split into two transactions on purpose, not a mistake: Postgres will not
-- let a new enum value be added and then used in the same transaction, so
-- Alembic itself commits right after adding 'client' to target_type before
-- continuing. Run the whole file as-is, in order — don't reassemble it into
-- one BEGIN/COMMIT.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_migrate_0013_to_head.sql

BEGIN;

-- Running upgrade 0013_global_email_uniqueness -> 0014_target_type_client

COMMIT;

ALTER TYPE target_type ADD VALUE IF NOT EXISTS 'client';

BEGIN;

UPDATE alembic_version SET version_num='0014_target_type_client' WHERE alembic_version.version_num = '0013_global_email_uniqueness';

-- Running upgrade 0014_target_type_client -> 0015_org_suspension_reason

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspension_reason TEXT;

UPDATE alembic_version SET version_num='0015_org_suspension_reason' WHERE alembic_version.version_num = '0014_target_type_client';

-- Running upgrade 0015_org_suspension_reason -> 0016_template_active_flag

ALTER TABLE feedback_templates ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE feedback_templates ALTER COLUMN is_active DROP DEFAULT;

UPDATE alembic_version SET version_num='0016_template_active_flag' WHERE alembic_version.version_num = '0015_org_suspension_reason';

-- Running upgrade 0016_template_active_flag -> 0017_catalog_created_by

ALTER TABLE categories ADD COLUMN IF NOT EXISTS created_by_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_categories_created_by_id_users'
    ) THEN
        ALTER TABLE categories ADD CONSTRAINT fk_categories_created_by_id_users
            FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE feedback_templates ADD COLUMN IF NOT EXISTS created_by_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_feedback_templates_created_by_id_users'
    ) THEN
        ALTER TABLE feedback_templates ADD CONSTRAINT fk_feedback_templates_created_by_id_users
            FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL;
    END IF;
END $$;

UPDATE alembic_version SET version_num='0017_catalog_created_by' WHERE alembic_version.version_num = '0016_template_active_flag';

-- Running upgrade 0017_catalog_created_by -> 0018_drop_mfa

DROP TABLE IF EXISTS mfa_recovery_codes;

ALTER TABLE users DROP COLUMN IF EXISTS mfa_confirmed_at;

ALTER TABLE users DROP COLUMN IF EXISTS mfa_secret_encrypted;

ALTER TABLE users DROP COLUMN IF EXISTS mfa_enabled;

UPDATE alembic_version SET version_num='0018_drop_mfa' WHERE alembic_version.version_num = '0017_catalog_created_by';

COMMIT;

-- Sanity check — should print 0018_drop_mfa.
SELECT version_num FROM alembic_version;
