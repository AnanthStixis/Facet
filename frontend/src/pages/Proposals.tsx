import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconCheck, IconFile, IconSend, IconSpark } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Skeleton, Spinner, StatTile } from '../components/ui'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { Paged } from '../lib/types'

interface Proposal {
  id: string
  reference: string
  title: string
  client_name: string
  summary: string | null
  stage: string
  currency: string
  value_amount: string | null
  won_amount: string | null
  value_variance: string | null
  estimated_effort_days: number | null
  prospect_contact_id: string | null
  prospect_contact_name: string | null
  author_name: string | null
  submitted_at: string | null
  decision_due_on: string | null
  decided_at: string | null
  loss_reason: string | null
  competitor: string | null
  outcome_note: string | null
  target_id: string | null
  feedback_requested: boolean
  feedback_responses: number
  feedback_average: number | null
}

interface Summary {
  total: number
  open_value: string
  won_value: string
  by_stage: Record<string, number>
  win_rate_pct: number
  feedback_coverage_pct: number
}

interface Contact {
  id: string
  full_name: string
  email: string
  company: string | null
  unsubscribed_at: string | null
}

const LOSS_REASONS = [
  { value: 'price', label: 'Price' },
  { value: 'timeline', label: 'Timeline' },
  { value: 'technical_fit', label: 'Technical fit' },
  { value: 'relationship', label: 'Relationship' },
  { value: 'incumbent', label: 'Incumbent supplier' },
  { value: 'scope_mismatch', label: 'Scope mismatch' },
  { value: 'no_decision', label: 'No decision made' },
  { value: 'other', label: 'Other' },
]

const CURRENCIES = ['USD', 'EUR', 'GBP', 'INR', 'AED', 'AUD', 'CAD', 'SGD']

const money = (amount: string | null, currency = 'USD') =>
  amount === null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency,
        maximumFractionDigits: 0,
      }).format(Number(amount))

/** Colour a prospect score by band, so the pipeline is scannable. */
function ScorePill({ score }: { score: number | null }) {
  if (score === null) {
    return <span className="text-2xs text-ink-400">No response</span>
  }
  return (
    <span
      className={clsx(
        'tabular rounded-md px-2 py-0.5 text-sm font-semibold',
        score >= 4 && 'bg-positive/10 text-positive',
        score >= 3 && score < 4 && 'bg-caution/12 text-caution',
        score < 3 && 'bg-critical/10 text-critical',
      )}
    >
      {score.toFixed(2)}
    </span>
  )
}

function OutcomeForm({
  proposal,
  onDone,
  onCancel,
}: {
  proposal: Proposal
  onDone: (message: string) => void
  onCancel: () => void
}) {
  const [stage, setStage] = useState<'won' | 'lost' | 'withdrawn'>('won')
  const [lossReason, setLossReason] = useState('price')
  const [wonAmount, setWonAmount] = useState(proposal.value_amount ?? '')
  const [competitor, setCompetitor] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <form
      className="mt-4 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60"
      onSubmit={async (event) => {
        event.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await api.post(`/proposals/${proposal.id}/outcome`, {
            stage,
            loss_reason: stage === 'lost' ? lossReason : null,
            won_amount: stage === 'won' && wonAmount ? wonAmount : null,
            competitor: competitor || null,
            outcome_note: note || null,
          })
          onDone(`${proposal.reference} recorded as ${stage}.`)
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : 'Could not record the outcome.')
          setBusy(false)
        }
      }}
    >
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <p className="mb-3 text-sm text-ink-600 dark:text-ink-300">
        Recording the real outcome is what turns a prospect's rating into
        something you can act on.
      </p>

      <div className="mb-3 flex gap-2">
        {(['won', 'lost', 'withdrawn'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setStage(option)}
            className={clsx(
              'rounded-md border px-3 py-1.5 text-sm capitalize transition-colors',
              stage === option
                ? 'accent-bg border-transparent text-white'
                : 'border-ink-200 text-ink-600 dark:border-ink-700 dark:text-ink-300',
            )}
          >
            {option}
          </button>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {stage === 'won' && (
          <Field
            label="Signed value"
            type="number"
            step="0.01"
            min={0}
            value={wonAmount}
            onChange={(event) => setWonAmount(event.target.value)}
            hint="The gap against the proposed value is itself a signal."
          />
        )}
        {stage === 'lost' && (
          <>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Lost because
              </span>
              <select
                className="field"
                value={lossReason}
                onChange={(event) => setLossReason(event.target.value)}
              >
                {LOSS_REASONS.map((reason) => (
                  <option key={reason.value} value={reason.value}>
                    {reason.label}
                  </option>
                ))}
              </select>
              {/* Structured, because the whole value of this field is being
                  able to group by it later. */}
              <span className="mt-1 block text-xs text-ink-400">
                Grouped in the scorecard.
              </span>
            </label>
            <Field
              label="Lost to (optional)"
              value={competitor}
              onChange={(event) => setCompetitor(event.target.value)}
            />
          </>
        )}
        <Field
          label="Note (optional)"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>

      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
          {busy && <Spinner />}
          Record outcome
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function CreateProposal({ onCreated }: { onCreated: (message: string) => void }) {
  const [open, setOpen] = useState(false)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [form, setForm] = useState({
    title: '',
    client_name: '',
    currency: 'USD',
    value_amount: '',
    estimated_effort_days: '',
    prospect_contact_id: '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    api
      .get<Paged<Contact>>('/contacts?page_size=200')
      .then((page) => setContacts(page.items))
      .catch(() => setContacts([]))
  }, [open])

  if (!open) {
    return (
      <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setOpen(true)}>
        Record proposal
      </button>
    )
  }

  return (
    <Card className="mb-5" title="Record a proposal" hint="Enough to ask for feedback and to record what happened. This is not a CRM.">
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setError(null)
          try {
            await api.post('/proposals', {
              title: form.title,
              client_name: form.client_name,
              currency: form.currency,
              value_amount: form.value_amount || null,
              estimated_effort_days: form.estimated_effort_days
                ? Number(form.estimated_effort_days)
                : null,
              prospect_contact_id: form.prospect_contact_id || null,
            })
            onCreated(`${form.title} recorded as a draft.`)
            setOpen(false)
            setForm({
              title: '',
              client_name: '',
              currency: 'USD',
              value_amount: '',
              estimated_effort_days: '',
              prospect_contact_id: '',
            })
          } catch (caught) {
            setError(caught instanceof ApiError ? caught.message : 'Could not record it.')
          } finally {
            setBusy(false)
          }
        }}
      >
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field
            label="Title"
            value={form.title}
            onChange={(event) => setForm({ ...form, title: event.target.value })}
            required
            minLength={3}
            className="lg:col-span-2"
          />
          <Field
            label="Client"
            value={form.client_name}
            onChange={(event) => setForm({ ...form, client_name: event.target.value })}
            required
          />
          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Value
            </span>
            <div className="flex gap-1.5">
              <select
                className="field w-24 shrink-0"
                value={form.currency}
                onChange={(event) => setForm({ ...form, currency: event.target.value })}
              >
                {CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                step="1000"
                className="field"
                value={form.value_amount}
                onChange={(event) => setForm({ ...form, value_amount: event.target.value })}
              />
            </div>
          </div>
          <Field
            label="Effort (days)"
            type="number"
            min={0}
            value={form.estimated_effort_days}
            onChange={(event) =>
              setForm({ ...form, estimated_effort_days: event.target.value })
            }
          />
        </div>
        <label className="mt-3 block max-w-sm">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Prospect contact
          </span>
          <select
            className="field"
            value={form.prospect_contact_id}
            onChange={(event) =>
              setForm({ ...form, prospect_contact_id: event.target.value })
            }
          >
            <option value="">Choose who to ask later</option>
            {contacts
              .filter((contact) => contact.unsubscribed_at === null)
              .map((contact) => (
                <option key={contact.id} value={contact.id}>
                  {contact.full_name}
                  {contact.company ? ` — ${contact.company}` : ''}
                </option>
              ))}
          </select>
        </label>
        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Save draft
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  )
}

const STAGE_TABS = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'won', label: 'Won' },
  { value: 'lost', label: 'Lost' },
]

const PAGE_SIZE = 15

export function Proposals() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [proposals, setProposals] = useState<Proposal[] | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [stage, setStage] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [outcomeFor, setOutcomeFor] = useState<string | null>(null)

  // The dismiss button is easy to miss, and a confirmation that only goes
  // away on a manual click (or a reload) reads as "did that actually work?"
  // after a few seconds. Auto-clear it; the dismiss button still works for
  // anyone who wants it gone sooner.
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 6000)
    return () => window.clearTimeout(timer)
  }, [notice])
  const [busyId, setBusyId] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const load = () => {
    const query = new URLSearchParams()
    if (stage) query.set('stage', stage)
    if (search) query.set('search', search)
    api
      .get<Proposal[]>(`/proposals?${query}`)
      .then(setProposals)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load proposals.'),
      )
    api.get<Summary>('/proposals/summary').then(setSummary).catch(() => {})
  }

  useEffect(load, [stage, search])
  useEffect(() => setPage(1), [stage, search])
  useRefetchOnFocus(load)

  const act = async (proposal: Proposal, action: 'submit' | 'request-feedback') => {
    setBusyId(proposal.id)
    setError(null)
    try {
      if (action === 'submit') {
        await api.post(`/proposals/${proposal.id}/submit`)
        setNotice(`${proposal.reference} marked as submitted.`)
      } else {
        const result = await api.post<{ sent: boolean; contact: string }>(
          `/proposals/${proposal.id}/request-feedback`,
          {},
        )
        setNotice(
          result.sent
            ? `Feedback request sent to ${result.contact}.`
            : `Request created, but the email to ${result.contact} could not be sent.`,
        )
      }
      load()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That did not work.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Proposals"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Proposals and SOWs, the prospect's view of them, and what actually happened. The last part is what makes the first two worth collecting."
        actions={<CreateProposal onCreated={(message) => { setNotice(message); load() }} />}
      />

      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          {notice}
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Banner>
      )}

      {summary && (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Win rate"
            value={`${summary.win_rate_pct}%`}
            tone="accent"
            sub="Of decided proposals"
          />
          <StatTile label="Open pipeline" value={money(summary.open_value)} sub="Awaiting a decision" />
          <StatTile label="Won this period" value={money(summary.won_value)} sub="Signed value" />
          <StatTile
            label="Feedback coverage"
            value={`${summary.feedback_coverage_pct}%`}
            tone={summary.feedback_coverage_pct < 50 ? 'caution' : 'neutral'}
            sub="Submitted proposals surveyed"
          />
        </div>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="flex flex-wrap gap-1">
            {STAGE_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setStage(tab.value)}
                className={
                  stage === tab.value
                    ? 'rounded-md accent-soft-bg px-2.5 py-1 text-xs font-medium accent-text'
                    : 'rounded-md px-2.5 py-1 text-xs text-ink-500 hover:bg-ink-100 dark:hover:bg-ink-800'
                }
              >
                {tab.label}
                {summary?.by_stage[tab.value] ? ` (${summary.by_stage[tab.value]})` : ''}
              </button>
            ))}
          </div>
          <div className="ml-auto min-w-[200px]">
            <SearchBox value={search} onChange={setSearch} placeholder="Search proposals" />
          </div>
        </div>

        {!proposals ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full" />
            ))}
          </div>
        ) : proposals.length === 0 ? (
          <EmptyState
            icon={<IconFile width={19} height={19} />}
            title="No proposals here"
            body="Record one to start tracking how prospects rate what you send them."
          />
        ) : (
          <ul className="divide-y divide-ink-200 dark:divide-ink-800">
            {proposals.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((proposal) => (
              <li key={proposal.id} className="px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-2xs text-ink-400">
                        {proposal.reference}
                      </span>
                      <span className="text-base font-semibold text-ink-900 dark:text-ink-50">
                        {proposal.title}
                      </span>
                      <Chip value={proposal.stage} />
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500 dark:text-ink-400">
                      <span>{proposal.client_name}</span>
                      <span className="tabular">
                        {money(proposal.value_amount, proposal.currency)}
                      </span>
                      {proposal.won_amount && (
                        <span className="tabular text-positive">
                          signed {money(proposal.won_amount, proposal.currency)}
                        </span>
                      )}
                      {proposal.author_name && <span>by {proposal.author_name}</span>}
                      {proposal.loss_reason && (
                        <span className="text-critical">
                          lost: {proposal.loss_reason.replace(/_/g, ' ')}
                          {proposal.competitor ? ` to ${proposal.competitor}` : ''}
                        </span>
                      )}
                    </p>
                  </div>

                  {/* The two numbers side by side. This pairing is the entire
                      argument for the module. */}
                  <div className="flex shrink-0 items-center gap-5">
                    <div className="text-right">
                      <p className="label-caps">Prospect score</p>
                      <div className="mt-0.5">
                        <ScorePill score={proposal.feedback_average} />
                      </div>
                      {proposal.feedback_responses > 0 && (
                        <p className="mt-0.5 text-2xs text-ink-400">
                          {proposal.feedback_responses} response
                          {proposal.feedback_responses === 1 ? '' : 's'}
                        </p>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {proposal.stage === 'draft' && (
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          disabled={busyId === proposal.id}
                          onClick={() => act(proposal, 'submit')}
                        >
                          {busyId === proposal.id && <Spinner />}
                          Mark submitted
                        </button>
                      )}
                      {proposal.stage !== 'draft' && !proposal.feedback_requested && (
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          disabled={busyId === proposal.id || !proposal.prospect_contact_id}
                          title={
                            proposal.prospect_contact_id
                              ? 'Email the prospect a one-time feedback link'
                              : 'Record a prospect contact first'
                          }
                          onClick={() => act(proposal, 'request-feedback')}
                        >
                          {busyId === proposal.id && <Spinner />}
                          <IconSend width={14} height={14} />
                          Ask the prospect
                        </button>
                      )}
                      {proposal.feedback_requested &&
                        proposal.feedback_responses === 0 && (
                          <span className="flex items-center gap-1 text-2xs text-ink-400">
                            <IconSend width={12} height={12} />
                            Awaiting reply
                          </span>
                        )}
                      {['submitted', 'shortlisted'].includes(proposal.stage) &&
                        (outcomeFor === proposal.id ? null : (
                          <button
                            type="button"
                            className="btn-secondary px-3 py-1.5 text-sm"
                            onClick={() => setOutcomeFor(proposal.id)}
                          >
                            Record outcome
                          </button>
                        ))}
                      {['won', 'lost', 'withdrawn'].includes(proposal.stage) && (
                        <span className="flex items-center gap-1 text-2xs text-ink-400">
                          <IconCheck width={12} height={12} />
                          Decided
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {outcomeFor === proposal.id && (
                  <OutcomeForm
                    proposal={proposal}
                    onCancel={() => setOutcomeFor(null)}
                    onDone={(message) => {
                      setOutcomeFor(null)
                      setNotice(message)
                      load()
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
        {proposals && proposals.length > 0 && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={proposals.length} onPage={setPage} />
        )}
      </Card>

      <Banner tone="info" className="mt-5">
        <span className="flex flex-wrap items-center gap-x-1.5">
          <IconSpark width={14} height={14} />
          Open <strong>Reports &rarr; Proposal scorecard</strong> to see prospect
          ratings beside actual outcomes — whether the proposals that score well
          are the ones you win.
        </span>
      </Banner>
    </>
  )
}
