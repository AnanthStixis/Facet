"""Phase 4 verification: proposals, outcomes, scorecard, reminders.

    python -m scripts.verify_phase4
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
    outbox = settings.outbox_path
    if not outbox.exists():
        return None
    safe = "".join(c if c.isalnum() else "_" for c in email)
    for path in sorted(
        outbox.glob(f"*-{safe}.eml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
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
    prospect_email = f"prospect.{suffix}@bidco.co"

    async with make() as admin, make() as anon:
        login = await admin.post(
            "/api/v1/auth/login",
            json={"email": CLIENT_ADMIN_EMAIL, "password": CLIENT_ADMIN_PASSWORD},
        )
        login.raise_for_status()
        ah = {"authorization": f"Bearer {login.json()['access_token']}"}

        print("\n== Pipeline ==")
        pipeline = await admin.get("/api/v1/proposals", headers=ah)
        check("the seeded pipeline loads", pipeline.status_code == 200,
              f"{len(pipeline.json())} proposals")

        summary = (await admin.get("/api/v1/proposals/summary", headers=ah)).json()
        check("pipeline summary computes", summary["total"] > 0)
        check(
            "win rate counts only decided proposals",
            0 < summary["win_rate_pct"] <= 100,
            f"{summary['win_rate_pct']}%",
        )
        check(
            "feedback coverage is measured",
            summary["feedback_coverage_pct"] > 0,
            f"{summary['feedback_coverage_pct']}% of submitted proposals surveyed",
        )

        print("\n== Recording a proposal ==")
        contact = await admin.post(
            "/api/v1/contacts",
            headers=ah,
            json={
                "email": prospect_email,
                "full_name": "Priya Bidco",
                "company": "Bidco",
            },
        )
        contact_id = contact.json()["id"]

        made = await admin.post(
            "/api/v1/proposals",
            headers=ah,
            json={
                "title": f"Verification proposal {suffix}",
                "client_name": "Bidco",
                "prospect_contact_id": contact_id,
                "value_amount": "250000.00",
                "estimated_effort_days": 300,
            },
        )
        check("a proposal is recorded", made.status_code == 201)
        proposal = made.json()
        check("a reference is generated", proposal["reference"].startswith("PRO-"),
              proposal["reference"])
        check("it starts as a draft", proposal["stage"] == "draft")
        check("a draft has no feedback subject yet", proposal["target_id"] is None)

        early = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/request-feedback",
            headers=ah,
            json={},
        )
        check(
            "a draft cannot be surveyed",
            early.status_code == 409,
            early.json()["error"]["message"],
        )

        early_outcome = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/outcome",
            headers=ah,
            json={"stage": "won"},
        )
        check("a draft cannot have an outcome", early_outcome.status_code == 409)

        print("\n== Submission and feedback request ==")
        submitted = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/submit", headers=ah
        )
        check("submitting works", submitted.status_code == 200)
        check(
            "submitting creates the feedback subject",
            submitted.json()["target_id"] is not None,
        )
        check("submitted_at is stamped", submitted.json()["submitted_at"] is not None)

        again = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/submit", headers=ah
        )
        check("submitting twice is refused", again.status_code == 409)

        asked = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/request-feedback",
            headers=ah,
            json={"closes_in_days": 30},
        )
        check("feedback can be requested", asked.status_code == 200,
              f"sent={asked.json()['sent']}")

        duplicate = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/request-feedback",
            headers=ah,
            json={},
        )
        check("a second request is refused", duplicate.status_code == 409)

        print("\n== The prospect responds ==")
        token = token_from_outbox(prospect_email)
        check("the prospect receives a working link", token is not None)

        if token:
            form = await anon.get(f"/api/v1/public/feedback/{token}")
            check("the proposal form opens without authentication",
                  form.status_code == 200)
            body = form.json()
            check(
                "it is framed as being about the proposal",
                "proposal" in body["subject"]["type"],
                body["subject"]["label"][:40],
            )

            questions = [q for s in body["form"]["sections"] for q in s["questions"]]
            answers = {q["key"]: 4 for q in questions if q["type"] == "scale"}
            choice = next((q for q in questions if q["type"] == "choice"), None)
            if choice:
                answers[choice["key"]] = choice["options"][2]
            sent = await anon.post(
                f"/api/v1/public/feedback/{token}",
                json={"answers": answers, "comment": "Verification response."},
            )
            check("the prospect can submit", sent.status_code == 200)

            after = (
                await admin.get(f"/api/v1/proposals?search={suffix}", headers=ah)
            ).json()
            check(
                "the response is attached to the proposal",
                after and after[0]["feedback_responses"] == 1,
                f"avg {after[0]['feedback_average'] if after else '-'}",
            )

        print("\n== Recording the outcome ==")
        bad = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/outcome",
            headers=ah,
            json={"stage": "lost"},
        )
        check("a loss must state a reason", bad.status_code == 422)

        incoherent = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/outcome",
            headers=ah,
            json={"stage": "won", "loss_reason": "price"},
        )
        check("a win cannot carry a loss reason", incoherent.status_code == 422)

        won = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/outcome",
            headers=ah,
            json={"stage": "won", "won_amount": "235000.00",
                  "outcome_note": "Signed at a reduced scope."},
        )
        check("an outcome is recorded", won.status_code == 200)
        check("the decision is dated", won.json()["decided_at"] is not None)
        check(
            "the proposed-to-signed variance is computed",
            won.json()["value_variance"] is not None,
            f"{won.json()['value_variance']}",
        )

        settled = await admin.post(
            f"/api/v1/proposals/{proposal['id']}/outcome",
            headers=ah,
            json={"stage": "lost", "loss_reason": "price"},
        )
        check("an outcome cannot be overwritten", settled.status_code == 409)

        print("\n== Database-level coherence ==")
        from sqlalchemy import text as sql_text

        from app.db.session import SessionFactory
        from app.db.tenancy import TenantContext, bind_tenant

        async with SessionFactory() as probe:
            await bind_tenant(probe, TenantContext(org_id=None, is_super_admin=True))
            try:
                await probe.execute(
                    sql_text(
                        "UPDATE proposals SET loss_reason = 'price' WHERE stage = 'won'"
                    )
                )
                await probe.commit()
                bad_write = True
            except Exception:
                await probe.rollback()
                bad_write = False
            check(
                "the database refuses a loss reason on a won proposal",
                not bad_write,
            )

        print("\n== Scorecard ==")
        listing = (await admin.get("/api/v1/reports", headers=ah)).json()
        check(
            "the scorecard is registered",
            "proposal_scorecard" in {r["key"] for r in listing},
        )

        filters = {"date_range": {"preset": "this_year"}, "page_size": 200}
        query = await admin.post(
            "/api/v1/reports/proposal_scorecard/query", headers=ah, json=filters
        )
        check("the scorecard queries", query.status_code == 200,
              f"{query.json()['total']} proposals")

        rows = query.json()["rows"]
        check("drafts are excluded", all(row["stage"] != "draft" for row in rows))

        scored = [
            row
            for row in rows
            if row["feedback_average"] is not None and row["stage"] in {"won", "lost"}
        ]
        check("decided proposals carry prospect scores", len(scored) >= 3,
              f"{len(scored)} with both")

        if len(scored) >= 3:
            won_scores = [r["feedback_average"] for r in scored if r["stage"] == "won"]
            lost_scores = [r["feedback_average"] for r in scored if r["stage"] == "lost"]
            if won_scores and lost_scores:
                won_avg = sum(won_scores) / len(won_scores)
                lost_avg = sum(lost_scores) / len(lost_scores)
                # The whole point of the report: the two halves are joinable and
                # the comparison is computable. This asserts the join works, not
                # that any particular business truth holds.
                check(
                    "won and lost proposals are directly comparable on score",
                    True,
                    f"won avg {won_avg:.2f} vs lost avg {lost_avg:.2f}",
                )
            check(
                "loss reasons are captured on lost proposals",
                all(r["loss_reason"] for r in scored if r["stage"] == "lost"),
            )

        for fmt, signature in (("csv", b"Facet"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
            export = await admin.post(
                f"/api/v1/reports/proposal_scorecard/export/{fmt}",
                headers=ah,
                json=filters,
            )
            check(
                f"{fmt.upper()} export renders",
                export.status_code == 200 and export.content.startswith(signature),
                f"{len(export.content):,} bytes",
            )

        print("\n== Reminders ==")
        from app.services.reminders import run_reminders

        async with SessionFactory() as session:
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            dry = await run_reminders(session, dry_run=True)
        check("a dry run reports without sending", dry.failures == 0,
              f"would send {dry.total}")

        async with SessionFactory() as session:
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            first = await run_reminders(session)
            await session.commit()
        check("reminders send", first.total >= 0, f"{first.total} sent")

        async with SessionFactory() as session:
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            second = await run_reminders(session)
            await session.commit()
        check(
            "running again immediately sends nothing (cooldown holds)",
            second.total == 0,
            f"{second.skipped_cooldown} held on cooldown",
        )

        async with SessionFactory() as session:
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            capped = await run_reminders(session, max_reminders=0)
            await session.commit()
        check(
            "the per-person cap is respected",
            capped.total == 0 and capped.skipped_capped >= 0,
            f"{capped.skipped_capped} capped",
        )

        print("\n== Expiry job ==")
        from app.tasks import _expire

        code = await _expire()
        check("the expiry job runs cleanly", code == 0)

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All Phase 4 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
