"""Employee <-> Manager many-to-many (`UserManager`).

Shared by two callers that both need the same relationship: user CRUD
(`api/v1/users.py`, assigning who someone's managers are) and assignment
generation (`services/cycles.py`, deciding who a downward/upward/peer
review actually goes to). Kept as one small module rather than duplicated
in both, since the two have to agree on what "manager" means.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.models.user import UserManager


async def get_manager_ids(session: AsyncSession, employee_id: uuid.UUID) -> list[uuid.UUID]:
    """Every manager currently on record for one employee."""
    rows = (
        await session.execute(
            select(UserManager.manager_id).where(UserManager.employee_id == employee_id)
        )
    ).scalars().all()
    return list(rows)


async def get_manager_ids_map(
    session: AsyncSession, employee_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """employee_id -> list of manager_ids, batched for a page of people at
    once (the People list and assignment generation both need this for many
    employees in a single query, not one query per row)."""
    if not employee_ids:
        return {}
    rows = (
        await session.execute(
            select(UserManager.employee_id, UserManager.manager_id).where(
                UserManager.employee_id.in_(employee_ids)
            )
        )
    ).all()
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    for employee_id, manager_id in rows:
        result.setdefault(employee_id, []).append(manager_id)
    return result


async def get_reports_map(
    session: AsyncSession, employee_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """manager_id -> list of employee_ids who report to them, for a set of
    candidate employees. The inverse direction of get_manager_ids_map — one
    employee with several managers shows up under each of them here, which
    is exactly what makes "their direct reports" and "their peers" correct
    for someone with more than one manager."""
    if not employee_ids:
        return {}
    rows = (
        await session.execute(
            select(UserManager.manager_id, UserManager.employee_id).where(
                UserManager.employee_id.in_(employee_ids)
            )
        )
    ).all()
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    for manager_id, employee_id in rows:
        result.setdefault(manager_id, []).append(employee_id)
    return result


async def set_managers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    manager_ids: list[uuid.UUID],
) -> None:
    """Replace an employee's manager set with exactly `manager_ids`.

    Full replace rather than a diff — the People form always submits the
    complete checked set, not an incremental add/remove, so this is what
    "save" on that form actually means.
    """
    await session.execute(delete(UserManager).where(UserManager.employee_id == employee_id))
    for manager_id in dict.fromkeys(manager_ids):  # de-dupe, keep first-seen order
        if manager_id == employee_id:
            raise ValidationFailed("A person cannot be their own manager.")
        session.add(
            UserManager(org_id=org_id, employee_id=employee_id, manager_id=manager_id)
        )