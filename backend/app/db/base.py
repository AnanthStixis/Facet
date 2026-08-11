"""Declarative base, naming conventions, and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit constraint naming makes Alembic autogenerate produce stable,
# reversible migrations instead of database-assigned random names.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def pg_enum(enum_cls, name: str, *, native: bool = True, create_type: bool = True, **kwargs):
    """Postgres enum column bound to the enum's *values*.

    SQLAlchemy persists `Enum(...)` members by `.name` unless told otherwise,
    which for a StrEnum means writing "SUPER_ADMIN" into a type whose labels
    are "super_admin". `values_callable` is the fix, and routing every enum
    column through this helper means no model can forget it.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=native,
        create_type=create_type,
        values_callable=lambda enum: [member.value for member in enum],
        **kwargs,
    )


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantScoped:
    """Marks a table as belonging to exactly one organization.

    Presence of this mixin is what the migration helper looks for when deciding
    which tables get a row level security policy. If you add a tenant table and
    forget the mixin, the RLS test in tests/test_tenancy.py fails.
    """

    __tenant_scoped__ = True

    @staticmethod
    def _org_fk() -> Mapped[uuid.UUID]:
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
