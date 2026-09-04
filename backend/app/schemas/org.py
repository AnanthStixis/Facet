"""Organization and user-management payloads."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import OrgPlan, UserRole
from app.schemas.common import LookupItem, ORMModel

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
    # The licence/plan the applicant is asking for. Purely a signal for the
    # Super Admin reviewing the request — it is stored, never applied
    # automatically. The authoritative `plan` (and `seat_limit`) are set on
    # Organization only when a Super Admin approves, via OrgApprovalRequest.
    requested_plan: OrgPlan | None = None


class OrgSelfRegisterRequest(OrgRegistrationRequest):
    """Instant self-registration — the same fields as the pending-review
    flow, plus a password, since there's no separate "click an email link"
    step here: the org goes live and the person is signed in immediately.

    `plan` is taken directly from whatever the person picks on the form —
    there is no payment gateway wired up yet, so nothing actually verifies
    it. Defaults to Starter if omitted."""

    password: str = Field(min_length=6, max_length=256)
    plan: OrgPlan = OrgPlan.STARTER


class OrgProvisionRequest(OrgRegistrationRequest):
    """Super Admin direct provisioning. Auto-approved, since it is pre-vetted."""

    # Pre-vetted by the Super Admin doing the provisioning, unlike public
    # self-registration — a phone number is a nice-to-have here, not a
    # prerequisite for trusting the request.
    contact_phone: str | None = Field(default=None, max_length=40)
    slug: str | None = Field(default=None, max_length=80)
    admin_full_name: str = Field(min_length=2, max_length=150)
    admin_email: EmailStr
    plan: OrgPlan = OrgPlan.STARTER
    # Number of user licences granted to the tenant. Nullable = unlimited,
    # matching Organization.seat_limit; enforced in api/v1/users.py's
    # _seat_limit_reason() whenever a user is invited or added.
    seat_limit: int | None = Field(default=None, ge=1, le=100000)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        if value and not _SLUG_RE.match(value):
            raise ValueError(
                "Slug must be lowercase letters, digits and hyphens, 3-64 characters."
            )
        return value


class OrgApprovalRequest(BaseModel):
    """Super Admin decision on a pending self-registration.

    The requesting organization never chooses its own plan or licence
    count on the public form (see OrgRegistrationRequest) — both are set
    here, by the Super Admin, at the moment of approval.
    """

    admin_full_name: str = Field(min_length=2, max_length=150)
    admin_email: EmailStr
    plan: OrgPlan = OrgPlan.STARTER
    # Licence count for this tenant. None = unlimited seats.
    seat_limit: int | None = Field(default=None, ge=1, le=100000)
    note: str | None = Field(default=None, max_length=500)


class OrgInviteAdminRequest(BaseModel):
    """Invite an additional Client Admin into an already-active organization,
    from that org's Edit popup. Distinct from OrgApprovalRequest (pending ->
    active, one-time) and OrgProvisionRequest's create-time admin fields —
    this is the third path: an org that is already active getting a new
    Client Admin added to it later."""

    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr


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
    plan: OrgPlan
    seat_limit: int | None = Field(default=None, ge=1, le=100000)


class OrgRejectionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OrgStatusChangeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OrgReactivateRequest(BaseModel):
    # Unlike suspend/reject, reactivating isn't adverse to anyone — recording
    # why is nice-to-have for the audit trail, not something worth blocking
    # the action over.
    reason: str | None = Field(default=None, max_length=500)


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
    timezone: str
    plan: str
    seat_limit: int | None = None
    requested_plan: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    suspension_reason: str | None = None
    created_at: datetime
    user_count: int = 0
    branding: BrandingDetail | None = None


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    role: UserRole = UserRole.EMPLOYEE
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    manager_ids: list[uuid.UUID] | None = None

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
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole | None = None
    manager_ids: list[uuid.UUID] | None = None

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
    phone: str | None = None
    role: str
    status: str
    manager_ids: list[uuid.UUID] = Field(default_factory=list)
    # Display-ready form of manager_ids above — actual names/job titles for
    # the People-page table's Manager column, which needs something to show
    # on screen rather than bare ids. manager_ids stays for what already
    # consumes it (EditUserForm's manager picker, which only needs ids to
    # pre-check boxes); this is additive, not a replacement.
    managers: list[LookupItem] = Field(default_factory=list)
    last_login_at: datetime | None
    created_at: datetime
    feedback_count: int = 0


class InviteResult(BaseModel):
    user: UserDetail
    invite_url: str | None = None
    email_sent: bool = False