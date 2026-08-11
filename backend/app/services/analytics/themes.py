"""Theme clustering over free-text comments.

Runs entirely locally: TF-IDF vectors of each anonymised comment, grouped
with k-means, with the cluster label taken from the terms closest to each
centroid. No embeddings API call, no OpenAI dependency — the `embedding`
column reserved on `feedback_responses` is for a future upgrade, not a
prerequisite. This is deliberately unsupervised and deliberately unlabelled
by an LLM: k-means on a few hundred comments is fast, free, and good enough to
say "these eleven comments are about the same thing" without anyone having to
trust a model's idea of what that thing is called beyond the words it used.

Individual respondent identity never appears in the output — comments are
already free text an author chose to submit, and results are only ever
returned in aggregate (cluster size, sample terms, a couple of excerpts),
gated by the same minimum-evidence floor used everywhere else in Module H.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cycle import FeedbackResponse
from app.models.enums import TargetType

MIN_COMMENTS = 12
MAX_COMMENTS = 500
MAX_EXCERPT = 220


@dataclass(frozen=True, slots=True)
class Theme:
    terms: list[str]
    size: int
    avg_sentiment: float | None
    excerpts: list[str]


def _truncate(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_EXCERPT else text[:MAX_EXCERPT].rsplit(" ", 1)[0] + "…"


async def cluster_themes(
    session: AsyncSession, *, org_id: uuid.UUID, target_type: str | None = None
) -> dict:
    """Group an organization's recent comments into rough themes.

    Returns `{"available": False, "reason": ...}` below the evidence floor —
    the same refusal-over-guess convention as the predictive models, because
    three comments clustered into three one-comment "themes" is not a theme,
    it is a coincidence with a label on it.
    """
    stmt = (
        select(FeedbackResponse.comment, FeedbackResponse.sentiment_score)
        .where(
            FeedbackResponse.org_id == org_id,
            FeedbackResponse.comment.isnot(None),
        )
        .order_by(FeedbackResponse.submitted_at.desc())
        .limit(MAX_COMMENTS)
    )
    if target_type:
        try:
            resolved = TargetType(target_type)
        except ValueError:
            resolved = None
        if resolved is not None:
            from app.models.catalog import FeedbackTarget  # local import avoids a cycle

            stmt = stmt.join(
                FeedbackTarget, FeedbackTarget.id == FeedbackResponse.target_id
            ).where(FeedbackTarget.target_type == resolved)

    rows = (await session.execute(stmt)).all()
    comments = [(row[0].strip(), row[1]) for row in rows if row[0] and row[0].strip()]

    if len(comments) < MIN_COMMENTS:
        return {
            "available": False,
            "reason": (
                f"Not enough comments yet: {len(comments)} of the {MIN_COMMENTS} "
                f"needed before grouping them into themes would mean anything."
            ),
            "themes": [],
        }

    texts = [c[0] for c in comments]
    vectorizer = TfidfVectorizer(
        max_features=300,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        # Every comment was pure stopwords/punctuation once vectorised —
        # nothing left to cluster on.
        return {
            "available": False,
            "reason": "The comments did not have enough distinct wording to group.",
            "themes": [],
        }

    # One cluster per ~8 comments, bounded so a small org gets a handful of
    # readable groups rather than one, and a large org does not get fifty.
    k = max(2, min(8, len(comments) // 8))
    model = KMeans(n_clusters=k, n_init=10, random_state=0)
    assignments = model.fit_predict(matrix)

    terms = vectorizer.get_feature_names_out()
    themes: list[Theme] = []
    for cluster_id in range(k):
        members = [i for i, label in enumerate(assignments) if label == cluster_id]
        if len(members) < 3:
            # A cluster this small is noise the algorithm had to put
            # somewhere, not a theme worth surfacing.
            continue

        centroid = model.cluster_centers_[cluster_id]
        top_indices = centroid.argsort()[::-1][:5]
        top_terms = [terms[i] for i in top_indices if centroid[i] > 0]

        scores = [comments[i][1] for i in members if comments[i][1] is not None]
        avg_sentiment = round(sum(scores) / len(scores), 3) if scores else None

        excerpts = [_truncate(comments[i][0]) for i in members[:3]]

        themes.append(
            Theme(
                terms=top_terms or ["(mixed wording)"],
                size=len(members),
                avg_sentiment=avg_sentiment,
                excerpts=excerpts,
            )
        )

    themes.sort(key=lambda t: t.size, reverse=True)

    return {
        "available": True,
        "total_comments": len(comments),
        "themes": [
            {
                "terms": theme.terms,
                "size": theme.size,
                "avg_sentiment": theme.avg_sentiment,
                "excerpts": theme.excerpts,
            }
            for theme in themes
        ],
    }
