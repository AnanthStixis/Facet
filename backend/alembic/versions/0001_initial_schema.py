"""Initial schema: tenancy, identity, auth, audit, template catalog.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

ORG_GUC = "app.current_org_id"
SA_GUC = "app.is_super_admin"

# Standard tenant predicate: the row belongs to the bound tenant, or the caller
# is a platform operator. Rows with a NULL org_id are platform-level and are
# therefore visible to Super Admins only, which is what we want for users and
# audit entries.
TENANT_PREDICATE = (
    f"(org_id = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
    f"OR current_setting('{SA_GUC}', true) = 'on')"
)

# Catalog predicate: additionally exposes vendor-authored rows (org_id IS NULL)
# to every tenant for reading. Writing them still requires an org match, so a
# tenant cannot create or edit a global template.
CATALOG_READ_PREDICATE = f"(org_id IS NULL OR {TENANT_PREDICATE})"

STANDARD_RLS_TABLES = [
    "users",
    "org_branding",
    "invitations",
    "audit_logs",
    "feedback_targets",
    "contacts",
]

CATALOG_RLS_TABLES = [
    "categories",
    "feedback_templates",
    "feedback_template_versions",
]


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    # --- Extensions -------------------------------------------------------
    # Also created by infra/initdb, but repeated here so a migration against a
    # database provisioned some other way (Azure Flexible Server) still works.
    for ext in ("pgcrypto", "pg_trgm", "btree_gin"):
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
    # pgvector is only needed once Module H ships; tolerate its absence locally.
    op.execute(
        "DO $$ BEGIN "
        "  CREATE EXTENSION IF NOT EXISTS vector; "
        "EXCEPTION WHEN OTHERS THEN "
        "  RAISE NOTICE 'pgvector unavailable, AI features will need it later'; "
        "END $$"
    )

    # --- Enum types -------------------------------------------------------
    enums = {
        "org_status": ("pending", "active", "rejected", "suspended"),
        "org_registration_source": ("self_service", "provisioned"),
        "user_role": ("super_admin", "client_admin", "manager", "employee"),
        "user_status": ("invited", "active", "disabled"),
        "audit_severity": ("info", "notice", "alert"),
        "template_status": ("draft", "published", "archived"),
        "template_scope": ("global", "org"),
        "target_type": (
            "employee",
            "manager",
            "team",
            "department",
            "product",
            "service",
            "proposal",
        ),
    }
    for name, values in enums.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # --- organizations ----------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("legal_name", sa.String(250)),
        sa.Column("primary_domain", sa.String(255)),
        sa.Column("status", _enum("org_status"), nullable=False, server_default="pending"),
        sa.Column(
            "registration_source",
            _enum("org_registration_source"),
            nullable=False,
            server_default="self_service",
        ),
        sa.Column("contact_name", sa.String(150), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(40)),
        sa.Column("country", sa.String(2)),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("seat_limit", sa.Integer()),
        sa.Column(
            "settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_status", "organizations", ["status"])
    op.execute(
        "CREATE INDEX ix_organizations_name_trgm ON organizations "
        "USING gin (name gin_trgm_ops)"
    )

    # --- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("job_title", sa.String(150)),
        sa.Column("role", _enum("user_role"), nullable=False),
        sa.Column("status", _enum("user_status"), nullable=False, server_default="invited"),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mfa_secret_encrypted", sa.String(255)),
        sa.Column("mfa_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True)),
        sa.Column("department", sa.String(150)),
        sa.Column(
            "preferences", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_users_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["users.id"], name="fk_users_manager_id_users", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "(role = 'super_admin' AND org_id IS NULL) "
            "OR (role <> 'super_admin' AND org_id IS NOT NULL)",
            name="ck_users_super_admin_has_no_org",
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_org_status", "users", ["org_id", "status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_users_org_email ON users (org_id, email) "
        "WHERE org_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_platform_email ON users (email) WHERE org_id IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_users_name_trgm ON users USING gin (full_name gin_trgm_ops)"
    )

    # Deferred because organizations and users reference each other.
    op.create_foreign_key(
        "fk_organizations_approved_by_id_users",
        "organizations",
        "users",
        ["approved_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- org_branding -----------------------------------------------------
    op.create_table(
        "org_branding",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logo_path", sa.String(500)),
        sa.Column("logo_content_type", sa.String(80)),
        sa.Column("logo_width", sa.Integer()),
        sa.Column("logo_height", sa.Integer()),
        sa.Column("logo_updated_at", sa.DateTime(timezone=True)),
        sa.Column("accent_color", sa.String(9), nullable=False, server_default="#B4633A"),
        sa.Column("email_footer_note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_branding"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_org_branding_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", name="uq_org_branding_org_id"),
    )
    op.create_index("ix_org_branding_org_id", "org_branding", ["org_id"])

    # --- mfa_recovery_codes ----------------------------------------------
    op.create_table(
        "mfa_recovery_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mfa_recovery_codes"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mfa_recovery_codes_user_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])

    # --- invitations ------------------------------------------------------
    op.create_table(
        "invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("role", _enum("user_role"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("invited_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_invitations_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"], ["users.id"], name="fk_invitations_invited_by_id_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"])
    op.create_index("ix_invitations_org_email", "invitations", ["org_id", "email"])

    # --- session_families -------------------------------------------------
    op.create_table(
        "session_families",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_agent", sa.String(400)),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("device_label", sa.String(120)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(120)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_families"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_session_families_user_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_session_families_user_id", "session_families", ["user_id"])
    op.create_index("ix_session_families_org_id", "session_families", ["org_id"])
    op.create_index(
        "ix_session_families_user_active", "session_families", ["user_id", "revoked_at"]
    )

    # --- refresh_tokens ---------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["family_id"], ["session_families.id"],
            name="fk_refresh_tokens_family_id_session_families", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    # --- login_attempts ---------------------------------------------------
    op.create_table(
        "login_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(80)),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempts"),
    )
    op.create_index("ix_login_attempts_email", "login_attempts", ["email"])
    op.create_index("ix_login_attempts_occurred_at", "login_attempts", ["occurred_at"])

    # --- audit_logs -------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("severity", _enum("audit_severity"), nullable=False, server_default="info"),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_email", sa.String(255)),
        sa.Column("actor_name", sa.String(150)),
        sa.Column("actor_role", sa.String(40)),
        sa.Column("target_type", sa.String(60)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_label", sa.String(250)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_audit_logs_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_logs_actor_id_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_org_occurred", "audit_logs", ["org_id", "occurred_at"])
    op.create_index("ix_audit_logs_action_occurred", "audit_logs", ["action", "occurred_at"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_id", "occurred_at"])
    op.execute("CREATE INDEX ix_audit_logs_context ON audit_logs USING gin (context)")

    # The spec requires audit entries to be uneditable by any role. Convention
    # is not enforcement, so the database refuses the write.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only (attempted %)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION facet_audit_immutable()
        """
    )

    # --- categories -------------------------------------------------------
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "applies_to", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("icon", sa.String(40)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_categories_org_id_organizations",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_categories_org_id", "categories", ["org_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_categories_global_key ON categories (key) WHERE org_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_categories_org_key ON categories (org_id, key) "
        "WHERE org_id IS NOT NULL"
    )

    # --- feedback_templates ----------------------------------------------
    op.create_table(
        "feedback_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", _enum("template_scope"), nullable=False, server_default="org"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("target_type", _enum("target_type"), nullable=False),
        sa.Column("cloned_from_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_responses_to_reveal", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_templates"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_feedback_templates_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"],
            name="fk_feedback_templates_category_id_categories", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cloned_from_id"], ["feedback_templates.id"],
            name="fk_feedback_templates_cloned_from_id_feedback_templates", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND org_id IS NULL) OR (scope = 'org' AND org_id IS NOT NULL)",
            name="ck_feedback_templates_template_scope_matches_org",
        ),
    )
    op.create_index("ix_feedback_templates_org_id", "feedback_templates", ["org_id"])
    op.create_index("ix_feedback_templates_category_id", "feedback_templates", ["category_id"])
    op.create_index(
        "ix_feedback_templates_org_category", "feedback_templates", ["org_id", "category_id"]
    )
    op.execute(
        "CREATE INDEX ix_feedback_templates_name_trgm ON feedback_templates "
        "USING gin (name gin_trgm_ops)"
    )

    # --- feedback_template_versions --------------------------------------
    op.create_table(
        "feedback_template_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", _enum("template_status"), nullable=False, server_default="draft"),
        sa.Column(
            "definition", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_template_versions"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name="fk_feedback_template_versions_org_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["feedback_templates.id"],
            name="fk_feedback_template_versions_template_id_feedback_templates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"], ["users.id"],
            name="fk_feedback_template_versions_published_by_id_users", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("template_id", "version", name="uq_template_version"),
    )
    op.create_index(
        "ix_feedback_template_versions_org_id", "feedback_template_versions", ["org_id"]
    )
    op.create_index(
        "ix_feedback_template_versions_template_id", "feedback_template_versions", ["template_id"]
    )
    op.create_index(
        "ix_template_versions_status", "feedback_template_versions", ["template_id", "status"]
    )

    # A published version is a historical record that campaigns point at, so it
    # must never change. Editing means creating the next version.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION facet_template_version_immutable() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' AND NEW.definition IS DISTINCT FROM OLD.definition THEN
                RAISE EXCEPTION 'published template versions are immutable; create a new version'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_template_version_immutable
            BEFORE UPDATE ON feedback_template_versions
            FOR EACH ROW EXECUTE FUNCTION facet_template_version_immutable()
        """
    )

    # --- feedback_targets -------------------------------------------------
    op.create_table(
        "feedback_targets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", _enum("target_type"), nullable=False),
        sa.Column("label", sa.String(250), nullable=False),
        sa.Column("reference", sa.String(120)),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_targets"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_feedback_targets_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"], ["users.id"],
            name="fk_feedback_targets_subject_user_id_users", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "org_id", "target_type", "reference", name="uq_target_org_type_reference"
        ),
    )
    op.create_index("ix_feedback_targets_org_id", "feedback_targets", ["org_id"])
    op.create_index("ix_feedback_targets_subject_user_id", "feedback_targets", ["subject_user_id"])
    op.create_index("ix_feedback_targets_org_type", "feedback_targets", ["org_id", "target_type"])
    op.execute(
        "CREATE INDEX ix_feedback_targets_label_trgm ON feedback_targets "
        "USING gin (label gin_trgm_ops)"
    )

    # --- contacts ---------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("company", sa.String(200)),
        sa.Column("job_title", sa.String(150)),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_contacts_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "email", name="uq_contacts_org_email"),
    )
    op.create_index("ix_contacts_org_id", "contacts", ["org_id"])
    op.execute(
        "CREATE INDEX ix_contacts_name_trgm ON contacts USING gin (full_name gin_trgm_ops)"
    )

    # --- Row level security ----------------------------------------------
    for table in STANDARD_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
        )

    for table in CATALOG_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING {CATALOG_READ_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
        )

    # The application role owns no tables, so grants are explicit.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO facet_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO facet_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_template_version_immutable ON feedback_template_versions")
    op.execute("DROP FUNCTION IF EXISTS facet_template_version_immutable()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS facet_audit_immutable()")

    for table in [
        "contacts",
        "feedback_targets",
        "feedback_template_versions",
        "feedback_templates",
        "categories",
        "audit_logs",
        "login_attempts",
        "refresh_tokens",
        "session_families",
        "invitations",
        "mfa_recovery_codes",
        "org_branding",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    op.execute("ALTER TABLE organizations DROP CONSTRAINT IF EXISTS "
               "fk_organizations_approved_by_id_users")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TABLE IF EXISTS organizations CASCADE")

    for name in [
        "target_type",
        "template_scope",
        "template_status",
        "audit_severity",
        "user_status",
        "user_role",
        "org_registration_source",
        "org_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
