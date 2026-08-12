"""Organization and user-management payloads."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class OrgRegistrationRequest(BaseModel):
    """Public self-registration. Creates a tenant in `pending`."""

    name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=150)
    contact_email: EmailStr
    contact_phone: str = Field(min_length=6, max_length=40)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str = Field(min_length=1, max_length=64)
    primary_domain: str | None = Field(default=None, max_length=255)


class OrgProvisionRequest(OrgRegistrationRequest):
    """Super Admin direct provisioning. Auto-approved, since it is pre-vetted."""

    # Pre-vetted by the Super Admin doing the provisioning, unlike public
    # self-registration — a phone number is a nice-to-have here, not a
    # prerequisite for trusting the request.
    contact_phone: str | None = Field(default=None, max_length=40)
    slug: str | None = Field(default=None, max_length=80)
    admin_full_name: str = Field(min_length=2, max_length=150)
    admin_email: EmailStr
    seat_limit: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        if value and not _SLUG_RE.match(value):
            raise ValueError(
                "Slug must be lowercase letters, digits and hyphens, 3-64 characters."
            )
        return value


class OrgApprovalRequest(BaseModel):
    admin_full_name: str = Field(min_length=2, max_length=150)
    admin_email: EmailStr
    seat_limit: int | None = Field(default=None, ge=1, le=100_000)
    note: str | None = Field(default=None, max_length=500)


class OrgUpdateRequest(BaseModel):
    """Super Admin edit of an existing organization's profile.

    Deliberately excludes `slug` — it is baked into every tenant-branded link
    already handed out, so changing it after the fact would silently break
    whatever a customer bookmarked or embedded.
    """

    name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=150)
    contact_email: EmailStr
    contact_phone: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str = Field(min_length=1, max_length=64)
    seat_limit: int | None = Field(default=None, ge=1, le=100_000)


class OrgRejectionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OrgStatusChangeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class BrandingUpdateRequest(BaseModel):
    accent_color: str | None = None
    email_footer_note: str | None = Field(default=None, max_length=500)

    @field_validator("accent_color")
    @classmethod
    def _check_hex(cls, value: str | None) -> str | None:
        if value and not _HEX_RE.match(value):
            raise ValueError("Accent colour must be a hex value such as #B4633A.")
        return value


class BrandingDetail(ORMModel):
    accent_color: str
    email_footer_note: str | None = None
    logo_url: str | None = None
    logo_updated_at: datetime | None = None


class OrgDetail(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    legal_name: str | None = None
    primary_domain: str | None = None
    status: str
    registration_source: str
    contact_name: str
    contact_email: str
    contact_phone: str | None = None
    country: str | None = None
    timezone: str
    seat_limit: int | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    user_count: int = 0
    branding: BrandingDetail | None = None
    # Set only by provision/approve, and only outside production — see
    # InviteResult.invite_url for why this is never populated in prod.
    invite_url: str | None = None


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    role: UserRole = UserRole.EMPLOYEE
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    manager_id: uuid.UUID | None = None

    @field_validator("role")
    @classmethod
    def _no_super_admin(cls, value: UserRole) -> UserRole:
        # Super Admin is a platform role with no organization. Allowing it to be
        # requested through a tenant-scoped endpoint would let a Client Admin
        # escalate straight past the tenancy boundary.
        if value == UserRole.SUPER_ADMIN:
            raise ValueError("Super Admin accounts cannot be created from an organization.")
        return value


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    role: UserRole | None = None
    manager_id: uuid.UUID | None = None

    @field_validator("role")
    @classmethod
    def _no_super_admin(cls, value: UserRole | None) -> UserRole | None:
        if value == UserRole.SUPER_ADMIN:
            raise ValueError("Super Admin cannot be assigned from an organization.")
        return value


class UserDetail(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID | None
    org_name: str | None = None
    email: str
    full_name: str
    job_title: str | None
    department: str | None
    role: str
    status: str
    mfa_enabled: bool
    manager_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime


class InviteResult(BaseModel):
    user: UserDetail
    invite_url: str | None = None
    email_sent: bool = False
