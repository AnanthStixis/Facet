BEGIN;

-- Running upgrade 0019_fix_auth_principal_mfa -> 0020_masters_and_phone

ALTER TABLE users ADD COLUMN phone VARCHAR(30);

CREATE TABLE departments (
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    org_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    created_by_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_departments PRIMARY KEY (id), 
    CONSTRAINT fk_departments_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    CONSTRAINT fk_departments_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_departments_org_id ON departments (org_id);

CREATE UNIQUE INDEX uq_departments_org_name ON departments (org_id, name);

ALTER TABLE departments ENABLE ROW LEVEL SECURITY;

ALTER TABLE departments FORCE ROW LEVEL SECURITY;

CREATE POLICY departments_tenant_isolation ON departments USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on') WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');

CREATE TABLE job_titles (
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    org_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    created_by_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_job_titles PRIMARY KEY (id), 
    CONSTRAINT fk_job_titles_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    CONSTRAINT fk_job_titles_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_job_titles_org_id ON job_titles (org_id);

CREATE UNIQUE INDEX uq_job_titles_org_name ON job_titles (org_id, name);

ALTER TABLE job_titles ENABLE ROW LEVEL SECURITY;

ALTER TABLE job_titles FORCE ROW LEVEL SECURITY;

CREATE POLICY job_titles_tenant_isolation ON job_titles USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on') WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');

CREATE TABLE cycle_names (
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    org_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    created_by_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cycle_names PRIMARY KEY (id), 
    CONSTRAINT fk_cycle_names_org_id_organizations FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    CONSTRAINT fk_cycle_names_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_cycle_names_org_id ON cycle_names (org_id);

CREATE UNIQUE INDEX uq_cycle_names_org_name ON cycle_names (org_id, name);

ALTER TABLE cycle_names ENABLE ROW LEVEL SECURITY;

ALTER TABLE cycle_names FORCE ROW LEVEL SECURITY;

CREATE POLICY cycle_names_tenant_isolation ON cycle_names USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on') WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app;

UPDATE alembic_version SET version_num='0020_masters_and_phone' WHERE alembic_version.version_num = '0019_fix_auth_principal_mfa';

COMMIT;

