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


PLAN_LIMITS: dict[OrgPlan, PlanLimits] = {
    OrgPlan.STARTER: PlanLimits(employee_seats=50, admin_seats=1, external_review=False),
    OrgPlan.GROWTH: PlanLimits(employee_seats=150, admin_seats=3, external_review=True),
    OrgPlan.ENTERPRISE: PlanLimits(employee_seats=None, admin_seats=None, external_review=True),
}


def limits_for(plan: OrgPlan) -> PlanLimits:
    return PLAN_LIMITS[plan]