# Facet — Technical Design

**Status:** Phases 1–6 built and verified · **Date:** 08 August 2026
**Working name:** Facet *(provisional — see [Product name](#product-name))*
**Supersedes nothing.** Complements `Functional_Spec_360_Feedback_Platform.docx` v0.2.

---

## 1. Positioning and differentiation

The brief was explicit that this is going to market and must not be a copy of an
existing product. That constraint drove the data model, not just the styling.

### What the market already covers

| Segment | Who owns it | What they do not do |
|---|---|---|
| Employee 360 / performance | Culture Amp, Lattice, 15Five, Peoplebox, Workhuman | No customer feedback. No proposal quality. |
| Voice of the customer | Qualtrics, Sprinklr, Zonka, Sogolytics | No internal 360. Enterprise pricing, not white-label multi-tenant. |
| Proposal / bid quality | *effectively nobody* | — |

Qualtrics is the only vendor that plausibly spans employee and customer
experience, and it does so as two large products under one brand, priced for
enterprises, and not resold as a white-labelled tenant platform.

### The thesis

> One organization's feedback relationships — employee, client, and proposal —
> belong in a single graph, because the interesting questions cross the
> boundaries the incumbents built their products along.

"Do the teams that score highest on internal collaboration produce the proposals
prospects rate best?" is unanswerable in every tool listed above without
exporting from two systems into a spreadsheet. It is a single join here.

### How that became a schema decision

`feedback_targets` is one table with a `target_type` discriminator covering
employee, manager, team, department, product, service, and proposal. A template
points at a target type; a response points at a target. There is no
"employee module" table and no separate "survey" table.

This is the difference between a product that can add cross-domain analytics
later and one that would need a migration and a rewrite to do it. It cost
nothing to do on day one and is close to impossible to retrofit.

### Product name

`Facet` — *every relationship has more than one side*. Provisional: the
functional spec lists final naming as an open question. It is centralised in
`PRODUCT_NAME` / `PRODUCT_TAGLINE` in `.env` and read from one settings object,
so renaming is a config change plus a logo swap, not a search-and-replace.

---

## 2. Stack

| Layer | Choice | Why this and not the obvious alternative |
|---|---|---|
| API | FastAPI + async SQLAlchemy 2.x | Matches the stack already running in production at Stixis. |
| Database | **PostgreSQL 18, local install** | Row-level security is the tenancy mechanism; JSONB carries the configurable form definitions. No Docker anywhere. |
| Migrations | Alembic | Schema will churn across four phases; hand-managed DDL will not survive that. |
| Frontend | React 19 + TypeScript + Vite + Tailwind | Same shape as qstudio, so context-switching between projects is cheap. |
| PDF | **ReportLab** | WeasyPrint needs the GTK/Pango/Cairo native stack — a real install burden on Windows and a permanent support cost for a self-hosted product. ReportLab is pure Python wheels. |
| Excel | xlsxwriter (constant-memory mode) | Streams; does not hold the workbook in RAM. |
| Rate limiting | In-process, Redis-ready | Single worker locally. `REDIS_URL` switches to shared counters — and production config validation *requires* it, because per-worker limits are not limits. |
| Email (dev) | `.eml` files to `backend/var/outbox` | Reviewable templates with no SMTP server and no container. |
| AI | OpenAI, Phase 5+ | See §7. |

`pgvector`, `pg_trgm`, `pgcrypto`, and `btree_gin` are all installed and
verified on the local PostgreSQL 18 instance.

---

## 3. Multi-tenancy

**Shared schema, `org_id` on every tenant table, enforced by Postgres row-level
security.**

The reasoning, recorded because it is the decision everything else rests on:

> A forgotten `WHERE org_id = ...` in application code is a cross-tenant data
> leak. A forgotten `WHERE` with RLS enabled returns zero rows. One of those
> failure modes ends in a breach notification and the other ends in a bug
> report, so the enforcement belongs in the database.

Mechanics:

- The API connects as `facet_app`, which owns **no tables** and is **not** a
  superuser. Both owners and superusers bypass RLS, so this separation is what
  makes the policies real. Migrations connect as the owner over a separate URL.
- Two transaction-local GUCs drive every policy: `app.current_org_id` and
  `app.is_super_admin`. Both are set with `set_config(..., is_local => true)`,
  so they cannot leak to the next request that borrows the pooled connection.
- Policies use `FORCE ROW LEVEL SECURITY`, so they apply to the table owner too.
- A session opens with **no tenant bound**. The tenant is applied only after the
  bearer token is verified. A route that forgets to authenticate therefore reads
  nothing rather than everything.

### The two sanctioned escapes

RLS created two genuine bootstrapping problems. Both are solved with narrow
`SECURITY DEFINER` functions rather than a bypass flag in application code,
because a bypass flag is one stray code path away from a full cross-tenant read.

| Function | Migration | Can do | Cannot do |
|---|---|---|---|
| `facet_auth_principal(uuid, text)` | 0002 | Return the auth columns for **one** user by exact id or email | Enumerate, list, or return anything else |
| `facet_audit_append(...)` | 0003 | Insert **one** audit row | Read, update, or delete anything |

Both are `REVOKE ALL ... FROM PUBLIC` then granted only to `facet_app`. Audit
*reads* still go through RLS, so a Client Admin's audit page stays scoped to
their own organization.

---

## 4. Authentication

Hardening was called out as the primary concern. What was built:

| Control | Implementation |
|---|---|
| Password hashing | argon2id, 64 MiB / 3 passes / 4 lanes (OWASP-aligned) |
| Access token | JWT, **15 min**, carries `org_id` + `role`, which feed the RLS GUCs |
| Refresh token | **Opaque random, not a JWT** — a JWT refresh token cannot be revoked without a denylist, which has all the cost of a database token and none of the benefit |
| Rotation | Every refresh issues a new token and spends the old one |
| **Reuse detection** | Replaying a spent token **destroys the whole session family** — attacker and victim are both signed out, so the victim notices. Silently re-issuing is how stolen sessions live for weeks. |
| Cookie | `httpOnly` + `Secure` + `SameSite=Strict`, path-scoped |
| CSRF | Double-submit token in a readable cookie, echoed in `x-facet-csrf` |
| MFA | TOTP + 10 single-use recovery codes stored as argon2 hashes; secret encrypted with a key derived from `SECRET_KEY` |
| Half-auth state | Post-password, pre-code tokens have `scope: mfa_pending`, a 5-minute TTL, and reach only the MFA endpoints |
| Brute force | Per-IP **and** per-account limits, plus account lockout |
| Enumeration | Identical error and identical timing for unknown account and wrong password — the unknown path still runs a real argon2 verify against a dummy hash |
| Breach check | HaveIBeenPwned k-anonymity (5 hash chars leave the server); fails open |
| Blast radius | Password change, user disable, and org suspend all revoke sessions immediately rather than waiting for token expiry |
| Storage | The access token lives in a **module variable** — never `localStorage`. Anything script can read survives a tab close, but also survives an XSS bug. |

External respondents are deliberately **not** users. They get an opaque
single-use link and no credentials, so an engagement ending leaves no dormant
account behind.

---

## 5. Reporting and export

**One registry, three renderers.** Each report declares its columns, its query,
and its minimum role once. CSV, Excel, and PDF are renderers over that
declaration.

The rule that makes it trustworthy:

> The same `FilterState` instance that produced the rows on screen is what the
> renderer receives. Export never rebuilds its own filtering.

The alternative — one export endpoint per report per format — is where
"the CSV says 412 but the dashboard says 408" comes from, the first time
someone fixes a filter in only one of them.

Also handled:

- **CSV injection.** A cell starting `=`, `+`, `-`, or `@` executes as a formula
  in Excel and Sheets. Free-text feedback is attacker-controllable, so every
  such cell is prefixed with `'`.
- **Provenance.** Every file carries the organization, the resolved filters, the
  period, who generated it, and when. The same summary appears above the table
  on screen.
- **Branding.** PDFs carry the *tenant's* logo and accent, not the vendor's.
- **Audit.** Every export writes an audit entry including the filters used.
- **Limits.** Above `EXPORT_SYNC_ROW_LIMIT` the export is queued; a hard ceiling
  rejects unbounded pulls.

### Filters

- Autocomplete is `pg_trgm` + GIN indexes; endpoints return `{id, label}` only,
  because a typeahead that returns records is a directory export for anyone who
  can type a letter.
- Date ranges resolve **once, server-side, in the organization's timezone** into
  a half-open UTC interval. "Last 30 days" must mean the same thing on screen
  and in the file, and that is only guaranteed by resolving it in one place.

---

## 5a. Anonymity (Phase 2)

The spec left anonymity as an open question. It is built as a per-template
setting, defaulting to **anonymous for upward feedback** and attributable for
peer review — but the mechanism matters more than the default, so it is
recorded here.

### The problem with how this is normally done

Most feedback products mean, by "anonymous", that the reviewer's name is hidden
in the UI while the database still holds a `reviewer_id` on the response row.
That is not anonymity. It is a promise that survives exactly as long as nobody
runs a query, and the person being asked to be honest about their manager is
the one with most to lose when it doesn't.

### What is built

An anonymous response stores **no path back to the reviewer at all**:

- `reviewer_user_id` is NULL
- `assignment_id` is NULL — so it cannot be joined back to the assignment that
  names the reviewer
- the assignment is marked submitted in the same transaction, so completion
  tracking and reminders still work

A database `CHECK` constraint enforces the combination, so no future code path
can populate one and forget the other. The result: *"has Vikram responded?"* is
answerable and *"what did Vikram say?"* is not — not by a Client Admin, not by
a Super Admin, and not by someone holding the production password.

Self-assessments are always attributable, because they are the reviewee's own
answers and hiding them from the reviewee would be nonsense.

### Suppression under aggregation

Storage anonymity is worthless if aggregates leak it back, so three rules are
applied in the query, never in the UI:

1. **Overall** — below `min_responses_to_reveal` (default 4), only the count
   is shown.
2. **Per direction** — a breakdown appears only when that direction clears the
   threshold *on its own*. "Upward: 4.0" from one direct report names the
   author precisely, however safe the overall number looked.
3. **Self excluded** — a self-assessment never counts toward the threshold, or
   one person's own input would unlock everyone else's.

Free-text comments ride the same threshold (a verbatim is far more identifying
than a number) and are sorted by content rather than submission time, removing
the ordering side channel.

Because suppression lives in the query, the CSV, Excel, and PDF exports withhold
exactly the same values. Exports are the classic way this guarantee gets
bypassed — the screen hides a two-response average and the spreadsheet
cheerfully prints it.

## 5b. External campaigns (Phase 3)

### A campaign is not a new thing

The obvious build is a `campaigns` table beside `review_cycles`, with its own
recipients, its own responses, its own results code and its own exports. That
is exactly the split every incumbent has, and it is why none of them can answer
a question that crosses it.

Here a campaign **is** a `ReviewCycle` with `audience = external`. What differs
is only how the round reaches people:

| | Internal round | External round |
|---|---|---|
| Reaches people via | `feedback_assignments` | `campaign_recipients` + emailed link |
| Respondent is | a `User` | a `Contact`, with no account |
| Writes to | `feedback_responses` | `feedback_responses` |
| Aggregation, suppression, reports, exports | shared | shared |

Phase 3 therefore added **zero** results code. `/campaigns/{id}/results` calls
the same `cycle_overview` the internal 360 uses, and the anonymity threshold
applies to client feedback exactly as it does to upward feedback. That is the
unified-graph thesis from §1 paying rent rather than being a slogan.

### One-time link security

The public endpoint is the only unauthenticated, internet-facing surface that
touches tenant data, so it is the most carefully constrained code in the repo.

- **Opaque token, not a JWT.** A JWT carries tenant and campaign identifiers in
  a decodable payload — anyone forwarded an invitation could read the customer
  list out of it.
- **Only the SHA-256 hash is stored.** The raw token exists once, in the
  delivered email. `verify_phase3` proves this by recovering the token from the
  `.eml` file and confirming the raw value appears nowhere in the database.
- **One token per recipient**, never per campaign. A shared link means one
  forwarded email lets a stranger answer as the client, and makes "who has
  responded" unanswerable.
- **Minted at send time**, so a link prepared but never delivered is never
  valid. Re-sending issues a fresh token and invalidates the previous one.
- **Single use.** The token is burnt in the same transaction as the response,
  so there is no window where a spent link still works.
- **Tenant containment.** Resolution goes through `facet_public_link`
  (SECURITY DEFINER, migration 0005), which returns only enough to identify the
  link's organization. The handler then binds *that* tenant and does everything
  else under ordinary RLS — so a bug in the public handler can only ever reach
  the tenant the presented token already belonged to.
- **No enumeration.** Unknown, expired, spent, revoked and closed-campaign all
  return the identical 404 body. Distinguishing them would let a guesser learn
  which tokens exist and which customers are running campaigns.
- **Self-service unsubscribe** from the confirmation screen. An opt-out that
  requires emailing a human is an opt-out that gets ignored and then reported
  as spam. Unsubscribed contacts are skipped at send time *and reported as
  skipped*, so an admin chasing a missing response is told the reason.

## 5c. Proposals and the payoff (Phase 4)

### Why this module exists

Proposal feedback on its own is mildly interesting: a prospect rates the
technical approach 4.2 and the estimate 3.1. It becomes *valuable* only when it
sits beside what actually happened — won or lost, at what value, and if lost,
why.

That join is the question neither category of incumbent can answer. The
employee-feedback tools have no proposals. The customer-experience tools have
no commercial outcome. A CRM has the outcome but never asked the prospect what
they thought of the document.

Here both halves are columns in one query, and the seeded data shows the shape
the report is built to reveal:

| Outcome | Average prospect score |
|---|---|
| Won | 4.33 |
| Lost | 2.83 |

### Deliberately not a CRM

`proposals` records only what is needed to ask for feedback at the right moment
and to correlate it with the outcome: reference, client, value, effort, author,
stage, and the decision. Stages are coarse on purpose. Anything more belongs in
whatever system the sales team already uses, and building it here would produce
a second-rate CRM nobody maintains.

Two constraints keep the analytics honest:

- A loss reason may exist **only** on a lost proposal. Otherwise every "why do
  we lose" breakdown silently accumulates junk.
- A decided stage must carry a decision date, so win rate over a period is
  computable rather than approximate.

`LossReason` is an enum rather than free text for the same reason: the entire
value of the field is grouping by it, and "too expensive" typed forty ways
answers nothing.

### Reuse, again

Submitting a proposal creates a `FeedbackTarget` of type `proposal`. Asking the
prospect creates an ordinary **external campaign** — so proposal surveys inherit
the one-time link security, delivery tracking, results aggregation and exports
built in Phase 3. There is no proposal-specific response handling anywhere,
because none is needed.

The target is created at *submission*, not at draft, so a proposal that was
never sent can never be surveyed.

## 5d. Reminders and escalation

A 30% response rate is not a finding; it is a nudge that never got sent. But an
over-eager reminder system is worse than none, so three rules constrain it:

- **Cooldown** — nobody is nudged more than once every few days regardless of
  how often the job runs. That makes it safe to schedule hourly and safe to run
  twice by accident.
- **Cap** — at most N reminders per person per round. Past that the silence is
  an answer, and continuing to email is how a sending domain reaches a
  blocklist.
- **Escalate once** — when everyone outstanding has hit the cap, the round's
  owner gets a single digest naming them. `escalated_at` ensures it happens
  once. A human walking over to ask beats a fourth email.

External reminders issue a **fresh link**, invalidating the previous one —
otherwise a recipient with two emails open holds two live tokens and "single
use" quietly stops being true.

There is no container runtime here, so these run as commands rather than Celery
beat entries:

```
python -m app.tasks reminders [--dry-run]
python -m app.tasks expire
```

Point Windows Task Scheduler at them daily. The cooldown makes the cadence
forgiving.

## 5e. AI intelligence, as built (Phase 5)

Section 7 set out the design. This records what was actually built and the two
places reality differed from the plan.

### The provider is swappable, and honest about itself

`OpenAIProvider` uses Structured Outputs with the strict schemas in
`prompts.py`. `LocalProvider` is a deterministic lexicon-and-extraction
analyser used whenever no API key is configured.

The local analyser is **not** presented as a language model. `/ai/status`
reports `is_local_fallback`, every stored insight carries its `provider` and
`model_id`, and the UI badges the panel "Offline analyser". A summary about a
person is not something to be vague about the provenance of.

> **Not verified against the live API.** There is no OpenAI key in this
> environment, so the OpenAI path is written to the documented Structured
> Outputs contract but has never made a real call. The verification suite runs
> against the local provider — deliberately, because the guarantees below must
> hold for *any* provider and can only be asserted repeatably against a
> deterministic one. Switching is `AI_ENABLED=true` plus a key; expect to
> shake out request/response details on first contact.

### Prompt injection: three layers, and one the plan missed

As designed:

1. **Structural separation** — respondent text never enters the instruction
   body. It goes in a fenced, numbered data block, and the fence markers are
   escaped out of the text so a comment cannot close the block early.
2. **A hard output contract** — strict JSON schema with
   `additionalProperties: false`. Prose produced instead of the schema fails
   rather than renders.
3. **Detection and flagging** — injection markers are recorded and audited
   (`ai.injection_detected`), not silently scrubbed. Someone trying to steer
   the model is an event an admin should see.

The fourth layer was not in the plan and was found by looking at the rendered
page rather than the test output:

4. **Excluded from summarisation.** Flagging alone let an injected comment be
   *quoted* into the summary's "consistently praised" list by the extractive
   summariser. The attacker failed to control the model and still got their
   text promoted into the most prominent part of a report about someone else.
   Text attempting to manipulate the analysis is not evidence about the
   subject, so it is now excluded from summarisation entirely — while
   remaining visible in the raw comment list and still counting toward the
   response total. The exclusion count is stored on the insight.

### The anonymity gate is stricter here than anywhere else

Elsewhere in the product, suppression means "collected but not shown". For
summaries it means **not generated at all**: nothing is sent to a provider and
no payload is stored. A stored summary of two anonymous comments is a
de-anonymising artefact sitting in a table, one bug or one export away from the
person it describes.

Two thresholds apply and the stricter wins: the round's own anonymity setting,
and a platform floor (`AI_MIN_RESPONSES_FOR_SUMMARY`, default 4) that holds
even for attributable rounds. The gate counts **written comments**, not
responses — a summary synthesises text, and synthesising three comments
reproduces them. Self-assessments never count toward it. `force=true` cannot
bypass it, which the verification asserts by calling the service directly
rather than through the route.

### Caching, cost and provenance

`ai_insights` is keyed by a digest of the exact prompt inputs plus model plus
prompt version. Same inputs mean the stored insight is reused; changing the
prompt version is what safely rolls out a prompt change. Sentiment lives in
columns on `feedback_responses` rather than in `ai_insights`, because it is
per-comment, high volume, and every aggregate wants to average it in SQL.

Per-organization monthly token budgets are enforced before any paid call. The
local provider is exempt, since budgeting a free operation only blocks it.

## 5f. Recommendations and prediction (Phase 6)

### The sufficiency gate

Section 7 warned that predictive analytics has a cold-start problem. In build
that became a hard control rather than a caveat.

> A win-probability model fitted to eight proposals will happily produce
> "73%". The number is arithmetically real and epistemically worthless. But it
> will be repeated in a pipeline review, because a percentage on a screen
> carries an authority that a sample size in a tooltip does not.

So every model asks `sufficiency` for permission and takes no for an answer.
There are three tests, and all three must pass:

1. **Enough samples** — 30 decided proposals for win probability, 3 rounds for
   a trend, 20 assignments for the disengagement signal.
2. **Enough of each outcome** — at least 8 wins *and* 8 losses. A model that
   has seen two losses knows nothing about losing.
3. **Lift over baseline** — the cross-validated score must beat always-guess-
   the-majority by 5 points. 82% accuracy where 80% of proposals are won is
   not a model, it is a coin that knows which way it usually lands.

A refusal is *stored*, with its reason, and returned by the API in place of a
number. There is no override flag, because an override flag is what someone
reaches for at 5pm before a board meeting.

Performance is always cross-validated and always reported next to its baseline.
Confidence is a coarse word — low / moderate / reasonable — rather than a
decimal interval, because a decimal interval gets read as precision by exactly
the audience least equipped to interpret it.

### Interpretable by choice

Logistic regression, with coefficients stored in the database rather than a
pickled estimator. On tenant-sized data a gradient-boosted anything overfits
beautifully, and a coefficient a human can read is worth more than a marginal
accuracy gain nobody can interrogate. Storing the maths rather than a binary
also avoids an artefact that must be versioned against the library that made
it.

The **disengagement signal is deliberately not a classifier.** Nobody records
"was about to resign", so there is no ground truth to train against; a
supervised model would be fitting to a target that does not exist. It is a
transparent weighted combination of observable behaviour, labelled a signal,
returned with the contributing factors so a manager can disagree with it.

### Recommendations: rules compute, the model only phrases

    Rules decide what to flag and compute every number.
    The language model, if there is one, only writes the sentence.

A pure-LLM recommender asked to "review this feedback and advise" produces
fluent advice containing invented figures — which then sit next to a dashboard
showing different ones. Catch that once and the whole surface loses credibility,
including the parts that were right.

So every finding carries `metric` and `evidence` computed in SQL, and the model
is handed the already-computed statements rather than the raw data, leaving it
nothing to invent from. The verification asserts that any figure quoted in a
finding's text also appears in that finding's own metric.

Findings are actionable by construction. "Engagement is trending down" is a
mood; "only 1 of 9 people have responded, so nothing will clear the anonymity
threshold" is a decision.

One rule is only computable because of the unified graph: loss reasons grouped
against the prospect's own rating. It surfaces the genuinely interesting case —
proposals lost on timeline that prospects nonetheless rated 4.4, meaning the
document was fine and something else killed the deal.

## 6. Immutability guarantees

Enforced by database triggers, not convention — "no role can edit this" has to
include a Client Admin with SQL access during an incident.

- `audit_logs` rejects `UPDATE` and `DELETE` outright.
- A **published** `feedback_template_versions` row rejects changes to its
  definition. Cycles pin a version, never a template, so editing a template
  next quarter cannot retroactively change what a respondent was asked last
  quarter. Getting this wrong silently corrupts trend reporting and is close to
  unrepairable after the fact.
- A submitted `feedback_responses` row rejects both `UPDATE` of its content and
  `DELETE` outright. A response is evidence; letting an administrator quietly
  rewrite what someone said about them defeats the point of collecting it.

---

## 7. AI design (Modules H, Phase 5+)

The four requested capabilities split into two different technical problems.

**LLM-suited — OpenAI:**

- **Sentiment** — per response: score, label, aspect tags, confidence. Cheap
  model, batched 20–30 comments per call, Structured Outputs with a strict
  schema.
- **Summaries** — map-reduce over responses. Frontier model; low volume, and
  quality matters more than cost.
- **Recommendations** — **hybrid**. Deterministic rules over the scores decide
  *what* to flag; the LLM writes the narrative. A pure-LLM recommender will
  hallucinate numbers that contradict the dashboard next to it.

**Not LLM-suited:**

- **Predictive analytics** — attrition risk, trend forecasting, win probability.
  This is scikit-learn / statsmodels over structured history. It also has a
  cold-start problem: it needs 2–3 completed cycles before it predicts anything
  meaningful, so it cannot ship early regardless of effort.

**Two guardrails, already reflected in the schema:**

1. **Respondent comments are untrusted input.** They flow into prompts, so a
   respondent can attempt prompt injection. Comments go in a delimited data
   section, never concatenated into the instruction body.
2. **AI summaries can de-anonymize.** A summary over 2 responses often lets the
   reviewee identify the authors. `min_responses_to_reveal` (default 4) is a
   column on every template and `AI_MIN_RESPONSES_FOR_SUMMARY` is a config
   floor. Anonymity that leaks under aggregation is not anonymity.

Supporting infrastructure: async jobs only, `ai_insights` cached on an input
hash, `model_id` + `prompt_version` recorded on every insight, `pgvector` for
theme clustering, per-org monthly token budget.

---

## 8. Design language

Deliberately not the pastel-purple, rounded, friendly look that Lattice, Culture
Amp, and 15Five all share — a buyer evaluating four tools in a week should not
have to check which tab they are on.

- **Ink navy + copper.** One high-chroma accent, tenant-overridable.
- **Editorial density.** Hairline borders instead of drop shadows, tight
  type scale, tabular numerals, data-dense tables.
- **A constant dark sidebar** in both themes, so the chrome stays put and only
  the content area changes.
- **The signature visual** is the feedback-graph ring on the dashboard and its
  animated counterpart on the sign-in screen. It states the positioning before a
  word is read, and it is the one thing no competitor's dashboard can show.
- Full light/dark support; tenant logo and accent applied to the shell, emails,
  and PDF exports.

---

## 9. What exists today

Verified by `scripts.verify` through `scripts.verify_phase6` — 260+ checks
between them, all passing, and stable across repeated runs. Every suite is self-contained: they create whatever
state they need rather than depending on untouched seed data, so they stay
runnable repeatedly.

**Phase 1:** tenancy + RLS, hardened auth with MFA and reuse detection, org
self-registration and Super Admin provisioning/approval/suspension, user
management and invitations, branding and logo upload, append-only audit trail,
the report registry with CSV/Excel/PDF and the filter engine, dashboard, and the
full UI shell.

**Phase 2:** template authoring (clone → draft → publish, immutable versions),
review cycles pinned to a version, assignment generation from the org chart
across self/downward/upward/peer, the reviewer's inbox and feedback form,
response capture with storage-level anonymity, results aggregation with
three-rule suppression, self-awareness gap, and two new reports (cycle
completion, feedback results) that inherit all three export formats.

**Phase 3:** external campaigns as external-audience cycles, contact and target
management, per-recipient one-time links, single and bulk send with the
tenant's branding, delivery funnel (sent → opened → responded), link revocation,
self-service unsubscribe, the standalone respondent page, and a campaign
delivery report with all three export formats.

**Phase 4:** proposals with commercial outcomes and structured loss reasons,
one-click prospect feedback requests, the proposal scorecard correlating
ratings with wins, reminders with cooldown/cap/escalation, and the expiry job.

**Phase 5:** sentiment with aspect tagging, map-reduce summaries, the four-layer
injection defence, the strict anonymity gate, insight caching with provenance,
per-org token budgets, and the AI panel on both the admin results view and the
subject's own results.

**Phase 6:** the sufficiency gate, win-probability model, score trend,
disengagement signal, the rule-based recommendation engine, and the Insights
screen that shows refusals as content rather than as empty panels.

**Not built:** a settings surface for reminder cadence, AI thresholds and model
minimums (all are arguments with defaults rather than per-organization
configuration), theme clustering over embeddings, and any model beyond the
three above. The dashboard and the Insights page both say what is missing
rather than showing empty charts.

### Revised phasing

| Phase | Contents | State |
|---|---|---|
| 1 | Foundation: auth, tenancy, onboarding, branding, audit, reports/export | **Done** |
| 2 | Templates (Module I), internal 360 (A), results and suppression | **Done** |
| 3 | Campaigns, respondent links, bulk send, delivery tracking (B) | **Done** |
| 4 | Proposal feedback and outcomes (C), reminders and escalation | **Done** |
| 5 | AI sentiment + summaries (H.1) | **Done** |
| 6 | Recommendations + predictive analytics (H.2) | **Done** |

All six phases of the original plan are built. What remains is productisation
rather than new capability: per-organization settings, real email delivery in
production, and the naming and packaging decisions in §10.

### One sharp edge worth knowing about

The tenancy GUCs are transaction-local, which is what stops them leaking across
pooled connections. The consequence is that a handler which commits and then
keeps reading loses its tenant context and silently sees zero rows. Handlers in
that position call `rebind_tenant(session, actor)`. It fails safe — the symptom
is missing data, never another tenant's data — but it is the one thing to
remember when adding a route.

---

## 10. Open questions still blocking

Carried from the functional spec, plus two the build surfaced:

1. ~~**Anonymity in internal 360**~~ — **resolved by construction.** Built as a
   per-template setting with genuine storage-level anonymity and three-rule
   suppression (§5a). Seeded defaults: upward feedback anonymous at a threshold
   of 4, peer review attributable. Confirm those defaults are the policy you
   want; the mechanism does not change either way.
2. ~~**Template scope**~~ — **built as vendor-authored globals that tenants
   clone.** Provided templates are read-only for tenants because they are
   shared by every customer. Confirm this is right for resale.
3. **Default rating scale** — currently a 1–5 Likert across the seeded library.
   Configurable per template; no global default is enforced.
4. **Peer cap** — assignment generation caps peers at 6 per reviewee, on the
   view that a 360 with thirty reviewers is a survey nobody finishes. Confirm.
5. CRM integration for Module C · pricing model · logo upload specs · audit
   retention period · **final product name**.
