-- Inserts the "Getting started" category and its 6 simple default feedback
-- templates (one per feedback type) — global (org_id IS NULL), so every
-- organization sees them.
--
-- Why this is needed: these were added to app/seed.py this session and
-- applied by running the seed function against local dev directly — that
-- updates data, not schema, so none of the earlier migration files touched
-- it. QA's schema is now caught up (0019), but its actual catalog data
-- never had these rows to begin with, which is why no organization on QA
-- can see them in Create Feedback.
--
-- Idempotent: each INSERT is guarded by a NOT EXISTS check on
-- key/name + org_id IS NULL, so running this more than once (or on a
-- database that already has some of these from a previous partial run)
-- won't create duplicates or error.
--
-- Needs a role with DDL/write privileges (same as every other script here).
--
-- Usage:
--   psql "postgresql://<user>:<password>@<qa-host>:5432/<database>" -f qa_seed_default_templates.sql

BEGIN;

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    -- --- Category ----------------------------------------------------------
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;
    IF cat_id IS NULL THEN
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
        ) RETURNING id INTO cat_id;
    END IF;

    -- --- Employees -----------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Employees Feedback' AND org_id IS NULL) THEN
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
    END IF;

    -- --- Management ------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Management Feedback' AND org_id IS NULL) THEN
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
    END IF;

    -- --- Client ------------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Client Feedback' AND org_id IS NULL) THEN
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
    END IF;

    -- --- Product -------------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Product Feedback' AND org_id IS NULL) THEN
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
    END IF;

    -- --- Service -------------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Service Feedback' AND org_id IS NULL) THEN
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
    END IF;

    -- --- Proposal Review -----------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM feedback_templates WHERE name = 'Default Proposal Review Feedback' AND org_id IS NULL) THEN
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
    END IF;
END $$;

COMMIT;

-- Sanity check.
SELECT name, target_type FROM feedback_templates WHERE org_id IS NULL ORDER BY name;
