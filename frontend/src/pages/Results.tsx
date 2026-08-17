import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'
import { FEEDBACK_TYPES } from './CreateFeedback'
import { Pagination } from '../components/DataTable'
import { IconSearch } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Modal, Skeleton, Spinner, StatTile } from '../components/ui'
import { useToast } from '../components/Toast'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { RELATIONSHIP_SHORT } from '../lib/cycleTypes'
import type { Relationship, TargetResults } from '../lib/cycleTypes'
import type { OrgDetail, Paged } from '../lib/types'
import { useAuth } from '../store/auth'

interface FeedbackListItem {
  id: string
  kind: string
  audience: string
  target_id: string | null
  target_label: string | null
  target_type: string | null
  template_name: string | null
  name: string
  status: string
  is_anonymous: boolean
  sent_at: string | null
  created_at: string
  closes_at: string | null
  total: number
  responded: number
  org_id: string | null
  org_name: string | null
  recipients: string[]
}

interface FeedbackResponseAnswer {
  key: string
  text: string
  type: string
  value: unknown
}

/** Five stars scaled to whatever the template's max actually is (not every
 * scale is 1-5), with a partial-fill star for a non-integer average. */
function StarRating({ value, max }: { value: number | null | undefined; max: number }) {
  if (value == null) return <span>—</span>
  const fraction = Math.max(0, Math.min(1, value / max)) * 5
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${value.toFixed(2)} out of ${max}`}>
      {Array.from({ length: 5 }, (_, index) => {
        const fill = Math.max(0, Math.min(1, fraction - index))
        return (
          <span key={index} className="relative inline-block h-6 w-6">
            <svg viewBox="0 0 20 20" className="absolute inset-0 h-full w-full text-ink-200 dark:text-ink-700" fill="currentColor">
              <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
            </svg>
            <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
              <svg viewBox="0 0 20 20" className="h-6 w-6 accent-text" fill="currentColor">
                <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
              </svg>
            </span>
          </span>
        )
      })}
    </span>
  )
}

interface Delivery {
  audience: 'external' | 'internal'
  total: number
  pending: number
  sent?: number
  opened?: number
  submitted: number
  unsubscribed?: number
  revoked?: number
  response_rate_pct?: number
  in_progress?: number
  declined?: number
  completion_pct?: number
}

interface FeedbackResponseItem {
  id: string
  respondent_name: string | null
  respondent_email: string | null
  relationship: Relationship
  is_anonymous: boolean
  submitted_at: string
  overall_score: number | null
  comment: string | null
  answers: FeedbackResponseAnswer[]
}

// Draft and Cancelled are internal states from the Cycles/Campaigns
// management pages — a round created through Create Feedback goes straight
// to Open, and closes automatically once everyone's responded, so results
// only ever need to be filtered by Open or Closed.
const STATUS_OPTIONS = ['open', 'closed']

const DATE_PRESETS: { value: string; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: 'last_30_days', label: 'Last 30 days' },
  { value: 'last_6_months', label: 'Last 6 months' },
  { value: 'last_12_months', label: 'Last year' },
  { value: 'custom', label: 'Custom range' },
]

const PAGE_SIZE = 15

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function ProgressBar({ total, responded }: { total: number; responded: number }) {
  const pct = total > 0 ? Math.round((responded / total) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
        <div className="accent-bg h-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular text-xs text-ink-500 dark:text-ink-400">
        {responded}/{total}
      </span>
    </div>
  )
}

/** The delivery funnel — sent → opened → responded — for an external round.
 * This is what the old, separate Campaigns page showed on each campaign
 * card; folded into the unified Results detail popup instead of living on
 * its own page. The send/chase button reuses the same `/campaigns/{id}/send`
 * endpoint that page called — a round created through the unified Create
 * Feedback flow is still a `ReviewCycle` with `audience=external` underneath,
 * so that endpoint works on it unchanged. */
function DeliveryFunnel({
  cycleId,
  status,
  delivery,
  onSent,
}: {
  cycleId: string
  status: string
  delivery: Delivery
  onSent: (updated: Delivery) => void
}) {
  const toast = useToast()
  const [sending, setSending] = useState(false)
  if (delivery.audience !== 'external') return null

  const stages = [
    { label: 'Sent', value: delivery.sent ?? 0, tone: 'bg-ink-300 dark:bg-ink-700' },
    { label: 'Opened', value: delivery.opened ?? 0, tone: 'bg-internal' },
    { label: 'Responded', value: delivery.submitted, tone: 'accent-bg' },
  ]
  const peak = Math.max(1, delivery.sent ?? 0)
  const hasPending = delivery.pending > 0
  const notYetResponded = (delivery.sent ?? 0) - delivery.submitted

  const send = async (resend: boolean) => {
    setSending(true)
    try {
      const result = await api.post<{ sent: number; failed: number; skipped: number }>(
        `/campaigns/${cycleId}/send`,
        { resend },
      )
      toast.show(
        'success',
        'Invitations sent',
        `${result.sent} invitation(s) sent` +
          (result.skipped ? `, ${result.skipped} skipped (unsubscribed)` : '') +
          (result.failed ? `, ${result.failed} failed` : '') +
          '.',
      )
      const updated = await api.get<Delivery>(`/feedback/${cycleId}/delivery`)
      onSent(updated)
    } catch (caught) {
      toast.show('critical', 'Sending failed', caught instanceof ApiError ? caught.message : undefined)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mb-5 rounded-lg border border-ink-200 p-4 dark:border-ink-700">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="label-caps">Delivery</p>
        {status === 'open' && (hasPending || notYetResponded > 0) && (
          <button
            type="button"
            className="btn-secondary px-2.5 py-1 text-xs"
            disabled={sending}
            onClick={() => send(hasPending)}
            title={
              hasPending
                ? undefined
                : 'Re-sending issues a fresh link and invalidates the previous one'
            }
          >
            {sending && <Spinner />}
            {hasPending
              ? `Send ${delivery.pending} invitation${delivery.pending === 1 ? '' : 's'}`
              : 'Chase non-responders'}
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-4">
        {stages.map((stage) => (
          <div key={stage.label} className="min-w-20">
            <p className="tabular text-2xl font-semibold text-ink-900 dark:text-ink-50">
              {stage.value}
            </p>
            <p className="label-caps">{stage.label}</p>
            <div className="mt-1 h-1 w-16 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
              <div
                className={clsx('h-full', stage.tone)}
                style={{ width: `${(stage.value / peak) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      {(delivery.pending > 0 || (delivery.unsubscribed ?? 0) > 0 || (delivery.revoked ?? 0) > 0) && (
        <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-2xs text-ink-400">
          {delivery.pending > 0 && <span>{delivery.pending} not yet sent</span>}
          {(delivery.unsubscribed ?? 0) > 0 && <span>{delivery.unsubscribed} unsubscribed</span>}
          {(delivery.revoked ?? 0) > 0 && <span>{delivery.revoked} revoked</span>}
        </p>
      )}
    </div>
  )
}

function AnswerValue({ answer }: { answer: FeedbackResponseAnswer }) {
  if (answer.value === null || answer.value === undefined || answer.value === '') {
    return <span className="text-ink-400">Not answered</span>
  }
  if (answer.type === 'boolean') {
    return <span>{answer.value ? 'Yes' : 'No'}</span>
  }
  if (answer.type === 'scale' && typeof answer.value === 'number') {
    return <span className="tabular font-semibold">{answer.value}</span>
  }
  return <span>{String(answer.value)}</span>
}

function ResultsDetailModal({ row, onClose }: { row: FeedbackListItem; onClose: () => void }) {
  const [data, setData] = useState<TargetResults | null>(null)
  const [responses, setResponses] = useState<FeedbackResponseItem[] | null>(null)
  const [delivery, setDelivery] = useState<Delivery | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<Delivery>(`/feedback/${row.id}/delivery`).then(setDelivery).catch(() => setDelivery(null))
    if (!row.target_id) {
      setError('This round has no recorded subject yet.')
      return
    }
    api
      .get<TargetResults>(`/cycles/${row.id}/results/${row.target_id}`)
      .then(setData)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load results.'),
      )
    api
      .get<FeedbackResponseItem[]>(`/feedback/${row.id}/responses`)
      .then(setResponses)
      .catch(() => setResponses([]))
  }, [row.id, row.target_id])

  return (
    <Modal title={row.name} hint={row.target_label ?? undefined} onClose={onClose} className="max-w-3xl">
      {delivery && (
        <DeliveryFunnel cycleId={row.id} status={row.status} delivery={delivery} onSent={setDelivery} />
      )}
      {error && <Banner tone="error">{error}</Banner>}
      {!error && !data && <Skeleton className="h-64 w-full rounded-lg" />}
      {data && data.found && (
        <>
          {/* Self assessment / self-awareness gap only mean anything where a
              self-review actually exists — that's the "Employees Review"
              kind alone (create_and_send() only sets include_self=True
              there; Management Review and every external kind never collect
              a self response, so these tiles would always read "—"). */}
          <div className={row.kind === 'employee' ? 'grid gap-3 sm:grid-cols-2 xl:grid-cols-4' : 'grid gap-3 sm:grid-cols-2'}>
            <StatTile
              label="Overall rating"
              value={<StarRating value={data.overall_average} max={data.scale?.max ?? 5} />}
              tone="accent"
              sub={
                data.overall_average != null
                  ? `${data.overall_average.toFixed(2)} out of ${data.scale?.max ?? 5}`
                  : `Out of ${data.scale?.max ?? 5}`
              }
            />
            {row.kind === 'employee' && (
              <>
                <StatTile
                  label="Self assessment"
                  value={data.self_average?.toFixed(2) ?? '—'}
                  sub={data.self_response_count ? 'Their own rating' : 'Not completed'}
                />
                <StatTile
                  label="Self-awareness gap"
                  value={
                    data.self_awareness_gap === null || data.self_awareness_gap === undefined
                      ? '—'
                      : `${data.self_awareness_gap > 0 ? '+' : ''}${data.self_awareness_gap.toFixed(2)}`
                  }
                  sub="Self minus others"
                />
              </>
            )}
            <StatTile label="Responses" value={data.response_count} />
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
            <p className="label-caps">Responses</p>
            <span className="text-2xs text-ink-400">
              {row.is_anonymous ? 'Anonymous template — identity hidden per response' : 'Not anonymous'}
            </span>
          </div>

          {!responses ? (
            <Skeleton className="mt-2 h-24 w-full rounded-lg" />
          ) : responses.length === 0 ? (
            <p className="mt-2 text-sm text-ink-400">No one has responded yet.</p>
          ) : (
            <ul className="mt-2 space-y-3">
              {responses.map((response) => (
                <li
                  key={response.id}
                  className="rounded-lg border border-ink-200 p-3.5 dark:border-ink-700"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink-900 dark:text-ink-50">
                        {response.respondent_name ?? 'Anonymous'}
                      </p>
                      {response.respondent_email && (
                        <p className="truncate text-2xs text-ink-400">{response.respondent_email}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-2xs text-ink-400">
                      <span className="rounded-full bg-ink-100 px-2 py-0.5 font-medium uppercase tracking-[0.06em] text-ink-500 dark:bg-ink-800 dark:text-ink-300">
                        {RELATIONSHIP_SHORT[response.relationship]}
                      </span>
                      <span>Responded {formatDateTime(response.submitted_at)}</span>
                    </div>
                  </div>

                  {response.answers.length > 0 && (
                    <ul className="mt-3 space-y-1.5 border-t border-ink-100 pt-3 dark:border-ink-800">
                      {response.answers.map((answer) => (
                        <li
                          key={answer.key}
                          className="flex flex-wrap items-center justify-between gap-2 text-sm"
                        >
                          <span className="text-ink-600 dark:text-ink-300">{answer.text}</span>
                          <AnswerValue answer={answer} />
                        </li>
                      ))}
                    </ul>
                  )}

                  {response.comment && (
                    <p className="mt-3 border-t border-ink-100 pt-3 text-sm leading-relaxed text-ink-700 dark:border-ink-800 dark:text-ink-200">
                      {response.comment}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {data && !data.found && <Banner tone="warning">That subject could not be found.</Banner>}
    </Modal>
  )
}

const KIND_LABEL: Record<string, string> = Object.fromEntries(
  FEEDBACK_TYPES.map((t) => [t.kind, t.label]),
)

export function Results() {
  const { user } = useAuth()
  const isPlatform = user?.role === 'super_admin'

  const [data, setData] = useState<Paged<FeedbackListItem> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<FeedbackListItem | null>(null)
  const [loading, setLoading] = useState(true)

  const [kindFilter, setKindFilter] = useState('')
  const [cycleNameFilter, setCycleNameFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [orgFilter, setOrgFilter] = useState('')
  const [datePreset, setDatePreset] = useState('all')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [page, setPage] = useState(1)

  const [orgs, setOrgs] = useState<OrgDetail[]>([])
  useEffect(() => {
    if (!isPlatform) return
    api
      .get<Paged<OrgDetail>>('/orgs?page_size=200')
      .then((result) => setOrgs(result.items))
      .catch(() => {})
  }, [isPlatform])

  const load = () => {
    setLoading(true)
    const query = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) })
    if (kindFilter) query.set('kind', kindFilter)
    if (cycleNameFilter) query.set('cycle_name', cycleNameFilter)
    if (statusFilter) query.set('status', statusFilter)
    if (orgFilter) query.set('org_id', orgFilter)
    if (datePreset !== 'all') query.set('date_preset', datePreset)
    if (datePreset === 'custom' && dateStart) query.set('date_start', dateStart)
    if (datePreset === 'custom' && dateEnd) query.set('date_end', dateEnd)
    api
      .get<Paged<FeedbackListItem>>(`/feedback?${query}`)
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load results.'),
      )
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    const timer = setTimeout(load, cycleNameFilter ? 250 : 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindFilter, cycleNameFilter, statusFilter, orgFilter, datePreset, dateStart, dateEnd, page])

  const filtersActive = useMemo(
    () => Boolean(kindFilter || cycleNameFilter || statusFilter || orgFilter || datePreset !== 'all'),
    [kindFilter, cycleNameFilter, statusFilter, orgFilter, datePreset],
  )

  const resetFilters = () => {
    setKindFilter('')
    setCycleNameFilter('')
    setStatusFilter('')
    setOrgFilter('')
    setDatePreset('all')
    setDateStart('')
    setDateEnd('')
    setPage(1)
  }

  const rows = data?.items ?? []

  return (
    <>
      <PageHeader title="Results" />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Feedback type
            </span>
            <select
              className="field"
              value={kindFilter}
              onChange={(event) => {
                setKindFilter(event.target.value)
                setPage(1)
              }}
            >
              <option value="">All types</option>
              {FEEDBACK_TYPES.map((t) => (
                <option key={t.kind} value={t.kind}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>

          <Field
            label="Cycle name"
            value={cycleNameFilter}
            onChange={(event) => {
              setCycleNameFilter(event.target.value)
              setPage(1)
            }}
            placeholder="Search by cycle name"
          />

          {isPlatform && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Organization
              </span>
              <select
                className="field"
                value={orgFilter}
                onChange={(event) => {
                  setOrgFilter(event.target.value)
                  setPage(1)
                }}
              >
                <option value="">All organizations</option>
                {orgs.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Status
            </span>
            <select
              className="field"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value)
                setPage(1)
              }}
            >
              <option value="">Any status</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Date range
            </span>
            <select
              className="field"
              value={datePreset}
              onChange={(event) => {
                setDatePreset(event.target.value)
                setPage(1)
              }}
            >
              {DATE_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>

          {datePreset === 'custom' && (
            <div className="grid grid-cols-2 gap-2">
              <Field
                label="From"
                type="date"
                value={dateStart}
                onChange={(event) => {
                  setDateStart(event.target.value)
                  setPage(1)
                }}
              />
              <Field
                label="To"
                type="date"
                value={dateEnd}
                onChange={(event) => {
                  setDateEnd(event.target.value)
                  setPage(1)
                }}
              />
            </div>
          )}
        </div>

        {filtersActive && (
          <button
            type="button"
            className="mt-3 text-xs text-ink-400 underline hover:text-ink-700 dark:hover:text-ink-100"
            onClick={resetFilters}
          >
            Clear filters
          </button>
        )}
      </Card>

      {loading && !data ? (
        <Skeleton className="h-64 w-full rounded-lg" />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconSearch width={19} height={19} />}
            title="Nothing here yet"
            body={filtersActive ? 'Nothing matches these filters.' : 'Create some feedback to see it show up here.'}
          />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>About</th>
                  <th>Recipients</th>
                  {isPlatform && <th>Organization</th>}
                  <th>Template</th>
                  <th>Sent</th>
                  <th>Progress</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-800/60"
                    onClick={() => setSelected(row)}
                  >
                    <td className="font-medium text-ink-900 dark:text-ink-50">{row.name}</td>
                    <td>{KIND_LABEL[row.kind] ?? row.kind}</td>
                    <td className="text-ink-600 dark:text-ink-300">
                      {row.target_label ?? '—'}
                    </td>
                    <td
                      className="max-w-[220px] truncate text-ink-600 dark:text-ink-300"
                      title={row.recipients.join(', ') || undefined}
                    >
                      {row.recipients.length === 0
                        ? '—'
                        : row.recipients.length === 1
                          ? row.recipients[0]
                          : `${row.recipients[0]} +${row.recipients.length - 1} more`}
                    </td>
                    {isPlatform && (
                      <td className="text-ink-600 dark:text-ink-300">{row.org_name ?? '—'}</td>
                    )}
                    <td className="text-ink-600 dark:text-ink-300">
                      {row.template_name ?? '—'}
                    </td>
                    <td className="text-ink-500 dark:text-ink-400">
                      {row.sent_at ? new Date(row.sent_at).toLocaleDateString() : '—'}
                    </td>
                    <td>
                      <ProgressBar total={row.total} responded={row.responded} />
                    </td>
                    <td>
                      <Chip value={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data && data.total > 0 && (
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          )}
        </Card>
      )}

      {selected && <ResultsDetailModal row={selected} onClose={() => setSelected(null)} />}
    </>
  )
}
