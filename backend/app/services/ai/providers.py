"""AI providers.

`LocalProvider` is the only implementation: a deterministic lexicon-and-
extraction analyser. It is not a pretend LLM and the UI never claims it is —
results it produces are labelled with `provider = "local"` and the interface
surfaces that honestly. It exists so the feature is developable, demonstrable
and *testable* without a network call, and so the injection and anonymity
guarantees can be verified deterministically rather than against a
probabilistic endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.ai import prompts


@dataclass(slots=True)
class SentimentResult:
    index: int
    score: float
    confidence: float
    aspects: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class ProviderResponse:
    payload: Any
    usage: Usage
    model_id: str
    provider: str


class AiProvider(Protocol):
    name: str
    sentiment_model: str
    summary_model: str

    async def classify(self, comments: list[str]) -> ProviderResponse: ...
    async def summarise(self, comments: list[str], context: dict) -> ProviderResponse: ...


# --- Local ------------------------------------------------------------------

_POSITIVE = {
    "excellent": 0.9, "outstanding": 0.9, "brilliant": 0.9, "best": 0.8,
    "great": 0.7, "strong": 0.6, "clear": 0.5, "useful": 0.5, "good": 0.5,
    "helpful": 0.6, "responsive": 0.6, "reliable": 0.6, "credible": 0.5,
    "trust": 0.6, "supports": 0.5, "consistently": 0.4, "genuinely": 0.4,
    "solid": 0.4, "approachable": 0.6, "appreciate": 0.6, "recommend": 0.7,
    "quickly": 0.4, "specific": 0.4, "actionable": 0.5, "well": 0.4,
}
_NEGATIVE = {
    "poor": -0.8, "bad": -0.7, "worst": -0.9, "unacceptable": -0.9,
    "slow": -0.5, "unclear": -0.6, "confusing": -0.6, "late": -0.5,
    "bottleneck": -0.5, "optimistic": -0.3, "harder": -0.4, "difficult": -0.5,
    "wider": -0.3, "not": -0.3, "never": -0.4, "lacking": -0.6,
    "disappointing": -0.8, "concern": -0.4, "problem": -0.5, "issue": -0.4,
    "hesitate": -0.3, "struggle": -0.5, "delay": -0.5, "expensive": -0.4,
}
# Understatement carries real weight in the English this product will meet.
_HEDGED_CRITICISM = [
    (re.compile(r"could be better", re.I), -0.45),
    (re.compile(r"would (?:have )?like[d]? (?:to see )?more", re.I), -0.35),
    (re.compile(r"would benefit from", re.I), -0.4),
    (re.compile(r"took longer than", re.I), -0.45),
    (re.compile(r"than (?:it|they) needed to", re.I), -0.4),
    (re.compile(r"room for improvement", re.I), -0.4),
    (re.compile(r"not always", re.I), -0.35),
]
_INTENSIFIERS = {"very": 1.3, "extremely": 1.5, "really": 1.2, "consistently": 1.2}
_NEGATORS = {"not", "never", "no", "without", "hardly", "rarely"}

_ASPECTS = {
    "communication": ["communicat", "explain", "inform", "update", "clarity", "clear"],
    "responsiveness": ["respond", "quick", "timely", "slow", "delay", "unblock"],
    "delivery": ["deliver", "schedule", "on time", "milestone", "late"],
    "quality": ["quality", "technical", "standard", "documentation"],
    "pricing": ["price", "pricing", "cost", "expensive", "budget", "commercial"],
    "scope": ["scope", "estimate", "estimation", "effort", "wider"],
    "leadership": ["decision", "priorit", "direction", "lead"],
    "support": ["support", "develop", "coach", "one-to-one", "growth"],
    "trust": ["trust", "honest", "credit", "safe", "hesitat"],
    "collaboration": ["collaborat", "team", "together", "peer"],
}


class LocalProvider:
    """Deterministic analyser used when no API key is configured.

    Lexicon-based sentiment with negation, intensifier and understatement
    handling, plus extractive summarisation. Genuinely useful for a demo and
    perfectly repeatable for tests; nowhere near an LLM for nuance, which is
    exactly why the output is labelled as locally generated.
    """

    name = "local"
    sentiment_model = "facet-local-lexicon-1"
    summary_model = "facet-local-extractive-1"

    async def classify(self, comments: list[str]) -> ProviderResponse:
        results = []
        for index, comment in enumerate(comments):
            score, matched = self._score(comment)
            aspects = self._aspects(comment)
            flags = ["injection_attempt"] if prompts.looks_like_injection(comment) else []
            results.append(
                {
                    "index": index + 1,
                    "score": round(score, 3),
                    # Confidence rises with how much of the text the lexicon
                    # actually recognised, rather than being a constant that
                    # pretends to mean something.
                    "confidence": round(min(0.95, 0.35 + 0.12 * matched), 3),
                    "aspects": aspects,
                    "flags": flags,
                }
            )
        return ProviderResponse(
            payload={"results": results},
            usage=Usage(),
            model_id=self.sentiment_model,
            provider=self.name,
        )

    def _score(self, text: str) -> tuple[float, int]:
        words = re.findall(r"[a-z'\-]+", text.lower())
        total = 0.0
        matched = 0

        for position, word in enumerate(words):
            weight = _POSITIVE.get(word) or _NEGATIVE.get(word)
            if weight is None:
                continue
            matched += 1
            window = words[max(0, position - 3) : position]
            if any(previous in _NEGATORS for previous in window):
                weight = -weight * 0.8
            for previous in window:
                if previous in _INTENSIFIERS:
                    weight *= _INTENSIFIERS[previous]
            total += weight

        for pattern, weight in _HEDGED_CRITICISM:
            if pattern.search(text):
                total += weight
                matched += 1

        if not matched:
            return 0.0, 0
        # Squash to -1..1 so a long comment full of mild praise cannot outrank
        # a short, emphatic complaint. The constant is tuned so one unambiguous
        # word ("excellent") clears the positive band on its own — at 2.2 it
        # landed at 0.29, a hair under the 0.25 boundary and far too close to
        # neutral for a sentence that is plainly praise.
        normalised = total / (abs(total) + 1.6)
        return max(-1.0, min(1.0, normalised)), matched

    def _aspects(self, text: str) -> list[str]:
        lowered = text.lower()
        found = [
            aspect
            for aspect, needles in _ASPECTS.items()
            if any(needle in lowered for needle in needles)
        ]
        return found[:4]

    async def summarise(self, comments: list[str], context: dict) -> ProviderResponse:
        scored: list[tuple[float, str]] = []
        aspect_counts: dict[str, int] = {}
        for comment in comments:
            score, _ = self._score(comment)
            scored.append((score, comment.strip()))
            for aspect in self._aspects(comment):
                aspect_counts[aspect] = aspect_counts.get(aspect, 0) + 1

        positives = sorted((s for s in scored if s[0] > 0.15), reverse=True)
        negatives = sorted(s for s in scored if s[0] < -0.15)
        average = sum(score for score, _ in scored) / len(scored) if scored else 0.0
        themes = [
            aspect
            for aspect, _ in sorted(
                aspect_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ][:5]

        def shorten(text: str, limit: int = 110) -> str:
            first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
            return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"

        subject = context.get("subject", "This subject")
        if average > 0.25:
            headline = f"{subject} is rated positively, with consistent praise for {themes[0] if themes else 'their work'}."
        elif average < -0.15:
            headline = f"Feedback on {subject} raises recurring concerns about {themes[0] if themes else 'delivery'}."
        else:
            headline = f"Feedback on {subject} is mixed, with clear strengths and clear areas to work on."

        narrative_bits = [
            f"{len(comments)} contributor(s) left written feedback.",
        ]
        if positives:
            narrative_bits.append(f"The most positive comment noted: “{shorten(positives[0][1])}”")
        if negatives:
            narrative_bits.append(f"The main concern raised was: “{shorten(negatives[0][1])}”")
        if themes:
            narrative_bits.append(f"Recurring topics were {', '.join(themes[:3])}.")

        return ProviderResponse(
            payload={
                "headline": headline[:200],
                "strengths": [shorten(text) for _, text in positives[:3]],
                "watch_outs": [shorten(text) for _, text in negatives[:2]],
                "themes": themes,
                "narrative": " ".join(narrative_bits)[:1200],
            },
            usage=Usage(),
            model_id=self.summary_model,
            provider=self.name,
        )


def build_provider() -> AiProvider:
    """The deterministic local analyser is the only provider."""
    return LocalProvider()
