# Facet

Multi-tenant feedback platform spanning **employee, client, and proposal**
relationships in a single graph.

Working name — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for
positioning, the tenancy model, the security design, and the AI plan.

> No Docker. Runs against a locally installed PostgreSQL.

---

## Prerequisites

- PostgreSQL 18 running on `localhost:5432`
- Python 3.12+
- Node 22+

## First-time setup

```bash
psql -U postgres -h localhost -c "CREATE DATABASE facet;"
```

```bash
psql -U postgres -h localhost -d facet -f infra/bootstrap.sql
```

Creates the extensions (`pgcrypto`, `pg_trgm`, `btree_gin`, `vector`) and the
`facet_app` application role. That role owns no tables and is not a superuser,
which is what makes row-level security actually enforce anything.

```bash
cp .env.example .env
```

Then set `SECRET_KEY` and check `ALEMBIC_DATABASE_URL` matches your superuser
password:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### Backend

```bash
cd backend && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt
```

```bash
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
```

```bash
cd backend && .venv/Scripts/python.exe -m app.seed
```

Then add the demo org chart, an open review cycle, and realistic responses:

```bash
cd backend && .venv/Scripts/python.exe -m app.seed_cycle
```

And an external client campaign with a delivery funnel:

```bash
cd backend && .venv/Scripts/python.exe -m app.seed_campaign
```

And a proposal pipeline with prospect ratings and real outcomes:

```bash
cd backend && .venv/Scripts/python.exe -m app.seed_proposals
```

Optionally, synthetic history so the predictive models have enough to fit —
without it they will correctly refuse to predict:

```bash
cd backend && .venv/Scripts/python.exe -m app.seed_history
```

Everything it creates is tagged `attributes->>'synthetic' = 'true'`.

### Frontend

```bash
cd frontend && npm install
```

## Running

Two terminals.

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8010 --reload
```

```bash
cd frontend && npm run dev
```

- App — http://localhost:5174
- API docs — http://localhost:8010/docs

Vite proxies `/api` onto its own origin, so the refresh cookie stays
`SameSite=Strict` in development exactly as it will in production.

## Seeded accounts

| Role | Email | Password |
|---|---|---|
| Super Admin | `admin@stixis.com` | `FacetPlatform!2026` |
| Client Admin | `priya.raman@northwind.example` | `NorthwindAdmin!2026` |
| Employees | `vikram.s@northwind.example` and others | `NorthwindUser!2026` |

Development only. The seed is idempotent.

## Verifying

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify
```

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify_phase2
```

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify_phase3
```

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify_phase4
```

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify_phase5
```

```bash
cd backend && .venv/Scripts/python.exe -m scripts.verify_phase6
```

Both run the real ASGI app in-process against the real database.

Phase 1 checks tenant isolation, refresh-token reuse detection,
account-enumeration resistance, role-scoped reports, all three export formats,
and audit immutability.

Phase 2 checks template cloning and publishing, cycle creation and assignment
generation, the submit path, storage-level anonymity (including that the
database refuses an anonymous row naming a reviewer), response immutability,
and that suppression thresholds hold in exports as well as on screen.

Phase 3 checks campaign setup, that the raw link token is recoverable from the
delivered email but appears nowhere in the database, single-use enforcement,
revocation, unsubscribe, that every public failure returns an identical
non-enumerable response, and that external feedback reaches the same results
pipeline as internal 360s.

## AI

Off by default. With no `OPENAI_API_KEY` the app uses a built-in deterministic
analyser — genuinely useful for sentiment and extractive summaries, clearly
labelled as such everywhere it appears, and costing nothing. To use OpenAI:

```
AI_ENABLED=true
OPENAI_API_KEY=sk-...
```

The OpenAI path is written to the Structured Outputs contract but has not been
exercised against the live API from this machine — expect to shake out
request/response details on first contact. Everything else about the feature
(the anonymity gate, injection handling, caching, budgets) is provider-agnostic
and verified.

Summaries are never generated below `AI_MIN_RESPONSES_FOR_SUMMARY` written
comments. That is a hard gate, not a display rule: nothing is sent to a
provider and nothing is stored.

## Predictions

Models refuse to predict when the data cannot support it, and say why. That is
the intended behaviour, not a bug: below 30 decided proposals (with at least 8
of each outcome, and measurable lift over guessing the majority) the
win-probability model is not fitted, no coefficients are stored, and the API
returns the reason instead of a number.

Refusals appear in the UI as content — "this is why there is no forecast" —
rather than as an empty panel.

## Scheduled jobs

No container runtime, so these are commands. Point Windows Task Scheduler at
them daily — both are idempotent and internally rate-limited, so running them
twice by accident does nothing.

```bash
cd backend && .venv/Scripts/python.exe -m app.tasks reminders --dry-run
```

```bash
cd backend && .venv/Scripts/python.exe -m app.tasks all
```

`reminders` nudges non-responders (internal and external) subject to a cooldown
and a per-person cap, then escalates once to the round's owner. `expire` retires
lapsed links, closes rounds past their closing date, and marks stranded
assignments — expiry is already enforced on read, so this exists to keep
reporting honest rather than to enforce anything.

## Layout

```
backend/
  app/
    core/        config, security primitives, errors, logging, rate limits
    db/          engine, session, tenancy (RLS binding + policy helpers)
    models/      SQLAlchemy models
    schemas/     Pydantic request/response contracts
    services/    auth, audit, email, storage
    reporting/   report registry, filter resolution, CSV/Excel/PDF renderers
    api/v1/      routes
  alembic/       migrations (incl. RLS policies and immutability triggers)
  scripts/       verify.py
frontend/
  src/
    components/  design system, filters, data table, signature visuals
    layout/      app shell
    pages/       login, dashboard, organizations, people, cycles, results,
                 campaigns, public respondent form, my feedback, my results,
                 templates, reports, audit, security
    lib/         API client (token handling, refresh dedupe, downloads), types
    store/       auth state
docs/            ARCHITECTURE.md
infra/           bootstrap.sql
```

## Notes for whoever picks this up

- Mail in development goes to `backend/var/outbox` as `.eml` files.
- `EMAIL_BACKEND=file` and an empty `REDIS_URL` are rejected in production by
  config validation at startup, along with a default `SECRET_KEY`, non-HTTPS
  CORS origins, and `COOKIE_SECURE=false`.
- Audit rows cannot be updated or deleted by anyone, including via psql.
- Published template versions are immutable; editing means a new version.
- Submitted feedback responses are immutable and cannot be deleted. Derived
  analysis columns (sentiment) are writable — the trigger guards the answers,
  the comment and the reviewer link, not the analysis.
- Comments that attempt to instruct the AI are flagged, audited, and excluded
  from summarisation, but still shown in the raw comment list.
- Anonymous responses carry no reviewer link at all — not a hidden column, no
  link. A `CHECK` constraint enforces it, and it covers the external
  `recipient_id` too. See §5a of the architecture doc.
- A campaign is a `ReviewCycle` with `audience = external`; it shares the whole
  results pipeline with internal 360s. See §5b.
- Feedback links are minted at send time, stored only as a SHA-256 hash, and
  burnt on submission. Re-sending invalidates the previous link.
- A handler that commits and then keeps querying must call
  `rebind_tenant(session, actor)`; tenancy GUCs are transaction-local.
- `email-validator` rejects reserved TLDs (`.test`, `.example`, `.invalid`), so
  seeded `@*.example` addresses work only because the seed bypasses the API.
