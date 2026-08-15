"""Vendor template library — the full category/template catalog.

Separate from `app.seed` on purpose: that script also creates the Super
Admin and a demo tenant with fake people, which you do not want to run
again against a server that already has real data on it (it would resurrect
a demo org you deleted, for one). This script only touches the vendor
catalog — rows with org_id = NULL, visible to every tenant, the same rows
`Templates.tsx` renders as "Provided templates". Safe to run repeatedly:
every category and template is upserted by its stable key/name, never
duplicated.

    python -m app.seed_templates

The question sets below are modelled on the dimensions real 360/engagement
platforms converge on — Culture Amp and Lattice for manager effectiveness
and peer review, Officevibe/Gallup-style items (paraphrased, not verbatim)
for engagement pulses, and standard SaaS onboarding/exit-interview practice
— adapted to this schema (Likert-5 by default, `choice`/`text`/`boolean`
where a scale question does not fit).

As of the templates-redesign session, this seeds exactly one template per
target type actually reachable from Create Feedback's six kinds: employee,
manager, client, product, service, proposal. `team` and `department` exist
in the `TargetType` schema but are not wired to any Create Feedback kind
today, so they are intentionally not seeded here — re-add them if that
changes. Every template that existed before this run is deactivated
(`is_active = False`, never hard-deleted — see the FK note in
`seed_templates()`) rather than replaced in place.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
from app.models.catalog import Category, FeedbackTemplate, FeedbackTemplateVersion
from app.models.enums import TargetType, TemplateScope, TemplateStatus
from app.models.user import User
from datetime import UTC, datetime

LIKERT_5 = {
    "type": "likert",
    "min": 1,
    "max": 5,
    "labels": {
        "1": "Strongly disagree",
        "2": "Disagree",
        "3": "Neutral",
        "4": "Agree",
        "5": "Strongly agree",
    },
}


def _definition(intro: str, sections: list[dict], comment_prompt: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "intro": intro,
        "scale": LIKERT_5,
        "sections": sections,
        "closing": {
            "comment_prompt": comment_prompt or "Anything else you would like to add?",
            "comment_required": False,
        },
    }


CATEGORIES = [
    {
        "key": "internal_360",
        "name": "Internal 360",
        "description": "Manager, upward, downward, and peer feedback inside the organization.",
        "applies_to": ["employee", "manager", "team", "department"],
        "icon": "users",
        "sort_order": 10,
    },
    {
        "key": "self_assessment",
        "name": "Self-assessment",
        "description": "A person's own view of their performance and growth, for comparison against how others see them.",
        "applies_to": ["employee", "manager"],
        "icon": "user-check",
        "sort_order": 15,
    },
    {
        "key": "onboarding",
        "name": "Onboarding",
        "description": "New-hire check-ins at 30/60/90 days, before problems become resignations.",
        "applies_to": ["employee"],
        "icon": "compass",
        "sort_order": 20,
    },
    {
        "key": "engagement",
        "name": "Engagement",
        "description": "Pulse surveys on how people feel about the team and the org, run on a regular cadence.",
        "applies_to": ["team", "department"],
        "icon": "activity",
        "sort_order": 25,
    },
    {
        "key": "exit",
        "name": "Exit interview",
        "description": "Structured, anonymous feedback from someone who has already decided to leave.",
        "applies_to": ["employee"],
        "icon": "log-out",
        "sort_order": 30,
    },
    {
        "key": "client_experience",
        "name": "Client experience",
        "description": "How clients and customers rate your products, services and people.",
        "applies_to": ["product", "service", "employee", "client"],
        "icon": "handshake",
        "sort_order": 40,
    },
    {
        "key": "proposal_quality",
        "name": "Proposal quality",
        "description": "Structured prospect feedback on proposals and statements of work.",
        "applies_to": ["proposal"],
        "icon": "file-text",
        "sort_order": 50,
    },
]

TEMPLATES = [
    # --- Employee: peer/self 360, works whether it's a peer or the person
    # themself answering ---------------------------------------------------
    {
        "category": "internal_360",
        "name": "360 review — collaboration and growth",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "A peer or self 360 covering how this person works with others, delivers, and grows — the default questionnaire for an employee review.",
        "definition": _definition(
            "Answer based on how this person has actually worked over the last review "
            "period. Be specific — vague praise or criticism is not useful to them.",
            [
                {
                    "key": "working_together",
                    "title": "Working together",
                    "questions": [
                        {"key": "responsiveness", "text": "This person responds to requests and messages in good time."},
                        {"key": "follow_through", "text": "When they commit to something, it gets done without needing to be chased."},
                        {"key": "communication_clarity", "text": "Their updates and explanations are clear enough to act on without follow-up questions."},
                    ],
                },
                {
                    "key": "growth",
                    "title": "Growth and impact",
                    "questions": [
                        {"key": "skill_growth", "text": "I have noticed a specific skill or capability of theirs improve this period.", "type": "boolean"},
                        {"key": "biggest_strength", "text": "What is the single biggest strength this person brought to the team this period?", "type": "text"},
                        {"key": "growth_area", "text": "What is one specific thing they could do differently to have more impact?", "type": "text"},
                    ],
                },
            ],
            comment_prompt="Anything else about how they worked this period that would be useful for them to hear?",
        ),
    },
    # --- Manager: upward review from direct reports ------------------------
    {
        "category": "internal_360",
        "name": "Upward review — manager effectiveness",
        "target_type": TargetType.MANAGER,
        "is_anonymous": True,
        "description": "Direct reports rate how well their manager sets direction, clears blockers, and coaches — anonymised and only shown once enough responses are in.",
        "definition": _definition(
            "Your answers are anonymous and are only revealed once enough people on "
            "the team have responded. Answer about your direct manager specifically.",
            [
                {
                    "key": "direction",
                    "title": "Direction and blockers",
                    "questions": [
                        {"key": "clear_priorities", "text": "My manager makes it clear what I should be prioritizing right now."},
                        {"key": "removes_blockers", "text": "When I raise a blocker, my manager helps get it resolved rather than leaving it to me."},
                        {"key": "decisions_explained", "text": "Decisions that affect my work are explained, not just announced."},
                    ],
                },
                {
                    "key": "coaching",
                    "title": "Coaching and safety",
                    "questions": [
                        {"key": "useful_feedback", "text": "I get specific, useful feedback often enough to actually improve."},
                        {"key": "psychological_safety", "text": "I feel safe telling my manager about a mistake or a problem before it becomes bigger."},
                        {"key": "advocates_for_me", "text": "My manager advocates for me and my work to others."},
                    ],
                },
            ],
            comment_prompt="What is the one change that would make this person a more effective manager?",
        ),
    },
    # --- Client: relationship health -------------------------------------
    {
        "category": "client_experience",
        "name": "Client relationship health check",
        "target_type": TargetType.CLIENT,
        "is_anonymous": False,
        "description": "How a client rates the overall working relationship — trust, responsiveness, and value delivered — independent of any single delivery.",
        "definition": _definition(
            "A few minutes on how the relationship is working for you overall, not "
            "any single project or delivery.",
            [
                {
                    "key": "relationship",
                    "title": "The relationship",
                    "questions": [
                        {"key": "trust", "text": "We trust this team to flag problems to us before we have to ask."},
                        {"key": "responsiveness", "text": "Our requests and concerns get a timely response."},
                        {"key": "value_delivered", "text": "What we're getting is worth what we're paying for it."},
                    ],
                },
                {
                    "key": "outlook",
                    "title": "Outlook",
                    "questions": [
                        {"key": "most_valuable", "text": "What has this team done recently that mattered most to you?", "type": "text"},
                    ],
                    "extra": [
                        {
                            "key": "renew_likelihood",
                            "type": "choice",
                            "text": "How likely are you to continue or expand this relationship?",
                            "options": ["Not likely", "Slightly likely", "Neutral", "Likely", "Very likely"],
                        },
                        {
                            "key": "recommend",
                            "type": "choice",
                            "text": "How likely are you to recommend us to a peer facing a similar problem?",
                            "options": ["Not likely", "Slightly likely", "Neutral", "Likely", "Very likely"],
                        },
                    ],
                },
            ],
            comment_prompt="What is the one thing that would most improve this relationship?",
        ),
    },
    # --- Product: usability and problem-solved ------------------------------
    {
        "category": "client_experience",
        "name": "Product feedback — usability and fit",
        "target_type": TargetType.PRODUCT,
        "is_anonymous": False,
        "description": "Sent to a user or client stakeholder after real usage — did the product solve their actual problem, and what's missing.",
        "definition": _definition(
            "A few minutes on how the product is actually working for you day to day.",
            [
                {
                    "key": "usability",
                    "title": "Using it day to day",
                    "questions": [
                        {"key": "ease_of_use", "text": "The product is easy to use without needing help."},
                        {"key": "reliability", "text": "The product behaves reliably — no surprises or unexpected breakage."},
                        {"key": "solved_problem", "text": "The product solved the actual problem I needed solved."},
                    ],
                },
                {
                    "key": "gaps",
                    "title": "Gaps",
                    "questions": [
                        {"key": "missing", "text": "What is the one thing missing that would make this product noticeably better for you?", "type": "text"},
                    ],
                    "extra": [
                        {
                            "key": "nps",
                            "type": "choice",
                            "text": "How likely are you to recommend this product to a colleague facing a similar need?",
                            "options": ["Not likely", "Slightly likely", "Neutral", "Likely", "Very likely"],
                        }
                    ],
                },
            ],
        ),
    },
    # --- Service: satisfaction with a specific interaction ------------------
    {
        "category": "client_experience",
        "name": "Service delivery satisfaction",
        "target_type": TargetType.SERVICE,
        "is_anonymous": False,
        "description": "Sent right after a specific service interaction or delivery milestone — timeliness, quality, and whether they'd use the service again.",
        "definition": _definition(
            "Thinking specifically about the service you just received — not the "
            "relationship overall — a couple of minutes on how it went.",
            [
                {
                    "key": "this_interaction",
                    "title": "This interaction",
                    "questions": [
                        {"key": "timeliness", "text": "This was delivered within the timeframe we agreed on."},
                        {"key": "quality", "text": "The quality of the work met what was scoped."},
                        {"key": "kept_informed", "text": "We were kept informed of progress without having to ask."},
                    ],
                },
                {
                    "key": "would_return",
                    "title": "Would you use this again",
                    "questions": [
                        {"key": "use_again", "text": "I would request this specific service again.", "type": "boolean"},
                        {"key": "what_stood_out", "text": "What, if anything, stood out — good or bad — about this delivery?", "type": "text"},
                    ],
                },
            ],
        ),
    },
    # --- Proposal: fit, clarity, and what decided it -----------------------
    {
        "category": "proposal_quality",
        "name": "Proposal feedback — fit and clarity",
        "target_type": TargetType.PROPOSAL,
        "is_anonymous": False,
        "description": "Sent to a prospect after they've reviewed a proposal — whether it fit their stated needs, how clear the pitch and pricing were, and what tipped their decision.",
        "definition": _definition(
            "Your feedback helps us scope and price proposals better, whether or not "
            "you decide to proceed with us.",
            [
                {
                    "key": "fit",
                    "title": "Fit to what we asked for",
                    "questions": [
                        {"key": "understood_need", "text": "The proposal showed a clear understanding of what we actually needed."},
                        {"key": "approach_appropriate", "text": "The proposed approach felt appropriately scoped — not over- or under-built."},
                    ],
                },
                {
                    "key": "clarity",
                    "title": "Clarity of the pitch",
                    "questions": [
                        {"key": "pricing_clarity", "text": "The pricing was clear and easy to compare against alternatives."},
                        {"key": "timeline_clarity", "text": "The proposed timeline was clear and believable."},
                    ],
                    "extra": [
                        {
                            "key": "estimate_vs_expectation",
                            "type": "choice",
                            "text": "Compared with what you expected going in, the price was:",
                            "options": ["Well under expectation", "Slightly under", "About right", "Slightly over", "Well over expectation"],
                        }
                    ],
                },
                {
                    "key": "decision",
                    "title": "What tipped it",
                    "questions": [
                        {"key": "deciding_factor", "text": "What was the single biggest factor in your decision, either way?", "type": "text"},
                    ],
                },
            ],
        ),
    },
]


async def seed_templates() -> None:
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

        # published_by needs a real user id — attribute new versions to the
        # platform Super Admin if one exists yet, else leave it unattributed
        # (the column is nullable) rather than fail the whole run.
        publisher = (
            await session.execute(
                select(User.id).where(User.role == "super_admin").limit(1)
            )
        ).scalar_one_or_none()

        created: list[str] = []

        # "Clear all the templates" per the client: every pre-existing
        # template (org-owned and global alike) gets deactivated rather than
        # hard-deleted, because `ReviewCycle.template_version_id` is an
        # `ON DELETE RESTRICT` foreign key and this dev DB already has cycles
        # pinned to old template versions from earlier verification runs.
        # `is_active = False` is sufficient on its own: it removes the
        # template from every UI surface (Templates page list default view,
        # Create Feedback's dropdown) without touching ReviewCycle history.
        # The six templates this script is about to (re)create below are
        # named distinctly from anything that came before, so this pass never
        # deactivates something this same run just created.
        new_names = {spec["name"] for spec in TEMPLATES}
        existing_templates = (
            await session.execute(select(FeedbackTemplate))
        ).scalars().all()
        deactivated = 0
        for existing in existing_templates:
            if existing.name in new_names:
                continue
            if existing.is_active:
                existing.is_active = False
                deactivated += 1
        if deactivated:
            await session.flush()

        category_ids: dict[str, object] = {}
        for spec in CATEGORIES:
            category = (
                await session.execute(
                    select(Category).where(
                        Category.key == spec["key"], Category.org_id.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if category is None:
                category = Category(org_id=None, **spec)
                session.add(category)
                created.append(f"category {spec['key']}")
            else:
                # Keep an existing category's copy in sync with the source of
                # truth here, so re-running this after a wording tweak
                # actually updates it instead of silently no-op'ing forever.
                category.name = spec["name"]
                category.description = spec["description"]
                category.applies_to = spec["applies_to"]
                category.icon = spec["icon"]
                category.sort_order = spec["sort_order"]
            await session.flush()
            category_ids[spec["key"]] = category.id

        for spec in TEMPLATES:
            template = (
                await session.execute(
                    select(FeedbackTemplate).where(
                        FeedbackTemplate.name == spec["name"],
                        FeedbackTemplate.org_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if template is None:
                template = FeedbackTemplate(
                    org_id=None,
                    category_id=category_ids[spec["category"]],
                    scope=TemplateScope.GLOBAL,
                    name=spec["name"],
                    description=spec["description"],
                    target_type=spec["target_type"],
                    is_anonymous=spec["is_anonymous"],
                    min_responses_to_reveal=settings.ai_min_responses_for_summary,
                )
                session.add(template)
                await session.flush()
                session.add(
                    FeedbackTemplateVersion(
                        org_id=None,
                        template_id=template.id,
                        version=1,
                        status=TemplateStatus.PUBLISHED,
                        definition=spec["definition"],
                        published_at=datetime.now(UTC),
                        published_by_id=publisher,
                    )
                )
                created.append(f"template {spec['name']}")
            else:
                # An existing global template already has a published v1.
                # Bumping the question wording here would silently change
                # what an in-flight cycle asked, which is exactly what
                # version-pinning exists to prevent — so an existing
                # template's questions are left alone; only new templates
                # get created. Delete it manually first if you need to
                # replace one's content.
                pass

        await session.commit()

        print(
            f"Template library sync complete. {len(created)} object(s) created, "
            f"{deactivated} pre-existing template(s) deactivated."
        )
        for item in created:
            print(f"  + {item}")
        if not created:
            print("  (nothing new — already up to date)")


if __name__ == "__main__":
    asyncio.run(seed_templates())
