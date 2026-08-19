"""Filter resolution shared by screen queries and exports.

Every report resolves its filters exactly once, here, and hands the resolved
object to both the query and the renderer. That is what guarantees the numbers
in a downloaded file match the numbers on the screen it came from.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import ValidationFailed
from app.schemas.common import DateRange, FilterState, ResolvedWindow

_PRESET_LABELS = {
    "all": "All time",
    "today": "Today",
    "yesterday": "Yesterday",
    "last_7_days": "Last 7 days",
    "last_30_days": "Last 30 days",
    "last_90_days": "Last 90 days",
    "this_month": "This month",
    "last_month": "Last month",
    "this_quarter": "This quarter",
    "this_year": "This year",
    "custom": "Custom range",
}

MAX_RANGE_DAYS = 1096  # three years, enough for trend reporting


def get_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _quarter_start(value: date) -> date:
    first_month = 3 * ((value.month - 1) // 3) + 1
    return value.replace(month=first_month, day=1)


def resolve_window(date_range: DateRange, timezone_name: str) -> ResolvedWindow:
    """Turn a preset or explicit range into a half-open UTC interval.

    Boundaries are computed in the organization's timezone and then converted,
    so "today" for a Bengaluru tenant is their day, not the server's.
    """
    zone = get_zone(timezone_name)
    today = datetime.now(zone).date()
    preset = date_range.preset

    # "All time" has no meaningful start date, so it is resolved directly
    # rather than falling into the day-count math below — a decade-plus span
    # would otherwise trip the MAX_RANGE_DAYS guard meant for accidental
    # multi-year custom ranges, not for a deliberate "everything" export.
    if preset == "all":
        start_at = datetime(2000, 1, 1, tzinfo=UTC)
        end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
        return ResolvedWindow(start_at=start_at, end_at=end_at, label=_PRESET_LABELS["all"])

    if preset == "custom":
        if not date_range.start or not date_range.end:
            raise ValidationFailed("A custom range needs both a start and an end date.")
        start, end = date_range.start, date_range.end
    elif preset == "today":
        start = end = today
    elif preset == "yesterday":
        start = end = today - timedelta(days=1)
    elif preset == "last_7_days":
        start, end = today - timedelta(days=6), today
    elif preset == "last_30_days":
        start, end = today - timedelta(days=29), today
    elif preset == "last_90_days":
        start, end = today - timedelta(days=89), today
    elif preset == "this_month":
        start, end = _month_start(today), today
    elif preset == "last_month":
        first_of_this = _month_start(today)
        end = first_of_this - timedelta(days=1)
        start = _month_start(end)
    elif preset == "this_quarter":
        start, end = _quarter_start(today), today
    elif preset == "this_year":
        start, end = today.replace(month=1, day=1), today
    else:  # pragma: no cover - the Literal type makes this unreachable
        raise ValidationFailed(f"Unknown date range preset '{preset}'.")

    if start > end:
        raise ValidationFailed("The start date must be on or before the end date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValidationFailed(
            f"Date ranges are limited to {MAX_RANGE_DAYS} days. Narrow the range."
        )

    start_at = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    # Half-open: the day after `end` at midnight, so the final day is included
    # whole without depending on microsecond precision.
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)

    if preset == "custom":
        label = f"{start.isoformat()} to {end.isoformat()}"
    else:
        label = _PRESET_LABELS[preset]

    return ResolvedWindow(start_at=start_at, end_at=end_at, label=label)


def describe_filters(filters: FilterState, window: ResolvedWindow) -> list[tuple[str, str]]:
    """Human-readable filter summary, printed on every exported file.

    An export that does not state its own filters is a spreadsheet that will be
    misread in three months. This is cheap and prevents that.
    """
    described: list[tuple[str, str]] = [("Period", window.label)]
    if filters.search:
        described.append(("Search", filters.search))
    if filters.actions:
        described.append(("Actions", ", ".join(filters.actions)))
    if filters.severities:
        described.append(("Severity", ", ".join(filters.severities)))
    if filters.actor_ids:
        described.append(("People", f"{len(filters.actor_ids)} selected"))
    if filters.org_ids:
        described.append(("Organizations", f"{len(filters.org_ids)} selected"))
    return described


def escape_like(term: str) -> str:
    """Neutralise LIKE wildcards so a user's '%' searches for a literal '%'."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")