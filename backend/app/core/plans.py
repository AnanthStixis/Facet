"""Plan limits — one place defining what each pricing tier allows.

No payment gateway exists yet (see Organization.plan's docstring) — a Super
Admin sets an org's plan directly. These numbers are a business decision,
not architecture, and are expected to change; keeping them in one small
table here means changing a limit later is a one-line edit here, not a hunt
through every place that currently checks it by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import OrgPlan


@dataclass(frozen=True, slots=True)
class PlanLimits:
    # None means unlimited on both seat fields.
    employee_seats: int | None
    admin_seats: int | None
    # Client / Product / Service / Proposal Review. Employee & Management
    # Review are available on every plan, so there's no separate flag for
    # those — only the external kinds are ever gated.
    external_review: bool
    # Total feedback cycles ("feedback forms") this org can ever create.
    # None means unlimited. A lifetime cap, not monthly — same as the seat
    # caps above, there's no billing period yet to reset anything against.
    max_cycles: int | None


PLAN_LIMITS: dict[OrgPlan, PlanLimits] = {
    OrgPlan.STARTER: PlanLimits(employee_seats=50, admin_seats=1, external_review=False, max_cycles=100),
    OrgPlan.GROWTH: PlanLimits(employee_seats=150, admin_seats=3, external_review=True, max_cycles=500),
    OrgPlan.ENTERPRISE: PlanLimits(employee_seats=None, admin_seats=None, external_review=True, max_cycles=None),

}


def limits_for(plan: OrgPlan) -> PlanLimits:
    return PLAN_LIMITS[plan]


# The public-facing name for each tier — Starter/Growth/Enterprise internally
# (the OrgPlan enum, baked into the database) is never what a person should
# see; Basic/Standard/Enterprise is what's shown everywhere else (pricing
# page, signup form, org detail popups). Every user-facing message that
# names a plan should go through this, not org.plan.value.title(), or it
# silently reverts to the internal name.
PLAN_DISPLAY_NAMES: dict[OrgPlan, str] = {
    OrgPlan.STARTER: "Basic",
    OrgPlan.GROWTH: "Standard",
    OrgPlan.ENTERPRISE: "Enterprise",
}


def display_name_for(plan: OrgPlan) -> str:
    return PLAN_DISPLAY_NAMES[plan]