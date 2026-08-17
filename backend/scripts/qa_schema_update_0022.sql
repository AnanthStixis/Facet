-- Schema change to deploy to QA: the Product and Service master tables.
--
-- This is the SQL equivalent of Alembic migration 0022_products_services
-- (backend/alembic/versions/0022_products_services.py) — same pattern as
-- departments/job_titles/cycle_names, a simple org-scoped name list with
-- RLS, picked from a dropdown on the Product/Service review forms in
-- Create Feedback.
--
-- Tested end-to-end on local dev via `alembic upgrade head` /
-- `alembic downgrade -1` / `alembic upgrade head` before writing this file —
-- both directions apply cleanly.
--
-- Idempotent (IF NOT EXISTS / existence-guarded), so safe to run again if
-- an earlier attempt partially applied — same lesson as the 2026-08-17
-- combined deploy script, where an unguarded step failed partway through.
--
-- IMPORTANT: run this with a role that owns these tables (the app's normal
-- runtime role does not have DDL privileges) — e.g. the same `postgres`
-- role used for prior QA migrations.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_schema_update_0022.sql
--
-- If you deploy by running `alembic upgrade head` on QA instead, you do not
-- need this file at all; it exists only for deploying the schema change
-- directly via psql without going through the app's migration tooling.

BEGIN;

CREATE TABLE IF NOT EXISTS products (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    org_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    created_by_id UUID,
    is_active BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_products PRIMARY KEY (id),
    CONSTRAINT fk_products_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_products_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_products_org_id ON products (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_org_name ON products (org_id, name);

ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'products' AND policyname = 'products_tenant_isolation') THEN
        CREATE POLICY products_tenant_isolation ON products
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS services (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    org_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    created_by_id UUID,
    is_active BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_services PRIMARY KEY (id),
    CONSTRAINT fk_services_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_services_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_services_org_id ON services (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_services_org_name ON services (org_id, name);

ALTER TABLE services ENABLE ROW LEVEL SECURITY;
ALTER TABLE services FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'services' AND policyname = 'services_tenant_isolation') THEN
        CREATE POLICY services_tenant_isolation ON services
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app;

UPDATE alembic_version SET version_num = '0022_products_services'
WHERE version_num = '0021_contacts_phone_master_flag';

COMMIT;

-- Sanity check.
SELECT version_num FROM alembic_version;
