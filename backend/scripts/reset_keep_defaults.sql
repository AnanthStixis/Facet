-- Wipes every table in the Facet database EXCEPT the global (org_id IS
-- NULL) category and template catalog, and leaves one fresh Super Admin
-- login behind.
--
-- Difference from reset_all_data.sql / reset_all_data.py: those wipe the
-- catalog too and need a separate reseed step afterward. This one preserves
-- whatever global categories/templates/template-versions already exist in
-- the database exactly as they are (including anything added by hand
-- through the app, not just what app/seed.py would create), so the app is
-- immediately usable — Create Feedback has templates to pick — with no
-- second step.
--
-- Schema-version tolerant on purpose: this is meant to run against a server
-- whose exact migration state may not match local dev (e.g. QA a few
-- migrations behind). `created_by_id` (added in 0017_catalog_created_by)
-- and `mfa_recovery_codes` (dropped in 0018_drop_mfa) are both handled
-- conditionally below rather than assumed present/absent — the script works
-- either way instead of failing on a column or table that doesn't exist yet
-- on that particular server.
--
-- Irreversible. Every organization, user, contact, cycle, campaign,
-- response, and audit record is gone for good. What's left afterwards:
--   - One Super Admin:
--       email:    admin@stixis.com
--       password: FacetPlatform!2026
--     (a fresh row — not whatever Super Admin existed before)
--   - Every global category and template, unchanged (creator attribution
--     cleared to NULL where that column exists, since the users who
--     created them no longer exist after the wipe).
--   - Any org-scoped category or template (org_id IS NOT NULL) is gone
--     along with the organization it belonged to.
--   - Nothing else.
--
-- Usage:
--   psql "postgresql://<user>:<password>@<host>:5432/<database>" -f reset_keep_defaults.sql
--
-- The password hash below is a real argon2id hash of "FacetPlatform!2026",
-- generated the same way app/core/security.py:hash_password() generates
-- every other password hash. Regenerate it if you change the password:
--   .venv\Scripts\python.exe -c "from app.core.security import hash_password; print(hash_password('FacetPlatform!2026'))"

BEGIN;

-- Preserve the global catalog before it's wiped along with everything else.
CREATE TEMP TABLE _kept_categories AS
SELECT * FROM categories WHERE org_id IS NULL;

CREATE TEMP TABLE _kept_templates AS
SELECT * FROM feedback_templates WHERE org_id IS NULL;

CREATE TEMP TABLE _kept_template_versions AS
SELECT v.* FROM feedback_template_versions v
JOIN feedback_templates t ON t.id = v.template_id
WHERE t.org_id IS NULL;

-- created_by_id / published_by_id, where the column exists on this server,
-- are cleared here rather than left pointing at a user row that is about to
-- stop existing — a dangling reference would fail the foreign key check on
-- re-insert below. Guarded by information_schema so this doesn't fail on a
-- server that predates migration 0017_catalog_created_by (no
-- categories.created_by_id / feedback_templates.created_by_id yet).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = '_kept_categories' AND column_name = 'created_by_id'
    ) THEN
        UPDATE _kept_categories SET created_by_id = NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = '_kept_templates' AND column_name = 'created_by_id'
    ) THEN
        UPDATE _kept_templates SET created_by_id = NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = '_kept_template_versions' AND column_name = 'published_by_id'
    ) THEN
        UPDATE _kept_template_versions SET published_by_id = NULL;
    END IF;
END $$;

-- Every app-data table except the catalog (handled separately above/below).
-- mfa_recovery_codes is only truncated if it still exists on this server
-- (dropped in migration 0018_drop_mfa) — guarded the same way as the
-- columns above, so this doesn't fail on a server that hasn't run that
-- migration yet.
TRUNCATE TABLE
    ai_insights,
    analytics_models,
    audit_logs,
    campaign_recipients,
    categories,
    contacts,
    feedback_assignments,
    feedback_responses,
    feedback_targets,
    feedback_template_versions,
    feedback_templates,
    invitations,
    login_attempts,
    org_branding,
    organizations,
    password_reset_tokens,
    proposals,
    refresh_tokens,
    review_cycles,
    session_families,
    users
RESTART IDENTITY CASCADE;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'mfa_recovery_codes') THEN
        EXECUTE 'TRUNCATE TABLE mfa_recovery_codes RESTART IDENTITY CASCADE';
    END IF;
END $$;

-- --- Super Admin ---------------------------------------------------------
INSERT INTO users (
    id, org_id, email, full_name, job_title, role, status,
    password_hash, password_changed_at, must_change_password,
    created_at, updated_at
) VALUES (
    gen_random_uuid(), NULL,
    'admin@stixis.com',
    'Super Admin',
    'Platform owner',
    'super_admin', 'active',
    '$argon2id$v=19$m=65536,t=3,p=4$XaiOz7hs8uwMMn1MEJo24w$WFXazuNxJySSb+BmS5UIxMfDZa2GsozNJB4CWx1nLMc',
    now(), false,
    now(), now()
);

-- --- Restore the global catalog, in FK order (categories -> templates ->
-- template versions) --------------------------------------------------------
INSERT INTO categories SELECT * FROM _kept_categories;
INSERT INTO feedback_templates SELECT * FROM _kept_templates;
INSERT INTO feedback_template_versions SELECT * FROM _kept_template_versions;

DROP TABLE _kept_categories;
DROP TABLE _kept_templates;
DROP TABLE _kept_template_versions;

COMMIT;

-- Sanity check.
SELECT 'users' AS table_name, count(*) FROM users
UNION ALL SELECT 'categories', count(*) FROM categories
UNION ALL SELECT 'feedback_templates', count(*) FROM feedback_templates
UNION ALL SELECT 'feedback_template_versions', count(*) FROM feedback_template_versions
UNION ALL SELECT 'organizations', count(*) FROM organizations;
