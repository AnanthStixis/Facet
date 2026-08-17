-- Default Feedback Template Reset & Seed — corrected for our actual schema.
--
-- Adapted from an externally-sourced draft (final_reset_and_seed_default_
-- feedback_templates.sql). The structure (safe deletion, category upsert,
-- one rich 8-question template per type) was sound and is kept as-is; the
-- question content needed fixing to actually work against this app:
--
--   1. Question "type" values didn't match our schema. app/services/
--      forms.py's QUESTION_TYPES is exactly {scale, choice, text, boolean}
--      — the original used "rating", "yes_no", "multiple_choice", none of
--      which exist. validate_definition() rejects anything outside that
--      set, so as written, every one of these templates would have been
--      unusable the moment anyone opened it (Create Feedback calls
--      validate_definition on the template's definition). Fixed by
--      mapping: rating -> scale, yes_no -> boolean, multiple_choice ->
--      choice.
--   2. The scale (min/max/labels) is only ever read from the TOP LEVEL of
--      the definition (definition.scale) — never per-question. The
--      original nested a different scale+labels inside each question,
--      which our code silently ignores; it would have fallen back to an
--      unlabeled default 1-5 range and lost all that label copy. Fixed by
--      adding one shared top-level scale per template (a generic
--      Poor..Excellent quality scale, since these templates mix agreement-
--      style and satisfaction-style questions that don't share one natural
--      wording) and removing the now-redundant per-question scale objects.
--   3. Added a "closing" block (comment prompt) to match every other
--      template in the catalog — not required by validate_definition, but
--      an omission compared to the rest of the catalog otherwise.
--
-- Deletion logic (safe, verified against the schema, kept as originally
-- written): only removes GLOBAL (org_id IS NULL) template versions that no
-- review_cycle still references, then only removes templates left with no
-- versions. Both review_cycles.template_version_id and
-- feedback_responses.template_version_id are ON DELETE RESTRICT, so if
-- anything is actually still in use this fails loudly with a clear FK
-- error rather than silently corrupting or orphaning data.
--
-- Organization-specific templates (org_id IS NOT NULL) are never touched.
--
-- Needs a role with DDL/write privileges (same as every other script here).
--
-- Usage:
--   psql "postgresql://<user>:<password>@<host>:5432/<database>" -f qa_reset_and_seed_default_templates.sql

BEGIN;

-- ------------------------------------------------
-- 1. Remove existing GLOBAL/default templates, but only what's safe to
--    remove — anything still referenced by a real review cycle stays.
-- ------------------------------------------------

DELETE FROM feedback_template_versions ftv
WHERE ftv.template_id IN (
    SELECT ft.id FROM feedback_templates ft WHERE ft.org_id IS NULL
)
AND NOT EXISTS (
    SELECT 1 FROM review_cycles rc WHERE rc.template_version_id = ftv.id
);

DELETE FROM feedback_templates ft
WHERE ft.org_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM feedback_template_versions ftv WHERE ftv.template_id = ft.id
);

-- ------------------------------------------------
-- 2. Ensure the "Getting started" category exists.
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL LIMIT 1;

    IF cat_id IS NULL THEN
        INSERT INTO categories (
            id, org_id, key, name, description, applies_to, icon, sort_order,
            is_enabled, created_at, updated_at, created_by_id
        ) VALUES (
            gen_random_uuid(), NULL, 'getting_started', 'Getting Started',
            'Simple ready-to-use feedback templates for common feedback scenarios.',
            '[]'::jsonb, 'spark', 5, true, now(), now(), NULL
        );
    ELSE
        UPDATE categories
        SET name = 'Getting Started',
            description = 'Simple ready-to-use feedback templates for common feedback scenarios.',
            is_enabled = true,
            updated_at = now()
        WHERE id = cat_id;
    END IF;
END $$;

-- ------------------------------------------------
-- 3. Employees Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Employee Feedback - General Performance',
        'A simple 8-question feedback template to understand an employee''s performance, collaboration and development areas.',
        'employee', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Please share your feedback about this employee. Your feedback will help identify strengths and opportunities for improvement.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Below average", "3": "Average", "4": "Good", "5": "Excellent"}},
          "sections": [
            {
              "key": "performance",
              "title": "Performance & Collaboration",
              "questions": [
                {"key": "overall_performance", "type": "scale", "text": "How would you rate this employee's overall performance?", "required": true},
                {"key": "quality_of_work", "type": "scale", "text": "How would you rate the quality of this employee's work?", "required": true},
                {"key": "communicates_effectively", "type": "boolean", "text": "Does this employee communicate clearly and effectively?", "required": true},
                {"key": "works_well_with_team", "type": "boolean", "text": "Does this employee work well with the team?", "required": true},
                {"key": "takes_ownership", "type": "scale", "text": "How would you rate this employee's ownership and accountability?", "required": true},
                {"key": "key_strength", "type": "choice", "text": "What is this employee's strongest area?", "required": true,
                 "options": ["Technical skills", "Communication", "Teamwork", "Problem solving", "Leadership", "Customer focus"]},
                {"key": "improvement_area", "type": "text", "text": "What is the most important area where this employee could improve?", "required": false},
                {"key": "additional_comments", "type": "text", "text": "Is there anything else you would like to share?", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 4. Management Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Manager Feedback - Leadership & Support',
        'A simple anonymous feedback template to understand leadership, communication and team support.',
        'manager', true, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Your feedback is anonymous. Please answer honestly and constructively.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Below average", "3": "Good", "4": "Very good", "5": "Excellent"}},
          "sections": [
            {
              "key": "leadership",
              "title": "Leadership & Support",
              "questions": [
                {"key": "overall_leadership", "type": "scale", "text": "How would you rate this manager's overall leadership?", "required": true},
                {"key": "communicates_clearly", "type": "scale", "text": "How effectively does the manager communicate goals and expectations?", "required": true},
                {"key": "supports_team", "type": "boolean", "text": "Does the manager provide the support you need to do your job?", "required": true},
                {"key": "listens_to_feedback", "type": "boolean", "text": "Does the manager listen to employee ideas and concerns?", "required": true},
                {"key": "fair_decisions", "type": "scale", "text": "How would you rate the fairness and consistency of the manager's decisions?", "required": true},
                {"key": "leadership_strength", "type": "choice", "text": "What is the manager's strongest leadership area?", "required": true,
                 "options": ["Communication", "Coaching", "Decision making", "Team motivation", "Planning", "Conflict resolution"]},
                {"key": "improvement_area", "type": "text", "text": "What could this manager do differently to better support the team?", "required": false},
                {"key": "additional_comments", "type": "text", "text": "Any other feedback you would like to share?", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 5. Client Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Client Feedback - Relationship & Satisfaction',
        'A simple client feedback template covering satisfaction, communication, delivery and relationship quality.',
        'client', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Thank you for taking a few minutes to share your experience working with us.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Very dissatisfied", "2": "Dissatisfied", "3": "Neutral", "4": "Satisfied", "5": "Very satisfied"}},
          "sections": [
            {
              "key": "relationship",
              "title": "Client Relationship",
              "questions": [
                {"key": "overall_satisfaction", "type": "scale", "text": "How satisfied are you with our overall service?", "required": true},
                {"key": "understands_needs", "type": "scale", "text": "How well do we understand your business needs?", "required": true},
                {"key": "communication", "type": "scale", "text": "How would you rate the quality of our communication?", "required": true},
                {"key": "meets_expectations", "type": "boolean", "text": "Are we consistently meeting your expectations?", "required": true},
                {"key": "would_recommend", "type": "boolean", "text": "Would you recommend our services to another organization?", "required": true},
                {"key": "most_valuable_area", "type": "choice", "text": "Which area provides the most value to you?", "required": true,
                 "options": ["Quality", "Speed", "Communication", "Expertise", "Support", "Cost effectiveness"]},
                {"key": "improvement", "type": "text", "text": "What is the one thing we could improve?", "required": false},
                {"key": "additional_comments", "type": "text", "text": "Please share any additional comments or suggestions.", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 6. Product Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Product Feedback - Usability & Satisfaction',
        'A simple product feedback template covering satisfaction, usability, reliability and improvement opportunities.',
        'product', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Tell us about your experience using this product. Your feedback helps us improve it.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Very poor", "2": "Poor", "3": "Average", "4": "Good", "5": "Excellent"}},
          "sections": [
            {
              "key": "product_experience",
              "title": "Product Experience",
              "questions": [
                {"key": "overall_satisfaction", "type": "scale", "text": "How satisfied are you with the product overall?", "required": true},
                {"key": "ease_of_use", "type": "scale", "text": "How easy is the product to use?", "required": true},
                {"key": "meets_needs", "type": "boolean", "text": "Does the product meet your primary needs?", "required": true},
                {"key": "reliable", "type": "boolean", "text": "Do you consider the product reliable for your regular use?", "required": true},
                {"key": "performance", "type": "scale", "text": "How would you rate the product's overall performance?", "required": true},
                {"key": "most_used_area", "type": "choice", "text": "Which area of the product do you use most?", "required": true,
                 "options": ["Core features", "Reporting", "Dashboard", "Integrations", "Administration", "Other"]},
                {"key": "missing_feature", "type": "text", "text": "What feature or capability would you most like us to add?", "required": false},
                {"key": "additional_comments", "type": "text", "text": "What else could we do to improve your experience?", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 7. Service Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Service Feedback - Delivery & Support',
        'A simple service feedback template covering delivery quality, responsiveness and support experience.',
        'service', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Thank you for sharing your experience. Your feedback helps us improve the service we provide.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Very dissatisfied", "2": "Dissatisfied", "3": "Neutral", "4": "Satisfied", "5": "Very satisfied"}},
          "sections": [
            {
              "key": "service_experience",
              "title": "Service Experience",
              "questions": [
                {"key": "overall_satisfaction", "type": "scale", "text": "How satisfied are you with the service overall?", "required": true},
                {"key": "quality", "type": "scale", "text": "How would you rate the quality of the service delivered?", "required": true},
                {"key": "timeliness", "type": "scale", "text": "How would you rate the timeliness of the service?", "required": true},
                {"key": "met_expectations", "type": "boolean", "text": "Did the service meet your expectations?", "required": true},
                {"key": "support_responsive", "type": "boolean", "text": "Was our team responsive when you needed support?", "required": true},
                {"key": "most_important_factor", "type": "choice", "text": "Which service factor is most important to you?", "required": true,
                 "options": ["Quality", "Speed", "Communication", "Reliability", "Support", "Cost"]},
                {"key": "what_went_well", "type": "text", "text": "What did we do particularly well?", "required": false},
                {"key": "improvement", "type": "text", "text": "What could we improve in our service?", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 8. Proposal Review Feedback
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
    tmpl_id uuid;
BEGIN
    SELECT id INTO cat_id FROM categories WHERE key = 'getting_started' AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal, is_active, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, cat_id, 'global',
        'Proposal Review - Clarity & Quality',
        'A simple proposal review template covering clarity, relevance, quality and likelihood of moving forward.',
        'proposal', false, 4, true, now(), now()
    ) RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status, definition, published_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NULL, tmpl_id, 1, 'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Please review the proposal and share your feedback. Your responses will help us improve the proposal and next steps.",
          "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Needs improvement", "3": "Good", "4": "Very good", "5": "Excellent"}},
          "sections": [
            {
              "key": "proposal_review",
              "title": "Proposal Review",
              "questions": [
                {"key": "overall_quality", "type": "scale", "text": "How would you rate the overall quality of the proposal?", "required": true},
                {"key": "clarity", "type": "scale", "text": "How clear and easy to understand was the proposal?", "required": true},
                {"key": "relevant", "type": "boolean", "text": "Does the proposal address the key requirements?", "required": true},
                {"key": "realistic", "type": "boolean", "text": "Do you consider the proposed approach realistic and achievable?", "required": true},
                {"key": "value", "type": "scale", "text": "How would you rate the value offered by the proposal?", "required": true},
                {"key": "decision_factor", "type": "choice", "text": "What is the most important factor influencing your evaluation?", "required": true,
                 "options": ["Solution quality", "Pricing", "Timeline", "Experience", "Technical approach", "Support"]},
                {"key": "missing_information", "type": "text", "text": "What information is missing or needs more clarification?", "required": false},
                {"key": "additional_comments", "type": "text", "text": "Please share any additional feedback about the proposal.", "required": false}
              ]
            }
          ],
          "closing": {"comment_prompt": "Anything else you would like to add?", "comment_required": false}
        }
        $def$::jsonb,
        now(), now(), now()
    );
END $$;

-- ------------------------------------------------
-- 9. Verification (inside the same transaction, before COMMIT — so this
--    check happens before the change is final)
-- ------------------------------------------------

SELECT
    ft.name,
    ft.target_type,
    c.name AS category_name,
    ft.is_active,
    ftv.version,
    ftv.status,
    jsonb_array_length(ftv.definition->'sections'->0->'questions') AS question_count
FROM feedback_templates ft
JOIN categories c ON c.id = ft.category_id
LEFT JOIN feedback_template_versions ftv ON ftv.template_id = ft.id
WHERE ft.org_id IS NULL
ORDER BY ft.target_type, ft.name;

-- Expected result: 6 templates, 8 questions each, all under "Getting Started".

COMMIT;
