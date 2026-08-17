-- ================================================================
-- Default Feedback Template Reset & Seed
-- ================================================================
-- Purpose:
--   1. Remove all existing GLOBAL/default feedback templates.
--   2. Remove their template versions.
--   3. Keep organization-specific templates untouched.
--   4. Create one simple, ready-to-use template for each current
--      feedback type:
--        - Employees
--        - Management
--        - Client
--        - Product
--        - Service
--        - Proposal Review
--
-- Each template contains 8 questions using a mix of:
--   - rating
--   - yes_no
--   - text
--   - multiple_choice
--
-- NOTE:
--   The question "type" values below assume the frontend/template
--   renderer supports these input types. If your renderer uses
--   different enum names, change only the "type" values.
--
-- IMPORTANT:
--   This deletes only templates where org_id IS NULL (global/default
--   templates). Organization-specific templates are NOT deleted.
-- ================================================================

BEGIN;

-- ------------------------------------------------
-- 1. Remove existing global/default templates
-- ------------------------------------------------

DELETE FROM feedback_template_versions
WHERE template_id IN (
    SELECT id
    FROM feedback_templates
    WHERE org_id IS NULL
);

DELETE FROM feedback_templates
WHERE org_id IS NULL;


-- ------------------------------------------------
-- 2. Ensure the default category exists
-- ------------------------------------------------

DO $$
DECLARE
    cat_id uuid;
BEGIN

    SELECT id
    INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL
    LIMIT 1;

    IF cat_id IS NULL THEN

        INSERT INTO categories (
            id,
            org_id,
            key,
            name,
            description,
            applies_to,
            icon,
            sort_order,
            is_enabled,
            created_at,
            updated_at,
            created_by_id
        )
        VALUES (
            gen_random_uuid(),
            NULL,
            'getting_started',
            'Getting Started',
            'Simple ready-to-use feedback templates for common feedback scenarios.',
            '[]'::jsonb,
            'spark',
            5,
            true,
            now(),
            now(),
            NULL
        );

    ELSE

        UPDATE categories
        SET
            name = 'Getting Started',
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Employee Feedback - General Performance',
        'A simple 8-question feedback template to understand an employee''s performance, collaboration and development areas.',
        'employee',
        false,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Please share your feedback about this employee. Your feedback will help identify strengths and opportunities for improvement.",
          "sections": [
            {
              "key": "performance",
              "title": "Performance & Collaboration",
              "questions": [
                {
                  "key": "overall_performance",
                  "type": "rating",
                  "text": "How would you rate this employee's overall performance?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Needs improvement", "3": "Meets expectations", "4": "Very good", "5": "Excellent"}}
                },
                {
                  "key": "quality_of_work",
                  "type": "rating",
                  "text": "How would you rate the quality of this employee's work?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "communicates_effectively",
                  "type": "yes_no",
                  "text": "Does this employee communicate clearly and effectively?",
                  "required": true
                },
                {
                  "key": "works_well_with_team",
                  "type": "yes_no",
                  "text": "Does this employee work well with the team?",
                  "required": true
                },
                {
                  "key": "takes_ownership",
                  "type": "rating",
                  "text": "How would you rate this employee's ownership and accountability?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "key_strength",
                  "type": "multiple_choice",
                  "text": "What is this employee's strongest area?",
                  "required": true,
                  "options": ["Technical skills", "Communication", "Teamwork", "Problem solving", "Leadership", "Customer focus"]
                },
                {
                  "key": "improvement_area",
                  "type": "text",
                  "text": "What is the most important area where this employee could improve?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "additional_comments",
                  "type": "text",
                  "text": "Is there anything else you would like to share?",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Manager Feedback - Leadership & Support',
        'A simple anonymous feedback template to understand leadership, communication and team support.',
        'manager',
        true,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Your feedback is anonymous. Please answer honestly and constructively.",
          "sections": [
            {
              "key": "leadership",
              "title": "Leadership & Support",
              "questions": [
                {
                  "key": "overall_leadership",
                  "type": "rating",
                  "text": "How would you rate this manager's overall leadership?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Needs improvement", "3": "Good", "4": "Very good", "5": "Excellent"}}
                },
                {
                  "key": "communicates_clearly",
                  "type": "rating",
                  "text": "How effectively does the manager communicate goals and expectations?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "supports_team",
                  "type": "yes_no",
                  "text": "Does the manager provide the support you need to do your job?",
                  "required": true
                },
                {
                  "key": "listens_to_feedback",
                  "type": "yes_no",
                  "text": "Does the manager listen to employee ideas and concerns?",
                  "required": true
                },
                {
                  "key": "fair_decisions",
                  "type": "rating",
                  "text": "How would you rate the fairness and consistency of the manager's decisions?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "leadership_strength",
                  "type": "multiple_choice",
                  "text": "What is the manager's strongest leadership area?",
                  "required": true,
                  "options": ["Communication", "Coaching", "Decision making", "Team motivation", "Planning", "Conflict resolution"]
                },
                {
                  "key": "improvement_area",
                  "type": "text",
                  "text": "What could this manager do differently to better support the team?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "additional_comments",
                  "type": "text",
                  "text": "Any other feedback you would like to share?",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Client Feedback - Relationship & Satisfaction',
        'A simple client feedback template covering satisfaction, communication, delivery and relationship quality.',
        'client',
        false,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Thank you for taking a few minutes to share your experience working with us.",
          "sections": [
            {
              "key": "relationship",
              "title": "Client Relationship",
              "questions": [
                {
                  "key": "overall_satisfaction",
                  "type": "rating",
                  "text": "How satisfied are you with our overall service?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Very dissatisfied", "2": "Dissatisfied", "3": "Neutral", "4": "Satisfied", "5": "Very satisfied"}}
                },
                {
                  "key": "understands_needs",
                  "type": "rating",
                  "text": "How well do we understand your business needs?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "communication",
                  "type": "rating",
                  "text": "How would you rate the quality of our communication?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "meets_expectations",
                  "type": "yes_no",
                  "text": "Are we consistently meeting your expectations?",
                  "required": true
                },
                {
                  "key": "would_recommend",
                  "type": "yes_no",
                  "text": "Would you recommend our services to another organization?",
                  "required": true
                },
                {
                  "key": "most_valuable_area",
                  "type": "multiple_choice",
                  "text": "Which area provides the most value to you?",
                  "required": true,
                  "options": ["Quality", "Speed", "Communication", "Expertise", "Support", "Cost effectiveness"]
                },
                {
                  "key": "improvement",
                  "type": "text",
                  "text": "What is the one thing we could improve?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "additional_comments",
                  "type": "text",
                  "text": "Please share any additional comments or suggestions.",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Product Feedback - Usability & Satisfaction',
        'A simple product feedback template covering satisfaction, usability, reliability and improvement opportunities.',
        'product',
        false,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Tell us about your experience using this product. Your feedback helps us improve it.",
          "sections": [
            {
              "key": "product_experience",
              "title": "Product Experience",
              "questions": [
                {
                  "key": "overall_satisfaction",
                  "type": "rating",
                  "text": "How satisfied are you with the product overall?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Very dissatisfied", "2": "Dissatisfied", "3": "Neutral", "4": "Satisfied", "5": "Very satisfied"}}
                },
                {
                  "key": "ease_of_use",
                  "type": "rating",
                  "text": "How easy is the product to use?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Very difficult", "2": "Difficult", "3": "Average", "4": "Easy", "5": "Very easy"}}
                },
                {
                  "key": "meets_needs",
                  "type": "yes_no",
                  "text": "Does the product meet your primary needs?",
                  "required": true
                },
                {
                  "key": "reliable",
                  "type": "yes_no",
                  "text": "Do you consider the product reliable for your regular use?",
                  "required": true
                },
                {
                  "key": "performance",
                  "type": "rating",
                  "text": "How would you rate the product's overall performance?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "most_used_area",
                  "type": "multiple_choice",
                  "text": "Which area of the product do you use most?",
                  "required": true,
                  "options": ["Core features", "Reporting", "Dashboard", "Integrations", "Administration", "Other"]
                },
                {
                  "key": "missing_feature",
                  "type": "text",
                  "text": "What feature or capability would you most like us to add?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "additional_comments",
                  "type": "text",
                  "text": "What else could we do to improve your experience?",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Service Feedback - Delivery & Support',
        'A simple service feedback template covering delivery quality, responsiveness and support experience.',
        'service',
        false,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Thank you for sharing your experience. Your feedback helps us improve the service we provide.",
          "sections": [
            {
              "key": "service_experience",
              "title": "Service Experience",
              "questions": [
                {
                  "key": "overall_satisfaction",
                  "type": "rating",
                  "text": "How satisfied are you with the service overall?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Very dissatisfied", "2": "Dissatisfied", "3": "Neutral", "4": "Satisfied", "5": "Very satisfied"}}
                },
                {
                  "key": "quality",
                  "type": "rating",
                  "text": "How would you rate the quality of the service delivered?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "timeliness",
                  "type": "rating",
                  "text": "How would you rate the timeliness of the service?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "met_expectations",
                  "type": "yes_no",
                  "text": "Did the service meet your expectations?",
                  "required": true
                },
                {
                  "key": "support_responsive",
                  "type": "yes_no",
                  "text": "Was our team responsive when you needed support?",
                  "required": true
                },
                {
                  "key": "most_important_factor",
                  "type": "multiple_choice",
                  "text": "Which service factor is most important to you?",
                  "required": true,
                  "options": ["Quality", "Speed", "Communication", "Reliability", "Support", "Cost"]
                },
                {
                  "key": "what_went_well",
                  "type": "text",
                  "text": "What did we do particularly well?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "improvement",
                  "type": "text",
                  "text": "What could we improve in our service?",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
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

    SELECT id INTO cat_id
    FROM categories
    WHERE key = 'getting_started'
      AND org_id IS NULL;

    INSERT INTO feedback_templates (
        id, org_id, category_id, scope, name, description,
        target_type, is_anonymous, min_responses_to_reveal,
        is_active, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        cat_id,
        'global',
        'Proposal Review - Clarity & Quality',
        'A simple proposal review template covering clarity, relevance, quality and likelihood of moving forward.',
        'proposal',
        false,
        4,
        true,
        now(),
        now()
    )
    RETURNING id INTO tmpl_id;

    INSERT INTO feedback_template_versions (
        id, org_id, template_id, version, status,
        definition, published_at, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(),
        NULL,
        tmpl_id,
        1,
        'published',
        $def$
        {
          "schema_version": 1,
          "intro": "Please review the proposal and share your feedback. Your responses will help us improve the proposal and next steps.",
          "sections": [
            {
              "key": "proposal_review",
              "title": "Proposal Review",
              "questions": [
                {
                  "key": "overall_quality",
                  "type": "rating",
                  "text": "How would you rate the overall quality of the proposal?",
                  "required": true,
                  "scale": {"min": 1, "max": 5, "labels": {"1": "Poor", "2": "Needs improvement", "3": "Good", "4": "Very good", "5": "Excellent"}}
                },
                {
                  "key": "clarity",
                  "type": "rating",
                  "text": "How clear and easy to understand was the proposal?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "relevant",
                  "type": "yes_no",
                  "text": "Does the proposal address the key requirements?",
                  "required": true
                },
                {
                  "key": "realistic",
                  "type": "yes_no",
                  "text": "Do you consider the proposed approach realistic and achievable?",
                  "required": true
                },
                {
                  "key": "value",
                  "type": "rating",
                  "text": "How would you rate the value offered by the proposal?",
                  "required": true,
                  "scale": {"min": 1, "max": 5}
                },
                {
                  "key": "decision_factor",
                  "type": "multiple_choice",
                  "text": "What is the most important factor influencing your evaluation?",
                  "required": true,
                  "options": ["Solution quality", "Pricing", "Timeline", "Experience", "Technical approach", "Support"]
                },
                {
                  "key": "missing_information",
                  "type": "text",
                  "text": "What information is missing or needs more clarification?",
                  "required": false,
                  "multiline": true
                },
                {
                  "key": "additional_comments",
                  "type": "text",
                  "text": "Please share any additional feedback about the proposal.",
                  "required": false,
                  "multiline": true
                }
              ]
            }
          ]
        }
        $def$::jsonb,
        now(), now(), now()
    );

END $$;


-- ------------------------------------------------
-- 9. Verification
-- ------------------------------------------------

SELECT
    ft.name,
    ft.target_type,
    c.name AS category_name,
    ft.is_active,
    ftv.version,
    ftv.status,
    jsonb_array_length(
        ftv.definition->'sections'->0->'questions'
    ) AS question_count
FROM feedback_templates ft
JOIN categories c
    ON c.id = ft.category_id
LEFT JOIN feedback_template_versions ftv
    ON ftv.template_id = ft.id
WHERE ft.org_id IS NULL
ORDER BY ft.target_type, ft.name;

COMMIT;

-- Expected result:
--   6 templates
--   8 questions per template
--   1 category: Getting Started
