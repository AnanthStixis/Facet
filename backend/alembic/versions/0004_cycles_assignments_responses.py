"""Review cycles, assignments, and responses.

Revision ID: 0004_cycles
Revises: 0003_audit_append
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_cycles"
down_revision = "0003_audit_append"
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"

TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)

RLS_TABLES = ["review_cycles", "feedback_assignments", "feedback_responses"]


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for name, values in {
        "cycle_status": ("draft", "open", "closed", "cancelled"),
        "relationship_type": (
            "self", "manager", "upward", "peer", "skip_level", "external",
        ),
        "assignment_status": (
            "pending", "in_progress", "submitted", "declined", "expired",
        ),
    }.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # --- review_cycles ----------------------------------------------------
    op.create_table(
        "review_cycles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", _enum("cycle_status"), nullable=False, server_default="draft"),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_responses_to_reveal", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("opens_at", sa.DateTime(timezone=True)),
        sa.Column("closes_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_cycles"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_review_cycles_org_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"], ["feedback_template_versions.id"],
            name="fk_review_cycles_template_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_review_cycles_created_by_id_users", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_review_cycles_org_id", "review_cycles", ["org_id"])
    op.create_index(
        "ix_review_cycles_template_version_id", "review_cycles", ["template_version_id"]
    )
    op.create_index("ix_review_cycles_org_status", "review_cycles", ["org_id", "status"])
    op.execute(
        "CREATE INDEX ix_review_cycles_name_trgm ON review_cycles "
        "USING gin (name gin_trgm_ops)"
    )

    # --- feedback_assignments --------------------------------------------
    op.create_table(
        "feedback_assignments",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("relationship_type", _enum("relationship_type"), nullable=False),
        sa.Column("status", _enum("assignment_status"), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("declined_reason", sa.Text()),
        sa.Column("reminders_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_assignments"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_feedback_assignments_org_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["review_cycles.id"],
            name="fk_feedback_assignments_cycle_id_review_cycles", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["feedback_targets.id"],
            name="fk_feedback_assignments_target_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_feedback_assignments_reviewer_user_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "cycle_id", "target_id", "reviewer_user_id", name="uq_assignment_unique"
        ),
    )
    op.create_index("ix_feedback_assignments_org_id", "feedback_assignments", ["org_id"])
    op.create_index("ix_feedback_assignments_cycle_id", "feedback_assignments", ["cycle_id"])
    op.create_index("ix_feedback_assignments_target_id", "feedback_assignments", ["target_id"])
    op.create_index(
        "ix_feedback_assignments_reviewer_user_id", "feedback_assignments", ["reviewer_user_id"]
    )
    op.create_index(
        "ix_assignments_reviewer_status", "feedback_assignments",
        ["reviewer_user_id", "status"],
    )
    op.create_index(
        "ix_assignments_cycle_status", "feedback_assignments", ["cycle_id", "status"]
    )

    # --- feedback_responses ----------------------------------------------
    op.create_table(
        "feedback_responses",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("relationship_type", _enum("relationship_type"), nullable=False),
        sa.Column(
            "answers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("comment", sa.Text()),
        sa.Column("overall_score", sa.Numeric(4, 2)),
        sa.Column("answered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_responses"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_feedback_responses_org_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["review_cycles.id"],
            name="fk_feedback_responses_cycle_id_review_cycles", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["feedback_targets.id"],
            name="fk_feedback_responses_target_id_feedback_targets", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"], ["feedback_template_versions.id"],
            # Shortened: the convention-generated name would exceed the 63
            # character identifier limit Postgres silently truncates at.
            name="fk_feedback_responses_template_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["feedback_assignments.id"],
            name="fk_feedback_responses_assignment_id_feedback_assignments",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_feedback_responses_reviewer_user_id_users", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("assignment_id", name="uq_feedback_responses_assignment_id"),
        # The anonymity guarantee, enforced by the database rather than by
        # every future code path remembering to null two columns.
        sa.CheckConstraint(
            "(is_anonymous AND assignment_id IS NULL AND reviewer_user_id IS NULL) "
            "OR (NOT is_anonymous)",
            name="ck_feedback_responses_anonymous_has_no_reviewer_link",
        ),
    )
    op.create_index("ix_feedback_responses_org_id", "feedback_responses", ["org_id"])
    op.create_index("ix_feedback_responses_cycle_id", "feedback_responses", ["cycle_id"])
    op.create_index("ix_feedback_responses_target_id", "feedback_responses", ["target_id"])
    op.create_index("ix_feedback_responses_submitted_at", "feedback_responses", ["submitted_at"])
    op.create_index("ix_responses_target_cycle", "feedback_responses", ["target_id", "cycle_id"])
    op.create_index(
        "ix_responses_cycle_relationship", "feedback_responses",
        ["cycle_id", "relationship_type"],
    )
    op.execute(
        "CREATE INDEX ix_responses_answers ON feedback_responses USING gin (answers)"
    )

    # A submitted response is evidence. Editing one after the fact would let an
    # administrator quietly rewrite what someone said about them.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_response_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'feedback responses cannot be deleted'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.answers IS DISTINCT FROM OLD.answers
               OR NEW.comment IS DISTINCT FROM OLD.comment
               OR NEW.reviewer_user_id IS DISTINCT FROM OLD.reviewer_user_id
               OR NEW.is_anonymous IS DISTINCT FROM OLD.is_anonymous THEN
                RAISE EXCEPTION 'submitted feedback responses are immutable'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feedback_responses_immutable
            BEFORE UPDATE OR DELETE ON feedback_responses
            FOR EACH ROW EXECUTE FUNCTION facet_response_immutable()
        """
    )

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
        )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_feedback_responses_immutable ON feedback_responses"
    )
    op.execute("DROP FUNCTION IF EXISTS facet_response_immutable()")
    for table in ["feedback_responses", "feedback_assignments", "review_cycles"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for name in ["assignment_status", "relationship_type", "cycle_status"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
