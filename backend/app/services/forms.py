"""Questionnaire definitions: validation, answer checking, and scoring.

A template definition is author-supplied JSON and an answer set is
respondent-supplied JSON. Both are untrusted, both end up rendered in a
browser, in a spreadsheet, and eventually in an AI prompt, so both are
validated here rather than trusted at the point of use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.errors import ValidationFailed

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,58}[a-z0-9]$")

MAX_SECTIONS = 20
MAX_QUESTIONS_PER_SECTION = 30
MAX_QUESTIONS_TOTAL = 200
MAX_TEXT = 400
MAX_COMMENT = 5000
MAX_OPTIONS = 12

QUESTION_TYPES = {"scale", "choice", "text", "boolean"}
OVERALL_RATING_TITLE = "overall rating"

@dataclass(frozen=True, slots=True)
class Question:
    key: str
    text: str
    type: str
    required: bool
    options: list[str]
    section_key: str
    section_title: str
    


@dataclass(frozen=True, slots=True)
class Form:
    """A flattened, validated view of a template definition."""

    intro: str
    scale_min: int
    scale_max: int
    scale_labels: dict[str, str]
    questions: list[Question]
    comment_prompt: str
    comment_required: bool

    @property
    def scored_keys(self) -> list[str]:
        return [q.key for q in self.questions if q.type == "scale"]

    @property
    def overall_rating_key(self) -> str | None:
        """The key of the first rating-scale question titled exactly
        "Overall rating" (case-insensitive, extra whitespace collapsed), if
        the template author added one. None means they haven't —
        validate_answers below falls back to averaging every scale
        question, exactly the behavior every template already had. If more
        than one question happens to share that title, the first one (in
        question order) wins — a title collision is far more likely to be
        an innocent coincidence than a deliberate double-flag, so this
        resolves it rather than rejecting the whole template over it.
        """
        for question in self.questions:
            if (
                question.type == "scale"
                and OVERALL_RATING_TITLE in " ".join(question.text.split()).lower()
            ):
                return question.key
        return None

def _fail(message: str, **details: Any) -> None:
    raise ValidationFailed(message, **details)


def validate_definition(definition: Any) -> Form:
    """Validate an author-supplied questionnaire and return a flattened form.

    Raises `ValidationFailed` with a field-level message, so the editor can
    point at the problem rather than saying "invalid".
    """
    if not isinstance(definition, dict):
        _fail("The questionnaire definition must be an object.")

    scale = definition.get("scale") or {}
    if not isinstance(scale, dict):
        _fail("The rating scale must be an object.", scale=["not an object"])
    scale_min = scale.get("min", 1)
    scale_max = scale.get("max", 5)
    if not isinstance(scale_min, int) or not isinstance(scale_max, int):
        _fail("Scale bounds must be whole numbers.", scale=["min and max must be integers"])
    if not (2 <= scale_max - scale_min + 1 <= 11):
        _fail(
            "A rating scale needs between 2 and 11 points.",
            scale=[f"{scale_min}-{scale_max} is not a usable range"],
        )
    labels = scale.get("labels") or {}
    if not isinstance(labels, dict):
        _fail("Scale labels must be an object.", scale=["labels must be an object"])

    sections = definition.get("sections")
    if not isinstance(sections, list) or not sections:
        _fail("A questionnaire needs at least one section.", sections=["none provided"])
    if len(sections) > MAX_SECTIONS:
        _fail(f"A questionnaire cannot have more than {MAX_SECTIONS} sections.")

    questions: list[Question] = []
    seen_keys: set[str] = set()

    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            _fail(f"Section {index + 1} is not an object.")
        section_key = str(section.get("key") or f"section_{index + 1}")
        section_title = str(section.get("title") or "").strip()
        if not section_title:
            _fail(f"Section {index + 1} needs a title.")
        if len(section_title) > 120:
            _fail(f"The title of section {index + 1} is too long.")

        raw_questions = list(section.get("questions") or []) + list(section.get("extra") or [])
        if not raw_questions:
            _fail(f"Section '{section_title}' has no questions.")
        if len(raw_questions) > MAX_QUESTIONS_PER_SECTION:
            _fail(f"Section '{section_title}' has too many questions.")

        for question in raw_questions:
            if not isinstance(question, dict):
                _fail(f"A question in '{section_title}' is not an object.")
            key = str(question.get("key") or "").strip()
            if not KEY_RE.match(key):
                _fail(
                    f"Question key '{key}' is not valid.",
                    questions=["keys must be lowercase letters, digits and underscores"],
                )
            if key in seen_keys:
                # Duplicate keys would silently overwrite each other in the
                # answers object and corrupt every aggregate built from it.
                _fail(f"Question key '{key}' is used more than once.")
            seen_keys.add(key)

            text = str(question.get("text") or "").strip()
            if not text:
                _fail(f"Question '{key}' has no text.")
            if len(text) > MAX_TEXT:
                _fail(f"Question '{key}' is too long.")

            qtype = str(question.get("type") or "scale")
            if qtype not in QUESTION_TYPES:
                _fail(
                    f"Question '{key}' has an unknown type '{qtype}'.",
                    questions=[f"allowed: {', '.join(sorted(QUESTION_TYPES))}"],
                )

            options = [str(option) for option in (question.get("options") or [])]
            if qtype == "choice":
                if not 2 <= len(options) <= MAX_OPTIONS:
                    _fail(f"Question '{key}' needs between 2 and {MAX_OPTIONS} options.")
            else:
                options = []

            questions.append(
                Question(
                    key=key,
                    text=text,
                    type=qtype,
                    required=bool(question.get("required", qtype == "scale")),
                    options=options,
                    section_key=section_key,
                    section_title=section_title,
                )
            )

    if len(questions) > MAX_QUESTIONS_TOTAL:
        _fail(f"A questionnaire cannot have more than {MAX_QUESTIONS_TOTAL} questions.")

    closing = definition.get("closing") or {}
    
    return Form(
        intro=str(definition.get("intro") or "").strip()[:2000],
        scale_min=scale_min,
        scale_max=scale_max,
        scale_labels={str(k): str(v) for k, v in labels.items()},
        questions=questions,
        comment_prompt=str(
            closing.get("comment_prompt") or "Anything else you would like to add?"
        )[:300],
        comment_required=bool(closing.get("comment_required", False)),
    )


def normalise_definition(definition: Any) -> dict[str, Any]:
    """Validate, then return the definition with a schema version stamped on."""
    validate_definition(definition)
    output = dict(definition)
    output["schema_version"] = 1
    return output


@dataclass(frozen=True, slots=True)
class ScoredAnswers:
    answers: dict[str, Any]
    comment: str | None
    overall_score: float | None
    answered_count: int


def validate_answers(
    form: Form, submitted: Any, comment: Any = None
) -> ScoredAnswers:
    """Check a respondent's answers against the pinned form and score them.

    Problems are collected per-field (keyed by question key, plus
    "closing_comment" for the closing comment) rather than as one flat list.
    This lets the client point each message at the exact field it concerns,
    instead of dumping everything into a single banner.
    """
    if not isinstance(submitted, dict):
        _fail("Answers must be an object.")

    by_key = {question.key: question for question in form.questions}
    unknown = set(submitted) - set(by_key)
    if unknown:
        # Rejecting rather than ignoring: an answer to a question this version
        # does not contain means the client is out of date, and silently
        # dropping it would lose a respondent's input without telling anyone.
        _fail(
            "Some answers do not match this questionnaire.",
            answers=[f"unknown question(s): {', '.join(sorted(unknown))}"],
        )

    cleaned: dict[str, Any] = {}
    problems: dict[str, list[str]] = {}
    scores: list[int] = []

    for key, question in by_key.items():
        value = submitted.get(key)

        if value is None or value == "":
            if question.required:
                problems.setdefault(key, []).append(f"'{question.text}' is required")
            continue

        if question.type == "scale":
            if isinstance(value, bool) or not isinstance(value, int):
                problems.setdefault(key, []).append(f"'{question.text}' must be a whole number")
                continue
            if not form.scale_min <= value <= form.scale_max:
                problems.setdefault(key, []).append(
                    f"'{question.text}' must be between {form.scale_min} and {form.scale_max}"
                )
                continue
            cleaned[key] = value
            scores.append(value)

        elif question.type == "choice":
            if str(value) not in question.options:
                problems.setdefault(key, []).append(
                    f"'{question.text}' has an option that is not offered"
                )
                continue
            cleaned[key] = str(value)

        elif question.type == "boolean":
            if not isinstance(value, bool):
                problems.setdefault(key, []).append(f"'{question.text}' must be yes or no")
                continue
            cleaned[key] = value

        else:  # text
            text = str(value).strip()
            if len(text) > MAX_COMMENT:
                problems.setdefault(key, []).append(f"'{question.text}' is too long")
                continue
            cleaned[key] = text

    # Closing comment: previously this silently truncated an overlong comment
    # with no warning at all, losing whatever came after MAX_COMMENT without
    # telling the respondent. It is now checked and reported the same way a
    # text-question answer is, instead of being cut quietly.
    cleaned_comment = None
    if comment is not None:
        raw_comment = str(comment).strip()
        if len(raw_comment) > MAX_COMMENT:
            problems.setdefault("closing_comment", []).append(
                f"Your closing comment is too long (max {MAX_COMMENT} characters)"
            )
        else:
            cleaned_comment = raw_comment or None
    if form.comment_required and not cleaned_comment:
        problems.setdefault("closing_comment", []).append("A closing comment is required")

    if problems:
        _fail("Some answers still need attention.", **problems)

    if form.overall_rating_key is not None:
        rating_value = cleaned.get(form.overall_rating_key)
        overall = float(rating_value) if isinstance(rating_value, int) else None
    else:
        overall = round(sum(scores) / len(scores), 2) if scores else None
    return ScoredAnswers(
        answers=cleaned,
        comment=cleaned_comment,
        overall_score=overall,
        answered_count=len(cleaned),
    )


def form_payload(form: Form) -> dict[str, Any]:
    """Shape the form for the renderer, grouped back into sections."""
    sections: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for question in form.questions:
        section = index.get(question.section_key)
        if section is None:
            section = {
                "key": question.section_key,
                "title": question.section_title,
                "questions": [],
            }
            index[question.section_key] = section
            sections.append(section)
        section["questions"].append(
            {
                "key": question.key,
                "text": question.text,
                "type": question.type,
                "required": question.required,
                "options": question.options,
            }
        )

    return {
        "intro": form.intro,
        "scale": {
            "min": form.scale_min,
            "max": form.scale_max,
            "labels": form.scale_labels,
        },
        "sections": sections,
        "closing": {
            "comment_prompt": form.comment_prompt,
            "comment_required": form.comment_required,
        },
    }