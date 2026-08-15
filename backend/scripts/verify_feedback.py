"""Verification for the unified Create Feedback / Results flow.

    python -m scripts.verify_feedback

Runs the real ASGI app in-process against the real database. Covers:
  - each of the 6 kinds end-to-end via POST /feedback
  - a Client Review with about_user_id shows up in GET /users/{id}/feedback
    AND in that user's GET /me/results
  - GET /feedback returns internal and external rows together, in one list
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.seed import CLIENT_ADMIN_EMAIL, CLIENT_ADMIN_PASSWORD  # noqa: E402

PASS = "  [pass]"
FAIL = "  [FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


async def _lookup_template_id(client: httpx.AsyncClient, headers: dict, target_type: str) -> str | None:
    resp = await client.get("/api/v1/catalog/categories", headers=headers)
    resp.raise_for_status()
    for category in resp.json():
        for template in category["templates"]:
            if template["target_type"] == target_type and template["status"] == "published":
                return template["id"]
    return None


async def _lookup_user_id(client: httpx.AsyncClient, headers: dict, email: str) -> str:
    resp = await client.get(
        "/api/v1/users", headers=headers, params={"search": email, "page_size": 5}
    )
    resp.raise_for_status()
    items = resp.json()["items"]
    match = next(u for u in items if u["email"] == email)
    return match["id"]


async def _ensure_contact(client: httpx.AsyncClient, headers: dict) -> str:
    email = f"verify-feedback-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"email": email, "full_name": "Verify Feedback Contact", "company": "Verify Co"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def _submit_a_response_for_cycle(cycle_id: str) -> None:
    """Directly record one submitted response for an external cycle.

    Going through the real public link flow would mean parsing a raw token
    out of a written .eml file, which is brittle for a check whose only job
    is confirming the cross-link and list endpoints see a real response row.
    This writes the same shape of row `public.py::submit_link` writes.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db.session import SessionFactory
    from app.db.tenancy import TenantContext, bind_tenant
    from app.models.campaign import CampaignRecipient
    from app.models.cycle import FeedbackResponse, ReviewCycle
    from app.models.enums import Relationship

    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        cycle = (
            await session.execute(
                select(ReviewCycle).where(ReviewCycle.id == uuid.UUID(cycle_id))
            )
        ).scalar_one()
        recipient = (
            await session.execute(
                select(CampaignRecipient).where(CampaignRecipient.cycle_id == cycle.id).limit(1)
            )
        ).scalar_one()
        session.add(
            FeedbackResponse(
                org_id=cycle.org_id,
                cycle_id=cycle.id,
                target_id=cycle.target_id,
                template_version_id=cycle.template_version_id,
                recipient_id=None if cycle.is_anonymous else recipient.id,
                is_anonymous=cycle.is_anonymous,
                relationship_type=Relationship.EXTERNAL,
                answers={},
                comment="Verify script response.",
                overall_score=4.0,
                answered_count=0,
                submitted_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def main() -> int:
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": CLIENT_ADMIN_EMAIL, "password": CLIENT_ADMIN_PASSWORD},
        )
        login.raise_for_status()
        headers = {"authorization": f"Bearer {login.json()['access_token']}"}

        vikram_id = await _lookup_user_id(client, headers, "vikram.s@northwind.example")
        arun_id = await _lookup_user_id(client, headers, "arun.k@northwind.example")
        contact_id = await _ensure_contact(client, headers)

        created_cycle_ids: dict[str, str] = {}

        # --- employee -----------------------------------------------------
        template_id = await _lookup_template_id(client, headers, "employee")
        check("employee template exists", template_id is not None)
        if template_id:
            resp = await client.post(
                "/api/v1/feedback",
                headers=headers,
                json={
                    "kind": "employee",
                    "template_id": template_id,
                    "name": f"Verify employee {uuid.uuid4().hex[:6]}",
                    "reviewee_user_id": vikram_id,
                },
            )
            check("POST /feedback kind=employee", resp.status_code == 201, resp.text[:300])
            if resp.status_code == 201:
                body = resp.json()
                created_cycle_ids["employee"] = body["cycle_id"]
                check("employee cycle opened", body["status"] == "open")

        # --- management -----------------------------------------------------
        template_id = await _lookup_template_id(client, headers, "manager")
        check("manager template exists", template_id is not None)
        if template_id:
            resp = await client.post(
                "/api/v1/feedback",
                headers=headers,
                json={
                    "kind": "management",
                    "template_id": template_id,
                    "name": f"Verify management {uuid.uuid4().hex[:6]}",
                    "reviewee_user_id": arun_id,
                },
            )
            check("POST /feedback kind=management", resp.status_code == 201, resp.text[:300])
            if resp.status_code == 201:
                created_cycle_ids["management"] = resp.json()["cycle_id"]

        # --- product / service / proposal -----------------------------------
        for kind, target_type in (
            ("product", "product"),
            ("service", "service"),
            ("proposal", "proposal"),
        ):
            template_id = await _lookup_template_id(client, headers, target_type)
            check(f"{kind} template exists", template_id is not None)
            if not template_id:
                continue
            resp = await client.post(
                "/api/v1/feedback",
                headers=headers,
                json={
                    "kind": kind,
                    "template_id": template_id,
                    "name": f"Verify {kind} {uuid.uuid4().hex[:6]}",
                    "target_label": f"Verify {kind} subject {uuid.uuid4().hex[:6]}",
                    "contact_ids": [contact_id],
                },
            )
            check(f"POST /feedback kind={kind}", resp.status_code == 201, resp.text[:300])
            if resp.status_code == 201:
                created_cycle_ids[kind] = resp.json()["cycle_id"]

        # --- client, with about_user_id (the cross-linking case) ------------
        template_id = await _lookup_template_id(client, headers, "client")
        check("client template exists", template_id is not None)
        if template_id:
            resp = await client.post(
                "/api/v1/feedback",
                headers=headers,
                json={
                    "kind": "client",
                    "template_id": template_id,
                    "name": f"Verify client review {uuid.uuid4().hex[:6]}",
                    "about_user_id": vikram_id,
                    "contact_ids": [contact_id],
                },
            )
            check("POST /feedback kind=client (about_user_id)", resp.status_code == 201, resp.text[:300])
            if resp.status_code == 201:
                created_cycle_ids["client"] = resp.json()["cycle_id"]
                await _submit_a_response_for_cycle(created_cycle_ids["client"])

        check("all 6 kinds created", len(created_cycle_ids) == 6, str(sorted(created_cycle_ids)))

        # --- GET /feedback returns internal + external together -------------
        resp = await client.get("/api/v1/feedback", headers=headers)
        check("GET /feedback ok", resp.status_code == 200)
        rows = resp.json() if resp.status_code == 200 else []
        row_ids = {row["id"] for row in rows}
        audiences_present = {row["audience"] for row in rows if row["id"] in created_cycle_ids.values()}
        check(
            "GET /feedback includes every created round",
            all(cid in row_ids for cid in created_cycle_ids.values()),
        )
        check(
            "GET /feedback mixes internal and external in one list",
            {"internal", "external"} <= audiences_present,
            str(audiences_present),
        )
        kinds_seen = {row["kind"] for row in rows if row["id"] in created_cycle_ids.values()}
        check(
            "GET /feedback reports the right kind per row",
            kinds_seen == set(created_cycle_ids.keys()),
            str(kinds_seen),
        )

        # --- The Client Review's about_user_id cross-link --------------------
        # A Client Review targets someone's own person-target only when that
        # target is (re)typed to CLIENT — since Vikram had no prior CLIENT
        # target, ensure_person_target + the re-typing branch in
        # feedback_service.create_and_send should have created one now.
        resp = await client.get(f"/api/v1/users/{vikram_id}/feedback", headers=headers)
        check("GET /users/{id}/feedback ok", resp.status_code == 200, resp.text[:300])
        vikram_feedback = resp.json() if resp.status_code == 200 else []
        client_rows = [row for row in vikram_feedback if row["kind"] == "client"]
        check(
            "Client Review about Vikram shows up on his own feedback list",
            len(client_rows) >= 1,
            f"{len(vikram_feedback)} total row(s)",
        )

        # --- Also visible in Vikram's own /me/results (as himself) ----------
        vikram_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "vikram.s@northwind.example", "password": "NorthwindUser!2026"},
        )
        check("Vikram can log in", vikram_login.status_code == 200, vikram_login.text[:300])
        if vikram_login.status_code == 200:
            vikram_headers = {
                "authorization": f"Bearer {vikram_login.json()['access_token']}"
            }
            resp = await client.get("/api/v1/me/results", headers=vikram_headers)
            check("GET /me/results ok", resp.status_code == 200, resp.text[:300])
            if resp.status_code == 200:
                results = resp.json()
                found_client_cycle = any(
                    r.get("cycle", {}).get("id") == created_cycle_ids.get("client")
                    for r in results
                    if r.get("found")
                )
                check(
                    "Client Review about Vikram appears in his /me/results",
                    found_client_cycle,
                    f"{len(results)} cycle(s) in /me/results",
                )

    return 0 if not failures else 1


if __name__ == "__main__":
    code = asyncio.run(main())
    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
    else:
        print("All feedback checks passed.")
    raise SystemExit(code)
