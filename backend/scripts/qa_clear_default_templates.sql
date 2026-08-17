-- Hard-deletes the vendor default template library (org_id IS NULL rows) —
-- categories, templates, and template versions. Their descriptive content
-- (question set, wording) has been folded directly into each Create
-- Feedback type's own description in the app instead, so a separate
-- "Provided templates" catalog no longer needs to exist; every org creates
-- its own templates from here on.
--
-- Safety: feedback_template_versions.id is referenced by
-- review_cycles.template_version_id with ON DELETE RESTRICT. If any
-- organization on this server actually ran a round from one of these
-- default templates, this script fails loudly on that DELETE instead of
-- silently orphaning history — stop and investigate rather than re-running
-- with CASCADE.
--
-- Idempotent: every DELETE is scoped to org_id IS NULL, so running this
-- again after it already succeeded just deletes zero rows.
--
-- Usage:
--   psql "postgresql://<user>:<password>@<qa-host>:5432/<database>" -f qa_clear_default_templates.sql

BEGIN;

DELETE FROM feedback_template_versions
WHERE template_id IN (SELECT id FROM feedback_templates WHERE org_id IS NULL);

DELETE FROM feedback_templates
WHERE org_id IS NULL;

DELETE FROM categories
WHERE org_id IS NULL;

COMMIT;
