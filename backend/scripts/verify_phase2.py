"""Phase 2 verification: cycles, assignments, responses, anonymity, results.

    python -m scripts.verify_phase2
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.seed import (  # noqa: E402
    CLIENT_ADMIN_EMAIL,
    CLIENT_ADMIN_PASSWORD,
    SUPER_ADMIN_EMAIL,
    SUPER_ADMIN_PASSWORD,
)

PASS = "  [pass]"
FAIL = "  [FAIL]"
failures: list[str] = []

EMPLOYEE_EMAIL = "vikram.s@northwind.example"
EMPLOYEE_PASSWORD = "NorthwindUser!2026"
MANAGER_EMAIL = "sneha.d@northwind.example"


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


async def _submission_checks(
    client: httpx.AsyncClient, headers: dict, queue: list[dict]
) -> None:
    """Exercise the submit path as whichever reviewer still owes feedback."""
    if not queue:
        check("assignments were available to submit", False, "none pending")
        return

    # Prefer a non-self assignment: a self-assessment is deliberately always
    # attributable, so it cannot exercise the anonymity path.
    assignment = next(
        (item for item in queue if item["relationship"] != "self"), queue[0]
    )
    expect_anonymous = assignment["is_anonymous"] and assignment["relationship"] != "self"
    payload = (
        await client.get(f"/api/v1/assignments/{assignment['id']}", headers=headers)
    ).json()
    questions = [
        question
        for section in payload["form"]["sections"]
        for question in section["questions"]
    ]

    out_of_range = await client.post(
        f"/api/v1/assignments/{assignment['id']}/submit",
        headers=headers,
        json={"answers": {questions[0]["key"]: 99}},
    )
    check("an out-of-range rating is rejected", out_of_range.status_code == 422)

    unknown = await client.post(
        f"/api/v1/assignments/{assignment['id']}/submit",
        headers=headers,
        json={"answers": {"not_a_question": 3}},
    )
    check("an unknown question key is rejected", unknown.status_code == 422)

    answers = {q["key"]: 4 for q in questions if q["type"] == "scale"}
    ok = await client.post(
        f"/api/v1/assignments/{assignment['id']}/submit",
        headers=headers,
        json={"answers": answers, "comment": "Verification submission."},
    )
    check("a valid submission is accepted", ok.status_code == 200)
    if ok.status_code == 200:
        said_anonymous = "anonymous" in ok.json()["message"].lower()
        check(
            "the confirmation matches whether the response was anonymous",
            said_anonymous == expect_anonymous,
            f"{assignment['relationship']}: {ok.json()['message']}",
        )

    again = await client.post(
        f"/api/v1/assignments/{assignment['id']}/submit",
        headers=headers,
        json={"answers": answers},
    )
    check("double submission is refused", again.status_code == 409)


async def main() -> int:
    from app.main import app

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async with make() as admin, make() as employee, make() as other:
        ca = await login(admin, CLIENT_ADMIN_EMAIL, CLIENT_ADMIN_PASSWORD)
        emp = await login(employee, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)
        ah = {"authorization": f"Bearer {ca['access_token']}"}
        eh = {"authorization": f"Bearer {emp['access_token']}"}

        print("\n== Template library ==")
        categories = (await admin.get("/api/v1/catalog/categories", headers=ah)).json()
        check("catalog returns categories", len(categories) >= 3, f"{len(categories)}")
        global_template = next(
            (
                template
                for category in categories
                for template in category["templates"]
                if template["scope"] == "global"
            ),
            None,
        )
        check("vendor templates are visible to the tenant", global_template is not None)

        detail = (
            await admin.get(
                f"/api/v1/catalog/templates/{global_template['id']}", headers=ah
            )
        ).json()
        check("a provided template is not editable in place", detail["editable"] is False)
        check("template renders as a form", len(detail["latest"]["form"]["sections"]) > 0)

        print("\n== Template authoring ==")
        blocked = await admin.put(
            f"/api/v1/catalog/templates/{global_template['id']}/draft",
            headers=ah,
            json={"definition": detail["latest"]["definition"]},
        )
        check("editing a provided template is refused", blocked.status_code == 409)

        clone = await admin.post(
            f"/api/v1/catalog/templates/{global_template['id']}/clone",
            headers=ah,
            json={"name": f"Verify clone {emp['access_token'][-6:]}"},
        )
        check("cloning into the organization works", clone.status_code == 201)
        clone_id = clone.json()["id"]

        bad = await admin.put(
            f"/api/v1/catalog/templates/{clone_id}/draft",
            headers=ah,
            json={"definition": {"sections": [{"title": "X", "questions": [
                {"key": "a", "text": "One"}, {"key": "a", "text": "Two"}]}]}},
        )
        check("a duplicate question key is rejected", bad.status_code == 422,
              bad.json()["error"]["code"])

        good_def = detail["latest"]["definition"]
        saved = await admin.put(
            f"/api/v1/catalog/templates/{clone_id}/draft",
            headers=ah,
            json={"definition": good_def},
        )
        check("a valid draft saves", saved.status_code == 200)

        no_publish = await admin.post(
            "/api/v1/cycles",
            headers=ah,
            json={"name": "Should not start", "template_id": clone_id},
        )
        check(
            "a cycle cannot use an unpublished template",
            no_publish.status_code == 409,
            no_publish.json()["error"]["message"],
        )

        published = await admin.post(
            f"/api/v1/catalog/templates/{clone_id}/publish", headers=ah
        )
        check("publishing works", published.status_code == 200,
              f"v{published.json()['version']}")

        print("\n== Cycles ==")
        cycles = (await admin.get("/api/v1/cycles", headers=ah)).json()
        seeded = next(
            (c for c in cycles if c["name"] == "H1 2026 Manager Effectiveness"), None
        )
        check("the seeded cycle is listed", seeded is not None)
        check("the cycle pinned a template version", bool(seeded["template_version_id"]))
        check("the cycle is anonymous", seeded["is_anonymous"] is True)
        check(
            "progress is tracked",
            seeded["progress"]["total"] > 0,
            f"{seeded['progress']['completion_pct']}% of {seeded['progress']['total']}",
        )

        print("\n== The reviewer's inbox ==")
        mine = (await employee.get("/api/v1/assignments/mine", headers=eh)).json()
        check("an employee sees their own assignments", isinstance(mine, list),
              f"{len(mine)} open")

        all_mine = (
            await employee.get("/api/v1/assignments/mine?include_done=true", headers=eh)
        ).json()
        check("assignments exist for this reviewer", len(all_mine) > 0, f"{len(all_mine)}")

        target_assignment = all_mine[0]
        form = await employee.get(
            f"/api/v1/assignments/{target_assignment['id']}", headers=eh
        )
        check("the reviewer can open their form", form.status_code == 200)

        stolen = await admin.get(
            f"/api/v1/assignments/{target_assignment['id']}", headers=ah
        )
        check(
            "a Client Admin cannot open someone else's assignment",
            stolen.status_code == 403,
            f"HTTP {stolen.status_code}",
        )

        print("\n== A full cycle, end to end ==")
        # Build a throwaway cycle rather than borrowing the seed's leftovers.
        # Re-running the script must not depend on unconsumed state from the
        # previous run, which is exactly the trap a seed-dependent test falls
        # into the second time anyone executes it.
        directory = (await admin.get("/api/v1/users?page_size=100", headers=ah)).json()
        manager = next(
            (person for person in directory["items"] if person["role"] == "manager"),
            None,
        )
        check("a manager exists to be reviewed", manager is not None)

        made = await admin.post(
            "/api/v1/cycles",
            headers=ah,
            json={
                "name": f"Verification cycle {clone_id[:8]}",
                "template_id": clone_id,
            },
        )
        check("a cycle is created from the published clone", made.status_code == 201)
        new_cycle = made.json()
        check("anonymity is snapshotted onto the cycle", new_cycle["is_anonymous"] is True)

        early = await admin.post(f"/api/v1/cycles/{new_cycle['id']}/open", headers=ah)
        check(
            "a cycle with no assignments cannot open",
            early.status_code == 409,
            early.json()["error"]["message"],
        )

        generated = await admin.post(
            f"/api/v1/cycles/{new_cycle['id']}/assignments",
            headers=ah,
            json={"reviewee_ids": [manager["id"]]},
        )
        check("assignments generate from the org chart", generated.status_code == 200,
              f"{generated.json()['created']} created")
        check(
            "the reviewer set spans more than one direction",
            len(generated.json()["by_relationship"]) > 1,
            ", ".join(generated.json()["by_relationship"]),
        )

        again_gen = await admin.post(
            f"/api/v1/cycles/{new_cycle['id']}/assignments",
            headers=ah,
            json={"reviewee_ids": [manager["id"]]},
        )
        check(
            "regenerating is idempotent",
            again_gen.json()["created"] == 0 and again_gen.json()["skipped_existing"] > 0,
            f"{again_gen.json()['skipped_existing']} skipped",
        )

        opened = await admin.post(f"/api/v1/cycles/{new_cycle['id']}/open", headers=ah)
        check("the cycle opens", opened.status_code == 200)

        from sqlalchemy import select as sql_select

        from app.db.session import SessionFactory as SF
        from app.db.tenancy import TenantContext as TC, bind_tenant as bt
        from app.models.cycle import FeedbackAssignment as FA
        from app.models.enums import AssignmentStatus as AS
        from app.models.user import User as U

        async with SF() as probe:
            await bt(probe, TC(org_id=None, is_super_admin=True))
            row = (
                await probe.execute(
                    sql_select(U.email)
                    .join(FA, FA.reviewer_user_id == U.id)
                    .where(
                        FA.cycle_id == uuid.UUID(new_cycle["id"]),
                        FA.status.in_([AS.PENDING, AS.IN_PROGRESS]),
                        FA.relationship_type != "self",
                    )
                    .limit(1)
                )
            ).first()
        pending_email = row[0] if row else None
        check("a reviewer was assigned in the new cycle", pending_email is not None)

        print("\n== Submitting ==")
        if pending_email:
            async with make() as reviewer:
                password = (
                    CLIENT_ADMIN_PASSWORD
                    if pending_email == CLIENT_ADMIN_EMAIL
                    else EMPLOYEE_PASSWORD
                )
                who = await login(reviewer, pending_email, password)
                rh = {"authorization": f"Bearer {who['access_token']}"}
                queue = [
                    item
                    for item in (
                        await reviewer.get("/api/v1/assignments/mine", headers=rh)
                    ).json()
                    if item["cycle_id"] == new_cycle["id"]
                ]
                check(
                    f"{pending_email.split('@')[0]} sees the new assignment",
                    len(queue) > 0,
                    f"{len(queue)} open",
                )
                await _submission_checks(reviewer, rh, queue)
        else:
            check("assignments were available to submit", False, "none pending")

        closed = await admin.post(f"/api/v1/cycles/{new_cycle['id']}/close", headers=ah)
        check("the cycle closes", closed.status_code == 200)
        late = await admin.post(f"/api/v1/cycles/{new_cycle['id']}/close", headers=ah)
        check("closing twice is refused", late.status_code == 409)

        print("\n== Anonymity at the storage layer ==")
        from sqlalchemy import text as sql_text

        from app.db.session import SessionFactory
        from app.db.tenancy import TenantContext, bind_tenant

        async with SessionFactory() as session:
            # Bind the platform context first. Without it row level security
            # hides every row from this connection and the checks below would
            # pass vacuously against an empty result set.
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            linked = (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM feedback_responses "
                        "WHERE is_anonymous AND (reviewer_user_id IS NOT NULL "
                        "OR assignment_id IS NOT NULL)"
                    )
                )
            ).scalar_one()
            check(
                "no anonymous response retains a link to its reviewer",
                linked == 0,
                f"{linked} leaky rows",
            )

            total_anon = (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM feedback_responses WHERE is_anonymous"
                    )
                )
            ).scalar_one()
            check("anonymous responses exist to test", total_anon > 0, f"{total_anon}")

            # A rollback ends the transaction the GUC was local to, so the
            # context has to be re-bound before each subsequent attempt.
            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            try:
                await session.execute(
                    sql_text(
                        "INSERT INTO feedback_responses "
                        "(org_id, cycle_id, target_id, template_version_id, "
                        " is_anonymous, reviewer_user_id, relationship_type, "
                        " answers, submitted_at) "
                        "SELECT org_id, cycle_id, target_id, template_version_id, "
                        " true, gen_random_uuid(), relationship_type, '{}'::jsonb, now() "
                        "FROM feedback_responses LIMIT 1"
                    )
                )
                await session.commit()
                forged = True
            except Exception:
                await session.rollback()
                forged = False
            check(
                "the database refuses an anonymous row that names a reviewer",
                not forged,
            )

            await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
            visible = (
                await session.execute(
                    sql_text("SELECT count(*) FROM feedback_responses")
                )
            ).scalar_one()
            check("rows are visible to the tamper attempt", visible > 0, f"{visible} rows")
            try:
                await session.execute(
                    sql_text("UPDATE feedback_responses SET answers = '{}'::jsonb")
                )
                await session.commit()
                tampered = True
            except Exception:
                await session.rollback()
                tampered = False
            check("submitted responses cannot be edited", not tampered)

        print("\n== Results and suppression ==")
        results = (
            await admin.get(f"/api/v1/cycles/{seeded['id']}/results", headers=ah)
        ).json()
        check("cycle results render", len(results["rows"]) > 0,
              f"{len(results['rows'])} targets")

        revealed = [r for r in results["rows"] if r["revealed"]]
        withheld = [r for r in results["rows"] if not r["revealed"]]
        check("some targets clear the threshold", len(revealed) > 0, f"{len(revealed)}")
        check(
            "withheld targets expose no average",
            all(r["overall_average"] is None for r in withheld),
            f"{len(withheld)} withheld",
        )

        if revealed:
            detail_row = revealed[0]
            per_target = (
                await admin.get(
                    f"/api/v1/cycles/{seeded['id']}/results/{detail_row['target_id']}",
                    headers=ah,
                )
            ).json()
            check("per-target results reveal", per_target["revealed"] is True)
            check("question-level averages are present",
                  len(per_target["questions"]) > 0)
            thin = [
                group
                for group in per_target["by_relationship"]
                if not group["revealed"]
            ]
            check(
                "thin relationship groups are individually suppressed",
                all(group["average"] is None for group in thin),
                f"{len(thin)} suppressed group(s)",
            )

        if withheld:
            hidden = (
                await admin.get(
                    f"/api/v1/cycles/{seeded['id']}/results/{withheld[0]['target_id']}",
                    headers=ah,
                )
            ).json()
            check("a suppressed target returns no questions", "questions" not in hidden)
            check("a suppressed target explains why", "suppressed_reason" in hidden)

        print("\n== Exports respect suppression ==")
        listing = (await admin.get("/api/v1/reports", headers=ah)).json()
        keys = {report["key"] for report in listing}
        check(
            "the new reports are registered",
            {"cycle_completion", "feedback_results"} <= keys,
        )

        filters = {"date_range": {"preset": "last_90_days"}, "page_size": 200}
        export = await admin.post(
            "/api/v1/reports/feedback_results/export/csv", headers=ah, json=filters
        )
        check("results export renders", export.status_code == 200,
              f"{len(export.content):,} bytes")
        body = export.content.decode("utf-8", errors="replace")
        check(
            "the export repeats the withheld marker rather than the number",
            ("Withheld below" in body) if withheld else True,
        )

        completion = await admin.post(
            "/api/v1/reports/cycle_completion/export/xlsx", headers=ah, json=filters
        )
        check("completion export renders", completion.status_code == 200,
              f"{len(completion.content):,} bytes")

        print("\n== Access control ==")
        others = await other.get("/api/v1/cycles", headers={"authorization": "Bearer nope"})
        check("an invalid token is rejected", others.status_code == 401)

        emp_cycles = await employee.get("/api/v1/cycles", headers=eh)
        check(
            "an employee cannot browse cycle administration",
            emp_cycles.status_code == 403,
            f"HTTP {emp_cycles.status_code}",
        )

        own = await employee.get("/api/v1/me/results", headers=eh)
        check("an employee can request their own results", own.status_code == 200)

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All Phase 2 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
