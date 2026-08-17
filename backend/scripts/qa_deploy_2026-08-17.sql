-- Combined QA deploy script — everything needed to bring QA's database up
-- to date with local dev as of 2026-08-17.
--
-- Checked against QA directly before writing this file:
--   SELECT version_num FROM alembic_version;        -> 0019_fix_auth_principal_mfa
--   SELECT name, target_type FROM feedback_templates
--     WHERE org_id IS NULL;                          -> 7 old default templates present
--
-- Revision note: the first version of this script hard-deleted every old
-- default template unconditionally and failed on QA — one of them
-- ("Default Client Feedback") is still referenced by a real review_cycle
-- there, and feedback_template_versions.id is ON DELETE RESTRICT from
-- review_cycles.template_version_id for exactly this reason. Step 2 below
-- now checks first: any old template still in use is deactivated
-- (is_active = false, matching the same non-destructive pattern
-- app/seed_templates.py already uses) instead of deleted, so history is
-- never orphaned. Everything else about this script is unchanged.
--
-- Every DDL and DML statement below is guarded (IF NOT EXISTS / NOT
-- EXISTS / existence checks), so the ENTIRE file is safe to run again from
-- scratch no matter how much of a previous attempt already succeeded —
-- including this exact scenario, where step 1 already completed on QA
-- before step 2 failed.
--
-- Three steps, each its own transaction:
--   1. Schema — migrations 0020_masters_and_phone and 0021_contacts_phone_master_flag.
--   2. Data — retire the old vendor default template catalog: deactivate
--      any still referenced by a real review_cycle, hard-delete the rest.
--   3. Data — insert the six reference-form templates (Employee/Management/
--      Client/Product/Service/Proposal review), transcribed verbatim from
--      the client's own reference forms.
--
-- Run with a role that owns these tables (the app's runtime role,
-- facet_app, does not have DDL privileges) — e.g. the same `postgres` role
-- used for prior QA migrations.
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_deploy_2026-08-17.sql


-- =============================================================================
-- Step 1 of 3: schema (migrations 0020 + 0021) — idempotent
-- =============================================================================

BEGIN;

-- --- 0019 -> 0020: users.phone, and the Department/Job Title/Cycle Name
-- master tables ---------------------------------------------------------

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);

CREATE TABLE IF NOT EXISTS departments (
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

CREATE INDEX IF NOT EXISTS ix_departments_org_id ON departments (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_departments_org_name ON departments (org_id, name);

ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE departments FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'departments' AND policyname = 'departments_tenant_isolation') THEN
        CREATE POLICY departments_tenant_isolation ON departments
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS job_titles (
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

CREATE INDEX IF NOT EXISTS ix_job_titles_org_id ON job_titles (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_job_titles_org_name ON job_titles (org_id, name);

ALTER TABLE job_titles ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_titles FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'job_titles' AND policyname = 'job_titles_tenant_isolation') THEN
        CREATE POLICY job_titles_tenant_isolation ON job_titles
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS cycle_names (
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

CREATE INDEX IF NOT EXISTS ix_cycle_names_org_id ON cycle_names (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cycle_names_org_name ON cycle_names (org_id, name);

ALTER TABLE cycle_names ENABLE ROW LEVEL SECURITY;
ALTER TABLE cycle_names FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'cycle_names' AND policyname = 'cycle_names_tenant_isolation') THEN
        CREATE POLICY cycle_names_tenant_isolation ON cycle_names
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on')
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid OR current_setting('app.is_super_admin', true) = 'on');
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app;

UPDATE alembic_version SET version_num = '0020_masters_and_phone'
WHERE version_num = '0019_fix_auth_principal_mfa';

-- --- 0020 -> 0021: contacts.phone, and is_active on the three master
-- tables ------------------------------------------------------------------

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone VARCHAR(30);

ALTER TABLE departments ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;
ALTER TABLE job_titles ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;
ALTER TABLE cycle_names ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;

UPDATE alembic_version SET version_num = '0021_contacts_phone_master_flag'
WHERE version_num = '0020_masters_and_phone';

COMMIT;


-- =============================================================================
-- Step 2 of 3: retire the old default template catalog (org_id IS NULL)
--
-- Any old template still referenced by a real review_cycle is deactivated,
-- not deleted — feedback_template_versions.id is ON DELETE RESTRICT from
-- review_cycles.template_version_id, so a cycle that actually used one of
-- these must keep it. Everything unreferenced is hard-deleted. Safe to run
-- again: deactivating an already-inactive row, or deleting an already-gone
-- one, are both no-ops.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    tmpl RECORD;
    still_used boolean;
BEGIN
    FOR tmpl IN SELECT id, name FROM feedback_templates WHERE org_id IS NULL LOOP
        SELECT EXISTS (
            SELECT 1
            FROM review_cycles rc
            JOIN feedback_template_versions ftv ON ftv.id = rc.template_version_id
            WHERE ftv.template_id = tmpl.id
        ) INTO still_used;

        IF still_used THEN
            UPDATE feedback_templates SET is_active = false WHERE id = tmpl.id;
            RAISE NOTICE 'Deactivated (still in use by a review cycle): %', tmpl.name;
        ELSE
            DELETE FROM feedback_template_versions WHERE template_id = tmpl.id;
            DELETE FROM feedback_templates WHERE id = tmpl.id;
            RAISE NOTICE 'Deleted (unused): %', tmpl.name;
        END IF;
    END LOOP;

    -- A vendor category with no templates left under it (all deleted, none
    -- deactivated-and-kept) is safe to remove too.
    DELETE FROM categories c
    WHERE c.org_id IS NULL
      AND NOT EXISTS (SELECT 1 FROM feedback_templates t WHERE t.category_id = c.id);
END $$;

COMMIT;


-- =============================================================================
-- Step 3 of 3: insert the six reference-form templates — idempotent
-- (NOT EXISTS guarded)
-- =============================================================================

BEGIN;

DO $$
DECLARE
    cat_internal_360_id uuid;
    cat_client_experience_id uuid;
    cat_proposal_quality_id uuid;
    tmpl_id uuid;
BEGIN

    -- --- Category: Internal 360 ---
    SELECT id INTO cat_internal_360_id FROM categories WHERE key = 'internal_360' AND org_id IS NULL;
    IF cat_internal_360_id IS NULL THEN
        INSERT INTO categories (
            id, org_id, key, name, description, applies_to, icon, sort_order,
            is_enabled, created_at, updated_at, created_by_id
        ) VALUES (
            gen_random_uuid(), NULL,
            'internal_360',
            'Internal 360',
            'Manager, upward, downward, and peer feedback inside the organization.',
            '["employee", "manager", "team", "department"]'::jsonb,
            'users',
            10,
            true, now(), now(), NULL
        ) RETURNING id INTO cat_internal_360_id;
    END IF;

    -- --- Category: Client experience ---
    SELECT id INTO cat_client_experience_id FROM categories WHERE key = 'client_experience' AND org_id IS NULL;
    IF cat_client_experience_id IS NULL THEN
        INSERT INTO categories (
            id, org_id, key, name, description, applies_to, icon, sort_order,
            is_enabled, created_at, updated_at, created_by_id
        ) VALUES (
            gen_random_uuid(), NULL,
            'client_experience',
            'Client experience',
            'How clients and customers rate your products, services and people.',
            '["product", "service", "employee", "client"]'::jsonb,
            'handshake',
            40,
            true, now(), now(), NULL
        ) RETURNING id INTO cat_client_experience_id;
    END IF;

    -- --- Category: Proposal quality ---
    SELECT id INTO cat_proposal_quality_id FROM categories WHERE key = 'proposal_quality' AND org_id IS NULL;
    IF cat_proposal_quality_id IS NULL THEN
        INSERT INTO categories (
            id, org_id, key, name, description, applies_to, icon, sort_order,
            is_enabled, created_at, updated_at, created_by_id
        ) VALUES (
            gen_random_uuid(), NULL,
            'proposal_quality',
            'Proposal quality',
            'Structured prospect feedback on proposals and statements of work.',
            '["proposal"]'::jsonb,
            'file-text',
            50,
            true, now(), now(), NULL
        ) RETURNING id INTO cat_proposal_quality_id;
    END IF;

    -- --- Employee review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Employee review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_internal_360_id, 'global',
            'Employee review',
            'Technical, communication, and delivery ratings for one employee, plus an overall score.',
            'employee', false, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the employee's technical / job-related skills?", "type": "scale"}, {"key": "technical_2", "text": "How effectively does the employee apply their knowledge to solve problems?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How effectively does the employee communicate with team members and stakeholders?", "type": "scale"}, {"key": "communication_2", "text": "How well does the employee collaborate within the team?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How consistently does the employee meet deadlines and follow processes?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please provide additional feedback on the employee's overall performance.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;

    -- --- Management review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Management review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_internal_360_id, 'global',
            'Management review',
            'Technical, communication, and delivery ratings for a manager from their direct reports, plus an overall score.',
            'manager', true, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the manager's domain / technical knowledge?", "type": "scale"}, {"key": "technical_2", "text": "How effectively does the manager provide technical guidance and support decision-making?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How clearly does the manager communicate goals, expectations, and feedback?", "type": "scale"}, {"key": "communication_2", "text": "How approachable and open is the manager to team input?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How well does the manager ensure timely delivery and maintain team discipline?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please share additional comments on the manager's leadership.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;

    -- --- Client review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Client review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_client_experience_id, 'global',
            'Client review',
            'A client''s technical, communication, and delivery ratings for the team member they work with, plus an overall score.',
            'client', false, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the technical expertise demonstrated by the team member?", "type": "scale"}, {"key": "technical_2", "text": "How well did the team member understand and address your project requirements?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How clear and timely was the team member's communication with you?", "type": "scale"}, {"key": "communication_2", "text": "How responsive was the team member to your queries and concerns?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How would you rate the team member's adherence to deadlines and commitments?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please share any additional comments or suggestions for the team member.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;

    -- --- Product review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Product review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_client_experience_id, 'global',
            'Product review',
            'Technical quality, documentation, and delivery ratings for a product, plus an overall score.',
            'product', false, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the technical quality and functionality of the product?", "type": "scale"}, {"key": "technical_2", "text": "How reliable and bug-free is the product in daily use?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How clear and helpful is the product documentation / user guidance?", "type": "scale"}, {"key": "communication_2", "text": "How effective is the communication of updates and changes to users?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How would you rate the product's release / update timeliness and quality control?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please share suggestions for improving the product.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;

    -- --- Service review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Service review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_client_experience_id, 'global',
            'Service review',
            'Technical competency, communication, and delivery ratings for a service engagement, plus an overall score.',
            'service', false, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the technical competency of the service provided?", "type": "scale"}, {"key": "technical_2", "text": "How effectively were your issues / requests resolved?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How clear and courteous was the communication during service delivery?", "type": "scale"}, {"key": "communication_2", "text": "How responsive was the service team to your inquiries?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How would you rate the timeliness and consistency of the service delivery?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please share any additional comments about the service experience.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;

    -- --- Proposal review ---
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Proposal review' AND org_id IS NULL) THEN
        INSERT INTO feedback_templates (
            id, org_id, category_id, scope, name, description, target_type,
            is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, cat_proposal_quality_id, 'global',
            'Proposal review',
            'Technical soundness, clarity, and delivery-plan ratings for a submitted proposal or SOW, plus an overall score.',
            'proposal', false, 4, true, now(), now()
        ) RETURNING id INTO tmpl_id;
        INSERT INTO feedback_template_versions (
            id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), NULL, tmpl_id, 1, 'published',
            $def${"schema_version": 1, "intro": "Rate each item on a scale of 1 to 5.", "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}, "sections": [{"key": "technical", "title": "Technical", "questions": [{"key": "technical_1", "text": "How would you rate the technical feasibility and soundness of the proposal?", "type": "scale"}, {"key": "technical_2", "text": "How well does the proposal address the stated requirements / objectives?", "type": "scale"}]}, {"key": "communication", "title": "Communication", "questions": [{"key": "communication_1", "text": "How clearly is the proposal written and presented?", "type": "scale"}, {"key": "communication_2", "text": "How effectively were questions / clarifications addressed during discussions?", "type": "scale"}]}, {"key": "delivery", "title": "Delivery & Discipline", "questions": [{"key": "delivery_1", "text": "How realistic and well-structured is the proposed timeline and delivery plan?", "type": "scale"}]}, {"key": "overall", "title": "Overall Rating", "questions": [{"key": "overall_1", "text": "Overall Rating", "type": "scale"}]}], "closing": {"comment_prompt": "Please share additional comments or recommendations regarding the proposal.", "comment_required": false}}$def$::jsonb,
            now(), now(), now()
        );
    END IF;
END $$;

COMMIT;


-- =============================================================================
-- Sanity checks — run these after, confirm the output looks right
-- =============================================================================

SELECT version_num FROM alembic_version;

SELECT name, target_type, is_active FROM feedback_templates WHERE org_id IS NULL ORDER BY is_active, name;

SELECT count(*) AS department_rows FROM departments;
SELECT count(*) AS job_title_rows FROM job_titles;
SELECT count(*) AS cycle_name_rows FROM cycle_names;
