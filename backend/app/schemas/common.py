"""Shared response envelopes and filter primitives."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class LookupItem(BaseModel):
    """One autocomplete suggestion. Deliberately minimal.

    Autocomplete endpoints return an id and a label and nothing else. Returning
    full records would turn a typeahead into a bulk export of the directory for
    anyone who can type.
    """

    id: uuid.UUID
    label: str
    sublabel: str | None = None


DateRangePreset = Literal[
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_month",
    "last_month",
    "this_quarter",
    "this_year",
    "custom",
]


class DateRange(BaseModel):
    """A resolved date window.

    Interpreted in the organization's timezone, not the server's and not the
    browser's. "Last 30 days" has to mean the same thing on the screen and in
    the exported file, and the only way to guarantee that is to resolve it once,
    server side, from the tenant's own timezone.
    """

    preset: DateRangePreset = "last_30_days"
    start: date | None = None
    end: date | None = None


class FilterState(BaseModel):
    """The single filter object shared by screen queries and exports.

    This type is the contract that keeps an export honest: the same instance
    that produced the rows on screen is what the renderer receives. Rebuilding
    filters inside the export path is how a file quietly stops matching the
    report it claims to be.
    """

    search: str | None = Field(default=None, max_length=200)
    date_range: DateRange = Field(default_factory=DateRange)
    org_ids: list[uuid.UUID] = Field(default_factory=list)
    actor_ids: list[uuid.UUID] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=list)
    sort: str | None = None
    sort_dir: Literal["asc", "desc"] = "desc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class ResolvedWindow(BaseModel):
    start_at: datetime
    end_at: datetime
    label: str


class MessageResponse(BaseModel):
    message: str
