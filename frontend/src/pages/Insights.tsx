import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { IconAlert, IconLock, IconShield, IconSpark } from '../components/icons'
import { Card, EmptyState, Skeleton, Spinner, StatTile } from '../components/ui'
import { useToast } from '../components/Toast'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

interface Finding {
  key: string
  severity: 'info' | 'attention' | 'urgent'
  title: string
  detail: string
  subject: string | null
  metric: Record<string, unknown>
  evidence: string[]
  action: string | null
}

interface Recommendations {
  status: 'ready' | 'absent'
  findings: Finding[]
  narrative?: string | null
  computed_by?: string
  generated_at?: string
}

interface ModelInfo {
  kind: string
  status: string
  algorithm?: string
  reason?: string | null
  n_samples?: number
  metrics?: Record<string, number | string>
  trained_at?: string
  minimums: { samples: number; per_class: number }
  usable?: boolean
}

interface Prediction {
  proposal_id: string
  reference: string
  title: string
  client_name: string
  probability_pct: number
  prospect_score: number | null
}

interface Predictions {
  available: boolean
  reason?: string
  caveat?: string
  confidence?: string
  cv_accuracy?: number
  baseline_accuracy?: number
  n_samples?: number
  minimums?: { samples: number }
  predictions: Prediction[]
}

const MODEL_LABELS: Record<string, string> = {
  win_probability: 'Proposal win probability',
  score_trend: 'Score trend',
  disengagement_risk: 'Disengagement signal',
}

const SEVERITY_STYLE: Record<string, { chip: string; bar: string }> = {
  urgent: { chip: 'bg-critical/10 text-critical', bar: 'bg-critical' },
  attention: { chip: 'bg-caution/12 text-caution', bar: 'bg-caution' },
  info: { chip: 'bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400', bar: 'bg-ink-300 dark:bg-ink-600' },
}

function FindingCard({ finding }: { finding: Finding }) {
  const style = SEVERITY_STYLE[finding.severity] ?? SEVERITY_STYLE.info
  return (
    <li className="flex gap-0 overflow-hidden rounded-lg border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
      <span className={clsx('w-1 shrink-0', style.bar)} />
      <div className="min-w-0 flex-1 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-base font-medium text-ink-900 dark:text-ink-50">
            {finding.title}
          </p>
          <span className={clsx('chip shrink-0', style.chip)}>{finding.severity}</span>
        </div>
        <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">{finding.detail}</p>

        {/* Evidence sits with the claim. A recommendation a reader cannot
            check is a recommendation they have to take on faith. */}
        {finding.evidence.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {finding.evidence.map((item) => (
              <li key={item} className="text-2xs text-ink-400">
                · {item}
              </li>
            ))}
          </ul>
        )}

        {finding.action && (
          <p className="mt-2.5 flex items-start gap-1.5 text-sm accent-text">
            <IconSpark width={13} height={13} className="mt-0.5 shrink-0" />
            {finding.action}
          </p>
        )}
      </div>
    </li>
  )
}

function ModelCard({ model }: { model: ModelInfo }) {
  const usable = model.status === 'fitted'
  return (
    <div className="rounded-lg border border-ink-200 p-4 dark:border-ink-800">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink-900 dark:text-ink-50">
          {MODEL_LABELS[model.kind] ?? model.kind}
        </p>
        <span
          className={clsx(
            'chip shrink-0',
            usable
              ? 'bg-positive/10 text-positive'
              : 'bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400',
          )}
        >
          {usable ? 'fitted' : 'not available'}
        </span>
      </div>

      {usable ? (
        <>
          <p className="mt-2 text-2xs text-ink-500 dark:text-ink-400">
            {model.algorithm} on {model.n_samples} records
          </p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs">
            <span className="text-ink-500 dark:text-ink-400">
              Accuracy{' '}
              <span className="tabular font-medium text-ink-800 dark:text-ink-100">
                {Math.round(Number(model.metrics?.cv_accuracy ?? 0) * 100)}%
              </span>
            </span>
            <span className="text-ink-500 dark:text-ink-400">
              Baseline{' '}
              <span className="tabular">
                {Math.round(Number(model.metrics?.baseline_accuracy ?? 0) * 100)}%
              </span>
            </span>
            <span className="text-ink-500 dark:text-ink-400">
              Confidence{' '}
              <span className="font-medium">{model.metrics?.confidence}</span>
            </span>
          </div>
        </>
      ) : (
        /* The refusal is the content, not an error state. */
        <p className="mt-2 text-2xs leading-relaxed text-ink-500 dark:text-ink-400">
          {model.reason ?? 'Not trained yet.'}
        </p>
      )}
    </div>
  )
}

interface Theme {
  terms: string[]
  size: number
  avg_sentiment: number | null
  excerpts: string[]
}

interface Themes {
  available: boolean
  reason?: string
  total_comments?: number
  themes: Theme[]
}

interface OrgOption {
  id: string
  name: string
}

export function Insights() {
  const { user } = useAuth()
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const isSuperAdmin = user?.role === 'super_admin'
  const [orgs, setOrgs] = useState<OrgOption[] | null>(null)
  const [selectedOrg, setSelectedOrg] = useState<string>('')
  const [recommendations, setRecommendations] = useState<Recommendations | null>(null)
  const [models, setModels] = useState<ModelInfo[] | null>(null)
  const [predictions, setPredictions] = useState<Predictions | null>(null)
  const [themes, setThemes] = useState<Themes | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const toast = useToast()

  const isAdmin = user?.role === 'client_admin' || user?.role === 'super_admin'
  // Recommendations and predictive models are inherently per-tenant — a
  // Super Admin has no organization of their own, so one must be chosen
  // before any of this means anything.
  const ready = !isSuperAdmin || Boolean(selectedOrg)

  useEffect(() => {
    if (!isSuperAdmin) return
    api
      .get<{ items: OrgOption[] }>('/orgs?page_size=200&status=active')
      .then((page) => setOrgs(page.items))
      .catch(() => setOrgs([]))
  }, [isSuperAdmin])

  const orgQuery = isSuperAdmin && selectedOrg ? `?org_id=${selectedOrg}` : ''

  const load = () => {
    if (!ready) return
    api
      .get<Recommendations>(`/insights/recommendations${orgQuery}`)
      .then(setRecommendations)
      .catch(() => {})
    api.get<ModelInfo[]>(`/insights/models${orgQuery}`).then(setModels).catch(() => {})
    api
      .get<Predictions>(`/insights/proposals/predictions${orgQuery}`)
      .then(setPredictions)
      .catch(() => {})
    api.get<Themes>(`/insights/themes${orgQuery}`).then(setThemes).catch(() => {})
  }

  useEffect(load, [ready, selectedOrg])

  const run = async (what: 'rebuild' | 'train') => {
    setBusy(what)
    try {
      await api.post(
        what === 'rebuild'
          ? `/insights/recommendations/rebuild${orgQuery}`
          : `/insights/models/train${orgQuery}`,
      )
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'That did not work',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusy(null)
    }
  }

  const findings = recommendations?.findings ?? []
  const urgent = findings.filter((item) => item.severity === 'urgent').length
  const attention = findings.filter((item) => item.severity === 'attention').length

  return (
    <>
      <PageHeader
        title="Insights"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="What the feedback across every domain is telling you, and what it is not yet able to tell you."
        actions={
          isAdmin && (
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary px-3 py-1.5"
                disabled={busy !== null}
                onClick={() => run('train')}
              >
                {busy === 'train' && <Spinner />}
                Retrain models
              </button>
              <button
                type="button"
                className="btn-primary px-3 py-1.5"
                disabled={busy !== null}
                onClick={() => run('rebuild')}
              >
                {busy === 'rebuild' && <Spinner />}
                Rebuild
              </button>
            </div>
          )
        }
      />


      {isSuperAdmin && (
        <Card className="mb-5" padded={false}>
          <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
            <label className="flex items-center gap-2.5 text-sm font-medium text-ink-700 dark:text-ink-200">
              Organization
              <select
                className="field w-64"
                value={selectedOrg}
                onChange={(event) => setSelectedOrg(event.target.value)}
              >
                <option value="">Choose an organization…</option>
                {(orgs ?? []).map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
            </label>
            <span className="text-xs text-ink-400">
              Recommendations and predictive models are fitted per tenant — pick one to
              view or rebuild its insights.
            </span>
          </div>
        </Card>
      )}

      {!ready ? (
        <Card>
          <EmptyState
            icon={<IconSpark width={19} height={19} />}
            title="Choose an organization"
            body="Insights are computed per tenant. Select one above to see its recommendations and models."
          />
        </Card>
      ) : (
      <>
      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile
          label="Needs attention now"
          value={urgent}
          tone={urgent > 0 ? 'critical' : 'neutral'}
          sub="Urgent findings"
        />
        <StatTile
          label="Worth a look"
          value={attention}
          tone={attention > 0 ? 'caution' : 'neutral'}
          sub="Attention findings"
        />
        <StatTile
          label="Models available"
          value={`${models?.filter((m) => m.status === 'fitted').length ?? 0} of ${
            models?.length ?? 3
          }`}
          sub="Others need more history"
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div>
          <Card
            title="Attention list"
            hint="Every figure here is computed from your data by a fixed rule, not written by a model."
            padded={false}
          >
            {!recommendations ? (
              <div className="space-y-2 p-5">
                {Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-20 w-full" />
                ))}
              </div>
            ) : findings.length === 0 ? (
              <EmptyState
                icon={<IconShield width={19} height={19} />}
                title="Nothing is flagged"
                body="No rule found anything worth raising in the current data."
              />
            ) : (
              <ul className="space-y-3 p-5">
                {findings.map((finding) => (
                  <FindingCard key={finding.key} finding={finding} />
                ))}
              </ul>
            )}
          </Card>

          {recommendations?.narrative && (
            <Card className="mt-5" title="Summary">
              <p className="text-sm leading-relaxed text-ink-600 dark:text-ink-300">
                {recommendations.narrative}
              </p>
              <p className="mt-3 border-t border-ink-200 pt-2.5 text-2xs text-ink-400 dark:border-ink-800">
                Phrasing only. The figures above come from the rules, not the model.
              </p>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-5">
          <Card
            title="Models"
            hint="A model that has not seen enough history says so rather than guessing."
          >
            {!models ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <div className="space-y-3">
                {models.map((model) => (
                  <ModelCard key={model.kind} model={model} />
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Open proposals"
            hint={
              predictions?.available
                ? predictions.caveat
                : 'Win probability needs a decided history to learn from.'
            }
            padded={false}
          >
            {!predictions ? (
              <Skeleton className="m-5 h-32" />
            ) : !predictions.available ? (
              <div className="flex items-start gap-2.5 p-5 text-sm">
                <IconLock width={15} height={15} className="mt-0.5 shrink-0 text-ink-400" />
                <div>
                  <p className="font-medium text-ink-800 dark:text-ink-100">
                    No prediction offered
                  </p>
                  <p className="mt-0.5 text-ink-600 dark:text-ink-300">
                    {predictions.reason}
                  </p>
                  <p className="mt-1.5 text-2xs text-ink-400">
                    A number produced from too little history would be noise with a
                    percentage sign on it.
                  </p>
                </div>
              </div>
            ) : predictions.predictions.length === 0 ? (
              <p className="p-5 text-sm text-ink-500">
                No proposals are currently awaiting a decision.
              </p>
            ) : (
              <>
                <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                  {predictions.predictions.map((item) => (
                    <li
                      key={item.proposal_id}
                      className="flex items-center justify-between gap-3 px-5 py-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm text-ink-800 dark:text-ink-100">
                          {item.title}
                        </p>
                        <p className="text-2xs text-ink-400">
                          {item.reference}
                          {item.prospect_score !== null &&
                            ` · rated ${item.prospect_score.toFixed(2)}`}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-14 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                          <div
                            className="accent-bg h-full"
                            style={{ width: `${item.probability_pct}%` }}
                          />
                        </div>
                        <span className="tabular w-9 text-right text-sm font-semibold text-ink-900 dark:text-ink-50">
                          {item.probability_pct}%
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
                <p className="flex items-start gap-1.5 border-t border-ink-200 px-5 py-3 text-2xs text-ink-400 dark:border-ink-800">
                  <IconAlert width={11} height={11} className="mt-0.5 shrink-0" />
                  {predictions.cv_accuracy !== undefined && (
                    <>
                      {Math.round(predictions.cv_accuracy * 100)}% cross-validated
                      against a {Math.round((predictions.baseline_accuracy ?? 0) * 100)}%
                      baseline on {predictions.n_samples} proposals. Confidence:{' '}
                      {predictions.confidence}.
                    </>
                  )}
                </p>
              </>
            )}
          </Card>

          <Card
            title="Recurring themes"
            hint="Recent comments grouped by shared wording — a local calculation, not an AI summary."
          >
            {!themes ? (
              <Skeleton className="h-32 w-full" />
            ) : !themes.available ? (
              <p className="text-sm text-ink-500 dark:text-ink-400">{themes.reason}</p>
            ) : themes.themes.length === 0 ? (
              <p className="text-sm text-ink-500 dark:text-ink-400">
                No group of comments was large enough to call a theme yet.
              </p>
            ) : (
              <div className="space-y-3">
                {themes.themes.map((theme, index) => (
                  <div
                    key={index}
                    className="rounded-lg border border-ink-200 p-3 dark:border-ink-800"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="flex flex-wrap gap-1.5">
                        {theme.terms.map((term) => (
                          <span
                            key={term}
                            className="chip bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300"
                          >
                            {term}
                          </span>
                        ))}
                      </p>
                      <span className="text-2xs text-ink-400">
                        {theme.size} comments
                        {theme.avg_sentiment !== null &&
                          ` · avg sentiment ${theme.avg_sentiment > 0 ? '+' : ''}${theme.avg_sentiment}`}
                      </span>
                    </div>
                    {theme.excerpts.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {theme.excerpts.map((excerpt, excerptIndex) => (
                          <li
                            key={excerptIndex}
                            className="text-2xs italic text-ink-500 dark:text-ink-400"
                          >
                            “{excerpt}”
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
      </>
      )}
    </>
  )
}