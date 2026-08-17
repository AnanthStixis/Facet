"""Department / Job Title / Cycle Name / Product / Service master lists.

Five near-identical org-scoped name lists, one router each rather than one
generic parameterised router — the duplication is small (list, create, edit,
toggle) and keeping them as separate, readable endpoints avoids a layer of
indirection for what is intentionally simple, low-stakes reference data.

Any Manager or above may read and add to these lists (they're the ones
picking from them while creating people or feedback rounds); only an Admin
can rename, disable, or remove an entry, since that's an org-wide edit
rather than "I needed one more option".
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, DbSession, ManagerUser
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.masters import CycleName, Department, JobTitle, Product, Service
from app.models.user import User

departments_router = APIRouter(prefix="/masters/departments", tags=["masters"])
job_titles_router = APIRouter(prefix="/masters/job-titles", tags=["masters"])
cycle_names_router = APIRouter(prefix="/masters/cycle-names", tags=["masters"])
products_router = APIRouter(prefix="/masters/products", tags=["masters"])
services_router = APIRouter(prefix="/masters/services", tags=["masters"])

DEFAULT_PAGE_SIZE = 15


class MasterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MasterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "is_active": row.is_active,
        "created_by": row.created_by.full_name if row.created_by else None,
        "created_at": row.created_at.isoformat(),
    }


async def _find_duplicate(session: DbSession, model: type, org_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None):
    stmt = select(model).where(model.org_id == org_id, model.name.ilike(name))
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _build(model: type, router: APIRouter, singular: str) -> None:
    @router.get("", response_model=dict[str, Any])
    async def list_rows(
        session: DbSession,
        actor: ManagerUser,
        q: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        stmt = select(model).where(model.org_id == actor.org_id).options(selectinload(model.created_by))
        count_stmt = select(func.count()).select_from(model).where(model.org_id == actor.org_id)
        if q:
            stmt = stmt.where(model.name.ilike(f"%{q}%"))
            count_stmt = count_stmt.where(model.name.ilike(f"%{q}%"))
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(model.name).offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()
        return {
            "items": [_row(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @router.post("", status_code=201, response_model=dict[str, Any])
    async def create_row(
        payload: MasterCreateRequest, request: Request, session: DbSession, actor: ManagerUser
    ) -> dict[str, Any]:
        if actor.org_id is None:
            raise ValidationFailed("A Super Admin must act within an organization.")
        name = payload.name.strip()
        if not name:
            raise ValidationFailed(f"Give this {singular} a name.")
        existing = await _find_duplicate(session, model, actor.org_id, name)
        if existing:
            raise Conflict(f"'{name}' already exists in {singular}.")
        row = model(org_id=actor.org_id, name=name, created_by_id=actor.id)
        session.add(row)
        await session.commit()
        # `actor` is the resolved-identity dependency object, not the ORM
        # User instance, so it can't be assigned to the `created_by`
        # relationship — and reloading that relationship here would run in a
        # new transaction after commit, outside the tenant GUC that RLS
        # needs, and fail to find the row it just inserted. The creator is
        # this request's own actor either way, so just use its name directly.
        return {
            "id": str(row.id),
            "name": row.name,
            "is_active": row.is_active,
            "created_by": actor.user.full_name,
            "created_at": row.created_at.isoformat(),
        }

    @router.patch("/{row_id}", response_model=dict[str, Any])
    async def update_row(
        row_id: uuid.UUID, payload: MasterUpdateRequest, session: DbSession, actor: AdminUser
    ) -> dict[str, Any]:
        row = (
            await session.execute(
                select(model)
                .where(model.id == row_id, model.org_id == actor.org_id)
                .options(selectinload(model.created_by))
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(f"That {singular} does not exist.")
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise ValidationFailed(f"Give this {singular} a name.")
            duplicate = await _find_duplicate(session, model, actor.org_id, name, exclude_id=row_id)
            if duplicate:
                raise Conflict(f"'{name}' already exists in {singular}.")
            row.name = name
        if payload.is_active is not None:
            row.is_active = payload.is_active
        await session.commit()
        return _row(row)

    @router.delete("/{row_id}", status_code=204, response_model=None)
    async def delete_row(row_id: uuid.UUID, session: DbSession, actor: AdminUser) -> None:
        row = (
            await session.execute(
                select(model).where(model.id == row_id, model.org_id == actor.org_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(f"That {singular} does not exist.")
        await session.delete(row)
        await session.commit()


_build(Department, departments_router, "department")
_build(JobTitle, job_titles_router, "job title")
_build(CycleName, cycle_names_router, "cycle name")
_build(Product, products_router, "product")
_build(Service, services_router, "service")
