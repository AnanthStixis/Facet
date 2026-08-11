import { useEffect, useState } from 'react'
import { AiPanel } from '../components/AiPanel'
import { IconLock, IconSpark } from '../components/icons'
import { Banner, Card, EmptyState, Skeleton, StatTile } from '../components/ui'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { TargetResults } from '../lib/cycleTypes'
import { RELATIONSHIP_SHORT } from '../lib/cycleTypes'

/**
 * What the reviewee themselves sees.
 *
 * Identical suppression to the admin view — a person cannot unlock their own
 * results early by virtue of them being about them. If anything the threshold
 * matters more here, because the reviewee is the one person with both the
 * motive and the context to work out who said what.
 */
export function MyResults() {
  const [cycles, setCycles] = useState<TargetResults[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .get<TargetResults[]>('/me/results')
      .then(setCycles)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load your results.'),
      )
  }

  useEffect(load, [])
  useRefetchOnFocus(load)

  return (
    <>
      <PageHeader
        title="My results"
        description="Feedback other people have given about you, aggregated so no single response can be isolated."
      />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {!cycles ? (
        <Skeleton className="h-48 w-full rounded-lg" />
      ) : cycles.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconSpark width={19} height={19} />}
            title="No feedback about you yet"
            body="Once a review cycle that includes you collects enough responses, your results will appear here."
          />
        </Card>
      ) : (
        <div className="space-y-5">
          {cycles.map((result) => (
            <Card
              key={result.cycle.id}
              title={result.cycle.name}
              hint={`${result.response_count} response${
                result.response_count === 1 ? '' : 's'
              } about you`}
            >
              {!result.revealed ? (
                <div className="flex items-start gap-2.5 rounded-md border border-ink-200 bg-ink-50 p-4 text-sm text-ink-600 dark:border-ink-700 dark:bg-ink-900/60 dark:text-ink-300">
                  <IconLock width={15} height={15} className="mt-0.5 shrink-0" />
                  <div>
                    <p className="font-medium text-ink-800 dark:text-ink-100">
                      Not enough responses yet
                    </p>
                    <p className="mt-0.5">{result.suppressed_reason}</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <StatTile
                      label="How others rate you"
                      value={result.overall_average?.toFixed(2) ?? '—'}
                      tone="accent"
                      sub={`Out of ${result.scale?.max ?? 5}`}
                    />
                    <StatTile
                      label="How you rate yourself"
                      value={result.self_average?.toFixed(2) ?? '—'}
                      sub={result.self_response_count ? 'Your self-assessment' : 'Not completed'}
                    />
                    <StatTile
                      label="Gap"
                      value={
                        result.self_awareness_gap === null ||
                        result.self_awareness_gap === undefined
                          ? '—'
                          : `${result.self_awareness_gap > 0 ? '+' : ''}${result.self_awareness_gap.toFixed(2)}`
                      }
                      tone={
                        result.self_awareness_gap &&
                        Math.abs(result.self_awareness_gap) >= 0.75
                          ? 'caution'
                          : 'neutral'
                      }
                      sub={
                        result.self_awareness_gap && result.self_awareness_gap > 0
                          ? 'You rate yourself higher'
                          : result.self_awareness_gap && result.self_awareness_gap < 0
                            ? 'Others rate you higher'
                            : 'Closely aligned'
                      }
                    />
                  </div>

                  <div className="mt-5 grid gap-5 lg:grid-cols-2">
                    <div>
                      <p className="label-caps mb-2">Strongest</p>
                      <ul className="space-y-2">
                        {[...(result.questions ?? [])]
                          .filter((question) => question.average !== null)
                          .sort((a, b) => (b.average ?? 0) - (a.average ?? 0))
                          .slice(0, 3)
                          .map((question) => (
                            <li
                              key={question.key}
                              className="flex items-start justify-between gap-3 text-sm"
                            >
                              <span className="text-ink-700 dark:text-ink-200">
                                {question.text}
                              </span>
                              <span className="tabular font-medium text-positive">
                                {question.average?.toFixed(2)}
                              </span>
                            </li>
                          ))}
                      </ul>
                    </div>
                    <div>
                      <p className="label-caps mb-2">Most room to grow</p>
                      <ul className="space-y-2">
                        {[...(result.questions ?? [])]
                          .filter((question) => question.average !== null)
                          .sort((a, b) => (a.average ?? 0) - (b.average ?? 0))
                          .slice(0, 3)
                          .map((question) => (
                            <li
                              key={question.key}
                              className="flex items-start justify-between gap-3 text-sm"
                            >
                              <span className="text-ink-700 dark:text-ink-200">
                                {question.text}
                              </span>
                              <span className="tabular font-medium text-caution">
                                {question.average?.toFixed(2)}
                              </span>
                            </li>
                          ))}
                      </ul>
                    </div>
                  </div>

                  {/* Read-only for the subject: they see the summary about
                      them, but cannot spend the organization's AI budget. */}
                  <div className="mt-5">
                    <AiPanel
                      cycleId={result.cycle.id}
                      targetId={result.target.id}
                    />
                  </div>

                  {(result.comments ?? []).length > 0 && (
                    <div className="mt-5">
                      <p className="label-caps mb-2">What people said</p>
                      <ul className="space-y-3">
                        {(result.comments ?? []).map((entry, index) => (
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
                    </div>
                  )}
                </>
              )}
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
