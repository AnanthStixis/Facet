"""Per-organization settings.

Stored in the `organizations.settings` JSONB column rather than in columns,
because these are policy knobs that will keep being added and every addition
would otherwise be a migration.

**One rule governs the whole file: a tenant may make a threshold stricter, and
may never make it looser.**

That asymmetry is deliberate. The anonymity threshold, the AI summary floor and
the model minimums are safety properties, not preferences. A customer who wants
to hear from six people before results appear is exercising judgement; a
customer who wants to hear from one is removing a protection from their own
staff, usually under pressure to see a number. The platform floor stays put and
the setting can only raise it.

Reminder cadence has no such floor because there is no safety property at
stake — over-reminding is rude, not dangerous — so it is bounded only by
sanity limits.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings as platform


class ReminderSettings(BaseModel):
    """How persistently non-responders are chased."""

    enabled: bool = True
    cooldown_days: int = Field(default=3, ge=1, le=30)
    max_reminders: int = Field(default=2, ge=0, le=10)
    quiet_period_hours: int = Field(default=24, ge=0, le=168)
    escalate_to_owner: bool = True


class AnonymitySettings(BaseModel):
    """Defaults applied to newly created templates and rounds."""

    # 0 disables suppression entirely — a deliberate opt-out, not a bug. See
    # TemplateCreateRequest.min_responses_to_reveal for the same reasoning.
    default_min_responses_to_reveal: int = Field(default=0, ge=0, le=50)
    # Anonymous by default for upward feedback. Recorded as a setting because
    # it is a policy decision the customer should own, not a hidden constant.
    upward_anonymous_by_default: bool = True


class AiSettings(BaseModel):
    enabled: bool = True
    min_responses_for_summary: int = Field(default=4, ge=2, le=50)
    monthly_token_budget: int = Field(default=2_000_000, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def _not_below_platform_floor(self) -> "AiSettings":
        floor = platform.ai_min_responses_for_summary
        if self.min_responses_for_summary < floor:
            raise ValueError(
                f"The summary threshold cannot be lower than the platform "
                f"minimum of {floor}. You may raise it."
            )
        return self


class AuditSettings(BaseModel):
    # Zero means keep forever, which is the safe default: deleting audit
    # history should be a decision someone makes, never something that happens
    # because nobody set a value.
    retention_days: int = Field(default=0, ge=0, le=3650)

    @model_validator(mode="after")
    def _not_recklessly_short(self) -> "AuditSettings":
        if 0 < self.retention_days < 30:
            raise ValueError(
                "Audit retention below 30 days would discard records before "
                "most incidents are investigated."
            )
        return self


class EmailSettings(BaseModel):
    """Subject-line overrides for the two client-facing sends.

    Only the subject is customisable, not the body: the body carries the
    legal and functional content (the one-time link, its expiry, the
    unsubscribe notice) that must stay consistent for every tenant, but the
    subject line is what a recipient's inbox shows before they open anything,
    and a generic one gets ignored. `{org_name}` and `{subject_label}` are the
    only placeholders substituted — anything else in the string is used
    literally, including a stray `{` from a customer who did not mean it as a
    placeholder.
    """

    invitation_subject: str | None = Field(default=None, max_length=200)
    feedback_request_subject: str | None = Field(default=None, max_length=200)


class OrgSettings(BaseModel):
    """The complete, validated settings document for one organization."""

    reminders: ReminderSettings = Field(default_factory=ReminderSettings)
    anonymity: AnonymitySettings = Field(default_factory=AnonymitySettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)

    @classmethod
    def load(cls, raw: dict | None) -> "OrgSettings":
        """Read stored settings, falling back to defaults for anything absent.

        Tolerant on read by design: a settings document written before a field
        existed must not break the organization that owns it.
        """
        if not raw:
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:  # noqa: BLE001
            # A stored document that no longer validates (a lowered floor after
            # a platform change, say) falls back to defaults rather than taking
            # the tenant down. The next save will rewrite it correctly.
            return cls()

    def effective_summary_threshold(self, cycle_threshold: int) -> int:
        """The strictest of: the round, the tenant setting, the platform floor."""
        return max(
            cycle_threshold,
            self.ai.min_responses_for_summary,
            platform.ai_min_responses_for_summary,
        )


class SettingsUpdateRequest(BaseModel):
    """A partial update. Only the sections supplied are replaced."""

    reminders: ReminderSettings | None = None
    anonymity: AnonymitySettings | None = None
    ai: AiSettings | None = None
    audit: AuditSettings | None = None
    email: EmailSettings | None = None


class SettingsResponse(BaseModel):
    settings: OrgSettings
    # The floors are returned alongside the values so the UI can explain why a
    # field will not go lower, rather than just rejecting the input.
    platform_floors: dict[str, int]
