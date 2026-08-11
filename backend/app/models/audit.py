"""Append-only audit trail (Module F)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey, pg_enum
from app.models.enums import AuditAction, AuditSeverity


class AuditLog(UUIDPrimaryKey, Base):
    """One recorded action.

    Immutability is enforced by a database trigger that rejects UPDATE and
    DELETE, not by convention. The spec requires that no role can edit or
    delete entries, and "no role" has to include a Client Admin with SQL access
    during an incident.

    org_id is nullable because platform-level actions (approving a tenant,
    Super Admin sign-in) belong to no tenant. The RLS policy on this table
    therefore shows tenant rows to that tenant and platform rows to Super
    Admins only.
    """

    __tablename__ = "audit_logs"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )

    action: Mapped[AuditAction] = mapped_column(
        pg_enum(AuditAction, "audit_action", native=False, create_type=False, length=64),
        nullable=False,
    )
    severity: Mapped[AuditSeverity] = mapped_column(
        pg_enum(AuditSeverity, "audit_severity"),
        nullable=False,
        default=AuditSeverity.INFO,
    )

    # Actor identity is denormalised on purpose. If the user is later deleted
    # the audit entry must still say who did it, so the FK is SET NULL while
    # the display fields persist.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    actor_name: Mapped[str | None] = mapped_column(String(150))
    actor_role: Mapped[str | None] = mapped_column(String(40))

    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    target_label: Mapped[str | None] = mapped_column(String(250))

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured detail: before/after values, filter payloads for exports,
    # recipient counts for bulk sends. Never contains secrets or raw tokens.
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        # The audit page always filters by org and sorts by time descending.
        Index("ix_audit_logs_org_occurred", "org_id", "occurred_at"),
        Index("ix_audit_logs_action_occurred", "action", "occurred_at"),
        Index("ix_audit_logs_actor", "actor_id", "occurred_at"),
        Index("ix_audit_logs_context", "context", postgresql_using="gin"),
    )
