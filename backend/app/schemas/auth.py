"""Authentication request and response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    remember_device: bool = False


class BrandingSummary(ORMModel):
    accent_color: str
    logo_url: str | None = None


class OrgSummary(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    timezone: str
    branding: BrandingSummary | None = None


class UserSummary(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    job_title: str | None = None
    role: str
    status: str
    must_change_password: bool
    last_login_at: datetime | None = None


class SessionResponse(BaseModel):
    """What the client gets after a successful sign-in or refresh.

    The refresh token is absent on purpose: it is delivered as an httpOnly
    cookie the JavaScript cannot read, which is what stops a cross-site
    scripting bug from turning into a permanent account takeover.
    """

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    csrf_token: str
    user: UserSummary | None = None
    organization: OrgSummary | None = None


PASSWORD_MIN_LENGTH = 6

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)
    full_name: str | None = None


class PasswordResetCompleteRequest(BaseModel):
    token: str
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ActiveSession(ORMModel):
    id: uuid.UUID
    device_label: str | None
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime | None
    is_current: bool = False
