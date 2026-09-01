"""Small org-scoped reference lists: Department, Job Title, Cycle Name,
Product, Service.

Each is a simple reusable name list a Client Admin/Manager builds up over
time — picked from a dropdown wherever it's referenced (User.department /
User.job_title / ReviewCycle.name / the Product and Service review forms'
"what's this about" field), with an inline "add new" so the list grows from
actual usage rather than needing to be pre-populated. None of these are
foreign keys from the tables that use them: User.department, User.job_title,
ReviewCycle.name, and ReviewCycle.target label all stay the free-text
columns they already were — a master row only fills that text field once,
at selection time. That keeps this additive (no migration touching those
existing tables) and means a typo fixed on a past record never depends on
this list.
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

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[User | None] = relationship(User, foreign_keys=[created_by_id], lazy="noload")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # org_id IS NULL means "global" — a default department every organization
    # can read and pick from, owned by no tenant. Global names and per-org
    # names are separate namespaces, so an org may still create "Design" of
    # its own even when a global "Design" exists; that is why these are two
    # partial indexes rather than one plain unique index (which would treat
    # every NULL org_id as distinct and permit duplicate global names).
    __table_args__ = (
        Index(
            "uq_departments_global_name", "name", unique=True,
            postgresql_where=text("org_id IS NULL"),
        ),
        Index(
            "uq_departments_org_name", "org_id", "name", unique=True,
            postgresql_where=text("org_id IS NOT NULL"),
        ),
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


class Product(UUIDPrimaryKey, Timestamped, Base):
    """Reusable product names, picked when creating a Product review round."""

    __tablename__ = "products"
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
        Index("uq_products_org_name", "org_id", "name", unique=True),
    )


class Service(UUIDPrimaryKey, Timestamped, Base):
    """Reusable service names, picked when creating a Service review round."""

    __tablename__ = "services"
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
        Index("uq_services_org_name", "org_id", "name", unique=True),
    )