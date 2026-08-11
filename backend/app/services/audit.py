"""Audit trail writer (Module F)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditAction, AuditSeverity
from app.models.user import User

# Actions a Client Admin should see highlighted in their own log, and that a
# Super Admin should be able to alert on.
_ALERT_ACTIONS = {
    AuditAction.AUTH_TOKEN_REUSE_DETECTED,
    AuditAction.ORG_SUSPENDED,
    AuditAction.USER_ROLE_CHANGED,
}
_NOTICE_ACTIONS = {
    AuditAction.AUTH_LOGIN_FAILED,
    AuditAction.AUTH_MFA_DISABLED,
    AuditAction.AUTH_SESSION_REVOKED,
    AuditAction.ORG_APPROVED,
    AuditAction.ORG_REJECTED,
    AuditAction.REPORT_EXPORTED,
}


def _severity_for(action: AuditAction) -> AuditSeverity:
    if action in _ALERT_ACTIONS:
        return AuditSeverity.ALERT
    if action in _NOTICE_ACTIONS:
        return AuditSeverity.NOTICE
    return AuditSeverity.INFO


def client_ip(request: Request | None) -> str | None:
    """Caller IP, honouring one layer of reverse proxy.

    Only the last hop in X-Forwarded-For is trustworthy, and only when the app
    genuinely sits behind a proxy that rewrites it. Cloudflare's header is
    preferred when present because it cannot be spoofed by the client.
    """
    if request is None:
        return None
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


_APPEND_SQL = text(
    """
    SELECT facet_audit_append(
        :org_id, :action, CAST(:severity AS audit_severity), :actor_id,
        :actor_email, :actor_name, :actor_role, :target_type, :target_id,
        :target_label, :summary, CAST(:context AS jsonb), CAST(:ip AS inet),
        :user_agent, :request_id, :occurred_at
    )
    """
)


async def record(
    session: AsyncSession,
    *,
    action: AuditAction,
    summary: str,
    org_id: uuid.UUID | None = None,
    actor: User | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    target_label: str | None = None,
    context: dict[str, Any] | None = None,
    request: Request | None = None,
) -> uuid.UUID:
    """Append one entry.

    Written through `facet_audit_append` (migration 0003) rather than the ORM,
    because several of these fire before a tenant is bound and some belong to
    no tenant at all. The function can only insert, so this is a far narrower
    grant than letting the application bypass row level security.

    The caller is responsible for committing. Audit writes ride the same
    transaction as the action they describe, so a rolled-back change never
    leaves a log entry claiming it happened.
    """
    result = await session.execute(
        _APPEND_SQL,
        {
            "org_id": org_id if org_id is not None else (actor.org_id if actor else None),
            "action": action.value,
            "severity": _severity_for(action).value,
            "actor_id": actor.id if actor else None,
            "actor_email": actor.email if actor else actor_email,
            "actor_name": actor.full_name if actor else None,
            "actor_role": str(actor.role) if actor else None,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "summary": summary,
            "context": json.dumps(context or {}, default=str),
            "ip": client_ip(request),
            "user_agent": (request.headers.get("user-agent") if request else None),
            "request_id": getattr(request.state, "request_id", None) if request else None,
            "occurred_at": datetime.now(UTC),
        },
    )
    return result.scalar_one()
