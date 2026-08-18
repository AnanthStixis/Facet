"""Platform users."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import UserRole, UserStatus


class User(UUIDPrimaryKey, Timestamped, Base):
    """A person who can sign in.

    External respondents are intentionally NOT users. They never authenticate,
    so giving them accounts would create dormant credentials for people outside
    the customer's control. They live in `contacts` instead.
    """

    __tablename__ = "users"
    __tenant_scoped__ = True

    # NULL only for SUPER_ADMIN, which is enforced by the check constraint
    # below. Everyone else belongs to exactly one organization for life.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(150))

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"),
        nullable=False,
        default=UserStatus.INVITED,
    )

    # NULL until the invitation is accepted and a password is set. Passwords are
    # never transported in an email; the invite carries a single-use token.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    department: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # Email is unique platform-wide, case-insensitively — one account per
        # email, full stop. This used to be scoped per org (so the same
        # person could hold a separate account in several client
        # organizations), but that let the same email exist in more than one
        # org at once, which login had no way to safely disambiguate between.
        # See migration 0013_global_email_uniqueness.
        Index(
            "uq_users_email",
            text("lower(email)"),
            unique=True,
        ),
        Index(
            "ix_users_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index("ix_users_org_status", "org_id", "status"),
        CheckConstraint(
            "(role = 'super_admin' AND org_id IS NULL) "
            "OR (role <> 'super_admin' AND org_id IS NOT NULL)",
            name="super_admin_has_no_org",
        ),
    )

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} {self.role}>"


class UserManager(UUIDPrimaryKey, Timestamped, Base):
    """One employee-manager pairing. An employee can have several of these.

    Replaces `User.manager_id` — a single FK — as the actual source of truth
    for "who manages whom", because a single column cannot represent someone
    who reports to 2-3 managers at once. `User.manager_id` is left in place
    on the column, unused going forward, rather than dropped: a dormant
    column is a far safer migration than a destructive one, and the
    migration that introduces this table backfills every existing single
    manager_id relationship into it, so nothing about an org's existing data
    changes on upgrade.
    """

    __tablename__ = "user_managers"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "manager_id", name="uq_user_managers_employee_manager"
        ),
    )


class Invitation(UUIDPrimaryKey, Timestamped, Base):
    """A single-use invitation to join an organization."""

    __tablename__ = "invitations"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role", create_type=False),
        nullable=False,
    )

    # Only the hash is stored. The raw token exists exactly once, in the email
    # that was sent, and is unrecoverable from the database.
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        Index("ix_invitations_org_email", "org_id", "email"),
    )

    @property
    def is_open(self) -> bool:
        return self.accepted_at is None and self.revoked_at is None


class PasswordResetToken(UUIDPrimaryKey, Timestamped, Base):
    """A single-use link an admin can hand an existing user to set a new password.

    Deliberately a separate table from `Invitation` rather than a reused row
    there: an invitation activates a brand-new account and is rejected once
    the user is already active, which is exactly the state a reset needs to
    work *in*. Conflating the two would mean loosening that guard for
    invitations to make room for resets, or forking behaviour on a shared
    table — either way, two different security properties end up encoded in
    one column's meaning.
    """

    __tablename__ = "password_reset_tokens"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        Index("ix_password_reset_tokens_user", "user_id"),
    )

    @property
    def is_open(self) -> bool:
        return self.used_at is None