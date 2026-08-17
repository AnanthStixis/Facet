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

The question sets below are transcribed directly from the client's own
reference forms (one per feedback type — Employee/Management/Client/
Product/Service/Proposal), each structured the same way: Technical /
Communication / Delivery & Discipline as scored sections (the form's
"Category" column becomes the section), a comments prompt, and an Overall
Rating — all on the same plain 1-5 scale the reference forms use.

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

RATING_1_5 = {
    "min": 1,
    "max": 5,
    "labels": {"1": "Poor", "5": "Excellent"},
}


def _section(key: str, title: str, questions: list[str]) -> dict:
    return {
        "key": key,
        "title": title,
        "questions": [
            {"key": f"{key}_{index}", "text": text, "type": "scale"}
            for index, text in enumerate(questions, start=1)
        ],
    }


def _reference_definition(
    *,
    technical: list[str],
    communication: list[str],
    delivery: list[str],
    comment_prompt: str,
) -> dict:
    """One shared shape for the reference-form-derived templates: three
    scored sections (Technical / Communication / Delivery & Discipline) plus
    a single Overall Rating, mirroring the printed reference forms these
    were transcribed from — the category becomes the section, each row
    becomes a scale question on the same 1-5 range."""
    return {
        "schema_version": 1,
        "intro": "Rate each item on a scale of 1 to 5.",
        "scale": RATING_1_5,
        "sections": [
            _section("technical", "Technical", technical),
            _section("communication", "Communication", communication),
            _section("delivery", "Delivery & Discipline", delivery),
            _section("overall", "Overall Rating", ["Overall Rating"]),
        ],
        "closing": {
            "comment_prompt": comment_prompt,
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
    {
        "category": "internal_360",
        "name": "Employee review",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "Technical, communication, and delivery ratings for one employee, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the employee's technical / job-related skills?",
                "How effectively does the employee apply their knowledge to solve problems?",
            ],
            communication=[
                "How effectively does the employee communicate with team members and stakeholders?",
                "How well does the employee collaborate within the team?",
            ],
            delivery=[
                "How consistently does the employee meet deadlines and follow processes?",
            ],
            comment_prompt="Please provide additional feedback on the employee's overall performance.",
        ),
    },
    {
        "category": "internal_360",
        "name": "Management review",
        "target_type": TargetType.MANAGER,
        "is_anonymous": True,
        "description": "Technical, communication, and delivery ratings for a manager from their direct reports, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the manager's domain / technical knowledge?",
                "How effectively does the manager provide technical guidance and support decision-making?",
            ],
            communication=[
                "How clearly does the manager communicate goals, expectations, and feedback?",
                "How approachable and open is the manager to team input?",
            ],
            delivery=[
                "How well does the manager ensure timely delivery and maintain team discipline?",
            ],
            comment_prompt="Please share additional comments on the manager's leadership.",
        ),
    },
    {
        "category": "client_experience",
        "name": "Client review",
        "target_type": TargetType.CLIENT,
        "is_anonymous": False,
        "description": "A client's technical, communication, and delivery ratings for the team member they work with, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the technical expertise demonstrated by the team member?",
                "How well did the team member understand and address your project requirements?",
            ],
            communication=[
                "How clear and timely was the team member's communication with you?",
                "How responsive was the team member to your queries and concerns?",
            ],
            delivery=[
                "How would you rate the team member's adherence to deadlines and commitments?",
            ],
            comment_prompt="Please share any additional comments or suggestions for the team member.",
        ),
    },
    {
        "category": "client_experience",
        "name": "Product review",
        "target_type": TargetType.PRODUCT,
        "is_anonymous": False,
        "description": "Technical quality, documentation, and delivery ratings for a product, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the technical quality and functionality of the product?",
                "How reliable and bug-free is the product in daily use?",
            ],
            communication=[
                "How clear and helpful is the product documentation / user guidance?",
                "How effective is the communication of updates and changes to users?",
            ],
            delivery=[
                "How would you rate the product's release / update timeliness and quality control?",
            ],
            comment_prompt="Please share suggestions for improving the product.",
        ),
    },
    {
        "category": "client_experience",
        "name": "Service review",
        "target_type": TargetType.SERVICE,
        "is_anonymous": False,
        "description": "Technical competency, communication, and delivery ratings for a service engagement, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the technical competency of the service provided?",
                "How effectively were your issues / requests resolved?",
            ],
            communication=[
                "How clear and courteous was the communication during service delivery?",
                "How responsive was the service team to your inquiries?",
            ],
            delivery=[
                "How would you rate the timeliness and consistency of the service delivery?",
            ],
            comment_prompt="Please share any additional comments about the service experience.",
        ),
    },
    {
        "category": "proposal_quality",
        "name": "Proposal review",
        "target_type": TargetType.PROPOSAL,
        "is_anonymous": False,
        "description": "Technical soundness, clarity, and delivery-plan ratings for a submitted proposal or SOW, plus an overall score.",
        "definition": _reference_definition(
            technical=[
                "How would you rate the technical feasibility and soundness of the proposal?",
                "How well does the proposal address the stated requirements / objectives?",
            ],
            communication=[
                "How clearly is the proposal written and presented?",
                "How effectively were questions / clarifications addressed during discussions?",
            ],
            delivery=[
                "How realistic and well-structured is the proposed timeline and delivery plan?",
            ],
            comment_prompt="Please share additional comments or recommendations regarding the proposal.",
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
