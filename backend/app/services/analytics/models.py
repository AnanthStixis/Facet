"""Fitting and scoring the predictive models (Module H.2).

Three models, all small, all interpretable, all gated:

  * **Win probability** — logistic regression over proposal features including
    the prospect's own rating. This is the model that only exists because the
    product holds both the feedback and the outcome.
  * **Score trend** — least-squares slope of a subject's scores across cycles.
  * **Disengagement risk** — a transparent weighted signal, not a classifier,
    because there is no labelled ground truth for "about to leave" and
    pretending otherwise would be dishonest.

Logistic regression rather than anything fancier is a deliberate choice. On
tenant-sized data a gradient-boosted anything will overfit beautifully, and a
coefficient a human can read ("a one-point rise in prospect rating moves win
probability by X") is worth more here than a marginal accuracy gain nobody can
interrogate.
"""

from __future__ import annotations

import math
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.analytics import AnalyticsModel
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    ModelKind,
    ModelStatus,
    ProposalStage,
    Relationship,
)
from app.models.proposal import Proposal
from app.services import audit
from app.services.analytics import sufficiency

log = get_logger("facet.analytics")

# scikit-learn 1.6 passes an `iprint` option that SciPy 1.18 no longer accepts,
# producing an OptimizeWarning per fold on every fit. It is cosmetic — the
# optimisation converges normally — but it buries real output, so it is
# silenced narrowly rather than by blanket-ignoring OptimizeWarning.
warnings.filterwarnings(
    "ignore",
    message="Unknown solver options: iprint",
    category=RuntimeWarning,
)
try:  # pragma: no cover - depends on the installed SciPy
    from scipy.optimize import OptimizeWarning

    warnings.filterwarnings(
        "ignore", message="Unknown solver options: iprint", category=OptimizeWarning
    )
except Exception:  # noqa: BLE001
    pass

WIN_FEATURES = [
    "prospect_score",
    "value_log",
    "effort_log",
    "has_feedback",
    "days_to_decision",
]


@dataclass
class FitOutcome:
    kind: ModelKind
    status: ModelStatus
    reason: str | None = None
    metrics: dict = field(default_factory=dict)
    n_samples: int = 0


# --- Feature extraction -----------------------------------------------------

def _log1p(value: float | None) -> float:
    return math.log1p(max(0.0, float(value or 0.0)))


async def _proposal_rows(session: AsyncSession, org_id: uuid.UUID) -> list[dict]:
    """Decided proposals with their prospect rating, if any."""
    scores = (
        select(
            FeedbackResponse.target_id,
            func.avg(FeedbackResponse.overall_score).label("score"),
        )
        .group_by(FeedbackResponse.target_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Proposal.id,
                Proposal.stage,
                Proposal.value_amount,
                Proposal.estimated_effort_days,
                Proposal.submitted_at,
                Proposal.decided_at,
                scores.c.score,
            )
            .select_from(Proposal)
            .join(scores, scores.c.target_id == Proposal.target_id, isouter=True)
            .where(
                Proposal.org_id == org_id,
                Proposal.stage.in_([ProposalStage.WON, ProposalStage.LOST]),
            )
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _proposal_rows_open(session: AsyncSession, org_id: uuid.UUID) -> list[dict]:
    """Proposals still awaiting a decision, with their prospect rating."""
    scores = (
        select(
            FeedbackResponse.target_id,
            func.avg(FeedbackResponse.overall_score).label("score"),
        )
        .group_by(FeedbackResponse.target_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Proposal.id,
                Proposal.reference,
                Proposal.title,
                Proposal.client_name,
                Proposal.stage,
                Proposal.value_amount,
                Proposal.estimated_effort_days,
                Proposal.submitted_at,
                Proposal.decided_at,
                scores.c.score,
            )
            .select_from(Proposal)
            .join(scores, scores.c.target_id == Proposal.target_id, isouter=True)
            .where(
                Proposal.org_id == org_id,
                Proposal.stage.in_(
                    [ProposalStage.SUBMITTED, ProposalStage.SHORTLISTED]
                ),
            )
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _win_features(row: dict) -> list[float]:
    submitted = row.get("submitted_at")
    decided = row.get("decided_at")
    days = (
        (decided - submitted).days
        if submitted and decided and decided > submitted
        else 0
    )
    score = row.get("score")
    return [
        float(score) if score is not None else 0.0,
        _log1p(row.get("value_amount")),
        _log1p(row.get("estimated_effort_days")),
        1.0 if score is not None else 0.0,
        _log1p(days),
    ]


# --- Win probability --------------------------------------------------------

async def fit_win_probability(
    session: AsyncSession, *, org_id: uuid.UUID
) -> FitOutcome:
    rows = await _proposal_rows(session, org_id)
    labels = [1 if row["stage"] == ProposalStage.WON else 0 for row in rows]
    n_samples = len(rows)
    n_positive = sum(labels)

    verdict = sufficiency.check_samples(
        ModelKind.WIN_PROBABILITY, n_samples=n_samples, n_positive=n_positive
    )
    if not verdict.ok:
        return await _store_refusal(
            session,
            org_id=org_id,
            kind=ModelKind.WIN_PROBABILITY,
            reason=verdict.reason or "insufficient data",
            n_samples=n_samples,
            n_positive=n_positive,
            detail=verdict.detail,
        )

    features = np.array([_win_features(row) for row in rows], dtype=float)
    targets = np.array(labels, dtype=int)

    scaler = StandardScaler().fit(features)
    scaled = scaler.transform(features)

    # Regularised, because on a few dozen rows an unregularised fit will find
    # a separating hyperplane through the noise and report perfect accuracy.
    estimator = LogisticRegression(C=0.5, max_iter=1000, solver="lbfgs")

    folds = min(5, n_positive, n_samples - n_positive)
    baseline = max(n_positive, n_samples - n_positive) / n_samples
    try:
        cv = cross_val_score(
            estimator,
            scaled,
            targets,
            cv=StratifiedKFold(n_splits=max(2, folds), shuffle=True, random_state=7),
            scoring="accuracy",
        )
        cv_score = float(cv.mean())
    except Exception as exc:  # noqa: BLE001
        return await _store_refusal(
            session,
            org_id=org_id,
            kind=ModelKind.WIN_PROBABILITY,
            reason=f"Cross-validation could not be completed ({exc}).",
            n_samples=n_samples,
            n_positive=n_positive,
        )

    performance = sufficiency.check_performance(cv_score=cv_score, baseline=baseline)
    if not performance.ok:
        return await _store_refusal(
            session,
            org_id=org_id,
            kind=ModelKind.WIN_PROBABILITY,
            reason=performance.reason or "no lift over baseline",
            n_samples=n_samples,
            n_positive=n_positive,
            detail=performance.detail,
        )

    estimator.fit(scaled, targets)
    model = await _upsert(session, org_id=org_id, kind=ModelKind.WIN_PROBABILITY)
    model.status = ModelStatus.FITTED
    model.algorithm = "logistic_regression"
    model.reason = None
    model.n_samples = n_samples
    model.n_positive = n_positive
    model.n_features = len(WIN_FEATURES)
    model.feature_names = WIN_FEATURES
    model.coefficients = {
        "intercept": float(estimator.intercept_[0]),
        "weights": [float(value) for value in estimator.coef_[0]],
        "mean": [float(value) for value in scaler.mean_],
        "scale": [float(value) for value in scaler.scale_],
    }
    model.metrics = {
        "cv_accuracy": round(cv_score, 4),
        "baseline_accuracy": round(baseline, 4),
        "lift": round(cv_score - baseline, 4),
        "folds": max(2, folds),
        "confidence": sufficiency.confidence_band(cv_score, n_samples),
    }
    model.baseline_rate = round(n_positive / n_samples, 4)
    model.trained_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.ANALYTICS_MODEL_FITTED,
        summary=(
            f"Win probability model fitted on {n_samples} decided proposals "
            f"({cv_score:.0%} cross-validated)"
        ),
        org_id=org_id,
        context=model.metrics,
    )
    return FitOutcome(
        kind=ModelKind.WIN_PROBABILITY,
        status=ModelStatus.FITTED,
        metrics=model.metrics,
        n_samples=n_samples,
    )


def score_win_probability(model: AnalyticsModel, row: dict) -> float | None:
    """Apply stored coefficients. Returns None for an unusable model."""
    if not model.is_usable:
        return None
    weights = model.coefficients.get("weights") or []
    mean = model.coefficients.get("mean") or []
    scale = model.coefficients.get("scale") or []
    if not weights:
        return None

    raw = _win_features(row)
    total = float(model.coefficients.get("intercept", 0.0))
    for index, value in enumerate(raw):
        centred = (value - mean[index]) / (scale[index] or 1.0)
        total += centred * weights[index]
    return 1.0 / (1.0 + math.exp(-total))


# --- Score trend ------------------------------------------------------------

async def score_trend(
    session: AsyncSession, *, org_id: uuid.UUID, target_id: uuid.UUID
) -> dict:
    """Least-squares slope of a subject's average score across rounds.

    Not stored as a model: it is a per-subject calculation over a handful of
    points, and fitting a global estimator over three-point series would be
    theatre.
    """
    rows = (
        await session.execute(
            select(
                ReviewCycle.id,
                ReviewCycle.name,
                func.min(ReviewCycle.opened_at).label("at"),
                func.avg(FeedbackResponse.overall_score).label("score"),
                func.count().label("n"),
            )
            .select_from(FeedbackResponse)
            .join(ReviewCycle, ReviewCycle.id == FeedbackResponse.cycle_id)
            .where(
                FeedbackResponse.org_id == org_id,
                FeedbackResponse.target_id == target_id,
                FeedbackResponse.relationship_type != Relationship.SELF,
            )
            .group_by(ReviewCycle.id, ReviewCycle.name)
            .order_by(func.min(ReviewCycle.opened_at))
        )
    ).mappings().all()

    points = [
        {
            "cycle": row["name"],
            "at": row["at"],
            "score": round(float(row["score"]), 2),
            "responses": int(row["n"]),
        }
        for row in rows
        if row["score"] is not None
    ]

    verdict = sufficiency.check_samples(
        ModelKind.SCORE_TREND, n_samples=len(points)
    )
    if not verdict.ok:
        return {
            "available": False,
            "reason": verdict.reason,
            "points": points,
        }

    values = np.array([point["score"] for point in points], dtype=float)
    index = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(index, values, 1)

    return {
        "available": True,
        "points": points,
        "slope_per_cycle": round(float(slope), 3),
        "direction": (
            "improving" if slope > 0.08 else "declining" if slope < -0.08 else "steady"
        ),
        # A projection one cycle out, clamped to the scale and explicitly
        # labelled a projection. No further than one step: extrapolating a
        # three-point line four cycles ahead is astrology.
        "projected_next": round(
            float(max(1.0, min(5.0, intercept + slope * len(values)))), 2
        ),
        "cycles": len(points),
    }


# --- Disengagement risk -----------------------------------------------------

async def disengagement_signals(
    session: AsyncSession, *, org_id: uuid.UUID
) -> dict:
    """A transparent risk signal, deliberately not a classifier.

    There is no labelled ground truth here — nobody records "was about to
    resign" — so a supervised model would be fitting to a target that does not
    exist. Instead this is a weighted, fully inspectable combination of
    observable behaviours, presented as a signal to look into rather than a
    prediction. Every contributing factor is returned alongside the score so a
    manager can disagree with it.
    """
    rows = (
        await session.execute(
            select(
                FeedbackAssignment.reviewer_user_id,
                func.count().label("assigned"),
                func.count()
                .filter(FeedbackAssignment.status == AssignmentStatus.SUBMITTED)
                .label("submitted"),
                func.count()
                .filter(FeedbackAssignment.status == AssignmentStatus.DECLINED)
                .label("declined"),
            )
            .where(
                FeedbackAssignment.org_id == org_id,
                FeedbackAssignment.reviewer_user_id.isnot(None),
            )
            .group_by(FeedbackAssignment.reviewer_user_id)
        )
    ).mappings().all()

    verdict = sufficiency.check_samples(
        ModelKind.DISENGAGEMENT_RISK,
        n_samples=sum(row["assigned"] for row in rows),
        n_positive=sum(row["submitted"] for row in rows),
    )
    if not verdict.ok:
        return {"available": False, "reason": verdict.reason, "people": []}

    people = []
    for row in rows:
        assigned = row["assigned"] or 0
        if assigned == 0:
            continue
        participation = row["submitted"] / assigned
        declined_rate = row["declined"] / assigned

        factors = []
        score = 0.0
        if participation < 0.5:
            score += 0.5
            factors.append(
                f"responded to {row['submitted']} of {assigned} feedback requests"
            )
        if declined_rate > 0.2:
            score += 0.3
            factors.append(f"declined {row['declined']} requests")
        if participation < 0.25:
            score += 0.2
            factors.append("has largely stopped participating")

        if score > 0:
            people.append(
                {
                    "user_id": str(row["reviewer_user_id"]),
                    "signal": round(min(1.0, score), 2),
                    "participation_pct": round(participation * 100),
                    "factors": factors,
                }
            )

    people.sort(key=lambda item: -item["signal"])
    return {
        "available": True,
        "method": "weighted_participation_signal",
        "caveat": (
            "A participation signal, not a prediction. It reflects who has "
            "stopped engaging with feedback, which has many innocent causes."
        ),
        "people": people[:20],
    }


# --- Storage helpers --------------------------------------------------------

async def _upsert(
    session: AsyncSession, *, org_id: uuid.UUID, kind: ModelKind
) -> AnalyticsModel:
    model = (
        await session.execute(
            select(AnalyticsModel).where(
                AnalyticsModel.org_id == org_id, AnalyticsModel.kind == kind
            )
        )
    ).scalar_one_or_none()
    if model is None:
        model = AnalyticsModel(
            org_id=org_id,
            kind=kind,
            trained_at=datetime.now(UTC),
            # The check constraint requires every non-fitted row to explain
            # itself, including this transient one. Inserting a placeholder is
            # correct rather than annoying: a row that exists with no verdict
            # is exactly the ambiguous state the constraint exists to forbid.
            reason="Not yet trained.",
        )
        session.add(model)
        await session.flush()
    return model


async def _store_refusal(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: ModelKind,
    reason: str,
    n_samples: int,
    n_positive: int = 0,
    detail: dict | None = None,
) -> FitOutcome:
    """Record that the model declined, and why.

    Stored rather than discarded so the UI can explain the absence, and so the
    decision is auditable — "why is there no forecast" has an answer.
    """
    model = await _upsert(session, org_id=org_id, kind=kind)
    model.status = ModelStatus.INSUFFICIENT_DATA
    model.algorithm = "none"
    model.reason = reason
    model.n_samples = n_samples
    model.n_positive = n_positive
    model.n_features = 0
    model.feature_names = []
    model.coefficients = {}
    model.metrics = {"minimums": sufficiency.describe_minimums(kind), **(detail or {})}
    model.baseline_rate = None
    model.trained_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.ANALYTICS_INSUFFICIENT_DATA,
        summary=f"{kind} declined to fit: {reason}",
        org_id=org_id,
        context={"n_samples": n_samples, "kind": str(kind)},
    )
    return FitOutcome(
        kind=kind,
        status=ModelStatus.INSUFFICIENT_DATA,
        reason=reason,
        n_samples=n_samples,
    )
