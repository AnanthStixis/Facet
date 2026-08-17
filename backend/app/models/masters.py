"""Small org-scoped reference lists: Department, Job Title, Cycle Name.

Each is a simple reusable name list a Client Admin/Manager builds up over
time — picked from a dropdown wherever it's referenced (User.department /
User.job_title / ReviewCycle.name), with an inline "add new" so the list
grows from actual usage rather than needing to be pre-populated. None of
these are foreign keys from the tables that use them: User.department,
User.job_title and ReviewCycle.name all stay the free-text columns they
already were — a master row only fills that text field once, at selection
time. That keeps this additive (no migration touching those existing
tables) and means a typo fixed on a past record never depends on this list.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.models.user import User


class Department(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "departments"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[User | None] = relationship(User, foreign_keys=[created_by_id], lazy="noload")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index("uq_departments_org_name", "org_id", "name", unique=True),
    )


class JobTitle(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_titles"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[User | None] = relationship(User, foreign_keys=[created_by_id], lazy="noload")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index("uq_job_titles_org_name", "org_id", "name", unique=True),
    )


class CycleName(UUIDPrimaryKey, Timestamped, Base):
    """Reusable feedback-round names ('Q3 Review', 'Annual 360', ...).

    Picked from the '+' popup next to Create Feedback's "Feedback Cycle
    Name" field; selecting one just fills that text field the same as
    typing it would.
    """

    __tablename__ = "cycle_names"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[User | None] = relationship(User, foreign_keys=[created_by_id], lazy="noload")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index("uq_cycle_names_org_name", "org_id", "name", unique=True),
    )
