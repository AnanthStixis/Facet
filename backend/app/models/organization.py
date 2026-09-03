"""Organization (tenant) and its branding."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey, pg_enum
from app.models.enums import OrgPlan, OrgRegistrationSource, OrgStatus


class Organization(UUIDPrimaryKey, Timestamped, Base):
    """A client tenant.

    Deliberately NOT tenant-scoped itself: this is the table the tenancy system
    points at, and Super Admins need cross-org visibility over it. Access is
    controlled at the API layer by role, not by RLS.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # URL-safe identifier used for tenant-branded links and future subdomains.
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    legal_name: Mapped[str | None] = mapped_column(String(250))
    primary_domain: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[OrgStatus] = mapped_column(
        pg_enum(OrgStatus, "org_status"),
        nullable=False,
        default=OrgStatus.PENDING,
    )
    registration_source: Mapped[OrgRegistrationSource] = mapped_column(
        pg_enum(OrgRegistrationSource, "org_registration_source"),
        nullable=False,
        default=OrgRegistrationSource.SELF_SERVICE,
    )
    plan: Mapped[OrgPlan] = mapped_column(
        pg_enum(OrgPlan, "org_plan"),
        nullable=False,
        default=OrgPlan.STARTER,
    )
   

    # Contact captured at registration, before any user account exists.
    contact_name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str | None] = mapped_column(String(2))

    # Date ranges are filtered and exported in the organization's own timezone.
    # Storing it here is what stops "last 30 days" meaning something different
    # on screen than it does in the exported file.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    suspension_reason: Mapped[str | None] = mapped_column(Text)

    seat_limit: Mapped[int | None] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    branding: Mapped["OrgBranding | None"] = relationship(
        back_populates="organization",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_organizations_status", "status"),
        # Powers the Super Admin org autocomplete without a sequential scan.
        Index(
            "ix_organizations_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization {self.slug} {self.status}>"


class OrgBranding(UUIDPrimaryKey, Timestamped, Base):
    """White-label assets for one organization.

    Applied to the org dashboard, every outgoing email, and every respondent
    feedback form. Branding is resolved per request from the tenant context,
    so one organization's logo is structurally unable to render for another.
    """

    __tablename__ = "org_branding"
    __tenant_scoped__ = True

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    logo_path: Mapped[str | None] = mapped_column(String(500))
    logo_content_type: Mapped[str | None] = mapped_column(String(80))
    logo_width: Mapped[int | None] = mapped_column(Integer)
    logo_height: Mapped[int | None] = mapped_column(Integer)
    logo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Hex colours, validated at the API boundary. Kept narrow on purpose: a
    # full theme editor produces tenants whose forms look broken and reflects
    # badly on the platform. One accent is enough to feel owned.
    accent_color: Mapped[str] = mapped_column(String(9), nullable=False, default="#B4633A")
    email_footer_note: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="branding")

    __table_args__ = (UniqueConstraint("org_id", name="uq_org_branding_org_id"),)
