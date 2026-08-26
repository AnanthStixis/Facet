import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { AiPanel } from '../components/AiPanel'
import { IconSearch } from '../components/icons'
import { Banner, Card, EmptyState, Skeleton, StatTile } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { Cycle, ResultRow, TargetResults } from '../lib/cycleTypes'
import { RELATIONSHIP_SHORT } from '../lib/cycleTypes'

/** A compact horizontal distribution of ratings across the scale. */
function Distribution({
  distribution,
  scale,
}: {
  distribution: Record<string, number>
  scale: { min: number; max: number }
}) {
  const points = Array.from(
    { length: scale.max - scale.min + 1 },
    (_, index) => scale.min + index,
  )
  const peak = Math.max(1, ...points.map((point) => distribution[String(point)] ?? 0))
  return (
    <div className="flex items-end gap-1" aria-hidden="true">
      {points.map((point) => {
        const count = distribution[String(point)] ?? 0
        return (
          <div key={point} className="flex w-5 flex-col items-center gap-1">
            <div
              className={clsx(
                'w-full rounded-sm transition-all',
                count > 0 ? 'accent-bg' : 'bg-ink-200 dark:bg-ink-800',
              )}
              style={{ height: `${Math.max(3, (count / peak) * 34)}px` }}
              title={`${count} rated ${point}`}
            />
            <span className="text-2xs text-ink-400">{point}</span>
          </div>
        )
      })}
    </div>
  )
}

function TargetDetail({
  cycle,
  targetId,
  onBack,
}: {
  cycle: Cycle
  targetId: string
  onBack: () => void
}) {
  const [data, setData] = useState<TargetResults | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<TargetResults>(`/cycles/${cycle.id}/results/${targetId}`)
      .then(setData)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load results.'),
      )
  }, [cycle.id, targetId])

  if (error) return <Banner tone="error">{error}</Banner>
  if (!data) return <Skeleton className="h-64 w-full rounded-lg" />

  return (
    <>
      <button type="button" className="btn-ghost mb-3 px-2 py-1 text-xs" onClick={onBack}>
        &larr; All results
      </button>
      <PageHeader
        title={data.target.label}
        description={`${cycle.name} · ${data.response_count} contributing response${
          data.response_count === 1 ? '' : 's'
        }`}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Overall average"
              value={data.overall_average?.toFixed(2) ?? '—'}
              tone="accent"
              sub={`Out of ${data.scale?.max ?? 5}`}
            />
            {/* <StatTile
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
              tone={
                data.self_awareness_gap && Math.abs(data.self_awareness_gap) >= 0.75
                  ? 'caution'
                  : 'neutral'
              }
              sub="Self minus others"
            /> */}
            <StatTile
              label="Responses"
              value={data.response_count}
            />
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <Card title="By direction">
              <ul className="space-y-3">
                {(data.by_relationship ?? []).map((group) => (
                  <li key={group.relationship}>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-ink-700 dark:text-ink-200">
                        {RELATIONSHIP_SHORT[group.relationship]}
                      </span>
                      <span className="tabular font-medium text-ink-900 dark:text-ink-50">
                        {group.average?.toFixed(2)}
                      </span>
                    </div>
                    {data.scale && (
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                        <div
                          className="accent-bg h-full"
                          style={{
                            width: `${
                              (((group.average ?? 0) - data.scale.min) /
                                (data.scale.max - data.scale.min)) *
                              100
                            }%`,
                          }}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="By question" padded={false}>
              <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                {(data.questions ?? []).map((question) => (
                  <li
                    key={question.key}
                    className="flex flex-wrap items-center justify-between gap-4 px-5 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink-800 dark:text-ink-100">
                        {question.text}
                      </p>
                      <p className="text-2xs text-ink-400">{question.section}</p>
                    </div>
                    {data.scale && (
                      <Distribution
                        distribution={question.distribution}
                        scale={data.scale}
                      />
                    )}
                    <span className="tabular w-12 text-right text-base font-semibold text-ink-900 dark:text-ink-50">
                      {question.average?.toFixed(2) ?? '—'}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          {/* AI analysis panel removed from UI per request — kept here,
              commented out, so it can be restored without rebuilding it
              from scratch.
          <div className="mt-5">
            <AiPanel cycleId={cycle.id} targetId={targetId} canGenerate />
          </div>
          */}

          {(data.comments ?? []).length > 0 && (
            <Card
              className="mt-5"
              title="Comments"
              hint="Shown in a fixed order, not the order they were submitted, so timing cannot identify an author."
            >
              <ul className="space-y-3">
                {(data.comments ?? []).map((entry, index) => (
                  <li
                    key={index}
                    className="border-l-2 border-[color:var(--accent)] pl-3.5 text-sm leading-relaxed text-ink-700 dark:text-ink-200"
                  >
                    {entry.comment}
                    <span className="mt-0.5 block text-2xs uppercase tracking-[0.08em] text-ink-400">
                      {RELATIONSHIP_SHORT[entry.relationship]}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
    </>
  )
}

export function CycleResults({ cycle, onBack }: { cycle: Cycle; onBack: () => void }) {
  const [rows, setRows] = useState<ResultRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<{ rows: ResultRow[] }>(`/cycles/${cycle.id}/results`)
      .then((data) => setRows(data.rows))
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load results.'),
      )
  }, [cycle.id])

  if (selected) {
    return (
      <TargetDetail
        cycle={cycle}
        targetId={selected}
        onBack={() => setSelected(null)}
      />
    )
  }

  return (
    <>
      <button type="button" className="btn-ghost mb-3 px-2 py-1 text-xs" onClick={onBack}>
        &larr; All cycles
      </button>
      <PageHeader
        title={`${cycle.name} — results`}
        description={
          cycle.is_anonymous
            ? `Anonymous cycle. Nothing is shown for anyone with fewer than ${cycle.min_responses_to_reveal} responses, here or in an export.`
            : 'Attributable cycle. Reviewer names are recorded against each response.'
        }
      />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {!rows ? (
        <Skeleton className="h-64 w-full rounded-lg" />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconSearch width={19} height={19} />}
            title="No responses yet"
            body="Results appear here as reviewers submit their feedback."
          />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Person or item</th>
                  <th>Responses</th>
                  <th>Overall</th>
                  <th>Self</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.target_id}>
                    <td className="font-medium text-ink-900 dark:text-ink-50">
                      {row.target}
                    </td>
                    <td className="tabular">{row.responses}</td>
                    <td className="tabular font-medium">
                      {row.overall_average?.toFixed(2) ?? '—'}
                    </td>
                    <td className="tabular text-ink-500">
                      {row.self_average?.toFixed(2) ?? '—'}
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="btn-ghost px-2 py-1 text-xs"
                        onClick={() => setSelected(row.target_id)}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  )
}
