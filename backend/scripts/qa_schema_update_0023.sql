-- Schema change to deploy to QA: the user_managers junction table
-- (Employee <-> Manager many-to-many).
--
-- This is the SQL equivalent of Alembic migration 0023_user_managers
-- (backend/alembic/versions/0023_user_managers.py). `users.manager_id` is a
-- single FK and cannot represent someone who reports to 2-3 managers at
-- once. This adds a proper junction table and backfills it with every
-- existing single manager_id relationship, so upgrading changes nothing
-- about who currently gets a downward review — only the storage.
-- `users.manager_id` itself is left in place, unused going forward, rather
-- than dropped: a dormant column is a far safer migration than a
-- destructive one.
--
-- Tested end-to-end on local dev via `alembic upgrade head` /
-- `alembic downgrade -1` / `alembic upgrade head` before writing this file
-- — both directions apply cleanly.
--
-- Idempotent (IF NOT EXISTS / existence-guarded throughout, backfill
-- guarded against re-inserting), so safe to run again if an earlier
-- attempt partially applied.
--
-- IMPORTANT: run this with a role that owns these tables (the app's normal
-- runtime role does not have DDL privileges) — e.g. the same `postgres`
-- role used for prior QA migrations.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_schema_update_0023.sql
--
-- If you deploy by running `alembic upgrade head` on QA instead, you do not
-- need this file at all; it exists only for deploying the schema change
-- directly via psql without going through the app's migration tooling.

BEGIN;

CREATE TABLE IF NOT EXISTS user_managers (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    org_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    manager_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_user_managers PRIMARY KEY (id),
    CONSTRAINT fk_user_managers_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_managers_employee_id_users FOREIGN KEY(employee_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_managers_manager_id_users FOREIGN KEY(manager_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_user_managers_org_id ON user_managers (org_id);
CREATE INDEX IF NOT EXISTS ix_user_managers_employee_id ON user_managers (employee_id);
CREATE INDEX IF NOT EXISTS ix_user_managers_manager_id ON user_managers (manager_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_managers_employee_manager ON user_managers (employee_id, manager_id);

ALTER TABLE user_managers ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_managers FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'user_managers' AND policyname = 'user_managers_tenant_isolation') THEN
        CREATE POLICY user_managers_tenant_isolation ON user_managers
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

-- Backfill every existing single manager_id relationship, skipping any pair
-- already present (e.g. from a previous partial run of this script).
INSERT INTO user_managers (id, org_id, employee_id, manager_id, created_at, updated_at)
SELECT gen_random_uuid(), u.org_id, u.id, u.manager_id, now(), now()
FROM users u
WHERE u.manager_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM user_managers um
      WHERE um.employee_id = u.id AND um.manager_id = u.manager_id
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app;

UPDATE alembic_version SET version_num = '0023_user_managers'
WHERE version_num = '0022_products_services';

COMMIT;

-- Sanity checks.
SELECT version_num FROM alembic_version;
SELECT count(*) AS user_manager_rows FROM user_managers;
