"""Resolves which `EmailTemplate` a feedback-request send should use.

An org's own row for a kind always wins; the platform's global row for that
kind is the fallback every org starts from until it customizes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_template import EmailTemplate
from app.models.enums import EmailTemplateKind


async def resolve(
    session: AsyncSession, *, org_id: uuid.UUID | None, kind: EmailTemplateKind | str
) -> EmailTemplate | None:
    """The template that should be used to send a `kind` invite for
    `org_id` right now: that org's own active row if it has one, else the
    active platform default for the kind, else `None` (in which case the
    caller should fall back to the hardcoded copy in `email.py`)."""
    kind = EmailTemplateKind(kind)
    if org_id is not None:
        own = (
            await session.execute(
                select(EmailTemplate).where(
                    EmailTemplate.org_id == org_id,
                    EmailTemplate.kind == kind,
                    EmailTemplate.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if own is not None:
            return own

    return (
        await session.execute(
            select(EmailTemplate).where(
                EmailTemplate.org_id.is_(None),
                EmailTemplate.kind == kind,
                EmailTemplate.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
