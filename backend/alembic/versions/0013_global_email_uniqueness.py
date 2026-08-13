"""Make user email unique platform-wide, not per organization.

Email was previously unique only within an org (uq_users_org_email) plus a
separate index for Super Admins (uq_users_platform_email) - the same person
could hold a separate account in several client organizations. That let the
same email exist in more than one org at once, which broke an assumption
`facet_auth_principal` (migration 0002) already relied on: that looking up a
user by email returns at most one row. With duplicates possible, login had no
way to know which of several matching accounts was meant, and could sign
someone into the wrong organization's account entirely.

This migration removes that possibility at the source: one email now maps to
exactly one account, platform-wide, case-insensitively.

**Existing duplicates are resolved automatically, not manually.** For each
email shared by more than one account, the earliest-created account (by
created_at, then id, as a tiebreak) keeps the email as-is; every other
account sharing it is renamed by inserting `+dup-<short id>` before the `@` -
non-destructive, reversible by hand later, and guaranteed unique since it's
keyed off each row's own primary key. Nothing is deleted. The affected rows
are printed to the migration's own output as they're renamed, so a rename is
never silent.

Revision ID: 0013_global_email_uniqueness
Revises: 0011_cycle_target
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op

revision = "0013_global_email_uniqueness"
down_revision = "0011_cycle_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Find every row that isn't the earliest-created holder of its
    # (case-insensitive) email, so it can be renamed out of the way.
    duplicates = bind.exec_driver_sql(
        """
        SELECT id, org_id, email
        FROM (
            SELECT id, org_id, email,
                   row_number() OVER (
                       PARTITION BY lower(email)
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM users
        ) ranked
        WHERE rn > 1
        """
    ).fetchall()

    for user_id, org_id, email in duplicates:
        local, _, domain = email.partition("@")
        new_email = f"{local}+dup-{str(user_id)[:8]}@{domain}"
        bind.exec_driver_sql(
            "UPDATE users SET email = %(new_email)s WHERE id = %(user_id)s",
            {"new_email": new_email, "user_id": user_id},
        )
        print(
            f"  [0013] renamed duplicate: {email} (org {org_id}, user {user_id}) "
            f"-> {new_email}"
        )

    op.execute("DROP INDEX IF EXISTS uq_users_org_email")
    op.execute("DROP INDEX IF EXISTS uq_users_platform_email")
    op.execute("CREATE UNIQUE INDEX uq_users_email ON users (lower(email))")


def downgrade() -> None:
    # The renames from upgrade() are not reversed - they're a one-way,
    # non-destructive record of what was ambiguous at the time this ran.
    # Reversing them would risk recreating the very ambiguity this migration
    # exists to remove.
    op.execute("DROP INDEX IF EXISTS uq_users_email")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_org_email ON users (org_id, email) "
        "WHERE org_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_platform_email ON users (email) "
        "WHERE org_id IS NULL"
    )