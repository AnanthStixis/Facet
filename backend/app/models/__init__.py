"""Model registry.

Importing this package registers every mapper with the declarative Base, which
is what Alembic autogenerate and the RLS coverage test both rely on.
"""

from app.db.base import Base
from app.models.audit import AuditLog
from app.models.auth import LoginAttempt, RefreshToken, SessionFamily
from app.models.analytics import AnalyticsModel
from app.models.campaign import CampaignRecipient
from app.models.insight import AiInsight
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.catalog import (
    Category,
    Contact,
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.organization import OrgBranding, Organization
from app.models.proposal import Proposal
from app.models.user import Invitation, User

__all__ = [
    "Base",
    "AiInsight",
    "AnalyticsModel",
    "AuditLog",
    "CampaignRecipient",
    "Category",
    "Contact",
    "FeedbackAssignment",
    "FeedbackResponse",
    "FeedbackTarget",
    "ReviewCycle",
    "FeedbackTemplate",
    "FeedbackTemplateVersion",
    "Invitation",
    "LoginAttempt",
    "OrgBranding",
    "Organization",
    "Proposal",
    "RefreshToken",
    "SessionFamily",
    "User",
]


def tenant_scoped_tables() -> list[str]:
    """Tables that must carry a row level security policy."""
    return sorted(
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if getattr(mapper.class_, "__tenant_scoped__", False)
    )
