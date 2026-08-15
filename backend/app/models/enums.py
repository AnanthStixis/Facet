"""Domain enumerations.

These are stored as native Postgres enums so the database rejects nonsense
values, and so a report grouping by status cannot silently invent a category.
"""

from __future__ import annotations

from enum import StrEnum


class OrgStatus(StrEnum):
    PENDING = "pending"          # self-registered, awaiting Super Admin review
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class OrgRegistrationSource(StrEnum):
    SELF_SERVICE = "self_service"   # requires approval
    PROVISIONED = "provisioned"     # created by Super Admin, auto-approved


class UserRole(StrEnum):
    """Platform roles, ordered from most to least privileged.

    Super Admin is the only role that exists outside an organization; every
    other role is meaningless without an org_id.
    """

    SUPER_ADMIN = "super_admin"
    CLIENT_ADMIN = "client_admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, other: "UserRole") -> bool:
        return self.rank <= other.rank


_ROLE_RANK: dict[UserRole, int] = {
    UserRole.SUPER_ADMIN: 0,
    UserRole.CLIENT_ADMIN: 1,
    UserRole.MANAGER: 2,
    UserRole.EMPLOYEE: 3,
}


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"


class TargetType(StrEnum):
    """What a piece of feedback is *about*.

    This single polymorphic axis is the core of the product. Competing tools
    model employee review and customer survey as unrelated subsystems; here
    they are one table with a discriminator, which is what makes cross-domain
    analytics (does proposal quality track with the team that wrote it?)
    possible at all.
    """

    EMPLOYEE = "employee"
    MANAGER = "manager"
    TEAM = "team"
    DEPARTMENT = "department"
    CLIENT = "client"
    PRODUCT = "product"
    SERVICE = "service"
    PROPOSAL = "proposal"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TemplateScope(StrEnum):
    GLOBAL = "global"   # vendor-authored, offered to every organization
    ORG = "org"         # authored or cloned by a client organization


class CycleStatus(StrEnum):
    DRAFT = "draft"       # being set up, assignments editable
    OPEN = "open"         # reviewers can submit
    CLOSED = "closed"     # submissions rejected, results readable
    CANCELLED = "cancelled"


class InsightKind(StrEnum):
    TARGET_SUMMARY = "target_summary"     # what people said about one subject
    CYCLE_SUMMARY = "cycle_summary"       # themes across a whole round
    THEME_CLUSTER = "theme_cluster"
    RECOMMENDATION = "recommendation"     # Phase 6


class ModelKind(StrEnum):
    WIN_PROBABILITY = "win_probability"       # will this proposal be won
    SCORE_TREND = "score_trend"               # where is a subject's score heading
    DISENGAGEMENT_RISK = "disengagement_risk" # who is quietly checking out


class ModelStatus(StrEnum):
    FITTED = "fitted"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"


class FindingSeverity(StrEnum):
    """How loudly a recommendation should be presented.

    Kept to three levels on purpose. A five-level scale invites arguments about
    whether something is a 3 or a 4 and produces dashboards where everything is
    amber.
    """

    INFO = "info"
    ATTENTION = "attention"
    URGENT = "urgent"


class InsightStatus(StrEnum):
    READY = "ready"
    SUPPRESSED = "suppressed"   # below the anonymity threshold; nothing generated
    FAILED = "failed"
    STALE = "stale"             # inputs changed since generation


class SentimentLabel(StrEnum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"

    @classmethod
    def from_score(cls, score: float) -> "SentimentLabel":
        """Map a -1..1 score onto a label.

        Bands are deliberately wide at the centre: most workplace feedback is
        mildly positive, and a narrow neutral band would classify ordinary
        politeness as enthusiasm.
        """
        if score <= -0.6:
            return cls.VERY_NEGATIVE
        if score <= -0.15:
            return cls.NEGATIVE
        if score < 0.25:
            return cls.NEUTRAL
        if score < 0.65:
            return cls.POSITIVE
        return cls.VERY_POSITIVE


class ProposalStage(StrEnum):
    """Where a proposal sits in the sales process.

    Deliberately coarse. This is not a CRM and should not try to be one — it
    tracks only what is needed to ask for feedback at the right moment and to
    correlate that feedback with what actually happened.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    SHORTLISTED = "shortlisted"
    WON = "won"
    LOST = "lost"
    WITHDRAWN = "withdrawn"

    @property
    def is_decided(self) -> bool:
        return self in {ProposalStage.WON, ProposalStage.LOST, ProposalStage.WITHDRAWN}


class LossReason(StrEnum):
    """Why a proposal was lost.

    Structured rather than free text, because the entire value of this field is
    being able to group by it. "Too expensive" typed forty different ways
    answers nothing.
    """

    PRICE = "price"
    TIMELINE = "timeline"
    TECHNICAL_FIT = "technical_fit"
    RELATIONSHIP = "relationship"
    INCUMBENT = "incumbent"
    NO_DECISION = "no_decision"
    SCOPE_MISMATCH = "scope_mismatch"
    OTHER = "other"


class CycleAudience(StrEnum):
    """Who a feedback round asks.

    The same container serves both. An internal round reaches people through
    `feedback_assignments`; an external round reaches them through
    `campaign_recipients` and a one-time emailed link. Both write to
    `feedback_responses` against the same targets, which is why results,
    suppression, reports and exports needed no external-specific code.
    """

    INTERNAL = "internal"
    EXTERNAL = "external"
    MIXED = "mixed"


class RecipientStatus(StrEnum):
    PENDING = "pending"          # link generated, not yet sent
    SENT = "sent"
    OPENED = "opened"            # the form was fetched with a valid link
    SUBMITTED = "submitted"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Relationship(StrEnum):
    """How the reviewer relates to the person or thing being reviewed.

    This is what makes a 360 a 360: the same question answered from four
    directions is the product, and slicing results by direction is the first
    thing any HR lead asks for.
    """

    SELF = "self"
    MANAGER = "manager"           # reviewer manages the reviewee
    UPWARD = "upward"             # reviewee manages the reviewer
    PEER = "peer"
    SKIP_LEVEL = "skip_level"
    EXTERNAL = "external"         # a client contact, used from Phase 3


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    DECLINED = "declined"
    EXPIRED = "expired"


class AuditAction(StrEnum):
    ORG_REGISTERED = "org.registered"
    ORG_APPROVED = "org.approved"
    ORG_REJECTED = "org.rejected"
    ORG_SUSPENDED = "org.suspended"
    ORG_REACTIVATED = "org.reactivated"
    ORG_BRANDING_UPDATED = "org.branding_updated"
    ORG_PROFILE_UPDATED = "org.profile_updated"
    ORG_SETTINGS_UPDATED = "org.settings_updated"

    USER_INVITED = "user.invited"
    USER_ACTIVATED = "user.activated"
    USER_DISABLED = "user.disabled"
    USER_ENABLED = "user.enabled"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DELETED = "user.deleted"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    USER_PASSWORD_RESET_COMPLETED = "user.password_reset_completed"

    AUTH_LOGIN_SUCCEEDED = "auth.login_succeeded"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESHED = "auth.token_refreshed"
    AUTH_TOKEN_REUSE_DETECTED = "auth.token_reuse_detected"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_MFA_ENROLLED = "auth.mfa_enrolled"
    AUTH_MFA_DISABLED = "auth.mfa_disabled"
    AUTH_SESSION_REVOKED = "auth.session_revoked"

    CATEGORY_CREATED = "category.created"
    CATEGORY_UPDATED = "category.updated"

    TEMPLATE_CREATED = "template.created"
    TEMPLATE_PUBLISHED = "template.published"
    TEMPLATE_ARCHIVED = "template.archived"
    TEMPLATE_DELETED = "template.deleted"

    TEMPLATE_CLONED = "template.cloned"
    TEMPLATE_DRAFT_SAVED = "template.draft_saved"
    TEMPLATE_ENABLED = "template.enabled"
    TEMPLATE_DISABLED = "template.disabled"

    CYCLE_CREATED = "cycle.created"
    CYCLE_OPENED = "cycle.opened"
    CYCLE_CLOSED = "cycle.closed"
    CYCLE_DELETED = "cycle.deleted"
    CYCLE_CANCELLED = "cycle.cancelled"
    ASSIGNMENTS_GENERATED = "cycle.assignments_generated"
    RESPONSE_SUBMITTED = "cycle.response_submitted"

    CAMPAIGN_CREATED = "campaign.created"
    CAMPAIGN_DELETED = "campaign.deleted"
    CAMPAIGN_LAUNCHED = "campaign.launched"
    RECIPIENTS_ADDED = "campaign.recipients_added"
    INVITATIONS_SENT = "campaign.invitations_sent"
    LINK_REVOKED = "campaign.link_revoked"
    EXTERNAL_RESPONSE = "campaign.external_response"
    CONTACT_UNSUBSCRIBED = "campaign.contact_unsubscribed"

    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_SUBMITTED = "proposal.submitted"
    PROPOSAL_FEEDBACK_REQUESTED = "proposal.feedback_requested"
    PROPOSAL_DECIDED = "proposal.decided"

    REMINDERS_SENT = "reminder.sent"
    ESCALATION_SENT = "reminder.escalated"

    AI_SENTIMENT_ANALYSED = "ai.sentiment_analysed"
    AI_SUMMARY_GENERATED = "ai.summary_generated"
    AI_SUMMARY_SUPPRESSED = "ai.summary_suppressed"
    AI_BUDGET_EXHAUSTED = "ai.budget_exhausted"
    AI_INJECTION_DETECTED = "ai.injection_detected"
    AI_RECOMMENDATIONS_BUILT = "ai.recommendations_built"
    ANALYTICS_MODEL_FITTED = "analytics.model_fitted"
    ANALYTICS_INSUFFICIENT_DATA = "analytics.insufficient_data"

    REPORT_EXPORTED = "report.exported"
    AI_INSIGHT_GENERATED = "ai.insight_generated"


class AuditSeverity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    ALERT = "alert"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"
