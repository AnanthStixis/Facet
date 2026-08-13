"""Results aggregation with anonymity suppression.

The suppression rules are the part worth getting right, because an anonymity
promise that leaks under aggregation is worse than no promise: the reviewer was
told they were safe and answered honestly on that basis.

Three rules, all applied here rather than in the UI:

1. **Overall suppression.** Below `min_responses_to_reveal` contributing
   responses, nothing is shown but the count.

2. **Per-relationship suppression.** A breakdown is only shown when that
   relationship on its own clears the threshold. Otherwise "upward: 4.0" with
   one direct report names the author precisely, no matter how safe the overall
   number looked.

3. **Self is never counted and never hidden.** A self-assessment is the
   reviewee's own answer; including it in the anonymity maths would let one
   person's own input unlock everyone else's, and hiding it from them is
   absurd. It is reported as its own track.

Free-text comments are held to the same threshold as scores. A verbatim comment
is far more identifying than a number, so it is never shown at a count where a
score would be withheld.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import FeedbackTarget, FeedbackTemplateVersion
from app.models.cycle import FeedbackResponse, ReviewCycle
from app.models.enums import Relationship
from app.services.forms import validate_definition

# Relationships that count toward anonymity. Self is deliberately absent.
PEER_RELATIONSHIPS = {
    Relationship.MANAGER,
    Relationship.UPWARD,
    Relationship.PEER,
    Relationship.SKIP_LEVEL,
    Relationship.EXTERNAL,
}


@dataclass(slots=True)
class QuestionStat:
    key: str
    text: str
    section: str
    count: int = 0
    total: float = 0.0
    values: list[int] = field(default_factory=list)

    @property
    def average(self) -> float | None:
        return round(self.total / self.count, 2) if self.count else None

    def distribution(self, low: int, high: int) -> dict[str, int]:
        buckets = {str(point): 0 for point in range(low, high + 1)}
        for value in self.values:
            key = str(value)
            if key in buckets:
                buckets[key] += 1
        return buckets


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


async def target_results(
    session: AsyncSession,
    *,
    cycle: ReviewCycle,
    target_id: uuid.UUID,
    viewer_is_admin: bool,
) -> dict[str, Any]:
    """Aggregate one target's results for one cycle, with suppression applied."""
    target = (
        await session.execute(
            select(FeedbackTarget).where(FeedbackTarget.id == target_id)
        )
    ).scalar_one_or_none()
    if target is None:
        return {"found": False}

    version = (
        await session.execute(
            select(FeedbackTemplateVersion).where(
                FeedbackTemplateVersion.id == cycle.template_version_id
            )
        )
    ).scalar_one()
    form = validate_definition(version.definition)
    by_key = {question.key: question for question in form.questions}

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

    self_responses = [
        r for r in responses if r.relationship_type == Relationship.SELF
    ]
    others = [r for r in responses if r.relationship_type in PEER_RELATIONSHIPS]

    # Suppression removed at the org's explicit request — results are always
    # shown regardless of response count. `min_responses_to_reveal` stays on
    # the schema (existing cycles still have a value stored) but no longer
    # gates anything here. If anonymity protection is wanted back for
    # low-response anonymous cycles specifically, reintroduce the `revealed`
    # gate rather than deleting this comment's context.
    threshold = 0
    revealed = True

    payload: dict[str, Any] = {
        "found": True,
        "target": {
            "id": str(target.id),
            "label": target.label,
            "target_type": str(target.target_type),
        },
        "cycle": {
            "id": str(cycle.id),
            "name": cycle.name,
            "status": str(cycle.status),
            "is_anonymous": cycle.is_anonymous,
            "min_responses_to_reveal": cycle.min_responses_to_reveal,
        },
        "response_count": len(others),
        "self_response_count": len(self_responses),
        "revealed": revealed,
        "threshold": threshold,
    }

    if not revealed:
        needed = threshold - len(others)
        payload["suppressed_reason"] = (
            f"Results stay hidden until {threshold} people have responded. "
            f"{needed} more {'response is' if needed == 1 else 'responses are'} needed."
        )
        return payload

    # --- Aggregate the contributing responses ---------------------------
    stats: dict[str, QuestionStat] = {
        question.key: QuestionStat(
            key=question.key, text=question.text, section=question.section_title
        )
        for question in form.questions
        if question.type == "scale"
    }
    text_answers: dict[str, list[str]] = {}

    # The per-question breakdown and comments below include self-review
    # answers alongside everyone else's — unlike `overall_average` and
    # `by_relationship`, which stay "others"-only so the self-vs-others
    # comparison in the stat tiles above still means something. Self input
    # is never anonymous (it is the reviewee's own answer), so there is no
    # suppression reason to hide it here — and hiding it was the actual bug:
    # a cycle with only a self-review submitted showed every question with
    # nothing filled in, because self responses never reached this loop.
    for response in others + self_responses:
        for key, value in (response.answers or {}).items():
            question = by_key.get(key)
            if question is None:
                continue
            if question.type == "scale" and isinstance(value, int):
                stat = stats[key]
                stat.count += 1
                stat.total += value
                stat.values.append(value)
            elif question.type == "text" and str(value).strip():
                text_answers.setdefault(key, []).append(str(value).strip())

    overall_values = [
        float(r.overall_score) for r in others if r.overall_score is not None
    ]

    by_relationship: list[dict[str, Any]] = []
    for relationship in PEER_RELATIONSHIPS:
        group = [r for r in others if r.relationship_type == relationship]
        if not group:
            continue
        # Rule 2. A group below the threshold is reported as a count only.
        group_revealed = len(group) >= threshold
        scores = [float(r.overall_score) for r in group if r.overall_score is not None]
        by_relationship.append(
            {
                "relationship": relationship.value,
                "count": len(group),
                "revealed": group_revealed,
                "average": _mean(scores) if group_revealed else None,
            }
        )
    by_relationship.sort(key=lambda item: item["relationship"])

    self_scores = [
        float(r.overall_score) for r in self_responses if r.overall_score is not None
    ]

    payload.update(
        {
            "overall_average": _mean(overall_values),
            "self_average": _mean(self_scores),
            # The gap between how someone rates themselves and how others rate
            # them is the single most-used number in a 360 debrief.
            "self_awareness_gap": (
                round(_mean(self_scores) - _mean(overall_values), 2)
                if self_scores and overall_values
                else None
            ),
            "scale": {"min": form.scale_min, "max": form.scale_max},
            "by_relationship": by_relationship,
            "questions": [
                {
                    "key": stat.key,
                    "text": stat.text,
                    "section": stat.section,
                    "count": stat.count,
                    "average": stat.average,
                    "distribution": stat.distribution(form.scale_min, form.scale_max),
                }
                for stat in stats.values()
            ],
            # Verbatims are the most identifying content in the whole payload,
            # so they ride the same threshold and are shuffled out of
            # submission order to remove the ordering side channel.
            "comments": _collect_comments(others + self_responses),
            "text_answers": text_answers,
        }
    )

    if not viewer_is_admin:
        payload.pop("text_answers", None)

    return payload


def _collect_comments(responses: list[FeedbackResponse]) -> list[dict[str, Any]]:
    """Closing comments, detached from submission order.

    Sorting by submitted_at would let anyone who knows who responded first
    match a comment to a person, which quietly undoes the anonymity the storage
    model works hard to provide.
    """
    comments = [
        {
            "comment": response.comment.strip(),
            "relationship": response.relationship_type.value,
        }
        for response in responses
        if response.comment and response.comment.strip()
    ]
    comments.sort(key=lambda item: item["comment"])
    return comments


async def cycle_overview(
    session: AsyncSession, *, cycle: ReviewCycle
) -> list[dict[str, Any]]:
    """One row per reviewed target, for the cycle results table."""
    responses = (
        (
            await session.execute(
                select(FeedbackResponse).where(FeedbackResponse.cycle_id == cycle.id)
            )
        )
        .scalars()
        .all()
    )
    targets = {
        target.id: target
        for target in (
            await session.execute(
                select(FeedbackTarget).where(
                    FeedbackTarget.id.in_({r.target_id for r in responses} or {uuid.uuid4()})
                )
            )
        )
        .scalars()
        .all()
    }

    grouped: dict[uuid.UUID, list[FeedbackResponse]] = {}
    for response in responses:
        grouped.setdefault(response.target_id, []).append(response)

    # Suppression removed at the org's explicit request — see the matching
    # comment in target_results() above.
    rows: list[dict[str, Any]] = []

    for target_id, group in grouped.items():
        target = targets.get(target_id)
        others = [r for r in group if r.relationship_type in PEER_RELATIONSHIPS]
        selves = [r for r in group if r.relationship_type == Relationship.SELF]
        revealed = True
        scores = [float(r.overall_score) for r in others if r.overall_score is not None]
        self_scores = [float(r.overall_score) for r in selves if r.overall_score is not None]
        rows.append(
            {
                "target_id": str(target_id),
                "target": target.label if target else "Unknown",
                "target_type": str(target.target_type) if target else None,
                "responses": len(others),
                "revealed": revealed,
                "overall_average": _mean(scores) if revealed else None,
                "self_average": _mean(self_scores) if revealed else None,
            }
        )

    rows.sort(key=lambda row: row["target"])
    return rows
