"""AI endpoints (Module H).

Reads are open to anyone who may already see the underlying results; generation
is restricted to admins, because it spends money.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, ManagerUser, rebind_tenant
from app.core.config import settings
from app.core.errors import NotFound, PermissionDenied
from app.models.catalog import FeedbackTarget
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import InsightKind, InsightStatus, UserRole
from app.models.insight import AiInsight
from app.services.ai import (
    analyse_cycle,
    build_provider,
    monthly_tokens_used,
    sentiment_breakdown,
    summarise_target,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
async def ai_status(session: DbSession, actor: CurrentUser) -> dict[str, Any]:
    """What the AI features are currently doing, and on what.

    Surfaced rather than hidden: a summary produced by a local analyser is not
    the same product as one produced by a frontier model, and the person
    reading it is entitled to know which they have.
    """
    provider = build_provider()
    used = (
        await monthly_tokens_used(session, actor.org_id) if actor.org_id else 0
    )
    return {
        "enabled": True,
        "provider": provider.name,
        "is_local_fallback": provider.name == "local",
        "sentiment_model": provider.sentiment_model,
        "summary_model": provider.summary_model,
        "min_responses_for_summary": settings.ai_min_responses_for_summary,
        "monthly_token_budget": settings.ai_monthly_token_budget_per_org,
        "monthly_tokens_used": used,
    }


@router.post("/cycles/{cycle_id}/analyse")
async def analyse(
    cycle_id: uuid.UUID,
    session: DbSession,
    actor: AdminUser,
    force: bool = False,
) -> dict[str, Any]:
    """Classify every comment in a round, then summarise each eligible subject."""
    cycle = (
        await session.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id))
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFound("That round does not exist.")

    run = await analyse_cycle(session, cycle=cycle, force=force)
    await session.commit()
    await rebind_tenant(session, actor)

    # Only subjects that actually received feedback in this round.
    target_ids = (
        (
            await session.execute(
                select(FeedbackResponse.target_id)
                .where(FeedbackResponse.cycle_id == cycle.id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )

    generated = 0
    suppressed = 0
    for target_id in target_ids:
        outcome = await summarise_target(
            session, cycle=cycle, target_id=target_id, force=force
        )
        if outcome.status == InsightStatus.READY and not outcome.cached:
            generated += 1
        elif outcome.status == InsightStatus.SUPPRESSED:
            suppressed += 1
    await session.commit()

    return {
        "provider": run.provider,
        "comments_analysed": run.analysed,
        "injection_flags": run.injection_flags,
        "summaries_generated": generated,
        "summaries_suppressed": suppressed,
        "tokens": run.tokens,
    }


@router.get("/cycles/{cycle_id}/sentiment")
async def cycle_sentiment(
    cycle_id: uuid.UUID,
    session: DbSession,
    actor: ManagerUser,
    target_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await sentiment_breakdown(session, cycle_id=cycle_id, target_id=target_id)


@router.get("/cycles/{cycle_id}/targets/{target_id}/summary")
async def target_summary(
    cycle_id: uuid.UUID,
    target_id: uuid.UUID,
    session: DbSession,
    actor: CurrentUser,
) -> dict[str, Any]:
    """The stored summary for one subject.

    Same visibility rule as the results page it sits on: an admin, a manager,
    or the subject themselves. The suppression state is returned rather than a
    404, so the UI can explain why there is nothing to show.
    """
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == target_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("That subject does not exist.")

    is_admin = actor.role in {UserRole.SUPER_ADMIN, UserRole.CLIENT_ADMIN}
    is_manager = actor.role == UserRole.MANAGER
    if not (is_admin or is_manager or target.subject_user_id == actor.id):
        raise PermissionDenied("You cannot view this summary.")

    insight = (
        await session.execute(
            select(AiInsight).where(
                AiInsight.kind == InsightKind.TARGET_SUMMARY,
                AiInsight.subject_id == target_id,
                AiInsight.cycle_id == cycle_id,
            )
        )
    ).scalar_one_or_none()

    if insight is None:
        return {"status": "absent", "reason": "No summary has been generated yet."}

    if insight.status != InsightStatus.READY:
        return {
            "status": str(insight.status),
            "reason": insight.error,
            "source_count": insight.source_count,
        }

    return {
        "status": "ready",
        "payload": insight.payload,
        "source_count": insight.source_count,
        # Provenance travels with the text. A reader deserves to know what
        # produced it and when, especially when it is about them.
        "provider": insight.provider,
        "model_id": insight.model_id,
        "prompt_version": insight.prompt_version,
        "generated_at": insight.generated_at,
        "is_local_fallback": insight.provider == "local",
    }
