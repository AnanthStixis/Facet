import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { LookupFilter } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconClock, IconLayers, IconLock } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Skeleton, Spinner } from '../components/ui'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { Cycle } from '../lib/cycleTypes'
import { RELATIONSHIP_SHORT } from '../lib/cycleTypes'
import type { Relationship } from '../lib/cycleTypes'
import { CycleResults } from './CycleResults'

interface TemplateOption {
  id: string
  name: string
  status: string | null
  target_type: string
  is_anonymous: boolean
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
        <div className="accent-bg h-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular text-xs text-ink-500 dark:text-ink-400">{pct}%</span>
    </div>
  )
}

const DIRECTIONS: { key: 'include_self' | 'include_manager' | 'include_upward' | 'include_peers'; label: string; hint: string }[] = [
  { key: 'include_self', label: 'Self', hint: 'Each reviewee also reviews themselves.' },
  { key: 'include_manager', label: 'Manager', hint: "Each reviewee's manager reviews them." },
  { key: 'include_upward', label: 'Upward', hint: 'Direct reports review their manager.' },
  { key: 'include_peers', label: 'Peers', hint: 'Peers on the same team review each other (capped at 6).' },
]

function CreateCycle({ onCreated }: { onCreated: (cycle: Cycle) => void }) {
  const [open, setOpen] = useState(false)
  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [form, setForm] = useState({ name: '', template_id: '', closes_at: '' })
  const [reviewees, setReviewees] = useState<string[]>([])
  const [plan, setPlan] = useState({
    include_self: true,
    include_manager: true,
    include_upward: false,
    include_peers: false,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    api
      .get<{ templates: TemplateOption[] }[]>('/catalog/categories')
      .then((categories) =>
        setTemplates(
          categories
            .flatMap((category) => category.templates)
            // Only published templates can back a cycle, so offering a draft
            // would just produce a 409 after the user has filled the form in.
            .filter((template) => template.status === 'published'),
        ),
      )
      .catch(() => setTemplates([]))
  }, [open])

  if (!open) {
    return (
      <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setOpen(true)}>
        New cycle
      </button>
    )
  }

  const reset = () => {
    setOpen(false)
    setForm({ name: '', template_id: '', closes_at: '' })
    setReviewees([])
  }

  // One click: create the cycle, generate its assignments from the org chart,
  // and open it — the three-step draft workflow underneath still exists (a
  // manager can always add more reviewees or hold a cycle in draft), but
  // nobody should have to do all three separately just to start a round.
  const createAndOpen = async () => {
    if (reviewees.length === 0) {
      setError('Add at least one person to review before opening — or create it as a draft.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const cycle = await api.post<Cycle>('/cycles', {
        name: form.name,
        template_id: form.template_id,
        closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : null,
      })
      await api.post(`/cycles/${cycle.id}/assignments`, { ...plan, reviewee_ids: reviewees })
      const opened = await api.post<Cycle>(`/cycles/${cycle.id}/open`)
      onCreated(opened)
      reset()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not create and open the cycle.')
    } finally {
      setBusy(false)
    }
  }

  const createAsDraft = async () => {
    setBusy(true)
    setError(null)
    try {
      const cycle = await api.post<Cycle>('/cycles', {
        name: form.name,
        template_id: form.template_id,
        closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : null,
      })
      onCreated(cycle)
      reset()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not create the cycle.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-5" title="New review cycle">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void createAndOpen()
        }}
      >
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            label="Cycle name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="H2 2026 Manager Effectiveness"
            required
            minLength={3}
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Template
            </span>
            <select
              className="field"
              required
              value={form.template_id}
              onChange={(event) => setForm({ ...form, template_id: event.target.value })}
            >
              <option value="">Choose a published template</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                  {template.is_anonymous ? ' (anonymous)' : ''}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-ink-400">
              The cycle pins this exact version, so later edits cannot change it.
            </span>
          </label>
          <Field
            label="Closes on (optional)"
            type="date"
            value={form.closes_at}
            onChange={(event) => setForm({ ...form, closes_at: event.target.value })}
            hint="Leave blank to collect feedback with no deadline."
          />
        </div>

        <div className="mt-4">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Who is being reviewed (optional — add people now to open immediately)
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <LookupFilter
              entity="users"
              label="People to review"
              selected={reviewees}
              onChange={setReviewees}
            />
            {DIRECTIONS.map((direction) => (
              <button
                key={direction.key}
                type="button"
                title={direction.hint}
                onClick={() =>
                  setPlan((current) => ({ ...current, [direction.key]: !current[direction.key] }))
                }
                className={clsx(
                  'rounded-md border px-2.5 py-1.5 text-xs transition-colors',
                  plan[direction.key]
                    ? 'accent-border accent-text accent-soft-bg'
                    : 'border-ink-200 text-ink-500 dark:border-ink-700',
                )}
              >
                {direction.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Create and open
          </button>
          <button
            type="button"
            className="btn-secondary px-3 py-1.5"
            disabled={busy}
            onClick={() => void createAsDraft()}
          >
            Create as draft instead
          </button>
          <button type="button" className="btn-ghost px-3 py-1.5" onClick={reset}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  )
}

function AssignmentPlanner({
  cycle,
  onDone,
}: {
  cycle: Cycle
  onDone: (message: string) => void
}) {
  const [reviewees, setReviewees] = useState<string[]>([])
  const [plan, setPlan] = useState({
    include_self: true,
    include_manager: true,
    include_upward: true,
    include_peers: true,
    max_peers: 6,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  const directions: { key: keyof typeof plan; label: string; hint: string }[] = [
    { key: 'include_self', label: 'Self', hint: 'The person rates themselves' },
    { key: 'include_manager', label: 'Downward', hint: 'Their manager reviews them' },
    { key: 'include_upward', label: 'Upward', hint: 'Their direct reports review them' },
    { key: 'include_peers', label: 'Peers', hint: 'Colleagues sharing a manager' },
  ]

  return (
    <div className="mt-4 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60">
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      {warnings.length > 0 && (
        <Banner tone="warning" className="mb-3" onDismiss={() => setWarnings([])}>
          <ul className="list-disc pl-4">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Banner>
      )}

      <p className="mb-3 text-sm text-ink-600 dark:text-ink-300">
        Choose who is being reviewed. Reviewers are worked out from the org chart —
        running this again only adds what is missing.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <LookupFilter
          entity="users"
          label="People to review"
          selected={reviewees}
          onChange={setReviewees}
        />
        {directions.map((direction) => (
          <button
            key={direction.key}
            type="button"
            title={direction.hint}
            onClick={() =>
              setPlan((current) => ({ ...current, [direction.key]: !current[direction.key] }))
            }
            className={clsx(
              'rounded-md border px-2.5 py-1.5 text-xs transition-colors',
              plan[direction.key]
                ? 'accent-border accent-text accent-soft-bg'
                : 'border-ink-200 text-ink-500 dark:border-ink-700',
            )}
          >
            {direction.label}
          </button>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          disabled={busy || reviewees.length === 0}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              const result = await api.post<{
                created: number
                skipped_existing: number
                by_relationship: Record<string, number>
                warnings: string[]
              }>(`/cycles/${cycle.id}/assignments`, { ...plan, reviewee_ids: reviewees })
              setWarnings(result.warnings)
              const breakdown = Object.entries(result.by_relationship)
                .map(([key, count]) => `${count} ${RELATIONSHIP_SHORT[key as Relationship] ?? key}`)
                .join(', ')
              onDone(
                `${result.created} assignment(s) created${breakdown ? ` — ${breakdown}` : ''}` +
                  (result.skipped_existing ? `. ${result.skipped_existing} already existed.` : '.'),
              )
            } catch (caught) {
              setError(caught instanceof ApiError ? caught.message : 'Generation failed.')
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy && <Spinner />}
          Generate assignments
        </button>
      </div>
    </div>
  )
}

const PAGE_SIZE = 15

export function Cycles() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [cycles, setCycles] = useState<Cycle[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // The dismiss button is easy to miss, and a confirmation that only goes
  // away on a manual click (or a reload) reads as "did that actually work?"
  // after a few seconds. Auto-clear it; the dismiss button still works for
  // anyone who wants it gone sooner.
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 6000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const [planning, setPlanning] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [viewing, setViewing] = useState<Cycle | null>(null)
  const [page, setPage] = useState(1)

  const load = () => {
    api
      .get<Cycle[]>('/cycles')
      .then(setCycles)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load cycles.'),
      )
  }

  useEffect(load, [])
  useRefetchOnFocus(load)

  if (viewing) {
    return <CycleResults cycle={viewing} onBack={() => setViewing(null)} />
  }

  const act = async (cycle: Cycle, action: 'open' | 'close') => {
    setError(null)
    try {
      await api.post(`/cycles/${cycle.id}/${action}`)
      setConfirming(null)
      setNotice(
        action === 'open'
          ? `'${cycle.name}' is open. Reviewers can now see it in My feedback.`
          : `'${cycle.name}' is closed. Results are final.`,
      )
      load()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That did not work.')
    }
  }

  return (
    <>
      <PageHeader
        title="Review cycles"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="A cycle asks a set of people for feedback about a set of colleagues, using one pinned template version."
        actions={
          <CreateCycle
            onCreated={(cycle) => {
              if (cycle.status === 'draft') {
                setNotice(`'${cycle.name}' created as a draft. Add assignments next.`)
                setPlanning(cycle.id)
              } else {
                setNotice(`'${cycle.name}' is open. Reviewers can now see it in My feedback.`)
              }
              load()
            }}
          />
        }
      />

      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          {notice}
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {!cycles ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full rounded-lg" />
          ))}
        </div>
      ) : cycles.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconLayers width={19} height={19} />}
            title="No cycles yet"
            body="Create one from a published template to start collecting feedback."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {cycles.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((cycle) => (
            <Card key={cycle.id}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold text-ink-900 dark:text-ink-50">
                      {cycle.name}
                    </span>
                    <Chip value={cycle.status} />
                    {cycle.is_anonymous && (
                      <span className="chip accent-soft-bg accent-text flex items-center gap-1">
                        <IconLock width={10} height={10} />
                        Hidden below {cycle.min_responses_to_reveal}
                      </span>
                    )}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500 dark:text-ink-400">
                    <span>
                      {cycle.template_name}
                      {cycle.template_version ? ` v${cycle.template_version}` : ''}
                    </span>
                    {cycle.closes_at && (
                      <span className="flex items-center gap-1">
                        <IconClock width={12} height={12} />
                        Closes {new Date(cycle.closes_at).toLocaleDateString()}
                      </span>
                    )}
                    <span className="tabular">
                      {cycle.progress.submitted}/{cycle.progress.total} responses
                    </span>
                    {cycle.created_by_name && <span>Created by {cycle.created_by_name}</span>}
                  </p>
                  {cycle.progress.total > 0 && (
                    <div className="mt-2">
                      <ProgressBar pct={cycle.progress.completion_pct} />
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 flex-wrap gap-2">
                  {cycle.status === 'draft' && (
                    <>
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-sm"
                        onClick={() =>
                          setPlanning(planning === cycle.id ? null : cycle.id)
                        }
                      >
                        {planning === cycle.id ? 'Hide' : 'Assignments'}
                      </button>
                      {confirming === cycle.id ? (
                        <span className="flex gap-1.5">
                          <button
                            type="button"
                            className="btn-primary px-2.5 py-1.5 text-sm"
                            onClick={() => act(cycle, 'open')}
                          >
                            Confirm open
                          </button>
                          <button
                            type="button"
                            className="btn-secondary px-2.5 py-1.5 text-sm"
                            onClick={() => setConfirming(null)}
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          onClick={() => setConfirming(cycle.id)}
                        >
                          Open cycle
                        </button>
                      )}
                    </>
                  )}

                  {cycle.status === 'open' &&
                    (confirming === cycle.id ? (
                      <span className="flex gap-1.5">
                        <button
                          type="button"
                          className="btn-danger px-2.5 py-1.5 text-sm"
                          onClick={() => act(cycle, 'close')}
                        >
                          Confirm close
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1.5 text-sm"
                          onClick={() => setConfirming(null)}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-sm"
                        onClick={() => setConfirming(cycle.id)}
                      >
                        Close cycle
                      </button>
                    ))}

                  {cycle.status !== 'closed' &&
                    cycle.progress.submitted === 0 &&
                    (deleting === cycle.id ? (
                      <span className="flex gap-1.5">
                        <button
                          type="button"
                          className="btn-danger px-2.5 py-1.5 text-sm"
                          onClick={async () => {
                            try {
                              await api.delete(`/cycles/${cycle.id}`)
                              setDeleting(null)
                              setNotice(`'${cycle.name}' deleted.`)
                              load()
                            } catch (caught) {
                              setError(
                                caught instanceof ApiError ? caught.message : 'Could not delete that cycle.',
                              )
                              setDeleting(null)
                            }
                          }}
                        >
                          Confirm delete
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1.5 text-sm"
                          onClick={() => setDeleting(null)}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn-ghost px-3 py-1.5 text-sm"
                        onClick={() => setDeleting(cycle.id)}
                      >
                        Delete
                      </button>
                    ))}

                  {/* Any round that has left draft can have results worth
                      looking at. Gating on submitted *assignments* hid the
                      results of rounds whose responses arrived another way —
                      an import, or a fixture — which is a confusing dead end.
                      The results page handles an empty round on its own. */}
                  {cycle.status !== 'draft' && (
                    <button
                      type="button"
                      className="btn-primary px-3 py-1.5 text-sm"
                      onClick={() => setViewing(cycle)}
                    >
                      Results
                    </button>
                  )}
                </div>
              </div>

              {planning === cycle.id && (
                <AssignmentPlanner
                  cycle={cycle}
                  onDone={(message) => {
                    setNotice(message)
                    load()
                  }}
                />
              )}
            </Card>
          ))}
        </div>
      )}
      {cycles && cycles.length > 0 && (
        <div className="mt-1 surface">
          <Pagination page={page} pageSize={PAGE_SIZE} total={cycles.length} onPage={setPage} />
        </div>
      )}
    </>
  )
}
