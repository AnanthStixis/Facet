"""The sufficiency gate.

Every predictive model in this product asks this module for permission before
it reports anything, and takes no for an answer.

The reasoning, recorded because it is the reason Phase 6 looks the way it does:

    A win-probability model fitted to eight proposals will happily produce
    "73%". The number is arithmetically real and epistemically worthless — it
    is a restatement of noise. But it will be repeated in a pipeline review,
    because a percentage on a screen carries authority that a sample size in a
    tooltip does not.

So the refusal is structural rather than advisory. Below the minimums the model
is not fitted, no coefficients are stored, and the API returns the reason
instead of a number. There is no override flag, because an override flag is
what someone reaches for at 5pm before a board meeting.

The minimums below are not statistically magical; they are the point at which a
cross-validated estimate stops being embarrassing. They are deliberately
conservative: the cost of refusing too long is a missing feature, and the cost
of refusing too little is a confident wrong answer about someone's job or a
deal.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ModelKind

# Per model: total samples, and where relevant the minimum in the smaller
# class. A logistic regression on 40 proposals of which 2 were lost knows
# almost nothing about losing.
MINIMUMS: dict[ModelKind, dict[str, int]] = {
    ModelKind.WIN_PROBABILITY: {"samples": 30, "per_class": 8},
    ModelKind.SCORE_TREND: {"samples": 3, "per_class": 0},   # 3 cycles per subject
    ModelKind.DISENGAGEMENT_RISK: {"samples": 20, "per_class": 5},
}

# A model that cannot beat "always guess the majority" by this margin is not
# adding information, whatever its accuracy looks like in isolation.
MIN_LIFT_OVER_BASELINE = 0.05


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    reason: str | None = None
    detail: dict | None = None


def check_samples(
    kind: ModelKind, *, n_samples: int, n_positive: int | None = None
) -> Verdict:
    """Is there enough history to fit this model at all?"""
    limits = MINIMUMS[kind]
    needed = limits["samples"]

    if n_samples < needed:
        short = needed - n_samples
        return Verdict(
            ok=False,
            reason=(
                f"Not enough history yet: {n_samples} of the {needed} records "
                f"needed. {short} more required before a prediction would mean "
                f"anything."
            ),
            detail={"have": n_samples, "need": needed},
        )

    per_class = limits["per_class"]
    if per_class and n_positive is not None:
        n_negative = n_samples - n_positive
        smaller = min(n_positive, n_negative)
        if smaller < per_class:
            which = "won" if n_positive < n_negative else "lost"
            return Verdict(
                ok=False,
                reason=(
                    f"The outcomes are too one-sided to learn from: only "
                    f"{smaller} {which}. At least {per_class} of each outcome "
                    f"are needed."
                ),
                detail={"smaller_class": smaller, "need": per_class},
            )

    return Verdict(ok=True)


def check_performance(
    *, cv_score: float, baseline: float, metric: str = "accuracy"
) -> Verdict:
    """Did the fitted model actually learn anything?

    Compared against the majority-class baseline, not against zero. A model
    that is 82% accurate where 80% of proposals are won has learned almost
    nothing, and reporting the 82% would be misleading.
    """
    lift = cv_score - baseline
    if lift < MIN_LIFT_OVER_BASELINE:
        return Verdict(
            ok=False,
            reason=(
                f"The model does not beat simply guessing the most common "
                f"outcome ({metric} {cv_score:.0%} against a baseline of "
                f"{baseline:.0%}). Predictions would be noise dressed as "
                f"insight."
            ),
            detail={"cv_score": round(cv_score, 4), "baseline": round(baseline, 4)},
        )
    return Verdict(ok=True, detail={"lift": round(lift, 4)})


def confidence_band(cv_score: float, n_samples: int) -> str:
    """A plain-English confidence label to show beside any number.

    Deliberately coarse and deliberately pessimistic. The alternative — a
    decimal-precision confidence interval — gets read as precision by exactly
    the audience least equipped to interpret it.
    """
    if n_samples < 60 or cv_score < 0.65:
        return "low"
    if n_samples < 150 or cv_score < 0.75:
        return "moderate"
    return "reasonable"


def describe_minimums(kind: ModelKind) -> dict:
    return dict(MINIMUMS[kind])
