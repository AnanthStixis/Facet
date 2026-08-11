"""The report registry.

One report is declared once - its columns, its query, and who may run it - and
three renderers (CSV, Excel, PDF) consume that declaration. Adding a report to
the product means adding one `ReportDefinition`; it gets a screen endpoint and
all three export formats with no further work.

The alternative, which every codebase drifts into if you let it, is a bespoke
export endpoint per report per format. That is where "the CSV says 412 but the
dashboard says 408" bugs come from, because the two paths diverge the first
time someone fixes a filter in only one of them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.models.enums import UserRole
from app.schemas.common import FilterState, ResolvedWindow


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    label: str
    # Character width, used by Excel column sizing and PDF column proportions.
    width: int = 22
    align: str = "left"
    # "text" | "number" | "datetime" | "badge"
    kind: str = "text"
    # Excluded from PDF, which has far less horizontal room than a spreadsheet.
    detail_only: bool = False


@dataclass(frozen=True, slots=True)
class ReportPage:
    rows: list[dict[str, Any]]
    total: int
    window: ResolvedWindow


class ReportQuery(Protocol):
    async def __call__(
        self, session: AsyncSession, actor: Any, filters: FilterState, *, paginate: bool
    ) -> ReportPage: ...


@dataclass(frozen=True, slots=True)
class ReportDefinition:
    key: str
    title: str
    description: str
    columns: list[Column]
    query: ReportQuery
    min_role: UserRole = UserRole.CLIENT_ADMIN
    # Reports whose rows contain individual feedback are subject to the
    # anonymity threshold; the query is responsible for applying it, but the
    # flag lets the UI warn before the user builds an export they cannot have.
    anonymity_sensitive: bool = False
    default_sort: str = "occurred_at"
    filters_supported: list[str] = field(default_factory=list)

    def export_columns(self, fmt: str) -> list[Column]:
        if fmt == "pdf":
            return [column for column in self.columns if not column.detail_only]
        return list(self.columns)

    def assert_allowed(self, actor: Any) -> None:
        if not actor.role.at_least(self.min_role):
            raise PermissionDenied(
                f"Your role cannot run the '{self.title}' report."
            )


_REGISTRY: dict[str, ReportDefinition] = {}


def register(definition: ReportDefinition) -> ReportDefinition:
    if definition.key in _REGISTRY:
        raise RuntimeError(f"Duplicate report key '{definition.key}'")
    _REGISTRY[definition.key] = definition
    return definition


def get_report(key: str) -> ReportDefinition:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise NotFound(f"No report named '{key}'.") from None


def available_reports(actor: Any) -> list[ReportDefinition]:
    return [
        definition
        for definition in _REGISTRY.values()
        if actor.role.at_least(definition.min_role)
    ]


ReportBuilder = Callable[[], Awaitable[None]]
