"""Phase 3 verification: campaigns, one-time links, and the public endpoint.

The token is recovered from the delivered .eml file rather than from the
database, because only a hash is stored — which is itself the property being
verified. It also means this exercises the whole chain a real respondent walks:
send, deliver, open, submit.

    python -m scripts.verify_phase3
"""

from __future__ import annotations

import asyncio
import re
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.seed import CLIENT_ADMIN_EMAIL, CLIENT_ADMIN_PASSWORD  # noqa: E402

PASS = "  [pass]"
FAIL = "  [FAIL]"
failures: list[str] = []

LINK_RE = re.compile(r"/f/([A-Za-z0-9_\-]{20,})")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def token_from_outbox(email: str) -> str | None:
    """Recover the raw token from the most recent message to an address."""
    outbox = settings.outbox_path
    if not outbox.exists():
        return None
    safe = "".join(c if c.isalnum() else "_" for c in email)
    files = sorted(
        (path for path in outbox.glob(f"*-{safe}.eml")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        # Quoted-printable can split a long URL across lines with a soft break.
        body = path.read_text(encoding="utf-8", errors="replace").replace("=\n", "")
        match = LINK_RE.search(body)
        if match:
            return match.group(1)
    return None


async def main() -> int:
    from app.main import app

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    suffix = uuid.uuid4().hex[:6]
    respondent_email = f"verify.{suffix}@clientco.co"

    async with make() as admin, make() as anon:
        login = await admin.post(
            "/api/v1/auth/login",
            json={"email": CLIENT_ADMIN_EMAIL, "password": CLIENT_ADMIN_PASSWORD},
        )
        login.raise_for_status()
        ah = {"authorization": f"Bearer {login.json()['access_token']}"}

        print("\n== Targets and contacts ==")
        target = await admin.post(
            "/api/v1/targets",
            headers=ah,
            json={
                "target_type": "service",
                "label": f"Verification Service {suffix}",
                "reference": f"svc:verify-{suffix}",
            },
        )
        check("a service target can be registered", target.status_code == 201)
        target_id = target.json()["id"]

        contact = await admin.post(
            "/api/v1/contacts",
            headers=ah,
            json={
                "email": respondent_email,
                "full_name": "Verification Respondent",
                "company": "ClientCo",
            },
        )
        check("an external contact can be added", contact.status_code == 201)
        contact_id = contact.json()["id"]

        dupe = await admin.post(
            "/api/v1/contacts",
            headers=ah,
            json={"email": respondent_email, "full_name": "Duplicate"},
        )
        check("duplicate contacts are refused", dupe.status_code == 409)

        print("\n== Campaign setup ==")
        cats = (await admin.get("/api/v1/catalog/categories", headers=ah)).json()
        all_templates = [t for c in cats for t in c["templates"] if t["status"] == "published"]
        service_template = next(
            (t for t in all_templates if t["target_type"] == "service"), None
        )
        person_template = next(
            (t for t in all_templates if t["target_type"] in {"manager", "employee"}),
            None,
        )
        check("a service-scoped template exists", service_template is not None)

        if person_template:
            mismatch = await admin.post(
                "/api/v1/campaigns",
                headers=ah,
                json={
                    "name": f"Mismatch {suffix}",
                    "template_id": person_template["id"],
                    "target_id": target_id,
                },
            )
            check(
                "a template cannot be pointed at the wrong kind of subject",
                mismatch.status_code == 422,
                mismatch.json()["error"]["message"][:70],
            )

        made = await admin.post(
            "/api/v1/campaigns",
            headers=ah,
            json={
                "name": f"Verification Campaign {suffix}",
                "template_id": service_template["id"],
                "target_id": target_id,
            },
        )
        check("a campaign is created", made.status_code == 201)
        campaign = made.json()
        check("it is an external audience", campaign["audience"] == "external")

        early = await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/open", headers=ah
        )
        check(
            "a campaign with no recipients cannot open",
            early.status_code == 409,
            early.json()["error"]["message"],
        )

        added = await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/recipients",
            headers=ah,
            json={
                "target_id": target_id,
                "contact_ids": [contact_id],
                "batch": "verify",
            },
        )
        check("recipients are added", added.status_code == 200,
              f"{added.json()['added']} added")

        again = await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/recipients",
            headers=ah,
            json={"target_id": target_id, "contact_ids": [contact_id]},
        )
        check(
            "adding the same contact twice is a no-op",
            again.json()["added"] == 0 and again.json()["skipped_existing"] == 1,
        )

        opened = await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/open", headers=ah
        )
        check("the campaign opens", opened.status_code == 200)

        print("\n== Sending ==")
        sent = await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/send", headers=ah, json={}
        )
        check("invitations send", sent.status_code == 200,
              f"{sent.json()['sent']} sent")

        token = token_from_outbox(respondent_email)
        check("the delivered email carries a working link", token is not None)
        if token is None:
            print("\nCannot continue without a token.")
            return 1

        print("\n== Token storage ==")
        from sqlalchemy import text as sql_text

        from app.core.security import hash_token
        from app.db.session import SessionFactory
        from app.db.tenancy import TenantContext, bind_tenant

        async with SessionFactory() as probe:
            await bind_tenant(probe, TenantContext(org_id=None, is_super_admin=True))
            raw_hits = (
                await probe.execute(
                    sql_text(
                        "SELECT count(*) FROM campaign_recipients WHERE token_hash = :raw"
                    ),
                    {"raw": token},
                )
            ).scalar_one()
            check("the raw token is not stored anywhere", raw_hits == 0)

            hashed_hits = (
                await probe.execute(
                    sql_text(
                        "SELECT count(*) FROM campaign_recipients WHERE token_hash = :h"
                    ),
                    {"h": hash_token(token)},
                )
            ).scalar_one()
            check("only its hash is stored", hashed_hits == 1)

        print("\n== The public endpoint ==")
        unknown = await anon.get(f"/api/v1/public/feedback/{'z' * 43}")
        check("an unknown token is refused", unknown.status_code == 404)
        unknown_message = unknown.json()["error"]["message"]

        short = await anon.get("/api/v1/public/feedback/abc")
        check("a malformed token is refused", short.status_code == 404)
        check(
            "every failure returns the identical message (no enumeration)",
            short.json()["error"]["message"] == unknown_message,
        )

        form = await anon.get(f"/api/v1/public/feedback/{token}")
        check("a valid link opens without any authentication", form.status_code == 200)
        body = form.json()
        check(
            "the form carries the client's branding, not the vendor's",
            body["organization"]["name"] == "Northwind Logistics",
            body["organization"]["name"],
        )
        check(
            "it greets the named recipient",
            body["recipient"]["full_name"] == "Verification Respondent",
        )
        check("it names the subject", body["subject"]["label"].startswith("Verification Service"))
        check("it returns a renderable form", len(body["form"]["sections"]) > 0)
        check(
            "the page is marked no-index",
            "noindex" in form.headers.get("x-robots-tag", ""),
        )
        check(
            "the page is marked no-store",
            "no-store" in form.headers.get("cache-control", ""),
        )

        recipients = (
            await admin.get(f"/api/v1/campaigns/{campaign['id']}/recipients", headers=ah)
        ).json()
        check(
            "opening the link is tracked",
            recipients[0]["status"] == "opened" and recipients[0]["open_count"] >= 1,
            f"{recipients[0]['status']}, {recipients[0]['open_count']} open(s)",
        )

        print("\n== Submitting ==")
        questions = [q for s in body["form"]["sections"] for q in s["questions"]]
        bad = await anon.post(
            f"/api/v1/public/feedback/{token}",
            json={"answers": {questions[0]["key"]: 42}},
        )
        check("an out-of-range answer is refused", bad.status_code == 422)

        answers = {q["key"]: 4 for q in questions if q["type"] == "scale"}
        submitted = await anon.post(
            f"/api/v1/public/feedback/{token}",
            json={"answers": answers, "comment": "Verification submission."},
        )
        check("a valid submission is accepted", submitted.status_code == 200,
              submitted.json().get("message", "")[:50])

        reused = await anon.get(f"/api/v1/public/feedback/{token}")
        check("the link is single use", reused.status_code == 404)
        check(
            "a spent link is indistinguishable from an unknown one",
            reused.json()["error"]["message"] == unknown_message,
        )

        resubmit = await anon.post(
            f"/api/v1/public/feedback/{token}", json={"answers": answers}
        )
        check("a spent link cannot submit again", resubmit.status_code == 404)

        after = (
            await admin.get(f"/api/v1/campaigns/{campaign['id']}/recipients", headers=ah)
        ).json()
        check("the response is tracked against the recipient",
              after[0]["status"] == "submitted")

        print("\n== Results reuse ==")
        results = await admin.get(
            f"/api/v1/campaigns/{campaign['id']}/results", headers=ah
        )
        check("campaign results render", results.status_code == 200)
        rows = results.json()["rows"]
        check("the external response reached the shared results pipeline",
              len(rows) == 1 and rows[0]["responses"] == 1,
              f"{len(rows)} target(s)")

        seeded = next(
            (
                c
                for c in (await admin.get("/api/v1/campaigns", headers=ah)).json()
                if c["name"] == "Q3 2026 Client Experience"
            ),
            None,
        )
        check("the seeded campaign is listed", seeded is not None)
        if seeded:
            check(
                "delivery funnel is measured",
                seeded["delivery"]["sent"] > 0
                and seeded["delivery"]["submitted"] > 0,
                f"{seeded['delivery']['sent']} sent, "
                f"{seeded['delivery']['opened']} opened, "
                f"{seeded['delivery']['submitted']} submitted "
                f"({seeded['delivery']['response_rate_pct']}%)",
            )
            check(
                "unsubscribed contacts were not invited",
                seeded["delivery"]["unsubscribed"] == 0,
                "none in the recipient list",
            )

        print("\n== Campaigns stay out of the internal cycle list ==")
        cycles = (await admin.get("/api/v1/cycles", headers=ah)).json()
        check(
            "external campaigns are not listed as review cycles",
            all(c["name"] != campaign["name"] for c in cycles),
        )

        print("\n== Revoking and unsubscribing ==")
        second_email = f"revoke.{suffix}@clientco.co"
        second = await admin.post(
            "/api/v1/contacts",
            headers=ah,
            json={"email": second_email, "full_name": "Revoke Target"},
        )
        await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/recipients",
            headers=ah,
            json={"target_id": target_id, "contact_ids": [second.json()["id"]]},
        )
        await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/send", headers=ah, json={}
        )
        second_token = token_from_outbox(second_email)
        check("a second invitation is delivered", second_token is not None)

        if second_token:
            live = await anon.get(f"/api/v1/public/feedback/{second_token}")
            check("the second link works before revocation", live.status_code == 200)

            listing = (
                await admin.get(
                    f"/api/v1/campaigns/{campaign['id']}/recipients", headers=ah
                )
            ).json()
            revoke_id = next(
                r["id"] for r in listing if r["contact_email"] == second_email
            )
            revoked = await admin.post(
                f"/api/v1/campaigns/{campaign['id']}/recipients/{revoke_id}/revoke",
                headers=ah,
            )
            check("a link can be revoked", revoked.status_code == 200)
            dead = await anon.get(f"/api/v1/public/feedback/{second_token}")
            check("a revoked link stops working immediately", dead.status_code == 404)

        third_email = f"unsub.{suffix}@clientco.co"
        third = await admin.post(
            "/api/v1/contacts",
            headers=ah,
            json={"email": third_email, "full_name": "Unsub Target"},
        )
        await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/recipients",
            headers=ah,
            json={"target_id": target_id, "contact_ids": [third.json()["id"]]},
        )
        await admin.post(
            f"/api/v1/campaigns/{campaign['id']}/send", headers=ah, json={}
        )
        third_token = token_from_outbox(third_email)
        if third_token:
            out = await anon.post(f"/api/v1/public/unsubscribe/{third_token}")
            check("a recipient can unsubscribe themselves", out.status_code == 200)
            resend = await admin.post(
                f"/api/v1/campaigns/{campaign['id']}/send",
                headers=ah,
                json={"resend": True},
            )
            check(
                "an unsubscribed contact is skipped on the next send",
                resend.json()["skipped"] >= 1,
                f"{resend.json()['skipped']} skipped",
            )

        print("\n== Delivery report ==")
        listing = (await admin.get("/api/v1/reports", headers=ah)).json()
        check(
            "the delivery report is registered",
            "campaign_delivery" in {r["key"] for r in listing},
        )
        filters = {"date_range": {"preset": "last_90_days"}, "page_size": 200}
        query = await admin.post(
            "/api/v1/reports/campaign_delivery/query", headers=ah, json=filters
        )
        check("it queries", query.status_code == 200, f"{query.json()['total']} rows")
        for fmt, signature in (("csv", b"Facet"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
            export = await admin.post(
                f"/api/v1/reports/campaign_delivery/export/{fmt}",
                headers=ah,
                json=filters,
            )
            check(
                f"{fmt.upper()} export renders",
                export.status_code == 200 and export.content.startswith(signature),
                f"{len(export.content):,} bytes",
            )

        print("\n== Tenant containment of the public path ==")
        async with SessionFactory() as probe:
            await bind_tenant(probe, TenantContext(org_id=None, is_super_admin=True))
            leaked = (
                await probe.execute(
                    sql_text(
                        "SELECT count(*) FROM feedback_responses r "
                        "JOIN review_cycles c ON c.id = r.cycle_id "
                        "WHERE r.org_id <> c.org_id"
                    )
                )
            ).scalar_one()
            check("no response landed in the wrong tenant", leaked == 0)

            orphan = (
                await probe.execute(
                    sql_text(
                        "SELECT count(*) FROM feedback_responses "
                        "WHERE is_anonymous AND recipient_id IS NOT NULL"
                    )
                )
            ).scalar_one()
            check(
                "no anonymous response retains a link to its recipient",
                orphan == 0,
            )

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All Phase 3 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
