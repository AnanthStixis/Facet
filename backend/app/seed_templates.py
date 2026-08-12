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
where a scale question does not fit). Every target_type the product
actually supports gets at least one template: employee, manager, team,
department, product, service, proposal.
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
        "applies_to": ["product", "service", "employee"],
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
    # --- Internal 360: every direction of the reporting line -----------------
    {
        "category": "internal_360",
        "name": "Manager effectiveness (upward feedback)",
        "target_type": TargetType.MANAGER,
        "is_anonymous": True,
        "description": "Upward feedback on a manager, anonymised and aggregated.",
        "definition": _definition(
            "Your answers are anonymous and are only shown once enough responses "
            "have been collected.",
            [
                {
                    "key": "support",
                    "title": "Support and development",
                    "questions": [
                        {"key": "clear_expectations",
                         "text": "My manager sets clear expectations for my work."},
                        {"key": "regular_feedback",
                         "text": "I receive useful feedback often enough to improve."},
                        {"key": "growth",
                         "text": "My manager actively supports my development."},
                        {"key": "recognition",
                         "text": "My manager recognises good work when it happens."},
                    ],
                },
                {
                    "key": "leadership",
                    "title": "Leadership",
                    "questions": [
                        {"key": "decisions",
                         "text": "Decisions are explained in a way I can understand."},
                        {"key": "trust", "text": "I can raise a concern without hesitation."},
                        {"key": "prioritisation",
                         "text": "My manager helps me focus on what matters most."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "internal_360",
        "name": "Downward review (manager on direct report)",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "A manager's structured review of a direct report — attributable, part of the normal review conversation.",
        "definition": _definition(
            "Rate this person's performance over the review period. This is not "
            "anonymous — it is meant to be discussed directly with them.",
            [
                {
                    "key": "delivery",
                    "title": "Delivery",
                    "questions": [
                        {"key": "quality", "text": "The quality of their work meets expectations."},
                        {"key": "reliability", "text": "They deliver what they commit to, on time."},
                        {"key": "ownership", "text": "They take ownership of problems without being asked."},
                    ],
                },
                {
                    "key": "growth",
                    "title": "Growth",
                    "questions": [
                        {"key": "improvement", "text": "They have visibly grown since the last review."},
                        {"key": "coachable", "text": "They respond well to feedback."},
                    ],
                },
            ],
            comment_prompt="What is the one thing they should focus on next?",
        ),
    },
    {
        "category": "internal_360",
        "name": "Peer collaboration review",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "Cross-team peer feedback on collaboration and delivery.",
        "definition": _definition(
            "Please answer based on how you have worked together over the last cycle.",
            [
                {
                    "key": "collaboration",
                    "title": "Collaboration",
                    "questions": [
                        {"key": "responsive", "text": "This person responds in good time."},
                        {"key": "clarity", "text": "Their communication is clear and direct."},
                        {"key": "reliability", "text": "They deliver what they commit to."},
                        {"key": "constructive", "text": "They give feedback that is honest and constructive."},
                    ],
                }
            ],
        ),
    },
    {
        "category": "internal_360",
        "name": "Team lead 360",
        "target_type": TargetType.TEAM,
        "is_anonymous": True,
        "description": "How a team functions as a unit — sent to everyone on the team, aggregated so no single voice stands out.",
        "definition": _definition(
            "Answer about the team as a whole, not any one person. Responses are "
            "anonymous and aggregated.",
            [
                {
                    "key": "function",
                    "title": "How the team works",
                    "questions": [
                        {"key": "clarity_of_roles", "text": "It is clear who is responsible for what."},
                        {"key": "psych_safety", "text": "People on this team feel safe raising problems early."},
                        {"key": "decision_speed", "text": "This team makes decisions without unnecessary delay."},
                        {"key": "conflict", "text": "Disagreements get resolved constructively, not avoided."},
                    ],
                },
            ],
        ),
    },
    # --- Self-assessment -------------------------------------------------
    {
        "category": "self_assessment",
        "name": "Self-assessment: performance and growth",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "A person's own rating of their period, submitted before or alongside their manager's — used to spot self-awareness gaps, not to be anonymous.",
        "definition": _definition(
            "Rate your own performance honestly. There is no reward for rating "
            "yourself higher than you believe is accurate.",
            [
                {
                    "key": "performance",
                    "title": "This period",
                    "questions": [
                        {"key": "goals_met", "text": "I met the goals I set for this period."},
                        {"key": "quality", "text": "I am proud of the quality of my work this period."},
                        {"key": "impact", "text": "My work had a visible impact on the team's outcomes."},
                    ],
                },
                {
                    "key": "development",
                    "title": "Development",
                    "questions": [
                        {"key": "skill_growth", "text": "I have grown a specific skill this period."},
                        {"key": "support_needed", "text": "I am getting the support I need to do my job well."},
                    ],
                },
            ],
            comment_prompt="What do you want to be different next period?",
        ),
    },
    # --- Onboarding ---------------------------------------------------------
    {
        "category": "onboarding",
        "name": "30/60/90 day onboarding check-in",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "Sent to a new hire at 30, 60, and 90 days — same questionnaire each time, so answers are comparable across the ramp period.",
        "definition": _definition(
            "There are no wrong answers here — this only works if you are honest "
            "about what is and is not working.",
            [
                {
                    "key": "ramp",
                    "title": "Getting up to speed",
                    "questions": [
                        {"key": "role_clarity", "text": "I understand what is expected of me in this role."},
                        {"key": "tools_access", "text": "I have the tools and access I need to do my job."},
                        {"key": "training", "text": "The onboarding/training I received prepared me well."},
                    ],
                },
                {
                    "key": "belonging",
                    "title": "Settling in",
                    "questions": [
                        {"key": "team_welcome", "text": "My team has made me feel welcome."},
                        {"key": "manager_checkins", "text": "My manager checks in with me often enough."},
                    ],
                },
                {
                    "key": "outlook",
                    "title": "Outlook",
                    "extra": [
                        {
                            "key": "would_recommend",
                            "type": "choice",
                            "text": "Based on your experience so far, would you recommend a friend apply here?",
                            "options": ["Definitely not", "Probably not", "Not sure", "Probably yes", "Definitely yes"],
                        }
                    ],
                    "questions": [],
                },
            ],
        ),
    },
    # --- Engagement pulse -----------------------------------------------
    {
        "category": "engagement",
        "name": "Team engagement pulse",
        "target_type": TargetType.TEAM,
        "is_anonymous": True,
        "description": "A short, regular-cadence pulse survey — designed to be sent monthly or quarterly without fatiguing people.",
        "definition": _definition(
            "This is a quick pulse, not a full review — five questions, anonymous "
            "and aggregated.",
            [
                {
                    "key": "pulse",
                    "title": "Right now",
                    "questions": [
                        {"key": "motivation", "text": "I feel motivated by the work I am doing."},
                        {"key": "workload", "text": "My workload is manageable right now."},
                        {"key": "voice", "text": "I feel my opinion counts on this team."},
                        {"key": "growth_path", "text": "I can see a path to grow here."},
                    ],
                    "extra": [
                        {
                            "key": "enps",
                            "type": "choice",
                            "text": "How likely are you to recommend this team as a great place to work?",
                            "options": ["Not likely", "Slightly likely", "Neutral", "Likely", "Very likely"],
                        }
                    ],
                },
            ],
        ),
    },
    {
        "category": "engagement",
        "name": "Department health check",
        "target_type": TargetType.DEPARTMENT,
        "is_anonymous": True,
        "description": "A broader, less frequent check on how a whole department is doing — direction, cross-team friction, resourcing.",
        "definition": _definition(
            "Answer about the department as a whole. Anonymous and aggregated.",
            [
                {
                    "key": "direction",
                    "title": "Direction",
                    "questions": [
                        {"key": "strategy_clarity", "text": "I understand this department's priorities for this period."},
                        {"key": "resourcing", "text": "This department is resourced well enough to meet its goals."},
                    ],
                },
                {
                    "key": "cross_team",
                    "title": "Working across teams",
                    "questions": [
                        {"key": "handoffs", "text": "Handoffs between teams in this department are smooth."},
                        {"key": "information_flow", "text": "Important information reaches the people who need it."},
                    ],
                },
            ],
        ),
    },
    # --- Exit interview -------------------------------------------------
    {
        "category": "exit",
        "name": "Exit interview",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": True,
        "description": "Sent once someone has confirmed they are leaving — anonymous, so the honest reason for leaving actually surfaces.",
        "definition": _definition(
            "Your responses are anonymous. Nothing here affects your reference or "
            "final pay — this only helps us understand what to change.",
            [
                {
                    "key": "reasons",
                    "title": "Why you're leaving",
                    "questions": [
                        {"key": "would_return", "text": "Under different circumstances, I would consider returning here."},
                        {"key": "manager_support", "text": "I felt supported by my manager while I was here."},
                        {"key": "growth_opportunity", "text": "I had enough opportunity to grow in this role."},
                    ],
                    "extra": [
                        {
                            "key": "primary_reason",
                            "type": "choice",
                            "text": "What is the single biggest reason you are leaving?",
                            "options": [
                                "Compensation", "Career growth", "Management",
                                "Work-life balance", "Relocation", "Company direction", "Other",
                            ],
                        },
                    ],
                },
            ],
            comment_prompt="What is the one thing that would have changed your mind?",
        ),
    },
    # --- Client experience -----------------------------------------------
    {
        "category": "client_experience",
        "name": "Post-delivery client satisfaction",
        "target_type": TargetType.SERVICE,
        "is_anonymous": False,
        "description": "Sent to a client contact after a delivery milestone.",
        "definition": _definition(
            "Thank you for taking two minutes to tell us how the engagement went.",
            [
                {
                    "key": "delivery",
                    "title": "Delivery",
                    "questions": [
                        {"key": "on_time", "text": "The work was delivered on schedule."},
                        {"key": "quality", "text": "The quality met our expectations."},
                        {"key": "communication", "text": "We were kept informed throughout."},
                    ],
                },
                {
                    "key": "outcome",
                    "title": "Outcome",
                    "questions": [
                        {"key": "value", "text": "The engagement delivered the value we expected."},
                        {"key": "recommend", "text": "I would recommend this team to a colleague."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "client_experience",
        "name": "Product satisfaction survey",
        "target_type": TargetType.PRODUCT,
        "is_anonymous": False,
        "description": "A short CSAT/NPS-style survey for a shipped product or feature, sent to end users or client stakeholders.",
        "definition": _definition(
            "A couple of minutes on how the product is working for you.",
            [
                {
                    "key": "experience",
                    "title": "Using the product",
                    "questions": [
                        {"key": "ease_of_use", "text": "The product is easy to use."},
                        {"key": "reliability", "text": "The product works reliably."},
                        {"key": "meets_needs", "text": "The product meets the needs it was built for."},
                    ],
                    "extra": [
                        {
                            "key": "nps",
                            "type": "choice",
                            "text": "How likely are you to recommend this product to a colleague?",
                            "options": ["Not likely", "Slightly likely", "Neutral", "Likely", "Very likely"],
                        }
                    ],
                },
            ],
        ),
    },
    # --- Proposal quality --------------------------------------------------
    {
        "category": "proposal_quality",
        "name": "Proposal and SOW quality",
        "target_type": TargetType.PROPOSAL,
        "is_anonymous": False,
        "description": (
            "Structured prospect feedback on a submitted proposal: technical quality, "
            "estimation accuracy, infrastructure, and responsiveness."
        ),
        "definition": _definition(
            "Your feedback on our proposal helps us estimate and scope better, whether "
            "or not you proceed with us.",
            [
                {
                    "key": "technical",
                    "title": "Technical quality",
                    "questions": [
                        {"key": "understanding",
                         "text": "The proposal showed a clear understanding of our problem."},
                        {"key": "approach", "text": "The proposed technical approach was sound."},
                        {"key": "infrastructure",
                         "text": "The proposed infrastructure suited our environment."},
                    ],
                },
                {
                    "key": "commercial",
                    "title": "Estimation and commercials",
                    "questions": [
                        {"key": "estimate_accuracy",
                         "text": "The effort estimate looked realistic for the scope."},
                        {"key": "pricing_clarity", "text": "Pricing was transparent and clear."},
                    ],
                    "extra": [
                        {
                            "key": "estimate_direction",
                            "type": "choice",
                            "text": "Compared with your expectation, the estimate was:",
                            "options": [
                                "Well under budget", "Slightly under", "About right",
                                "Slightly over", "Well over budget",
                            ],
                        }
                    ],
                },
                {
                    "key": "process",
                    "title": "Process",
                    "questions": [
                        {"key": "responsiveness",
                         "text": "We received timely responses to our questions."},
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

        print(f"Template library sync complete. {len(created)} object(s) created.")
        for item in created:
            print(f"  + {item}")
        if not created:
            print("  (nothing new — already up to date)")


if __name__ == "__main__":
    asyncio.run(seed_templates())
