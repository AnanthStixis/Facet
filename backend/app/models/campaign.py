"""External campaign recipients (Module B).

An external feedback round is a `ReviewCycle` with `audience = external`. What
differs is only how the round reaches people: internally through
`feedback_assignments`, externally through one of these rows plus an emailed
link. Both paths write to `feedback_responses` against the same
`feedback_targets`, so every aggregate, report and export already understands
external feedback without a line of external-specific code.

Link security, recorded here because the public endpoint is the most exposed
surface in the product:

  * The token is 32 bytes from `secrets.token_urlsafe` — opaque, not a JWT.
    A JWT would carry tenant and campaign identifiers in a base64 payload any
    recipient could decode, which leaks the customer list to anyone forwarded
    an invitation.
  * Only a SHA-256 hash is stored. The raw token exists once, in the email that
    was sent, and cannot be recovered from a database dump.
  * One token per recipient, never per campaign. A shared link means one
    forwarded email lets a stranger answer as the client, and makes "who has
    responded" unanswerable.
  * Single use and expiring, so a link sitting in a mailbox for a year is not a
    standing invitation to submit again.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import RecipientStatus


class CampaignRecipient(UUIDPrimaryKey, Timestamped, Base):
    """One external person invited to give feedback about one target."""

    __tablename__ = "campaign_recipients"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feedback_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[RecipientStatus] = mapped_column(
        pg_enum(RecipientStatus, "recipient_status"),
        nullable=False,
        default=RecipientStatus.PENDING,
    )

    # Free-text label for the batch, e.g. "cohort 1". The spec called for
    # sending to a 25-person cohort, and being able to compare cohorts later is
    # most of why anyone bothers naming them.
    batch: Mapped[str | None] = mapped_column(String(80))

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reminders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_ip: Mapped[str | None] = mapped_column(INET)

    __table_args__ = (
        # One invitation per contact per target per round. Sending the same
        # person two links about the same thing doubles their annoyance and
        # halves the value of the response count.
        UniqueConstraint(
            "cycle_id", "target_id", "contact_id", name="uq_recipient_unique"
        ),
        Index("ix_recipients_cycle_status", "cycle_id", "status"),
        Index("ix_recipients_token", "token_hash"),
    )

    @property
    def is_open_for_submission(self) -> bool:
        return self.status not in {
            RecipientStatus.SUBMITTED,
            RecipientStatus.REVOKED,
            RecipientStatus.EXPIRED,
            RecipientStatus.UNSUBSCRIBED,
        }
