"""Session and refresh-token storage.

The refresh token design is the security centrepiece, so the reasoning is
recorded here rather than in a ticket somewhere.

A refresh token is an opaque 32-byte random value, not a JWT. A JWT refresh
token cannot be revoked without a server-side denylist, at which point it has
all the costs of a database-backed token and none of the benefits.

Tokens belong to a *family*. Logging in creates a family; each refresh rotates
the token and appends a new generation to the same family. Because a legitimate
client never reuses a rotated token, presenting an already-rotated token means
the token was captured. When that happens the entire family is revoked, so both
the attacker and the victim are logged out and the victim notices. Silently
issuing a new token to whoever asks last is how stolen sessions persist for
weeks.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class SessionFamily(UUIDPrimaryKey, Timestamped, Base):
    """One sign-in on one device. Shown to the user as an active session."""

    __tablename__ = "session_families"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised so a Super Admin reviewing sessions across the platform does
    # not need a join, and so the row survives being read without tenant bind.
    org_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)

    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(INET)
    device_label: Mapped[str | None] = mapped_column(String(120))

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(120))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_session_families_user_active", "user_id", "revoked_at"),)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class RefreshToken(UUIDPrimaryKey, Timestamped, Base):
    """One generation within a session family."""

    __tablename__ = "refresh_tokens"

    family_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("session_families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 of the raw token. A fast hash is correct here, unlike for
    # passwords: the input is 256 bits of entropy, so there is nothing to brute
    # force, and refresh happens on a hot path where argon2 would be wasteful.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    family: Mapped[SessionFamily] = relationship(back_populates="tokens")

    __table_args__ = (Index("ix_refresh_tokens_hash", "token_hash"),)

    @property
    def is_spent(self) -> bool:
        return self.rotated_at is not None


class LoginAttempt(UUIDPrimaryKey, Base):
    """Append-only record of authentication attempts.

    Kept separate from the audit log because it is high volume, has a shorter
    retention, and must be writable before we know who the actor is.
    """

    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
