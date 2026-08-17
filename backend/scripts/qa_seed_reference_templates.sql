-- Inserts the six reference-form templates (Employee/Management/Client/
-- Product/Service/Proposal review) -- global (org_id IS NULL), so every
-- organization sees them in Create Feedback.
--
-- This is the SQL equivalent of running `python -m app.seed_templates`
-- (backend/app/seed_templates.py) against QA directly, for when psql access
-- is preferred over running the app's own management command. Content is
-- transcribed verbatim from the client's reference forms: each template's
-- three categories (Technical / Communication / Delivery & Discipline)
-- become its sections, plus a final Overall Rating question, all on a
-- plain 1-5 scale.
--
-- Idempotent: every INSERT is guarded by a NOT EXISTS check on
-- key/name + org_id IS NULL, so running this again is a no-op.
--
-- Usage:
--   psql "postgresql://<user>:<password>@<qa-host>:5432/<database>" -f qa_seed_reference_templates.sql

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

-- Sanity check.
SELECT name, target_type FROM feedback_templates WHERE org_id IS NULL ORDER BY name;
