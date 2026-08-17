-- Wipes every table in the Facet database, then recreates one Super Admin
-- login and a simple default template for every feedback type.
--
-- This is the SQL twin of scripts/reset_all_data.py — use this one when you
-- need to run the reset directly against a server via psql (no Python/venv
-- needed there). Both do exactly the same thing.
--
-- Irreversible. Every organization, user, contact, category, cycle,
-- campaign, response, and audit record is gone for good. What's left
-- afterwards:
--   - One Super Admin:
--       email:    admin@stixis.com
--       password: FacetPlatform!2026
--     (a fresh row — not whatever Super Admin existed before, so this is
--     safe to run even if that account's password had been changed)
--   - One "Getting started" category holding one deliberately simple
--     default template per feedback type (Employees, Management, Client,
--     Product, Service, Proposal Review), each published and ready to use.
--   - Nothing else. No demo organization, no demo users, no history.
--
-- Usage:
--   psql "postgresql://<user>:<password>@<host>:5432/<database>" -f reset_all_data.sql
--
-- The password hash below is a real argon2id hash of "FacetPlatform!2026" —
-- generated the same way app/core/security.py:hash_password() generates
-- every other user's password hash, so this Super Admin can sign in exactly
-- like any account created through the app. If you change
-- SUPER_ADMIN_PASSWORD in app/seed.py, regenerate this hash to match:
--   .venv\Scripts\python.exe -c "from app.core.security import hash_password; print(hash_password('FacetPlatform!2026'))"

BEGIN;

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

-- --- Super Admin -------------------------------------------------------
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

-- --- "Getting started" category -----------------------------------------
INSERT INTO categories (
    id, org_id, key, name, description, applies_to, icon, sort_order,
    is_enabled, created_at, updated_at, created_by_id
) VALUES (
    gen_random_uuid(), NULL,
    'getting_started',
    'Getting started',
    'One simple default template for each feedback type, ready to use immediately.',
    '[]'::jsonb,
    'spark',
    5,
    true, now(), now(), NULL
);

-- --- One simple default template per feedback type -----------------------
-- Each block: create the template row, then its one published version.
-- `type` is omitted on every question — the app treats a missing type as
-- "scale" (a 1-5 rating) when it loads the definition, same as every other
-- seeded template.

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    -- Employees
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Employees Feedback',
        'A simple, general-purpose review for one employee.',
        'employee', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "A quick, general check-in — no special preparation needed.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "does_good_work", "text": "This person does good work."},
                    {"key": "good_to_work_with", "text": "This person is good to work with."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );

    -- Management
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Management Feedback',
        'A simple, anonymous check-in on a manager.',
        'manager', true, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "Your answers are anonymous.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "supports_me", "text": "My manager supports me."},
                    {"key": "communicates_clearly", "text": "My manager communicates clearly."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );

    -- Client
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Client Feedback',
        'A simple relationship check-in for a client.',
        'client', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "Thank you for taking a minute to share your feedback.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "happy_with_relationship", "text": "I am happy with this relationship."},
                    {"key": "would_recommend", "text": "I would recommend us to others."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );

    -- Product
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Product Feedback',
        'A simple satisfaction check-in for a product.',
        'product', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "Thank you for taking a minute to share your feedback.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "meets_needs", "text": "This product meets my needs."},
                    {"key": "easy_to_use", "text": "This product is easy to use."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );

    -- Service
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Service Feedback',
        'A simple satisfaction check-in for a delivered service.',
        'service', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "Thank you for taking a minute to share your feedback.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "met_expectations", "text": "This service met my expectations."},
                    {"key": "would_use_again", "text": "I would use this service again."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );

    -- Proposal Review
    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description, target_type,
        is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Default Proposal Review Feedback',
        'A simple quality check-in for a submitted proposal.',
        'proposal', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;
    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
            "schema_version": 1,
            "intro": "Thank you for taking a minute to share your feedback.",
            "scale": {"type": "likert", "min": 1, "max": 5, "labels": {
                "1": "Strongly disagree", "2": "Disagree", "3": "Neutral",
                "4": "Agree", "5": "Strongly agree"
            }},
            "sections": [{
                "key": "general", "title": "General",
                "questions": [
                    {"key": "was_clear", "text": "The proposal was clear and easy to understand."},
                    {"key": "met_needs", "text": "The proposal addressed our needs."}
                ]
            }],
            "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

COMMIT;

-- Sanity check — should show only the fresh Super Admin.
SELECT id, email, role, status FROM users;
