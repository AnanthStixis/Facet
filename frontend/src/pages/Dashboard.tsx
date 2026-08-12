import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PerspectiveRing } from '../components/PerspectiveRing'
import { Banner, Card, Chip, EmptyState, Skeleton, StatTile } from '../components/ui'
import { IconAlert, IconClock, IconFile, IconInbox, IconSend, IconShield, IconSpark } from '../components/icons'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { DashboardData } from '../lib/types'
import { useAuth } from '../store/auth'

const formatTime = (iso: string, timezone?: string) =>
  new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone,
  }).format(new Date(iso))

export function Dashboard() {
  const { user, organization } = useAuth()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .get<DashboardData>('/dashboard')
      .then(setData)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load the dashboard.'),
      )
  }

  useEffect(load, [])
  useRefetchOnFocus(load)

  if (error) return <Banner tone="error">{error}</Banner>

  if (!data) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full rounded-lg" />
          ))}
        </div>
      </>
    )
  }

  const isPlatform = data.scope === 'platform'
  // An Employee's dashboard shows only what is theirs — no org-wide
  // headcount, no other people's activity, no links to pages they cannot
  // open. Manager and above see the operational view; Employee sees a
  // narrower one built from "My feedback" / "My results" instead.
  const isManagerPlus =
    user?.role === 'super_admin' || user?.role === 'client_admin' || user?.role === 'manager'
  const firstName = user?.full_name.split(' ')[0] ?? ''

  return (
    <>
      <PageHeader
        title={`Good to see you, ${firstName}`}
        description={
          isPlatform
            ? 'Platform-wide view across every tenant on Facet.'
            : `${organization?.name ?? ''} — activity, coverage, and directory health.`
        }
      />

      {/* Super Admins get the approval queue first, because a tenant sitting
          unapproved is the one thing on this page that blocks someone else. */}
      {isPlatform && data.platform && data.platform.orgs_pending > 0 && (
        <Banner tone="warning" className="mb-5">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <strong>{data.platform.orgs_pending}</strong> organization
            {data.platform.orgs_pending === 1 ? '' : 's'} awaiting review.
            <Link to="/organizations?status=pending" className="font-medium underline">
              Open the approval queue
            </Link>
          </span>
        </Banner>
      )}

      {user && !user.mfa_enabled && (
        <Banner tone="info" className="mb-5">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <IconShield width={15} height={15} />
            Two-factor authentication is not enabled on your account.
            <Link to="/security" className="font-medium underline">
              Set it up
            </Link>
          </span>
        </Banner>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {isPlatform && data.platform ? (
          <>
            <StatTile
              label="Organizations"
              value={data.platform.orgs_total}
              sub={`${data.platform.orgs_active} active`}
              to="/organizations"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Awaiting approval"
              value={data.platform.orgs_pending}
              tone={data.platform.orgs_pending > 0 ? 'caution' : 'neutral'}
              sub="Self-registered tenants"
              to="/organizations?status=pending"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Suspended"
              value={data.platform.orgs_suspended}
              tone={data.platform.orgs_suspended > 0 ? 'critical' : 'neutral'}
              sub="Access revoked"
              to="/organizations?status=suspended"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Client admins"
              value={data.platform.client_admins}
              sub="Across all tenants"
              to="/people?role=client_admin"
              state={{ from: 'dashboard' }}
            />
          
          </>
        ) : isManagerPlus ? (
          <>
            <StatTile
              label="People"
              value={data.metrics.users_total}
              sub={`${data.metrics.users_active} active`}
              to="/people"
            />
            <StatTile
              label="Pending invitations"
              value={data.metrics.users_pending}
              tone={data.metrics.users_pending > 0 ? 'caution' : 'neutral'}
              sub="Not yet activated"
              to="/people"
            />
            <StatTile
              label="Two-factor adoption"
              value={`${data.metrics.mfa_adoption_pct}%`}
              tone={data.metrics.mfa_adoption_pct < 50 ? 'caution' : 'neutral'}
              sub="Of all accounts"
              to="/security"
            />
            <StatTile
              label="External contacts"
              value={data.metrics.contacts}
              sub="Clients and prospects"
              to="/campaigns"
            />
          </>
        ) : (
          <>
            <StatTile
              label="My feedback"
              value={data.metrics.my_pending_feedback}
              tone={data.metrics.my_pending_feedback > 0 ? 'accent' : 'neutral'}
              sub="Waiting for your response"
              to="/my-feedback"
            />
            <StatTile
              label="My results"
              value={data.metrics.my_results}
              sub="Responses received about you"
              to="/my-results"
            />
            <StatTile
              label="Two-factor"
              value={user?.mfa_enabled ? 'On' : 'Off'}
              tone={user?.mfa_enabled ? 'neutral' : 'caution'}
              sub="Your account security"
              to="/security"
            />
          </>
        )}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* The signature visual. It exists to make the product's one structural
            claim visible in three seconds: internal and external feedback are
            arcs of the same ring, not two products bolted together. */}
        <Card
          title="Feedback coverage"
          hint={isPlatform
      ? 'Platform-wide feedback coverage across all organizations.'
      : 'Every relationship this workspace can collect feedback on, in one graph.'
  }
        >
          <div className="flex flex-col items-center gap-5">
            <PerspectiveRing coverage={data.coverage} />
            <div className="grid w-full grid-cols-2 gap-x-5 gap-y-1.5 text-sm">
              {data.coverage
                .filter((slice) => slice.count > 0)
                .map((slice) => (
                  <div
                    key={slice.target_type}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="flex min-w-0 items-center gap-2 text-ink-600 dark:text-ink-300">
                      <span
                        className={
                          slice.domain === 'internal'
                            ? 'h-1.5 w-1.5 shrink-0 rounded-full bg-internal'
                            : 'accent-bg h-1.5 w-1.5 shrink-0 rounded-full'
                        }
                      />
                      <span className="truncate">{slice.label}</span>
                    </span>
                    <span className="tabular font-medium text-ink-900 dark:text-ink-100">
                      {slice.count}
                    </span>
                  </div>
                ))}
            </div>
            {data.coverage.every((slice) => slice.count === 0) && (
              <p className="text-center text-sm text-ink-500">
                No feedback targets yet. Add people, services, or proposals to start
                building the graph.
              </p>
            )}
          </div>
        </Card>

        <div className="flex flex-col gap-5">
          {/* Counts that route straight to what resolves them, rather than a
              14-day bar chart that tells you activity happened without saying
              whether any of it needs you. */}
          {!isPlatform && isManagerPlus && data.attention && (
            <Card title="Needs attention" hint="Open work across your workspace.">
              <div className="grid grid-cols-2 gap-3">
                <StatTile
                  label="Open review cycles"
                  value={data.attention.open_cycles ?? 0}
                  tone={data.attention.open_cycles ? 'accent' : 'neutral'}
                  to="/cycles"
                  state={{ from: 'dashboard' }}
                />
                <StatTile
                  label="Open campaigns"
                  value={data.attention.open_campaigns ?? 0}
                  tone={data.attention.open_campaigns ? 'accent' : 'neutral'}
                  to="/campaigns"
                />
                <StatTile
                  label="Closing within 7 days"
                  value={data.attention.closing_soon ?? 0}
                  tone={data.attention.closing_soon ? 'caution' : 'neutral'}
                  to="/cycles"
                />
                <StatTile
                  label="Proposals awaiting outcome"
                  value={data.attention.proposals_awaiting_outcome ?? 0}
                  tone={data.attention.proposals_awaiting_outcome ? 'caution' : 'neutral'}
                  to="/proposals"
                />
              </div>
            </Card>
          )}

          {isManagerPlus ? (
            <Card
              title="Recent activity"
              padded={false}
              action={
                <Link to="/audit" className="btn-ghost px-2 py-1 text-xs">
                  Audit trail
                </Link>
              }
            >
              {data.recent_activity.length === 0 ? (
                <EmptyState
                  icon={<IconAlert width={19} height={19} />}
                  title="Nothing recorded yet"
                  body="Actions across the workspace will appear here."
                />
              ) : (
                <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                  {data.recent_activity.map((entry) => (
                    <li key={entry.id} className="flex items-start gap-3 px-5 py-2.5">
                      <span className="mt-0.5 shrink-0">
                        <Chip value={entry.severity} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-ink-800 dark:text-ink-200">
                          {entry.summary}
                        </p>
                        <p className="text-2xs text-ink-400">
                          {entry.actor_name ?? 'System'} &middot;{' '}
                          {formatTime(entry.occurred_at, organization?.timezone)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : (
            <Card title="Get started" hint="A couple of places worth a look.">
              <div className="grid gap-3">
                <Link
                  to="/my-feedback"
                  className="flex items-center gap-2 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <IconInbox width={16} height={16} className="accent-text shrink-0" />
                  Review what's waiting for you
                </Link>
                <Link
                  to="/my-results"
                  className="flex items-center gap-2 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <IconSpark width={16} height={16} className="accent-text shrink-0" />
                  See feedback you've received
                </Link>
              </div>
            </Card>
          )}
        </div>
      </div>

      {!isPlatform && isManagerPlus && (
        <Card className="mt-5" title="Quick links">
          <div className="grid gap-3 sm:grid-cols-4">
            {[
              { title: 'Review cycles', to: '/cycles', icon: IconClock },
              { title: 'Client campaigns', to: '/campaigns', icon: IconSend },
              { title: 'Proposals', to: '/proposals', icon: IconFile },
              { title: 'Insights', to: '/insights', icon: IconAlert },
            ].map((item) => (
              <Link
                key={item.title}
                to={item.to}
                className="flex items-center gap-2 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
              >
                <item.icon width={16} height={16} className="accent-text shrink-0" />
                {item.title}
              </Link>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}
