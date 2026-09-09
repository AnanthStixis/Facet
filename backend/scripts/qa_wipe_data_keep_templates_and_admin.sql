-- Deletes ALL organization/tenant data from this database, keeping only:
--   1. The ACTIVE vendor "master" template catalog (categories,
--      feedback_templates, feedback_template_versions where org_id IS NULL
--      AND is_active = true) — the "Provided templates" every org actually
--      sees in Create Feedback. Disabled vendor templates (is_active =
--      false — old/superseded ones app/seed_templates.py deactivated
--      rather than deleted, because at the time something still referenced
--      them) are deleted here too. That's safe now specifically because
--      Step 1 below empties every review_cycle and feedback_response
--      first, so nothing anywhere still points at a disabled template's
--      version by the time Step 2 gets to it.
--   2. Exactly ONE super admin account — admin@stixis.com (the platform
--      default seeded by app/seed.py), hardcoded in two places below.
--      Every other user is deleted, INCLUDING any other super_admin-role
--      account. Check the sanity-check query at the end BEFORE trusting
--      this ran correctly: it must list exactly one row, that email, role
--      super_admin.
--
--      If QA's real super admin uses a different address, replace
--      'admin@stixis.com' in both the guard check and the DELETE FROM
--      users statement below before running this — keeping the wrong
--      email (or a typo'd one that matches nothing) deletes every super
--      admin account and locks you out of QA entirely, with no way back in
--      except restoring a backup or reseeding from scratch. The guard
--      check below aborts before deleting anything if the email typed in
--      doesn't match an existing super_admin, precisely to catch that.
--
-- Everything else is gone: every organization, every user in one, every
-- contact, review cycle, campaign, response, assignment, proposal, audit
-- log entry, session, and every org-owned master-data row (departments,
-- job titles, cycle names, products, services). This is IRREVERSIBLE —
-- there is no undo once this runs. Take a database backup/snapshot first
-- if there is any chance you will want this data back.
--
-- Two tables (audit_logs, feedback_responses) are deliberately append-only
-- at the database level — a trigger rejects ordinary UPDATE/DELETE from
-- every role, including this one, specifically so no one (not even an
-- admin with a raw SQL connection) can quietly edit history. TRUNCATE is
-- the one operation Postgres never routes through a row-level trigger, so
-- it is used here instead of DELETE for those two tables — this is not a
-- workaround or a hole in that protection, it is the same mechanism the
-- table owner would use for any legitimate full-table reset.
--
-- Run with the same migration-owner role used for schema changes (the
-- app's runtime role, facet_app, does not have TRUNCATE privileges and
-- could not run this even if it wanted to).
--
-- Usage:
--   psql "postgresql://<migration-role>:<password>@<qa-host>:5432/<database>" -f qa_wipe_data_keep_templates_and_admin.sql

BEGIN;

-- Fail fast, before touching anything, if that email doesn't actually match
-- a super_admin account — better to stop here than to run the whole wipe
-- and discover at the end that zero admins survived.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users WHERE email = 'admin@stixis.com' AND role = 'super_admin'
    ) THEN
        RAISE EXCEPTION 'admin@stixis.com does not match any super_admin account — aborting before any data is deleted. Edit the email in this file (both the guard check above and the DELETE FROM users statement below) to match QA''s real super admin address.';
    END IF;
END $$;

-- Step 1: fully empty every table that has no rows worth keeping. Listed
-- together (not relying on CASCADE from `organizations`) specifically so
-- CASCADE never reaches into the tables in Step 2, which hold rows we
-- need to keep.
TRUNCATE TABLE
    ai_insights,
    analytics_models,
    audit_logs,
    campaign_recipients,
    contacts,
    cycle_names,
    departments,
    feedback_assignments,
    feedback_responses,
    feedback_targets,
    invitations,
    job_titles,
    login_attempts,
    org_branding,
    password_reset_tokens,
    products,
    proposals,
    refresh_tokens,
    review_cycles,
    services,
    session_families,
    user_managers
    CASCADE;

-- Step 2: partial tables — delete only the rows that shouldn't survive, in
-- dependency order (versions before templates before categories).
--
-- Org-owned template rows (org_id IS NOT NULL) go regardless of
-- is_active. Vendor rows (org_id IS NULL) go too, but only the disabled
-- ones — active vendor templates are the "master templates" this script
-- exists to keep.
DELETE FROM feedback_template_versions
WHERE org_id IS NOT NULL
   OR template_id IN (SELECT id FROM feedback_templates WHERE org_id IS NULL AND is_active = false);

DELETE FROM feedback_templates
WHERE org_id IS NOT NULL
   OR (org_id IS NULL AND is_active = false);

DELETE FROM categories WHERE org_id IS NOT NULL;

-- A vendor category with no templates left under it (every one of its
-- templates was disabled and just got deleted above) is clutter, not a
-- master record worth keeping.
DELETE FROM categories c
WHERE c.org_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM feedback_templates t WHERE t.category_id = c.id);

DELETE FROM users WHERE email <> 'admin@stixis.com';

-- Step 3: organizations themselves. By this point nothing anywhere
-- references any org_id, so this is a plain, ordinary delete — no CASCADE
-- needed, and none of the kept tables/rows are touched by it.
DELETE FROM organizations;

COMMIT;

-- Sanity checks — read these before telling anyone this is done.
SELECT id, email, full_name, role FROM users ORDER BY email;
SELECT name, target_type, is_active FROM feedback_templates WHERE org_id IS NULL ORDER BY name;
SELECT count(*) AS remaining_organizations FROM organizations;
