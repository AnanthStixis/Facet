"""The recommendation engine (Module H.2).

Hybrid, and the split is the whole point:

    **Rules decide what to flag and compute every number.**
    **The language model, if there is one, only phrases it.**

A pure-LLM recommender asked to "review this feedback and advise" will produce
fluent advice containing figures it invented — and those figures will sit on a
page next to a dashboard showing different ones. Once a user catches that
once, they stop trusting the whole surface, including the parts that were
right.

So every finding here is produced by a deterministic rule with its evidence
attached. `title`, `metric` and `evidence` come from SQL. Only `narrative` is
ever model-generated, and it is given the already-computed numbers rather than
the raw data, so it has nothing to invent from.

Findings are also *actionable by construction*: each rule exists because there
is something a manager could do about it. "Engagement is trending down" is not
a finding, it is a mood. "Three of Sneha's five reviewers rated communication
below 3, and it fell 0.8 since the last cycle" is a conversation.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.campaign import CampaignRecipient
from app.models.catalog import FeedbackTarget
from app.models.cycle import FeedbackAssignment, FeedbackResponse, ReviewCycle
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    CycleStatus,
    FindingSeverity,
    InsightKind,
    InsightStatus,
    ModelKind,
    ProposalStage,
    RecipientStatus,
    Relationship,
)
from app.models.insight import AiInsight
from app.models.proposal import Proposal
from app.services import audit
from app.services.ai import prompts
from app.services.analytics import models as analytics_models

# A finding needs enough underlying responses that it is not one person's
# opinion amplified into an organizational recommendation.
MIN_EVIDENCE = 3


@dataclass
class Finding:
    key: str
    severity: FindingSeverity
    title: str
    detail: str
    subject: str | None = None
    subject_id: str | None = None
    metric: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    action: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["severity"] = str(self.severity)
        return data


async def build(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[Finding]:
    """Run every rule. Each returns zero or more evidence-backed findings."""
    findings: list[Finding] = []
    for rule in (
        _rule_low_participation,
        _rule_sharp_decline,
        _rule_self_awareness_gap,
        _rule_negative_sentiment_cluster,
        _rule_proposal_estimation,
        _rule_stalled_campaign,
        _rule_no_feedback_coverage,
    ):
        findings.extend(await rule(session, org_id))

    order = {
        FindingSeverity.URGENT: 0,
        FindingSeverity.ATTENTION: 1,
        FindingSeverity.INFO: 2,
    }
    findings.sort(key=lambda item: (order[item.severity], item.key))
    return findings


# --- Rules ------------------------------------------------------------------

async def _rule_low_participation(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """An open round nobody is answering produces nothing worth reading."""
    rows = (
        await session.execute(
            select(
                ReviewCycle.id,
                ReviewCycle.name,
                func.count(FeedbackAssignment.id).label("total"),
                func.count(FeedbackAssignment.id)
                .filter(FeedbackAssignment.status == AssignmentStatus.SUBMITTED)
                .label("done"),
            )
            .select_from(ReviewCycle)
            .join(
                FeedbackAssignment,
                FeedbackAssignment.cycle_id == ReviewCycle.id,
                isouter=True,
            )
            .where(ReviewCycle.org_id == org_id, ReviewCycle.status == CycleStatus.OPEN)
            .group_by(ReviewCycle.id, ReviewCycle.name)
        )
    ).mappings().all()

    findings = []
    for row in rows:
        total = row["total"] or 0
        done = row["done"] or 0
        if total < 4:
            continue
        rate = done / total
        if rate >= 0.6:
            continue
        findings.append(
            Finding(
                key=f"participation:{row['id']}",
                severity=(
                    FindingSeverity.URGENT if rate < 0.3 else FindingSeverity.ATTENTION
                ),
                title=f"Only {done} of {total} people have responded to “{row['name']}”",
                detail=(
                    f"At {rate:.0%} completion the results will not clear the "
                    f"anonymity threshold for most people, so nobody will see "
                    f"anything."
                ),
                metric={"completion_pct": round(rate * 100), "outstanding": total - done},
                evidence=[f"{total - done} assignments still outstanding"],
                action="Send a reminder, or extend the closing date.",
            )
        )
    return findings


async def _rule_sharp_decline(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """A subject whose score has fallen materially between rounds."""
    rows = (
        await session.execute(
            select(
                FeedbackResponse.target_id,
                FeedbackTarget.label,
                ReviewCycle.id,
                ReviewCycle.opened_at,
                func.avg(FeedbackResponse.overall_score).label("score"),
                func.count().label("n"),
            )
            .select_from(FeedbackResponse)
            .join(ReviewCycle, ReviewCycle.id == FeedbackResponse.cycle_id)
            .join(FeedbackTarget, FeedbackTarget.id == FeedbackResponse.target_id)
            .where(
                FeedbackResponse.org_id == org_id,
                FeedbackResponse.relationship_type != Relationship.SELF,
            )
            .group_by(
                FeedbackResponse.target_id,
                FeedbackTarget.label,
                ReviewCycle.id,
                ReviewCycle.opened_at,
            )
            .order_by(FeedbackResponse.target_id, ReviewCycle.opened_at)
        )
    ).mappings().all()

    by_target: dict[uuid.UUID, list[dict]] = {}
    for row in rows:
        if row["score"] is None or (row["n"] or 0) < MIN_EVIDENCE:
            continue
        by_target.setdefault(row["target_id"], []).append(dict(row))

    findings = []
    for target_id, series in by_target.items():
        if len(series) < 2:
            continue
        previous, latest = series[-2], series[-1]
        delta = float(latest["score"]) - float(previous["score"])
        if delta > -0.4:
            continue
        findings.append(
            Finding(
                key=f"decline:{target_id}",
                severity=(
                    FindingSeverity.URGENT if delta <= -0.8 else FindingSeverity.ATTENTION
                ),
                title=f"{latest['label']}'s score fell {abs(delta):.1f} points",
                detail=(
                    f"From {float(previous['score']):.2f} to "
                    f"{float(latest['score']):.2f} between rounds."
                ),
                subject=latest["label"],
                subject_id=str(target_id),
                metric={
                    "previous": round(float(previous["score"]), 2),
                    "latest": round(float(latest["score"]), 2),
                    "delta": round(delta, 2),
                },
                evidence=[
                    f"{previous['n']} responses previously, {latest['n']} now",
                ],
                action="Look at the question-level breakdown before the next one-to-one.",
            )
        )
    return findings


async def _rule_self_awareness_gap(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """Someone rating themselves far above how others rate them."""
    rows = (
        await session.execute(
            select(
                FeedbackResponse.target_id,
                FeedbackTarget.label,
                func.avg(FeedbackResponse.overall_score)
                .filter(FeedbackResponse.relationship_type == Relationship.SELF)
                .label("self_score"),
                func.avg(FeedbackResponse.overall_score)
                .filter(FeedbackResponse.relationship_type != Relationship.SELF)
                .label("other_score"),
                func.count()
                .filter(FeedbackResponse.relationship_type != Relationship.SELF)
                .label("n"),
            )
            .select_from(FeedbackResponse)
            .join(FeedbackTarget, FeedbackTarget.id == FeedbackResponse.target_id)
            .where(FeedbackResponse.org_id == org_id)
            .group_by(FeedbackResponse.target_id, FeedbackTarget.label)
        )
    ).mappings().all()

    findings = []
    for row in rows:
        if row["self_score"] is None or row["other_score"] is None:
            continue
        if (row["n"] or 0) < MIN_EVIDENCE:
            continue
        gap = float(row["self_score"]) - float(row["other_score"])
        if gap < 0.75:
            continue
        findings.append(
            Finding(
                key=f"gap:{row['target_id']}",
                severity=FindingSeverity.ATTENTION,
                title=f"{row['label']} rates themselves {gap:.1f} points higher than others do",
                detail=(
                    f"Self-assessment {float(row['self_score']):.2f} against "
                    f"{float(row['other_score']):.2f} from {row['n']} colleagues."
                ),
                subject=row["label"],
                subject_id=str(row["target_id"]),
                metric={
                    "self": round(float(row["self_score"]), 2),
                    "others": round(float(row["other_score"]), 2),
                    "gap": round(gap, 2),
                },
                evidence=[f"{row['n']} colleague responses"],
                action="A gap this size is usually the most useful thing to discuss.",
            )
        )
    return findings


async def _rule_negative_sentiment_cluster(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """A recurring negative theme, not a single bad comment."""
    rows = (
        await session.execute(
            select(
                FeedbackResponse.target_id,
                FeedbackTarget.label,
                FeedbackResponse.sentiment_aspects,
                FeedbackResponse.sentiment_score,
            )
            .join(FeedbackTarget, FeedbackTarget.id == FeedbackResponse.target_id)
            .where(
                FeedbackResponse.org_id == org_id,
                FeedbackResponse.sentiment_at.isnot(None),
                FeedbackResponse.sentiment_score < -0.15,
                FeedbackResponse.relationship_type != Relationship.SELF,
            )
        )
    ).mappings().all()

    tally: dict[tuple, int] = {}
    labels: dict[uuid.UUID, str] = {}
    for row in rows:
        labels[row["target_id"]] = row["label"]
        for aspect in ((row["sentiment_aspects"] or {}).get("aspects") or []):
            key = (row["target_id"], aspect)
            tally[key] = tally.get(key, 0) + 1

    findings = []
    for (target_id, aspect), count in tally.items():
        if count < MIN_EVIDENCE:
            continue
        findings.append(
            Finding(
                key=f"sentiment:{target_id}:{aspect}",
                severity=FindingSeverity.ATTENTION,
                title=f"“{aspect}” comes up negatively about {labels[target_id]}",
                detail=f"{count} separate comments raised it in a negative tone.",
                subject=labels[target_id],
                subject_id=str(target_id),
                metric={"aspect": aspect, "mentions": count},
                evidence=[f"{count} negative comments tagged “{aspect}”"],
                action="Read the verbatims for that theme before drawing conclusions.",
            )
        )
    return findings


async def _rule_proposal_estimation(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """Proposals lost on price that prospects also rated poorly.

    The cross-domain rule. It is only computable because the outcome and the
    prospect's rating live in the same database.
    """
    scores = (
        select(
            FeedbackResponse.target_id,
            func.avg(FeedbackResponse.overall_score).label("score"),
            func.count().label("n"),
        )
        .group_by(FeedbackResponse.target_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Proposal.loss_reason,
                func.count().label("lost"),
                func.avg(scores.c.score).label("avg_score"),
            )
            .select_from(Proposal)
            .join(scores, scores.c.target_id == Proposal.target_id, isouter=True)
            .where(Proposal.org_id == org_id, Proposal.stage == ProposalStage.LOST)
            .group_by(Proposal.loss_reason)
        )
    ).mappings().all()

    eligible = [
        row
        for row in rows
        if row["loss_reason"] is not None and (row["lost"] or 0) >= MIN_EVIDENCE
    ]
    if not eligible:
        return []

    # Only one reason can be the most common. Titling every reason that way
    # produced a list of four contradictory "most common" claims — obviously
    # wrong to a reader, and corrosive to trust in the rest of the page.
    top = max(eligible, key=lambda row: row["lost"] or 0)

    findings = []
    for row in eligible:
        reason = str(row["loss_reason"]).replace("_", " ")
        score = float(row["avg_score"]) if row["avg_score"] is not None else None
        detail = f"{row['lost']} proposals lost to {reason}."
        if score is not None:
            detail += f" Prospects rated them {score:.2f} on average."
            # The interesting case, and the one only this product can see: lost
            # despite a good rating means the proposal was fine and something
            # else killed it.
            if score >= 4.0:
                detail += (
                    " These scored well, so the proposal itself was probably not"
                    " the problem."
                )
        title = (
            f"“{reason.title()}” is your most common loss reason"
            if row is top
            else f"{row['lost']} proposals lost to {reason}"
        )
        findings.append(
            Finding(
                key=f"loss:{row['loss_reason']}",
                severity=(
                    FindingSeverity.URGENT
                    if row is top and (row["lost"] or 0) >= 5
                    else FindingSeverity.ATTENTION
                ),
                title=title,
                detail=detail,
                metric={
                    "loss_reason": str(row["loss_reason"]),
                    "count": row["lost"],
                    "avg_prospect_score": round(score, 2) if score is not None else None,
                },
                evidence=[f"{row['lost']} lost proposals with this reason recorded"],
                action=(
                    "Compare the prospect feedback on these against the ones you won."
                ),
            )
        )
    return findings


async def _rule_stalled_campaign(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """Invitations sent, nobody replying."""
    rows = (
        await session.execute(
            select(
                ReviewCycle.id,
                ReviewCycle.name,
                func.count(CampaignRecipient.id).label("sent"),
                func.count(CampaignRecipient.id)
                .filter(CampaignRecipient.status == RecipientStatus.SUBMITTED)
                .label("done"),
            )
            .select_from(ReviewCycle)
            .join(CampaignRecipient, CampaignRecipient.cycle_id == ReviewCycle.id)
            .where(
                ReviewCycle.org_id == org_id,
                ReviewCycle.status == CycleStatus.OPEN,
                CampaignRecipient.status != RecipientStatus.PENDING,
            )
            .group_by(ReviewCycle.id, ReviewCycle.name)
        )
    ).mappings().all()

    findings = []
    for row in rows:
        sent = row["sent"] or 0
        done = row["done"] or 0
        if sent < 4 or done / sent >= 0.25:
            continue
        findings.append(
            Finding(
                key=f"campaign:{row['id']}",
                severity=FindingSeverity.ATTENTION,
                title=f"“{row['name']}” has a {done / sent:.0%} response rate",
                detail=f"{done} replies from {sent} invitations sent.",
                metric={"sent": sent, "responded": done},
                evidence=[f"{sent - done} recipients have not replied"],
                action="Chase non-responders, or reconsider the timing and framing.",
            )
        )
    return findings


async def _rule_no_feedback_coverage(
    session: AsyncSession, org_id: uuid.UUID
) -> list[Finding]:
    """Submitted proposals nobody asked the prospect about."""
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Proposal)
                .where(Proposal.org_id == org_id, Proposal.stage != ProposalStage.DRAFT)
            )
        ).scalar_one()
    )
    if total < MIN_EVIDENCE:
        return []

    # "Covered" means the prospect was asked *or* actually answered. Counting
    # only invitations under-reported proposals whose feedback arrived another
    # way, and produced a finding that contradicted the scorecard beside it.
    invited = select(CampaignRecipient.target_id).where(
        CampaignRecipient.target_id.isnot(None)
    )
    answered = select(FeedbackResponse.target_id).where(
        FeedbackResponse.target_id.isnot(None)
    )
    covered = int(
        (
            await session.execute(
                select(func.count(func.distinct(Proposal.id)))
                .select_from(Proposal)
                .where(
                    Proposal.org_id == org_id,
                    Proposal.stage != ProposalStage.DRAFT,
                    Proposal.target_id.in_(invited.union(answered)),
                )
            )
        ).scalar_one()
    )
    missing = total - covered
    if missing == 0 or missing / total < 0.3:
        return []

    return [
        Finding(
            key="coverage:proposals",
            severity=FindingSeverity.INFO,
            title=f"{missing} submitted proposals were never sent for feedback",
            detail=(
                f"{covered} of {total} have been surveyed. The unasked ones "
                f"cannot contribute to the win/loss picture."
            ),
            metric={"total": total, "covered": covered, "missing": missing},
            evidence=[f"{missing} proposals with no prospect survey"],
            action="Ask the prospect, even on the ones you lost — especially those.",
        )
    ]


# --- Narrative and storage --------------------------------------------------

async def generate(
    session: AsyncSession, *, org_id: uuid.UUID, provider=None
) -> dict:
    """Build findings, optionally phrase them, and store the result."""
    findings = await build(session, org_id=org_id)

    narrative = None
    provider_name = "rules"
    model_id = "facet-rules-1"
    if findings and settings.ai_enabled:
        from app.services.ai.providers import build_provider

        provider = provider or build_provider()
        try:
            # The model is handed the already-computed statements, never the
            # raw data. It has nothing to invent a number from.
            result = await provider.summarise(
                [f"{item.title}. {item.detail}" for item in findings[:8]],
                {"subject": "this organization", "cycle": "current", "count": len(findings)},
            )
            narrative = result.payload.get("narrative")
            provider_name = result.provider
            model_id = result.model_id
        except Exception:  # noqa: BLE001
            narrative = None

    digest = prompts.input_digest(
        [item.key for item in findings],
        [item.metric for item in findings],
        model_id,
    )

    existing = (
        await session.execute(
            select(AiInsight).where(
                AiInsight.kind == InsightKind.RECOMMENDATION,
                AiInsight.subject_id == org_id,
                AiInsight.cycle_id.is_(None),
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is None:
        existing = AiInsight(
            org_id=org_id,
            kind=InsightKind.RECOMMENDATION,
            subject_type="organization",
            subject_id=org_id,
            cycle_id=None,
            generated_at=now,
        )
        session.add(existing)

    existing.status = InsightStatus.READY
    existing.input_hash = digest
    existing.model_id = model_id
    existing.provider = provider_name
    existing.prompt_version = prompts.PROMPT_VERSION
    existing.payload = {
        "findings": [item.to_dict() for item in findings],
        "narrative": narrative,
        # Stated on the artefact itself: the numbers are not model output.
        "computed_by": "deterministic rules over stored data",
    }
    existing.source_count = len(findings)
    existing.generated_at = now
    existing.error = None

    await audit.record(
        session,
        action=AuditAction.AI_RECOMMENDATIONS_BUILT,
        summary=f"{len(findings)} recommendation(s) generated",
        org_id=org_id,
        context={
            "urgent": sum(1 for f in findings if f.severity == FindingSeverity.URGENT),
            "attention": sum(
                1 for f in findings if f.severity == FindingSeverity.ATTENTION
            ),
        },
    )

    return {
        "findings": [item.to_dict() for item in findings],
        "narrative": narrative,
        "generated_at": now,
        "computed_by": "deterministic rules over stored data",
    }
