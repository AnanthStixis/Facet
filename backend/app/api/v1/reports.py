"""Report and export endpoints.

One pair of endpoints serves every report in the registry:

    GET  /reports                     list what this role may run
    POST /reports/{key}/query         rows for the screen (paginated)
    POST /reports/{key}/export/{fmt}  the same rows as csv | xlsx | pdf

Because the screen and the file are produced from one definition and one filter
object, they cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import ValidationFailed
from app.core.ratelimit import EXPORT_PER_USER, limiter
from app.models.enums import AuditAction, ExportFormat
from app.reporting import reports as _reports  # noqa: F401  (registers definitions)
from app.reporting.filters import describe_filters
from app.reporting.registry import available_reports, get_report
from app.reporting.renderers import (
    MEDIA_TYPES,
    ExportContext,
    render_csv,
    render_pdf,
    render_xlsx,
)
from app.schemas.common import FilterState
from app.services import audit

router = APIRouter(prefix="/reports", tags=["reports"])


def _logo_path(actor: CurrentUser) -> Path | None:
    branding = actor.org.branding if actor.org else None
    if branding and branding.logo_path:
        candidate = settings.storage_path / branding.logo_path
        if candidate.exists():
            return candidate
    return None


def _build_context(actor: Any, report, window, filters: FilterState) -> ExportContext:
    branding = actor.org.branding if actor.org else None
    return ExportContext(
        report=report,
        window=window,
        filter_summary=describe_filters(filters, window),
        org_name=actor.org.name if actor.org else settings.vendor_name,
        org_timezone=actor.org.timezone if actor.org else "UTC",
        accent_color=branding.accent_color if branding else "#B4633A",
        logo_path=_logo_path(actor),
        generated_by=f"{actor.user.full_name} <{actor.user.email}>",
    )


@router.get("")
async def list_reports(actor: CurrentUser) -> list[dict[str, Any]]:
    return [
        {
            "key": definition.key,
            "title": definition.title,
            "description": definition.description,
            "columns": [
                {
                    "key": column.key,
                    "label": column.label,
                    "kind": column.kind,
                    "align": column.align,
                    "detail_only": column.detail_only,
                }
                for column in definition.columns
            ],
            "filters_supported": definition.filters_supported,
            "formats": [fmt.value for fmt in ExportFormat],
        }
        for definition in available_reports(actor)
    ]


@router.post("/{key}/query")
async def query_report(
    key: str,
    filters: FilterState,
    session: DbSession,
    actor: CurrentUser,
) -> dict[str, Any]:
    definition = get_report(key)
    definition.assert_allowed(actor)

    page = await definition.query(session, actor, filters, paginate=True)
    return {
        "key": definition.key,
        "title": definition.title,
        "rows": page.rows,
        "total": page.total,
        "page": filters.page,
        "page_size": filters.page_size,
        "window": {
            "label": page.window.label,
            "start_at": page.window.start_at,
            "end_at": page.window.end_at,
        },
        "applied_filters": describe_filters(filters, page.window),
    }


@router.post("/{key}/export/{fmt}")
async def export_report(
    key: str,
    fmt: ExportFormat,
    filters: FilterState,
    request: Request,
    session: DbSession,
    actor: CurrentUser,
) -> Response:
    definition = get_report(key)
    definition.assert_allowed(actor)
    await limiter.hit(f"export:{actor.id}", EXPORT_PER_USER)

    # Exports ignore pagination by design - the file is the whole result set,
    # which is the only behaviour users ever expect from a Download button.
    page = await definition.query(session, actor, filters, paginate=False)

    if page.total > settings.export_hard_row_limit:
        raise ValidationFailed(
            f"That export would contain {page.total:,} rows, above the "
            f"{settings.export_hard_row_limit:,} limit. Narrow the date range.",
        )

    context = _build_context(actor, definition, page.window, filters)
    filename = f"{context.filename_stem}.{fmt.value}"

    # Exporting feedback data is exactly the action a compliance review asks
    # about, so it is audited with the filters that produced the file.
    await audit.record(
        session,
        action=AuditAction.REPORT_EXPORTED,
        summary=f"{actor.user.full_name} exported '{definition.title}' as {fmt.value.upper()}",
        org_id=actor.org_id,
        actor=actor.user,
        target_type="report",
        target_label=definition.title,
        context={
            "format": fmt.value,
            "rows": page.total,
            "filters": filters.model_dump(mode="json"),
            "window": page.window.label,
        },
        request=request,
    )
    await session.commit()

    headers = {"content-disposition": f'attachment; filename="{filename}"'}

    if fmt is ExportFormat.CSV:
        return StreamingResponse(
            render_csv(context, page.rows),
            media_type=MEDIA_TYPES["csv"],
            headers=headers,
        )
    if fmt is ExportFormat.XLSX:
        return Response(
            content=render_xlsx(context, page.rows),
            media_type=MEDIA_TYPES["xlsx"],
            headers=headers,
        )
    return Response(
        content=render_pdf(context, page.rows),
        media_type=MEDIA_TYPES["pdf"],
        headers=headers,
    )
