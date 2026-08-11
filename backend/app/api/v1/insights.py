"""Recommendations and predictive analytics endpoints (Module H.2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, ManagerUser, rebind_tenant
from app.core.errors import NotFound, ValidationFailed
from app.db.tenancy import TenantContext, bind_tenant
from app.models.analytics import AnalyticsModel
from app.models.enums import InsightKind, ModelKind, ModelStatus, ProposalStage
from app.models.insight import AiInsight
from app.models.proposal import Proposal
from app.services.analytics import models as analytics_models
from app.services.analytics import recommendations, sufficiency, themes as theme_service

router = APIRouter(prefix="/insights", tags=["insights"])


async def _resolve_org(session: DbSession, actor, org_id: uuid.UUID | None) -> uuid.UUID:
    """Which tenant's insights this request is about.

    Recommendations and predictive models are inherently per-tenant — a
    win-probability model fitted across every customer's proposals at once
    would blend unrelated businesses into one meaningless number. A Client
    Admin or Manager belongs to exactly one organization and always gets that
    one; the `org_id` query parameter is accepted only from a Super Admin, who
    has no organization of their own and must say which tenant they mean.

    A non-super-admin's own `actor.org_id` is used unconditionally — the
    parameter is never trusted from that caller, or a Client Admin could pass
    another tenant's id and read across the boundary.
    """
    if actor.org_id is not None:
        return actor.org_id
    if org_id is None:
        raise ValidationFailed(
            "Choose an organization to view its insights.", needs_org=True
        )
    # Re-bind the transaction to the chosen tenant so every query after this
    # point is scoped by ordinary row level security rather than by an
    # application-level filter that a future change could forget to apply.
    await bind_tenant(session, TenantContext(org_id=org_id, is_super_admin=True))
    return org_id


@router.get("/recommendations")
async def read_recommendations(
    session: DbSession, actor: ManagerUser, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """The stored attention list."""
    org = await _resolve_org(session, actor, org_id)
    insight = (
        await session.execute(
            select(AiInsight).where(
                AiInsight.kind == InsightKind.RECOMMENDATION,
                AiInsight.subject_id == org,
            )
        )
    ).scalar_one_or_none()
    if insight is None:
        return {"status": "absent", "findings": []}
    return {
        "status": "ready",
        **insight.payload,
        "generated_at": insight.generated_at,
        "provider": insight.provider,
    }


@router.post("/recommendations/rebuild")
async def rebuild_recommendations(
    session: DbSession, actor: AdminUser, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    org = await _resolve_org(session, actor, org_id)
    result = await recommendations.generate(session, org_id=org)
    await session.commit()
    return result


@router.get("/models")
async def list_models(
    session: DbSession, actor: ManagerUser, org_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Every model, fitted or refused, with the reason either way.

    Refusals are returned rather than hidden. "There is no forecast because
    there are only 8 decided proposals" is a more useful thing to show a user
    than an empty panel.
    """
    org = await _resolve_org(session, actor, org_id)
    rows = (
        (
            await session.execute(
                select(AnalyticsModel).where(AnalyticsModel.org_id == org)
            )
        )
        .scalars()
        .all()
    )
    known = {row.kind: row for row in rows}

    output = []
    for kind in ModelKind:
        model = known.get(kind)
        if model is None:
            output.append(
                {
                    "kind": str(kind),
                    "status": "never_run",
                    "reason": "This model has not been trained yet.",
                    "minimums": sufficiency.describe_minimums(kind),
                }
            )
            continue
        output.append(
            {
                "kind": str(model.kind),
                "status": str(model.status),
                "algorithm": model.algorithm,
                "reason": model.reason,
                "n_samples": model.n_samples,
                "n_positive": model.n_positive,
                "metrics": model.metrics,
                "feature_names": model.feature_names,
                "trained_at": model.trained_at,
                "minimums": sufficiency.describe_minimums(model.kind),
                "usable": model.is_usable,
            }
        )
    return output


@router.post("/models/train")
async def train(
    session: DbSession, actor: AdminUser, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Fit what can be fitted; record a reason for what cannot."""
    org = await _resolve_org(session, actor, org_id)

    outcome = await analytics_models.fit_win_probability(session, org_id=org)
    await session.commit()
    await rebind_tenant(session, actor)

    return {
        "win_probability": {
            "status": str(outcome.status),
            "reason": outcome.reason,
            "metrics": outcome.metrics,
            "n_samples": outcome.n_samples,
        }
    }


@router.get("/proposals/predictions")
async def proposal_predictions(
    session: DbSession, actor: ManagerUser, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Win probability for proposals still awaiting a decision.

    Returns the refusal rather than a number when the model is not usable —
    the caller is told there is no prediction and why, never given a guess
    dressed as one.
    """
    org = await _resolve_org(session, actor, org_id)
    model = (
        await session.execute(
            select(AnalyticsModel).where(
                AnalyticsModel.kind == ModelKind.WIN_PROBABILITY,
                AnalyticsModel.org_id == org,
            )
        )
    ).scalar_one_or_none()

    if model is None or not model.is_usable:
        return {
            "available": False,
            "reason": (
                model.reason
                if model
                else "The win probability model has not been trained yet."
            ),
            "minimums": sufficiency.describe_minimums(ModelKind.WIN_PROBABILITY),
            "predictions": [],
        }

    open_rows = await analytics_models._proposal_rows_open(session, org)
    predictions = []
    for row in open_rows:
        probability = analytics_models.score_win_probability(model, row)
        if probability is None:
            continue
        predictions.append(
            {
                "proposal_id": str(row["id"]),
                "reference": row["reference"],
                "title": row["title"],
                "client_name": row["client_name"],
                "probability_pct": round(probability * 100),
                "prospect_score": (
                    round(float(row["score"]), 2) if row.get("score") is not None else None
                ),
            }
        )
    predictions.sort(key=lambda item: -item["probability_pct"])

    return {
        "available": True,
        "confidence": model.metrics.get("confidence", "low"),
        "cv_accuracy": model.metrics.get("cv_accuracy"),
        "baseline_accuracy": model.metrics.get("baseline_accuracy"),
        "n_samples": model.n_samples,
        # Repeated on every response, because a percentage travels further than
        # the caveat that came with it.
        "caveat": (
            f"Fitted on {model.n_samples} decided proposals. Treat as a rough "
            f"ordering, not a forecast."
        ),
        "predictions": predictions,
    }


@router.get("/targets/{target_id}/trend")
async def target_trend(
    target_id: uuid.UUID,
    session: DbSession,
    actor: ManagerUser,
    org_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    org = await _resolve_org(session, actor, org_id)
    return await analytics_models.score_trend(session, org_id=org, target_id=target_id)


@router.get("/disengagement")
async def disengagement(
    session: DbSession, actor: AdminUser, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    org = await _resolve_org(session, actor, org_id)
    return await analytics_models.disengagement_signals(session, org_id=org)


@router.get("/themes")
async def themes(
    session: DbSession,
    actor: ManagerUser,
    org_id: uuid.UUID | None = None,
    target_type: str | None = None,
) -> dict[str, Any]:
    """Recurring themes across recent free-text comments, grouped locally."""
    org = await _resolve_org(session, actor, org_id)
    return await theme_service.cluster_themes(session, org_id=org, target_type=target_type)
