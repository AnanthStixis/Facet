"""Development seed.

Creates the platform Super Admin, the vendor-authored category and template
library, and one demo tenant with people and feedback targets so the UI has
something real to render.

Idempotent: safe to run repeatedly.

    python -m app.seed
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionFactory
from app.db.tenancy import TenantContext, bind_tenant
from app.models.catalog import (
    Category,
    Contact,
    FeedbackTarget,
    FeedbackTemplate,
    FeedbackTemplateVersion,
)
from app.models.enums import (
    OrgRegistrationSource,
    OrgStatus,
    TargetType,
    TemplateScope,
    TemplateStatus,
    UserRole,
    UserStatus,
)
from app.models.organization import OrgBranding, Organization
from app.models.user import User

SUPER_ADMIN_EMAIL = "admin@stixis.com"
SUPER_ADMIN_PASSWORD = "FacetPlatform!2026"
CLIENT_ADMIN_EMAIL = "priya.raman@northwind.example"
CLIENT_ADMIN_PASSWORD = "NorthwindAdmin!2026"

# Vendor-authored library. These are the defaults a new tenant clones, and they
# are the reason a customer can run their first campaign on day one instead of
# staring at an empty form builder.
GLOBAL_CATEGORIES = [
    {
        "key": "internal_360",
        "name": "Internal 360",
        "description": "Manager, upward, and peer feedback inside the organization.",
        "applies_to": ["employee", "manager", "team", "department"],
        "icon": "users",
        "sort_order": 10,
    },
    {
        "key": "client_experience",
        "name": "Client experience",
        "description": "How clients and customers rate your products, services and people.",
        "applies_to": ["product", "service", "employee"],
        "icon": "handshake",
        "sort_order": 20,
    },
    {
        "key": "proposal_quality",
        "name": "Proposal quality",
        "description": "Structured prospect feedback on proposals and statements of work.",
        "applies_to": ["proposal"],
        "icon": "file-text",
        "sort_order": 30,
    },
    {
        "key": "getting_started",
        "name": "Getting started",
        "description": "One simple default template for each feedback type, ready to use immediately.",
        "applies_to": [],
        "icon": "spark",
        "sort_order": 5,
    },
]

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


def _definition(intro: str, sections: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "intro": intro,
        "scale": LIKERT_5,
        "sections": sections,
        "closing": {
            "comment_prompt": "Anything else you would like to add?",
            "comment_required": False,
        },
    }


GLOBAL_TEMPLATES = [
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
                    ],
                },
                {
                    "key": "leadership",
                    "title": "Leadership",
                    "questions": [
                        {"key": "decisions",
                         "text": "Decisions are explained in a way I can understand."},
                        {"key": "trust", "text": "I can raise a concern without hesitation."},
                    ],
                },
            ],
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
                    ],
                }
            ],
        ),
    },
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
                        {"key": "communication",
                         "text": "We were kept informed throughout."},
                    ],
                },
                {
                    "key": "outcome",
                    "title": "Outcome",
                    "questions": [
                        {"key": "value", "text": "The engagement delivered the value we expected."},
                        {"key": "recommend",
                         "text": "I would recommend this team to a colleague."},
                    ],
                },
            ],
        ),
    },
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
    # --- One deliberately simple default per feedback type ------------------
    # Everything above is a realistic, detailed example template. These are
    # the opposite on purpose: two or three plain questions each, so every
    # one of the six Create Feedback types has an obvious, no-thought-required
    # option to start with, especially right after `reset_all_data.py` wipes
    # the database and there is nothing else to pick from yet.
    {
        "category": "getting_started",
        "name": "Default Employees Feedback",
        "target_type": TargetType.EMPLOYEE,
        "is_anonymous": False,
        "description": "A simple, general-purpose review for one employee.",
        "definition": _definition(
            "A quick, general check-in — no special preparation needed.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "does_good_work", "text": "This person does good work."},
                        {"key": "good_to_work_with", "text": "This person is good to work with."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "getting_started",
        "name": "Default Management Feedback",
        "target_type": TargetType.MANAGER,
        "is_anonymous": True,
        "description": "A simple, anonymous check-in on a manager.",
        "definition": _definition(
            "Your answers are anonymous.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "supports_me", "text": "My manager supports me."},
                        {"key": "communicates_clearly", "text": "My manager communicates clearly."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "getting_started",
        "name": "Default Client Feedback",
        "target_type": TargetType.CLIENT,
        "is_anonymous": False,
        "description": "A simple relationship check-in for a client.",
        "definition": _definition(
            "Thank you for taking a minute to share your feedback.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "happy_with_relationship", "text": "I am happy with this relationship."},
                        {"key": "would_recommend", "text": "I would recommend us to others."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "getting_started",
        "name": "Default Product Feedback",
        "target_type": TargetType.PRODUCT,
        "is_anonymous": False,
        "description": "A simple satisfaction check-in for a product.",
        "definition": _definition(
            "Thank you for taking a minute to share your feedback.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "meets_needs", "text": "This product meets my needs."},
                        {"key": "easy_to_use", "text": "This product is easy to use."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "getting_started",
        "name": "Default Service Feedback",
        "target_type": TargetType.SERVICE,
        "is_anonymous": False,
        "description": "A simple satisfaction check-in for a delivered service.",
        "definition": _definition(
            "Thank you for taking a minute to share your feedback.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "met_expectations", "text": "This service met my expectations."},
                        {"key": "would_use_again", "text": "I would use this service again."},
                    ],
                },
            ],
        ),
    },
    {
        "category": "getting_started",
        "name": "Default Proposal Review Feedback",
        "target_type": TargetType.PROPOSAL,
        "is_anonymous": False,
        "description": "A simple quality check-in for a submitted proposal.",
        "definition": _definition(
            "Thank you for taking a minute to share your feedback.",
            [
                {
                    "key": "general",
                    "title": "General",
                    "questions": [
                        {"key": "was_clear", "text": "The proposal was clear and easy to understand."},
                        {"key": "met_needs", "text": "The proposal addressed our needs."},
                    ],
                },
            ],
        ),
    },
]


async def seed() -> None:
    async with SessionFactory() as session:
        # Seeding legitimately spans every tenant, so it runs with the platform
        # context bound. This is the only place outside authentication that
        # does so, and it is a developer script, not a request path.
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))

        created: list[str] = []

        # --- Super Admin ---------------------------------------------------
        super_admin = (
            await session.execute(select(User).where(User.email == SUPER_ADMIN_EMAIL))
        ).scalar_one_or_none()
        if super_admin is None:
            super_admin = User(
                org_id=None,
                email=SUPER_ADMIN_EMAIL,
                full_name="Mahesh Puttaswamy",
                job_title="Platform owner",
                role=UserRole.SUPER_ADMIN,
                status=UserStatus.ACTIVE,
                password_hash=hash_password(SUPER_ADMIN_PASSWORD),
                password_changed_at=datetime.now(UTC),
            )
            session.add(super_admin)
            created.append(f"super admin {SUPER_ADMIN_EMAIL}")
        await session.flush()

        # --- Global catalog -------------------------------------------------
        category_ids: dict[str, object] = {}
        for spec in GLOBAL_CATEGORIES:
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
            await session.flush()
            category_ids[spec["key"]] = category.id

        for spec in GLOBAL_TEMPLATES:
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
                        published_by_id=super_admin.id,
                    )
                )
                created.append(f"template {spec['name']}")

        # --- Demo tenant ----------------------------------------------------
        org = (
            await session.execute(
                select(Organization).where(Organization.slug == "northwind-logistics")
            )
        ).scalar_one_or_none()
        if org is None:
            org = Organization(
                name="Northwind Logistics",
                slug="northwind-logistics",
                legal_name="Northwind Logistics Pvt Ltd",
                status=OrgStatus.ACTIVE,
                registration_source=OrgRegistrationSource.PROVISIONED,
                contact_name="Priya Raman",
                contact_email=CLIENT_ADMIN_EMAIL,
                country="IN",
                timezone="Asia/Kolkata",
                seat_limit=250,
                approved_at=datetime.now(UTC),
                approved_by_id=super_admin.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgBranding(org_id=org.id, accent_color="#B4633A"))
            created.append("organization Northwind Logistics")

        people = [
            (CLIENT_ADMIN_EMAIL, "Priya Raman", UserRole.CLIENT_ADMIN,
             "Head of People", "People"),
            ("arun.k@northwind.example", "Arun Kulkarni", UserRole.MANAGER,
             "Delivery Manager", "Delivery"),
            ("sneha.d@northwind.example", "Sneha Deshpande", UserRole.MANAGER,
             "Engineering Manager", "Engineering"),
            ("vikram.s@northwind.example", "Vikram Shetty", UserRole.EMPLOYEE,
             "Senior Engineer", "Engineering"),
            ("meera.j@northwind.example", "Meera Joshi", UserRole.EMPLOYEE,
             "Business Analyst", "Delivery"),
            ("rahul.n@northwind.example", "Rahul Nair", UserRole.EMPLOYEE,
             "QA Lead", "Engineering"),
        ]
        for email, name, role, title, dept in people:
            existing = (
                await session.execute(
                    select(User).where(User.org_id == org.id, User.email == email)
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    User(
                        org_id=org.id,
                        email=email,
                        full_name=name,
                        job_title=title,
                        department=dept,
                        role=role,
                        status=UserStatus.ACTIVE,
                        password_hash=hash_password(
                            CLIENT_ADMIN_PASSWORD if role == UserRole.CLIENT_ADMIN
                            else "NorthwindUser!2026"
                        ),
                        password_changed_at=datetime.now(UTC),
                    )
                )
                created.append(f"user {email}")
        await session.flush()

        # Feedback targets across all three domains, which is what makes the
        # dashboard coverage view show the unified graph rather than an
        # employee-only product.
        members = (
            (await session.execute(select(User).where(User.org_id == org.id)))
            .scalars()
            .all()
        )
        target_specs: list[tuple[TargetType, str, str, object]] = [
            *[
                (
                    TargetType.MANAGER if member.role == UserRole.MANAGER
                    else TargetType.EMPLOYEE,
                    member.full_name,
                    f"user:{member.email}",
                    member.id,
                )
                for member in members
            ],
            (TargetType.TEAM, "Engineering", "team:engineering", None),
            (TargetType.TEAM, "Delivery", "team:delivery", None),
            (TargetType.DEPARTMENT, "Operations", "dept:operations", None),
            (TargetType.SERVICE, "Managed Integration Service", "svc:integration", None),
            (TargetType.SERVICE, "Warehouse Analytics", "svc:wh-analytics", None),
            (TargetType.PRODUCT, "Northwind Track & Trace", "prod:track-trace", None),
            (TargetType.PROPOSAL, "Parata / NEXiA platform modernisation",
             "prop:parata-nexia", None),
            (TargetType.PROPOSAL, "Gilbarco field service SOW", "prop:gilbarco-fs", None),
        ]
        for target_type, label, reference, subject_id in target_specs:
            found = (
                await session.execute(
                    select(FeedbackTarget).where(
                        FeedbackTarget.org_id == org.id,
                        FeedbackTarget.target_type == target_type,
                        FeedbackTarget.reference == reference,
                    )
                )
            ).scalar_one_or_none()
            if found is None:
                session.add(
                    FeedbackTarget(
                        org_id=org.id,
                        target_type=target_type,
                        label=label,
                        reference=reference,
                        subject_user_id=subject_id,
                        attributes=(
                            {"stage": "submitted", "value_band": "mid"}
                            if target_type == TargetType.PROPOSAL
                            else {}
                        ),
                    )
                )

        for email, name, company, title in [
            ("agni.rao@parata.example", "Agni Rao", "Parata", "Sales Lead"),
            ("dana.f@gilbarco.example", "Dana Fitzgerald", "Gilbarco", "Programme Manager"),
            ("s.iyer@bluefleet.example", "Sudha Iyer", "BlueFleet", "Operations Director"),
        ]:
            found = (
                await session.execute(
                    select(Contact).where(Contact.org_id == org.id, Contact.email == email)
                )
            ).scalar_one_or_none()
            if found is None:
                session.add(
                    Contact(
                        org_id=org.id,
                        email=email,
                        full_name=name,
                        company=company,
                        job_title=title,
                        tags=["prospect"] if company == "Parata" else ["client"],
                    )
                )

        # A pending tenant so the Super Admin approval queue is not empty.
        pending = (
            await session.execute(
                select(Organization).where(Organization.slug == "gilbarco-india")
            )
        ).scalar_one_or_none()
        if pending is None:
            pending = Organization(
                name="Gilbarco India",
                slug="gilbarco-india",
                status=OrgStatus.PENDING,
                registration_source=OrgRegistrationSource.SELF_SERVICE,
                contact_name="Dana Fitzgerald",
                contact_email="dana.f@gilbarco.example",
                country="IN",
                timezone="Asia/Kolkata",
            )
            session.add(pending)
            await session.flush()
            session.add(OrgBranding(org_id=pending.id))
            created.append("pending organization Gilbarco India")

        await session.commit()

    print(f"Seed complete. {len(created)} object(s) created.")
    for item in created:
        print(f"  + {item}")
    print()
    print("Sign in with:")
    print(f"  Super Admin   {SUPER_ADMIN_EMAIL} / {SUPER_ADMIN_PASSWORD}")
    print(f"  Client Admin  {CLIENT_ADMIN_EMAIL} / {CLIENT_ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
