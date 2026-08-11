"""Tenant isolation.

Facet is a shared-schema multi-tenant system: every tenant-scoped table carries
an `org_id`, and Postgres row level security filters on it using a session
variable set from the authenticated principal.

Why this and not `WHERE org_id = ...` in application code:

    A forgotten WHERE clause in application code is a cross-tenant data leak.
    A forgotten WHERE clause with RLS enabled returns zero rows. One of those
    failure modes ends up in a breach notification and the other ends up in a
    bug report, so the enforcement belongs in the database.

Two GUCs drive the policies:

    app.current_org_id   the tenant the request is acting within
    app.is_super_admin   'on' only for platform-level Stixis operators

Both are set with `set_config(..., is_local => true)`, so they are scoped to
the current transaction and cannot leak to the next request that borrows the
same pooled connection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ORG_GUC = "app.current_org_id"
SUPER_ADMIN_GUC = "app.is_super_admin"

# Sentinel used when no tenant is bound. It is a syntactically valid UUID so the
# policy expression never errors, and it will never match a real organization.
NIL_ORG = uuid.UUID("00000000-0000-0000-0000-000000000000")


@dataclass(frozen=True, slots=True)
class TenantContext:
    org_id: uuid.UUID | None
    is_super_admin: bool = False


async def bind_tenant(session: AsyncSession, ctx: TenantContext) -> None:
    """Bind the tenant context to the current transaction."""
    await session.execute(
        text(
            "SELECT set_config(:org_key, :org_val, true), "
            "       set_config(:sa_key, :sa_val, true)"
        ),
        {
            "org_key": ORG_GUC,
            "org_val": str(ctx.org_id or NIL_ORG),
            "sa_key": SUPER_ADMIN_GUC,
            "sa_val": "on" if ctx.is_super_admin else "off",
        },
    )


async def clear_tenant(session: AsyncSession) -> None:
    await bind_tenant(session, TenantContext(org_id=None, is_super_admin=False))


# --- DDL helpers used by migrations ---------------------------------------

def enable_rls(table: str, org_column: str = "org_id") -> list[str]:
    """SQL enabling row level security on a tenant-scoped table.

    A single policy covers SELECT/INSERT/UPDATE/DELETE. Super admins bypass the
    org match but are still subject to the policy existing at all, which keeps
    the audit story honest: there is no unfiltered path to the data.
    """
    predicate = (
        f"({org_column} = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid "
        f"OR current_setting('{SUPER_ADMIN_GUC}', true) = 'on')"
    )
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        # FORCE makes the policy apply to the table owner too, so a migration
        # role or a future superuser connection cannot silently bypass it.
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING {predicate}
            WITH CHECK {predicate}
        """,
    ]


def disable_rls(table: str) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]
