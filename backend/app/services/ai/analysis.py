"""Sentiment analysis and summary generation.

The anonymity gate is the important part of this module. Everywhere else in the
product, suppression means "collected but not shown". Here it means **not
generated at all**: below the threshold no summary is produced, nothing is sent
to a provider, and nothing is written to the database.

That is stricter on purpose. A stored summary of two anonymous comments is a
de-anonymising artefact sitting in a table, one bug or one export away from the
person it describes. Not creating it is the only version of the guarantee that
survives contact with a future feature.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict
from app.core.logging import get_logger
from app.models.catalog import FeedbackTarget
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import (
    AuditAction,
    InsightKind,
    InsightStatus,
    Relationship,
    SentimentLabel,
)
from app.models.insight import AiInsight
from app.models.organization import Organization
from app.schemas.settings import OrgSettings
from app.services import audit
from app.services.ai import prompts
from app.services.ai.providers import AiProvider, build_provider

log = get_logger("facet.ai.analysis")

# Sentiment is per comment and cheap; batching keeps the request count sane
# without making any single failure lose a whole cycle's work.
BATCH_SIZE = 25

# Relationships that count toward the anonymity threshold. Self-assessments are
# excluded for the same reason as everywhere else: they are the subject's own
# words and cannot identify anyone else.
CONTRIBUTING = {
    Relationship.MANAGER,
    Relationship.UPWARD,
    Relationship.PEER,
    Relationship.SKIP_LEVEL,
    Relationship.EXTERNAL,
}


@dataclass(slots=True)
class SentimentRun:
    analysed: int = 0
    skipped_existing: int = 0
    injection_flags: int = 0
    tokens: int = 0
    provider: str = "local"


@dataclass(slots=True)
class SummaryOutcome:
    status: InsightStatus
    insight: AiInsight | None
    reason: str | None = None
    cached: bool = False


async def monthly_tokens_used(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Tokens consumed this calendar month by one organization."""
    start = datetime.now(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    total = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(AiInsight.prompt_tokens + AiInsight.completion_tokens), 0
                )
            ).where(AiInsight.org_id == org_id, AiInsight.generated_at >= start)
        )
    ).scalar_one()
    return int(total)


async def _budget_available(
    session: AsyncSession, org_id: uuid.UUID, provider: AiProvider
) -> bool:
    # The local provider costs nothing, so a budget check there would only ever
    # block a free operation.
    if provider.name == "local":
        return True
    used = await monthly_tokens_used(session, org_id)
    return used < settings.ai_monthly_token_budget_per_org


# --- Sentiment --------------------------------------------------------------

async def analyse_cycle(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    provider: AiProvider | None = None,
    force: bool = False,
) -> SentimentRun:
    """Classify every unanalysed comment in a round."""
    provider = provider or build_provider()
    run = SentimentRun(provider=provider.name)

    stmt = select(FeedbackResponse).where(
        FeedbackResponse.cycle_id == cycle.id,
        FeedbackResponse.comment.isnot(None),
        FeedbackResponse.comment != "",
    )
    if not force:
        stmt = stmt.where(FeedbackResponse.sentiment_at.is_(None))

    responses = (await session.execute(stmt)).scalars().all()
    if not responses:
        return run

    if not await _budget_available(session, cycle.org_id, provider):
        await audit.record(
            session,
            action=AuditAction.AI_BUDGET_EXHAUSTED,
            summary="Monthly AI token budget reached; analysis skipped",
            org_id=cycle.org_id,
            context={"cycle": str(cycle.id)},
        )
        raise Conflict("This organization has reached its monthly AI budget.")

    now = datetime.now(UTC)

    for start in range(0, len(responses), BATCH_SIZE):
        batch = responses[start : start + BATCH_SIZE]
        comments = [response.comment or "" for response in batch]

        try:
            result = await provider.classify(comments)
        except Exception as exc:  # noqa: BLE001
            # One bad batch must not abandon the rest of the round.
            log.error("sentiment_batch_failed", error=str(exc), size=len(batch))
            continue

        by_index = {
            int(item["index"]): item
            for item in (result.payload or {}).get("results", [])
            if isinstance(item, dict) and "index" in item
        }

        for offset, response in enumerate(batch, start=1):
            item = by_index.get(offset)
            if item is None:
                continue
            score = float(item.get("score", 0.0))
            flags = list(item.get("flags") or [])

            response.sentiment_score = Decimal(str(round(score, 3)))
            response.sentiment_label = str(SentimentLabel.from_score(score))
            response.sentiment_confidence = Decimal(
                str(round(float(item.get("confidence", 0.5)), 3))
            )
            response.sentiment_aspects = {
                "aspects": list(item.get("aspects") or []),
                "flags": flags,
            }
            response.sentiment_model = result.model_id
            response.sentiment_at = now
            run.analysed += 1

            if "injection_attempt" in flags:
                run.injection_flags += 1

        run.tokens += result.usage.total

    if run.injection_flags:
        # Recorded, not silently sanitised. Someone trying to steer the model
        # is an event an administrator should be able to see.
        await audit.record(
            session,
            action=AuditAction.AI_INJECTION_DETECTED,
            summary=(
                f"{run.injection_flags} comment(s) in '{cycle.name}' attempted to "
                f"instruct the analysis model"
            ),
            org_id=cycle.org_id,
            target_type="review_cycle",
            target_id=cycle.id,
            target_label=cycle.name,
            context={"flagged": run.injection_flags},
        )

    if run.analysed:
        await audit.record(
            session,
            action=AuditAction.AI_SENTIMENT_ANALYSED,
            summary=f"{run.analysed} comment(s) analysed in '{cycle.name}'",
            org_id=cycle.org_id,
            target_type="review_cycle",
            target_id=cycle.id,
            target_label=cycle.name,
            context={"provider": provider.name, "tokens": run.tokens},
        )
    return run


# --- Summaries --------------------------------------------------------------

async def summarise_target(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    target_id: uuid.UUID,
    provider: AiProvider | None = None,
    force: bool = False,
) -> SummaryOutcome:
    """Generate (or reuse) the summary of one subject in one round."""
    provider = provider or build_provider()

    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == target_id)
        )
    ).scalar_one_or_none()
    if target is None:
        return SummaryOutcome(status=InsightStatus.FAILED, insight=None, reason="unknown target")

    responses = (
        (
            await session.execute(
                select(FeedbackResponse).where(
                    FeedbackResponse.cycle_id == cycle.id,
                    FeedbackResponse.target_id == target_id,
                )
            )
        )
        .scalars()
        .all()
    )
    contributing = [r for r in responses if r.relationship_type in CONTRIBUTING]

    existing = (
        await session.execute(
            select(AiInsight).where(
                AiInsight.kind == InsightKind.TARGET_SUMMARY,
                AiInsight.subject_id == target_id,
                AiInsight.cycle_id == cycle.id,
            )
        )
    ).scalar_one_or_none()

    # --- The gate --------------------------------------------------------
    # Three thresholds apply and the strictest wins: the round's own anonymity
    # setting, the tenant's own AI setting, and the platform floor that holds
    # even for attributable rounds. A tenant setting can only raise this floor
    # (OrgSettings.load enforces that on write); it can never lower it, which
    # is what `effective_summary_threshold` computes.
    org = (
        await session.execute(select(Organization).where(Organization.id == cycle.org_id))
    ).scalar_one_or_none()
    org_ai_settings = OrgSettings.load(org.settings if org else None).ai
    base_threshold = cycle.min_responses_to_reveal
    threshold = max(
        base_threshold,
        org_ai_settings.min_responses_for_summary,
        settings.ai_min_responses_for_summary,
    )
    if len(contributing) < threshold:
        needed = threshold - len(contributing)
        reason = (
            f"A summary needs {threshold} contributing responses. "
            f"{needed} more required."
        )
        if existing is None:
            # Recorded as suppressed so the UI can explain itself without
            # re-deciding, and so nothing is sent to a provider next time.
            existing = AiInsight(
                org_id=cycle.org_id,
                kind=InsightKind.TARGET_SUMMARY,
                status=InsightStatus.SUPPRESSED,
                subject_type="feedback_target",
                subject_id=target_id,
                cycle_id=cycle.id,
                input_hash="",
                model_id="none",
                prompt_version=prompts.PROMPT_VERSION,
                provider=provider.name,
                payload={},
                source_count=len(contributing),
                generated_at=datetime.now(UTC),
                error=reason,
            )
            session.add(existing)
        else:
            existing.status = InsightStatus.SUPPRESSED
            existing.payload = {}
            existing.source_count = len(contributing)
            existing.error = reason

        await audit.record(
            session,
            action=AuditAction.AI_SUMMARY_SUPPRESSED,
            summary=f"Summary withheld for '{target.label}' below the response threshold",
            org_id=cycle.org_id,
            target_type="feedback_target",
            target_id=target_id,
            target_label=target.label,
            context={"have": len(contributing), "need": threshold},
        )
        return SummaryOutcome(
            status=InsightStatus.SUPPRESSED, insight=existing, reason=reason
        )

    # Exclude comments that tried to instruct the model.
    #
    # Flagging alone is not enough. An extractive or quoting summariser will
    # happily lift an injected sentence into "consistently praised" — the
    # attacker fails to control the model but still gets their text promoted
    # into the most prominent part of a report about someone else. Text that
    # is attempting to manipulate the analysis is not evidence about the
    # subject, so it is not summarised. It remains visible in the raw comment
    # list and still counts toward the response total.
    usable: list[str] = []
    excluded = 0
    for response in contributing:
        comment = (response.comment or "").strip()
        if not comment:
            continue
        flagged = "injection_attempt" in (
            (response.sentiment_aspects or {}).get("flags") or []
        )
        if flagged or prompts.looks_like_injection(comment):
            excluded += 1
            continue
        usable.append(comment)

    comments = usable
    if len(comments) < threshold:
        reason = (
            f"Only {len(comments)} of {len(contributing)} responses left a usable "
            f"written comment; a summary needs {threshold}."
        )
        if excluded:
            reason += f" {excluded} were excluded as attempts to steer the analysis."
        return SummaryOutcome(
            status=InsightStatus.SUPPRESSED, insight=existing, reason=reason
        )

    digest = prompts.input_digest(
        sorted(comments),
        provider.summary_model,
        prompts.PROMPT_VERSION,
        len(contributing),
        excluded,
    )

    if (
        existing is not None
        and not force
        and existing.status == InsightStatus.READY
        and existing.input_hash == digest
    ):
        return SummaryOutcome(
            status=InsightStatus.READY, insight=existing, cached=True
        )

    if not await _budget_available(session, cycle.org_id, provider):
        raise Conflict("This organization has reached its monthly AI budget.")

    try:
        result = await provider.summarise(
            comments,
            {
                "subject": target.label,
                "cycle": cycle.name,
                "count": len(contributing),
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.error("summary_failed", error=str(exc), target=str(target_id))
        return SummaryOutcome(
            status=InsightStatus.FAILED, insight=existing, reason="generation failed"
        )

    now = datetime.now(UTC)
    if existing is None:
        existing = AiInsight(
            org_id=cycle.org_id,
            kind=InsightKind.TARGET_SUMMARY,
            subject_type="feedback_target",
            subject_id=target_id,
            cycle_id=cycle.id,
            generated_at=now,
        )
        session.add(existing)

    existing.status = InsightStatus.READY
    existing.input_hash = digest
    existing.model_id = result.model_id
    existing.provider = result.provider
    existing.prompt_version = prompts.PROMPT_VERSION
    existing.payload = {**result.payload, "excluded_comments": excluded}
    existing.source_count = len(contributing)
    existing.prompt_tokens = result.usage.prompt_tokens
    existing.completion_tokens = result.usage.completion_tokens
    existing.error = None
    existing.generated_at = now

    await audit.record(
        session,
        action=AuditAction.AI_SUMMARY_GENERATED,
        summary=f"Summary generated for '{target.label}' in '{cycle.name}'",
        org_id=cycle.org_id,
        target_type="feedback_target",
        target_id=target_id,
        target_label=target.label,
        context={
            "provider": result.provider,
            "model": result.model_id,
            "sources": len(contributing),
            "tokens": result.usage.total,
        },
    )
    return SummaryOutcome(status=InsightStatus.READY, insight=existing)


async def sentiment_breakdown(
    session: AsyncSession, *, cycle_id: uuid.UUID, target_id: uuid.UUID | None = None
) -> dict:
    """Distribution and aspect counts for a round or one subject."""
    stmt = select(
        FeedbackResponse.sentiment_label,
        func.count(),
        func.avg(FeedbackResponse.sentiment_score),
    ).where(
        FeedbackResponse.cycle_id == cycle_id,
        FeedbackResponse.sentiment_at.isnot(None),
        FeedbackResponse.relationship_type != Relationship.SELF,
    )
    if target_id:
        stmt = stmt.where(FeedbackResponse.target_id == target_id)

    rows = (await session.execute(stmt.group_by(FeedbackResponse.sentiment_label))).all()

    distribution = {str(label): 0 for label in SentimentLabel}
    total = 0
    weighted = 0.0
    for label, count, average in rows:
        if label is None:
            continue
        distribution[label] = count
        total += count
        if average is not None:
            weighted += float(average) * count

    aspects_stmt = select(FeedbackResponse.sentiment_aspects).where(
        FeedbackResponse.cycle_id == cycle_id,
        FeedbackResponse.sentiment_at.isnot(None),
        FeedbackResponse.relationship_type != Relationship.SELF,
    )
    if target_id:
        aspects_stmt = aspects_stmt.where(FeedbackResponse.target_id == target_id)

    counts: dict[str, int] = {}
    for (payload,) in (await session.execute(aspects_stmt)).all():
        for aspect in (payload or {}).get("aspects", []):
            counts[aspect] = counts.get(aspect, 0) + 1

    return {
        "analysed": total,
        "average_score": round(weighted / total, 3) if total else None,
        "distribution": distribution,
        "aspects": [
            {"aspect": aspect, "count": count}
            for aspect, count in sorted(counts.items(), key=lambda i: (-i[1], i[0]))
        ][:8],
    }
