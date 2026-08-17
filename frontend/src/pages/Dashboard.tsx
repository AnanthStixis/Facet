import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PerspectiveRing } from '../components/PerspectiveRing'
import { Banner, Card, Chip, EmptyState, Skeleton, StatTile } from '../components/ui'
import {
  IconAlert,
  IconBuilding,
  IconClock,
  IconInbox,
  IconSend,
  IconSpark,
  IconUsers,
} from '../components/icons'
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
  // Three distinct dashboards, not two. Client Admin/Super Admin see the
  // whole org — directory headcount, org-wide activity feed, everyone's
  // open cycles and campaigns. A Manager runs their own cycles/campaigns and
  // should see exactly that — not the directory, not other people's
  // activity, not another manager's (or the Client Admin's) work — which is
  // what the backend now scopes `attention` to for this role. Employee gets
  // the narrowest view, built from "My feedback" / "My results".
  const isAdminPlus = user?.role === 'super_admin' || user?.role === 'client_admin'
  const isManager = user?.role === 'manager'
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
            <Link
              to="/organizations?status=pending"
              state={{ from: 'dashboard' }}
              className="font-medium underline"
            >
              Open the approval queue
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
              icon={<IconBuilding width={17} height={17} />}
              to="/organizations"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Awaiting approval"
              value={data.platform.orgs_pending}
              tone={data.platform.orgs_pending > 0 ? 'caution' : 'neutral'}
              sub="Self-registered tenants"
              icon={<IconClock width={17} height={17} />}
              to="/organizations?status=pending"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Suspended"
              value={data.platform.orgs_suspended}
              tone={data.platform.orgs_suspended > 0 ? 'critical' : 'neutral'}
              sub="Access revoked"
              icon={<IconAlert width={17} height={17} />}
              to="/organizations?status=suspended"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Admins"
              value={data.platform.client_admins}
              sub="Across all tenants"
              icon={<IconUsers width={17} height={17} />}
              to="/people?role=client_admin"
              state={{ from: 'dashboard' }}
            />
          
          </>
        ) : isAdminPlus ? (
          <>
            <StatTile
              label="People"
              value={data.metrics.users_total}
              sub={`${data.metrics.users_active} active`}
              icon={<IconUsers width={17} height={17} />}
              to="/people"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Pending invitations"
              value={data.metrics.users_pending}
              tone={data.metrics.users_pending > 0 ? 'caution' : 'neutral'}
              sub="Not yet activated"
              icon={<IconInbox width={17} height={17} />}
              to="/people"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="External contacts"
              value={data.metrics.contacts}
              sub="Clients and prospects"
              icon={<IconSend width={17} height={17} />}
              to="/results"
              state={{ from: 'dashboard' }}
            />
          </>
        ) : isManager ? (
          <>
            <StatTile
              label="My open cycles"
              value={data.attention?.open_cycles ?? 0}
              tone={data.attention?.open_cycles ? 'accent' : 'neutral'}
              sub="Review cycles you're running"
              icon={<IconClock width={17} height={17} />}
              to="/cycles"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="My open campaigns"
              value={data.attention?.open_campaigns ?? 0}
              tone={data.attention?.open_campaigns ? 'accent' : 'neutral'}
              sub="Campaigns you're running"
              icon={<IconSend width={17} height={17} />}
              to="/campaigns"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="Closing within 7 days"
              value={data.attention?.closing_soon ?? 0}
              tone={data.attention?.closing_soon ? 'caution' : 'neutral'}
              sub="Across your cycles"
              icon={<IconAlert width={17} height={17} />}
              to="/cycles"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="My results"
              value={data.metrics.my_results}
              sub="Responses received about you"
              icon={<IconSpark width={17} height={17} />}
              to="/my-results"
              state={{ from: 'dashboard' }}
            />
          </>
        ) : (
          <>
            <StatTile
              label="My feedback"
              value={data.metrics.my_pending_feedback}
              tone={data.metrics.my_pending_feedback > 0 ? 'accent' : 'neutral'}
              sub="Waiting for your response"
              icon={<IconInbox width={17} height={17} />}
              to="/my-feedback"
              state={{ from: 'dashboard' }}
            />
            <StatTile
              label="My results"
              value={data.metrics.my_results}
              sub="Responses received about you"
              icon={<IconSpark width={17} height={17} />}
              to="/my-results"
              state={{ from: 'dashboard' }}
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
          {!isPlatform && isAdminPlus && data.attention && (
            <Card title="Needs attention" hint="Open work across your workspace.">
              <div className="grid grid-cols-2 gap-3">
                <StatTile
                  label="Open review cycles"
                  value={data.attention.open_cycles ?? 0}
                  tone={data.attention.open_cycles ? 'accent' : 'neutral'}
                  icon={<IconClock width={16} height={16} />}
                  to="/cycles"
                  state={{ from: 'dashboard' }}
                />
                <StatTile
                  label="Open campaigns"
                  value={data.attention.open_campaigns ?? 0}
                  tone={data.attention.open_campaigns ? 'accent' : 'neutral'}
                  icon={<IconSend width={16} height={16} />}
                  to="/campaigns"
                  state={{ from: 'dashboard' }}
                />
                <StatTile
                  label="Closing within 7 days"
                  value={data.attention.closing_soon ?? 0}
                  tone={data.attention.closing_soon ? 'caution' : 'neutral'}
                  icon={<IconAlert width={16} height={16} />}
                  to="/cycles"
                  state={{ from: 'dashboard' }}
                />
              </div>
            </Card>
          )}

          {isAdminPlus ? (
            <Card
              title="Recent activity"
              padded={false}
              action={
                <Link
                  to="/audit"
                  state={{ from: 'dashboard' }}
                  className="btn-ghost px-2 py-1 text-xs"
                >
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
          ) : isManager ? (
            <Card title="Quick links" hint="Run your own cycles and campaigns.">
              <div className="grid gap-3">
                <Link
                  to="/cycles"
                  state={{ from: 'dashboard' }}
                  className="flex items-center gap-3 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <span className="accent-soft-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                    <IconClock width={16} height={16} className="accent-text" />
                  </span>
                  Your review cycles
                </Link>
                <Link
                  to="/campaigns"
                  state={{ from: 'dashboard' }}
                  className="flex items-center gap-3 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <span className="accent-soft-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                    <IconSend width={16} height={16} className="accent-text" />
                  </span>
                  Your campaigns
                </Link>
              </div>
            </Card>
          ) : (
            <Card title="Get started" hint="A couple of places worth a look.">
              <div className="grid gap-3">
                <Link
                  to="/my-feedback"
                  state={{ from: 'dashboard' }}
                  className="flex items-center gap-3 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <span className="accent-soft-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                    <IconInbox width={16} height={16} className="accent-text" />
                  </span>
                  Review what's waiting for you
                </Link>
                <Link
                  to="/my-results"
                  state={{ from: 'dashboard' }}
                  className="flex items-center gap-3 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
                >
                  <span className="accent-soft-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                    <IconSpark width={16} height={16} className="accent-text" />
                  </span>
                  See feedback you've received
                </Link>
              </div>
            </Card>
          )}
        </div>
      </div>

      {!isPlatform && isAdminPlus && (
        <Card className="mt-5" title="Quick links">
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { title: 'Review cycles', to: '/cycles', icon: IconClock },
              { title: 'Client campaigns', to: '/campaigns', icon: IconSend },
            ].map((item) => (
              <Link
                key={item.title}
                to={item.to}
                state={{ from: 'dashboard' }}
                className="flex items-center gap-3 rounded-lg border border-ink-200 p-3.5 text-sm font-medium text-ink-700 transition-colors hover:border-[color:var(--accent)] hover:text-ink-900 dark:border-ink-700 dark:text-ink-200 dark:hover:text-ink-50"
              >
                <span className="accent-soft-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                  <item.icon width={16} height={16} className="accent-text" />
                </span>
                {item.title}
              </Link>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}