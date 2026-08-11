"""End-to-end verification of the Phase 1 security and reporting model.

Runs the real ASGI app in-process, so it exercises the same middleware,
dependencies, and database as a deployed server.

    python -m scripts.verify
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.seed import (  # noqa: E402
    CLIENT_ADMIN_EMAIL,
    CLIENT_ADMIN_PASSWORD,
    SUPER_ADMIN_EMAIL,
    SUPER_ADMIN_PASSWORD,
)

PASS = "  [pass]"
FAIL = "  [FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    response.raise_for_status()
    return response.json()


async def main() -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as client:
        print("\n== Health and metadata ==")
        health = await client.get("/health")
        check("health endpoint responds", health.status_code == 200)
        meta = await client.get("/api/v1/meta")
        check("meta exposes product name", meta.json().get("product_name") == "Facet")

        print("\n== Authentication ==")
        bad = await client.post(
            "/api/v1/auth/login",
            json={"email": SUPER_ADMIN_EMAIL, "password": "wrong-password-entirely"},
        )
        check("wrong password rejected", bad.status_code == 401)
        check(
            "error code is generic (no account enumeration)",
            bad.json()["error"]["code"] == "invalid_credentials",
            bad.json()["error"]["message"],
        )

        unknown = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nowhere.example", "password": "wrong-password"},
        )
        check(
            "unknown account returns the identical error",
            unknown.json()["error"]["code"] == bad.json()["error"]["code"],
        )

        sa = await login(client, SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)
        check("super admin signs in", bool(sa.get("access_token")))
        check("refresh token is httpOnly cookie, not body", "refresh_token" not in sa)
        sa_headers = {"authorization": f"Bearer {sa['access_token']}"}

        print("\n== Refresh rotation and reuse detection ==")
        csrf = client.cookies.get("facet_csrf")
        first_refresh_cookie = client.cookies.get("facet_rt")
        rotated = await client.post(
            "/api/v1/auth/refresh", headers={"x-facet-csrf": csrf or ""}
        )
        check("refresh succeeds with CSRF header", rotated.status_code == 200)
        check(
            "refresh token was rotated",
            client.cookies.get("facet_rt") != first_refresh_cookie,
        )

        no_csrf = await client.post("/api/v1/auth/refresh")
        check("refresh without CSRF header is rejected", no_csrf.status_code == 401)

        # Replay the superseded token: this must destroy the whole family.
        replay = httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"facet_rt": first_refresh_cookie or "", "facet_csrf": csrf or ""},
        )
        reused = await replay.post(
            "/api/v1/auth/refresh", headers={"x-facet-csrf": csrf or ""}
        )
        check(
            "replayed refresh token is detected",
            reused.status_code == 401
            and reused.json()["error"]["code"] == "token_reuse_detected",
            reused.json()["error"]["code"],
        )
        follow_up = await client.post(
            "/api/v1/auth/refresh",
            headers={"x-facet-csrf": client.cookies.get("facet_csrf") or ""},
        )
        check(
            "the legitimate session was also revoked (family killed)",
            follow_up.status_code == 401,
        )
        await replay.aclose()

    # Fresh clients, since the family above is now dead.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as sa_client, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ca_client:
        sa = await login(sa_client, SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)
        ca = await login(ca_client, CLIENT_ADMIN_EMAIL, CLIENT_ADMIN_PASSWORD)
        sa_headers = {"authorization": f"Bearer {sa['access_token']}"}
        ca_headers = {"authorization": f"Bearer {ca['access_token']}"}

        check("client admin signs in", bool(ca.get("access_token")))
        check(
            "client admin response carries their organization",
            (ca.get("organization") or {}).get("slug") == "northwind-logistics",
        )

        print("\n== Tenant isolation (row level security) ==")
        orgs = await sa_client.get("/api/v1/orgs", headers=sa_headers)
        check("super admin lists all organizations", orgs.status_code == 200,
              f"{orgs.json()['total']} orgs")

        pending = [o for o in orgs.json()["items"] if o["status"] == "pending"]
        if not pending:
            # The seeded pending tenant may already have been approved by hand.
            # Register one rather than depending on untouched seed state, so
            # this suite stays runnable more than once.
            await sa_client.post(
                "/api/v1/orgs/register",
                json={
                    "name": f"Verify Tenant {uuid.uuid4().hex[:6]}",
                    "contact_name": "Verification Contact",
                    # Not a .test/.invalid/.example address: email-validator
                    # rejects reserved TLDs, which is correct behaviour and
                    # would make this setup step fail for the wrong reason.
                    "contact_email": f"verify-{uuid.uuid4().hex[:8]}@verifytenant.co",
                    "timezone": "UTC",
                },
            )
            orgs = await sa_client.get("/api/v1/orgs", headers=sa_headers)
            pending = [o for o in orgs.json()["items"] if o["status"] == "pending"]
        check("pending approval queue is populated", len(pending) >= 1,
              f"{len(pending)} awaiting review")

        ca_orgs = await ca_client.get("/api/v1/orgs", headers=ca_headers)
        check("client admin cannot list organizations", ca_orgs.status_code == 403)

        # Any tenant other than the one the Client Admin belongs to will do.
        other_org_id = next(o["id"] for o in orgs.json()["items"]
                            if o["slug"] != "northwind-logistics")
        cross = await ca_client.get(f"/api/v1/orgs/{other_org_id}", headers=ca_headers)
        check("client admin cannot read another tenant", cross.status_code == 403,
              f"HTTP {cross.status_code}")

        ca_users = await ca_client.get("/api/v1/users", headers=ca_headers)
        emails = {u["email"] for u in ca_users.json()["items"]}
        check("client admin sees only their own people", ca_users.json()["total"] == 6,
              f"{ca_users.json()['total']} users")
        check(
            "platform super admin is invisible to the tenant",
            SUPER_ADMIN_EMAIL not in emails,
        )

        print("\n== Lookups and filters ==")
        lookup = await ca_client.get(
            "/api/v1/lookup/users?q=ar", headers=ca_headers
        )
        check("autocomplete returns matches", lookup.status_code == 200
              and len(lookup.json()) > 0, f"{len(lookup.json())} hits")
        check(
            "autocomplete returns id and label only",
            set(lookup.json()[0]) <= {"id", "label", "sublabel"},
        )
        forbidden = await ca_client.get(
            "/api/v1/lookup/organizations", headers=ca_headers
        )
        check("org autocomplete blocked for tenant users", forbidden.status_code == 404)

        print("\n== Dashboard ==")
        dash = await ca_client.get("/api/v1/dashboard", headers=ca_headers)
        body = dash.json()
        check("dashboard renders", dash.status_code == 200)
        check("coverage spans internal and external domains",
              {c["domain"] for c in body["coverage"]} == {"internal", "external"})
        check("proposal targets are present (cross-domain graph)",
              any(c["target_type"] == "proposal" and c["count"] > 0
                  for c in body["coverage"]))

        print("\n== Reports and exports ==")
        listing = await ca_client.get("/api/v1/reports", headers=ca_headers)
        keys = {r["key"] for r in listing.json()}
        check("client admin sees tenant reports", {"audit_trail", "user_directory"} <= keys)
        check("client admin does not see the platform report",
              "organizations" not in keys)

        sa_listing = await sa_client.get("/api/v1/reports", headers=sa_headers)
        check("super admin sees the platform report",
              "organizations" in {r["key"] for r in sa_listing.json()})

        filters = {"date_range": {"preset": "last_30_days"}, "page": 1, "page_size": 25}
        query = await ca_client.post(
            "/api/v1/reports/audit_trail/query", headers=ca_headers, json=filters
        )
        check("audit report queries", query.status_code == 200,
              f"{query.json()['total']} rows")
        screen_total = query.json()["total"]

        for fmt, signature in (
            ("csv", b"Facet"),
            ("xlsx", b"PK"),
            ("pdf", b"%PDF"),
        ):
            export = await ca_client.post(
                f"/api/v1/reports/audit_trail/export/{fmt}",
                headers=ca_headers,
                json=filters,
            )
            ok = export.status_code == 200 and export.content.startswith(signature)
            check(f"{fmt.upper()} export renders", ok,
                  f"{len(export.content):,} bytes")
            check(
                f"{fmt.upper()} sends a filename",
                "attachment" in export.headers.get("content-disposition", ""),
            )

        blocked = await ca_client.post(
            "/api/v1/reports/organizations/export/csv", headers=ca_headers, json=filters
        )
        check("tenant cannot export the platform report", blocked.status_code == 403)

        after = await ca_client.post(
            "/api/v1/reports/audit_trail/query", headers=ca_headers, json=filters
        )
        check(
            "exports are themselves audited",
            after.json()["total"] > screen_total,
            f"{screen_total} -> {after.json()['total']} rows",
        )

        print("\n== Audit immutability ==")
        from sqlalchemy import text as sql_text

        from app.db.session import SessionFactory

        from app.db.tenancy import TenantContext, bind_tenant

        async with SessionFactory() as session:
            # Bind the platform context first, otherwise RLS hides every row,
            # the UPDATE matches nothing, and the trigger never fires - which
            # would make this check pass for the wrong reason.
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            visible = int(
                (
                    await session.execute(sql_text("SELECT count(*) FROM audit_logs"))
                ).scalar_one()
            )
            try:
                await session.execute(
                    sql_text("UPDATE audit_logs SET summary = 'tampered'")
                )
                await session.commit()
                tampered = True
            except Exception:
                await session.rollback()
                tampered = False
        check("rows are visible to the tamper attempt", visible > 0, f"{visible} rows")
        check("audit log rejects UPDATE at the database level", not tampered)

        async with SessionFactory() as session:
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            try:
                await session.execute(sql_text("DELETE FROM audit_logs"))
                await session.commit()
                deleted = True
            except Exception:
                await session.rollback()
                deleted = False
        check("audit log rejects DELETE at the database level", not deleted)

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
