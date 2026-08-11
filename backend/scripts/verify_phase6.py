"""Phase 6 verification: the sufficiency gate, models, and recommendations.

    python -m scripts.verify_phase6

The headline check is the one that runs *before* the history seed: with only a
handful of decided proposals the model must decline, in writing, rather than
produce a confident number. That refusal is the feature.
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


async def _synthetic_count() -> int:
    from sqlalchemy import text as sql_text

    from app.db.session import SessionFactory
    from app.db.tenancy import TenantContext, bind_tenant

    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        return int(
            (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM proposals "
                        "WHERE attributes->>'synthetic' = 'true'"
                    )
                )
            ).scalar_one()
        )


async def _history_org(suffix: str, *, count: int = 60):
    """A tenant with a controlled, deterministic proposal history.

    The fitted path is checked here rather than against the shared demo tenant,
    because the other suites add proposals to that one on every run. Testing a
    model's performance against data other tests mutate produces a check that
    flaps — and a flapping check on a statistical gate is worse than useless,
    because the natural response is to loosen the gate.
    """
    import random
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.db.session import SessionFactory
    from app.db.tenancy import TenantContext, bind_tenant
    from app.models.catalog import FeedbackTarget, FeedbackTemplateVersion
    from app.models.cycle import FeedbackResponse, ReviewCycle
    from app.models.enums import (
        CycleAudience,
        CycleStatus,
        LossReason,
        OrgRegistrationSource,
        OrgStatus,
        ProposalStage,
        Relationship,
        TargetType,
        TemplateStatus,
    )
    from app.models.organization import Organization
    from app.models.proposal import Proposal

    rng = random.Random(9090)

    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        org = Organization(
            name=f"History Tenant {suffix}",
            slug=f"history-tenant-{suffix}",
            status=OrgStatus.ACTIVE,
            registration_source=OrgRegistrationSource.PROVISIONED,
            contact_name="Nobody",
            contact_email=f"history-{suffix}@verifytenant.co",
            timezone="UTC",
            approved_at=datetime.now(UTC),
        )
        session.add(org)
        await session.flush()

        version = (
            await session.execute(
                select(FeedbackTemplateVersion)
                .where(FeedbackTemplateVersion.status == TemplateStatus.PUBLISHED)
                .limit(1)
            )
        ).scalar_one()

        now = datetime.now(UTC)
        for index in range(count):
            score = round(rng.uniform(2.0, 5.0), 2)
            # A real but noisy relationship: better-rated proposals win more
            # often. 15% label noise keeps the model honest rather than perfect.
            is_won = (score >= 3.7) != (rng.random() < 0.15)
            submitted = now - timedelta(days=400 - index * 5)

            target = FeedbackTarget(
                org_id=org.id,
                target_type=TargetType.PROPOSAL,
                label=f"Fixture proposal {index}",
                reference=f"fixture:{suffix}:{index}",
                attributes={"synthetic": "true"},
            )
            session.add(target)
            await session.flush()

            session.add(
                Proposal(
                    org_id=org.id,
                    reference=f"FIX-{suffix}-{index:03d}",
                    title=f"Fixture proposal {index}",
                    client_name=f"Client {index}",
                    stage=ProposalStage.WON if is_won else ProposalStage.LOST,
                    currency="USD",
                    value_amount=Decimal(rng.choice([120, 200, 300, 450]) * 1000),
                    estimated_effort_days=rng.randint(80, 600),
                    submitted_at=submitted,
                    decided_at=submitted + timedelta(days=rng.randint(10, 60)),
                    loss_reason=None if is_won else LossReason.PRICE,
                    target_id=target.id,
                    attributes={"synthetic": "true"},
                )
            )

            cycle = ReviewCycle(
                org_id=org.id,
                name=f"Fixture round {index}",
                template_version_id=version.id,
                status=CycleStatus.CLOSED,
                audience=CycleAudience.EXTERNAL,
                is_anonymous=False,
                min_responses_to_reveal=4,
                opens_at=submitted,
                opened_at=submitted,
                closes_at=submitted + timedelta(days=20),
                closed_at=submitted + timedelta(days=20),
            )
            session.add(cycle)
            await session.flush()

            session.add(
                FeedbackResponse(
                    org_id=org.id,
                    cycle_id=cycle.id,
                    target_id=target.id,
                    template_version_id=version.id,
                    is_anonymous=False,
                    relationship_type=Relationship.EXTERNAL,
                    answers={},
                    overall_score=score,
                    answered_count=0,
                    submitted_at=submitted + timedelta(days=5),
                )
            )

        await session.commit()
        return org.id


async def _empty_org(suffix: str):
    """A throwaway tenant with no history, for exercising the refusal path.

    Deliberately not "delete the seeded history and retrain": submitted
    responses are immutable by database trigger, so tearing that data down is
    both impossible and undesirable. Testing the refusal against a genuinely
    empty tenant is closer to what a new customer actually experiences.
    """
    from datetime import UTC, datetime

    from app.db.session import SessionFactory
    from app.db.tenancy import TenantContext, bind_tenant
    from app.models.enums import OrgRegistrationSource, OrgStatus
    from app.models.organization import Organization

    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=None, is_super_admin=True))
        org = Organization(
            name=f"Empty Tenant {suffix}",
            slug=f"empty-tenant-{suffix}",
            status=OrgStatus.ACTIVE,
            registration_source=OrgRegistrationSource.PROVISIONED,
            contact_name="Nobody",
            contact_email=f"nobody-{suffix}@verifytenant.co",
            timezone="UTC",
            approved_at=datetime.now(UTC),
        )
        session.add(org)
        await session.commit()
        return org.id


async def main() -> int:
    from app.main import app
    from app.models.enums import ModelKind
    from app.services.analytics import sufficiency

    print("\n== The gate, as a unit ==")
    thin = sufficiency.check_samples(
        ModelKind.WIN_PROBABILITY, n_samples=8, n_positive=5
    )
    check("eight proposals is refused", not thin.ok, (thin.reason or "")[:60])
    check("the refusal says how many more are needed", "more required" in (thin.reason or ""))

    lopsided = sufficiency.check_samples(
        ModelKind.WIN_PROBABILITY, n_samples=40, n_positive=38
    )
    check("a one-sided outcome history is refused", not lopsided.ok,
          (lopsided.reason or "")[:60])

    fine = sufficiency.check_samples(
        ModelKind.WIN_PROBABILITY, n_samples=40, n_positive=18
    )
    check("a balanced 40-row history is allowed", fine.ok)

    no_lift = sufficiency.check_performance(cv_score=0.81, baseline=0.80)
    check(
        "a model that cannot beat the baseline is refused",
        not no_lift.ok,
        (no_lift.reason or "")[:70],
    )
    real_lift = sufficiency.check_performance(cv_score=0.78, baseline=0.55)
    check("a model with genuine lift is allowed", real_lift.ok)

    check(
        "confidence is reported pessimistically on small data",
        sufficiency.confidence_band(0.82, 40) == "low",
        sufficiency.confidence_band(0.82, 40),
    )

    print("\n== Before there is enough history (empty tenant) ==")
    from app.db.session import SessionFactory
    from app.db.tenancy import TenantContext, bind_tenant
    from app.services.analytics import models as analytics_models

    empty_org = await _empty_org(uuid.uuid4().hex[:6])
    async with SessionFactory() as session:
        await bind_tenant(session, TenantContext(org_id=empty_org, is_super_admin=True))
        refusal = await analytics_models.fit_win_probability(
            session, org_id=empty_org
        )
        await session.commit()

    check(
        "with no history the model declines rather than fitting",
        refusal.status.value == "insufficient_data",
        refusal.status.value,
    )
    check(
        "and explains why in plain words",
        bool(refusal.reason),
        (refusal.reason or "")[:70],
    )

    async with SessionFactory() as session:
        from sqlalchemy import select as sql_select

        from app.models.analytics import AnalyticsModel

        await bind_tenant(session, TenantContext(org_id=empty_org, is_super_admin=True))
        stored = (
            await session.execute(
                sql_select(AnalyticsModel).where(AnalyticsModel.org_id == empty_org)
            )
        ).scalar_one()
        check("the refusal is stored, not discarded", stored.reason is not None)
        check("a refused model stores no coefficients", stored.coefficients == {})
        check("and is not usable", stored.is_usable is False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as admin:
        login = await admin.post(
            "/api/v1/auth/login",
            json={"email": CLIENT_ADMIN_EMAIL, "password": CLIENT_ADMIN_PASSWORD},
        )
        login.raise_for_status()
        ah = {"authorization": f"Bearer {login.json()['access_token']}"}

        print("\n== The API surfaces refusals rather than hiding them ==")
        listing = (await admin.get("/api/v1/insights/models", headers=ah)).json()
        by_kind = {item["kind"]: item for item in listing}
        check("every model is listed, fitted or not", len(by_kind) == 3, str(len(by_kind)))
        untrained = [item for item in listing if not item.get("usable")]
        check(
            "untrained models still return a reason",
            all(item.get("reason") for item in untrained),
            f"{len(untrained)} not usable",
        )
        check(
            "and state what would be needed",
            all(item["minimums"]["samples"] > 0 for item in listing),
        )

        print("\n== With a controlled history ==")
        history_org = await _history_org(uuid.uuid4().hex[:6])
        async with SessionFactory() as session:
            await bind_tenant(
                session, TenantContext(org_id=history_org, is_super_admin=True)
            )
            fitted = await analytics_models.fit_win_probability(
                session, org_id=history_org
            )
            await session.commit()

        check(
            "the model fits once there is history",
            fitted.status.value == "fitted",
            f"{fitted.n_samples} samples"
            + (f" — {fitted.reason}" if fitted.reason else ""),
        )
        metrics = fitted.metrics or {}
        win = {"status": fitted.status.value, "n_samples": fitted.n_samples}
        check(
            "performance is cross-validated, not in-sample",
            "cv_accuracy" in metrics,
            f"cv {metrics.get('cv_accuracy')}",
        )
        check(
            "it is reported against a baseline",
            "baseline_accuracy" in metrics,
            f"baseline {metrics.get('baseline_accuracy')}",
        )
        check(
            "it beat the baseline",
            (metrics.get("lift") or 0) >= 0.05,
            f"lift {metrics.get('lift')}",
        )
        check(
            "confidence is stated",
            metrics.get("confidence") in {"low", "moderate", "reasonable"},
            metrics.get("confidence"),
        )

        print("\n== Scoring the fitted model ==")
        async with SessionFactory() as session:
            from sqlalchemy import select as sql_select

            from app.models.analytics import AnalyticsModel

            await bind_tenant(
                session, TenantContext(org_id=history_org, is_super_admin=True)
            )
            model = (
                await session.execute(
                    sql_select(AnalyticsModel).where(
                        AnalyticsModel.org_id == history_org
                    )
                )
            ).scalar_one()

            strong = analytics_models.score_win_probability(
                model,
                {"score": 4.8, "value_amount": 200000, "estimated_effort_days": 200,
                 "submitted_at": None, "decided_at": None},
            )
            weak = analytics_models.score_win_probability(
                model,
                {"score": 2.2, "value_amount": 200000, "estimated_effort_days": 200,
                 "submitted_at": None, "decided_at": None},
            )
        check("a probability is returned", strong is not None and weak is not None)
        check(
            "a well-rated proposal scores higher than a poorly-rated one",
            (strong or 0) > (weak or 0),
            f"{strong:.0%} vs {weak:.0%}" if strong and weak else "",
        )
        check(
            "probabilities stay inside 0-1",
            0.0 <= (strong or 0) <= 1.0 and 0.0 <= (weak or 0) <= 1.0,
        )

        print("\n== The predictions endpoint is coherent either way ==")
        # Asserted as a property rather than a fixed outcome: this tenant's
        # data is mutated by the other suites, so the honest check is that the
        # endpoint is *never* half-answered — never a number without a caveat,
        # never a refusal without a reason.
        predictions = (
            await admin.get("/api/v1/insights/proposals/predictions", headers=ah)
        ).json()
        if predictions["available"]:
            check(
                "an available prediction carries its caveat",
                "rough ordering" in predictions["caveat"],
            )
            check(
                "and its cross-validated accuracy",
                predictions.get("cv_accuracy") is not None,
                f"cv {predictions.get('cv_accuracy')}",
            )
            if predictions["predictions"]:
                sample = predictions["predictions"][0]
                check(
                    "a probability is a whole percentage, not false precision",
                    isinstance(sample["probability_pct"], int),
                    f"{sample['probability_pct']}%",
                )
                check(
                    "predictions are ordered",
                    all(
                        a["probability_pct"] >= b["probability_pct"]
                        for a, b in zip(
                            predictions["predictions"], predictions["predictions"][1:]
                        )
                    ),
                )
        else:
            check(
                "an unavailable prediction carries a reason",
                bool(predictions.get("reason")),
                (predictions.get("reason") or "")[:70],
            )
            check("and offers no numbers at all", predictions["predictions"] == [])

        print("\n== Recommendations are computed, not generated ==")
        # Ensure the demo tenant has history too, so the Insights screen has
        # something to show. Idempotent.
        from app.seed_history import seed_history

        await seed_history()
        await admin.post("/api/v1/insights/models/train", headers=ah)

        built = await admin.post("/api/v1/insights/recommendations/rebuild", headers=ah)
        check("recommendations build", built.status_code == 200)
        body = built.json()
        findings = body["findings"]
        check("findings were produced", len(findings) > 0, f"{len(findings)} findings")
        check(
            "the artefact states its numbers are rule-computed",
            body["computed_by"] == "deterministic rules over stored data",
        )

        check(
            "every finding carries evidence",
            all(item["evidence"] for item in findings),
        )
        check(
            "every finding carries a metric a reader can check",
            all(item["metric"] for item in findings),
        )
        check(
            "every finding suggests an action",
            all(item["action"] for item in findings),
        )
        check(
            "severities are from the fixed set",
            all(
                item["severity"] in {"info", "attention", "urgent"}
                for item in findings
            ),
        )
        check(
            "urgent findings sort first",
            [item["severity"] for item in findings]
            == sorted(
                [item["severity"] for item in findings],
                key=lambda s: {"urgent": 0, "attention": 1, "info": 2}[s],
            ),
        )

        # The central claim of the hybrid design: numbers in the text come from
        # the rule, so they cannot disagree with the metric beside them.
        mismatches = []
        for item in findings:
            metric = item["metric"]
            for key in ("delta", "gap", "count", "mentions", "missing"):
                if key in metric and metric[key] is not None:
                    value = metric[key]
                    rendered = f"{item['title']} {item['detail']}"
                    if isinstance(value, int) and str(value) not in rendered:
                        mismatches.append(f"{item['key']}:{key}")
        check(
            "figures quoted in a finding appear in its own metric",
            not mismatches,
            ", ".join(mismatches[:3]) or "all consistent",
        )

        stored = (await admin.get("/api/v1/insights/recommendations", headers=ah)).json()
        check("recommendations persist", stored["status"] == "ready")
        check(
            "the stored copy matches what was returned",
            len(stored["findings"]) == len(findings),
        )

        print("\n== Trend and disengagement ==")
        results = (await admin.get("/api/v1/cycles", headers=ah)).json()
        target_id = None
        for cycle in results:
            rows = (
                await admin.get(f"/api/v1/cycles/{cycle['id']}/results", headers=ah)
            ).json()["rows"]
            if rows:
                target_id = rows[0]["target_id"]
                break

        if target_id:
            trend = (
                await admin.get(f"/api/v1/insights/targets/{target_id}/trend", headers=ah)
            ).json()
            check("a trend endpoint responds", "available" in trend)
            if not trend["available"]:
                check(
                    "a single-cycle subject is refused a trend",
                    bool(trend["reason"]),
                    trend["reason"][:60],
                )
            else:
                check(
                    "a trend projects only one cycle ahead",
                    "projected_next" in trend,
                    f"slope {trend['slope_per_cycle']}",
                )

        risk = (await admin.get("/api/v1/insights/disengagement", headers=ah)).json()
        check("the disengagement signal responds", "available" in risk)
        if risk["available"]:
            check(
                "it is labelled a signal rather than a prediction",
                "not a prediction" in risk["caveat"],
            )
            check(
                "each person carries the factors behind their score",
                all(person["factors"] for person in risk["people"]),
            )

        print("\n== Access control ==")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as employee:
            emp = await employee.post(
                "/api/v1/auth/login",
                json={
                    "email": "vikram.s@northwind.example",
                    "password": "NorthwindUser!2026",
                },
            )
            eh = {"authorization": f"Bearer {emp.json()['access_token']}"}
            for path in (
                "/api/v1/insights/recommendations",
                "/api/v1/insights/proposals/predictions",
                "/api/v1/insights/disengagement",
            ):
                blocked = await employee.get(path, headers=eh)
                check(
                    f"an employee cannot read {path.split('/')[-1]}",
                    blocked.status_code == 403,
                    f"HTTP {blocked.status_code}",
                )

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All Phase 6 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
