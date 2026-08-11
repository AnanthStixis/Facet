-- Wipes every table in the Facet database except the Super Admin user row(s).
--
-- This also empties the global template catalog (categories, feedback
-- templates and their versions have org_id IS NULL, but they still live in
-- these tables, so they get truncated too). After running this, restore the
-- catalog by running the seed script from backend/:
--
--   .venv\Scripts\python.exe -c "import asyncio; from app.seed import seed; asyncio.run(seed())"
--
-- That same seed script also recreates a demo org and a demo client admin —
-- if you don't want those, remove them by hand afterwards (Organizations
-- page in the app, or DELETE FROM organizations WHERE ...).
--
-- Usage:
--   psql "postgresql://postgres:<password>@localhost:5432/facet" -f reset_db_keep_super_admin.sql
--
-- Irreversible. Everyone except the preserved Super Admin(s) will need to be
-- re-invited, and every org/campaign/response/audit record is gone for good.

BEGIN;

-- Fail loudly rather than silently wiping everyone if, for some reason,
-- there is no Super Admin row to preserve.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE role = 'super_admin') THEN
        RAISE EXCEPTION 'No super_admin user found — aborting to avoid locking everyone out.';
    END IF;
END $$;

CREATE TEMP TABLE _kept_super_admins AS
SELECT * FROM users WHERE role = 'super_admin';

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
    mfa_recovery_codes,
    org_branding,
    organizations,
    password_reset_tokens,
    proposals,
    refresh_tokens,
    review_cycles,
    session_families,
    users
RESTART IDENTITY CASCADE;

INSERT INTO users SELECT * FROM _kept_super_admins;

DROP TABLE _kept_super_admins;

COMMIT;

-- Sanity check — should show only the preserved super_admin row(s).
SELECT id, email, role, status FROM users;
