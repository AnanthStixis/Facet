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
from sqlalchemy import func, or_, select
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


def _row(row: Any, *, has_scope: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(row.id),
        "name": row.name,
        "is_active": row.is_active,
        "created_by": row.created_by.full_name if row.created_by else None,
        "created_at": row.created_at.isoformat(),
    }
    if has_scope:
        payload["scope"] = "global" if row.org_id is None else "org"
    return payload


async def _find_duplicate(
    session: DbSession, model: type, org_id: uuid.UUID | None, name: str, exclude_id: uuid.UUID | None = None
):
    # `model.org_id == org_id` degrades to `IS NULL` when org_id is None, so
    # this naturally checks for a name clash within the same scope — an
    # org's own list when org_id is set, or the shared global list when it's
    # not — never across the two.
    stmt = select(model).where(model.org_id == org_id, model.name.ilike(name))
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _build(model: type, router: APIRouter, singular: str, *, supports_global: bool = False) -> None:
    """`supports_global` is only True for Department. Every other master
    stays strictly org-scoped: a Super Admin has no org row to see or add
    to, same as before."""

    def _scope_filter(actor: Any):
        if supports_global:
            return or_(model.org_id == actor.org_id, model.org_id.is_(None))
        return model.org_id == actor.org_id

    @router.get("", response_model=dict[str, Any])
    async def list_rows(
        session: DbSession,
        actor: ManagerUser,
        q: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        if actor.org_id is None and not supports_global:
            return {"items": [], "total": 0, "page": 1, "page_size": page_size}
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        scope = _scope_filter(actor)
        stmt = select(model).where(scope).options(selectinload(model.created_by))
        count_stmt = select(func.count()).select_from(model).where(scope)
        if q:
            stmt = stmt.where(model.name.ilike(f"%{q}%"))
            count_stmt = count_stmt.where(model.name.ilike(f"%{q}%"))
        total = (await session.execute(count_stmt)).scalar_one()
        # Global rows first within a page so the "everyone sees this" set
        # reads as the stable top of the list rather than being interleaved.
        order = (model.org_id.is_not(None), model.name) if supports_global else (model.name,)
        stmt = stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()
        return {
            "items": [_row(r, has_scope=supports_global) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @router.post("", status_code=201, response_model=dict[str, Any])
    async def create_row(
        payload: MasterCreateRequest, request: Request, session: DbSession, actor: ManagerUser
    ) -> dict[str, Any]:
        if actor.org_id is None and not supports_global:
            raise ValidationFailed("A Super Admin must act within an organization.")
        # A Super Admin's create has no org to attach to, so for a
        # global-capable master it becomes the global row itself — visible
        # to every org from the moment it's created, same as a Super
        # Admin's template create.
        target_org_id = actor.org_id
        name = payload.name.strip()
        if not name:
            raise ValidationFailed(f"Give this {singular} a name.")
        existing = await _find_duplicate(session, model, target_org_id, name)
        if existing:
            raise Conflict(f"'{name}' already exists in {singular}.")
        row = model(org_id=target_org_id, name=name, created_by_id=actor.id)
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
            **({"scope": "global" if target_org_id is None else "org"} if supports_global else {}),
        }

    @router.patch("/{row_id}", response_model=dict[str, Any])
    async def update_row(
        row_id: uuid.UUID, payload: MasterUpdateRequest, session: DbSession, actor: AdminUser
    ) -> dict[str, Any]:
        # A global row (org_id NULL) is shared platform data — only a Super
        # Admin (who also has org_id None) can edit or disable it. An org
        # Admin's `model.org_id == actor.org_id` clause simply won't match a
        # global row's NULL org_id, so it 404s for them rather than leaking
        # a write path into every other org's shared list.
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
        return _row(row, has_scope=supports_global)

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


@departments_router.get("/in-use", response_model=dict[str, Any])
async def list_in_use_departments(session: DbSession, actor: ManagerUser) -> dict[str, Any]:
    """Departments actually assigned to at least one person in this org —
    what pickers that scope *people* (Create Feedback's participant filters,
    the User picker) should offer, rather than the full org+global master
    catalog which can list departments nobody here has picked yet.

    Registered ahead of the generic `/{row_id}` routes only matters for
    method collisions, and there are none here (this is GET-only, those are
    PATCH/DELETE), but it's kept next to `departments_router`'s own setup
    for visibility rather than folded into `_build`, since no other master
    list has an "in use" concept — only Department is ever selected onto a
    person's profile.
    """
    stmt = (
        select(User.department)
        .where(User.org_id == actor.org_id, User.department.isnot(None), User.department != "")
        .distinct()
        .order_by(User.department)
    )
    names = [row[0] for row in (await session.execute(stmt)).all()]
    return {"items": [{"id": name, "name": name} for name in names]}


_build(Department, departments_router, "department", supports_global=True)
_build(JobTitle, job_titles_router, "job title")
_build(CycleName, cycle_names_router, "cycle name")
_build(Product, products_router, "product")
_build(Service, services_router, "service")