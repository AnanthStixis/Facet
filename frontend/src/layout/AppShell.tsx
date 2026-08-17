import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { FacetMark } from '../components/Logo'
import { Chip } from '../components/ui'
import {
  IconArrowLeft,
  IconBriefcase,
  IconBuilding,
  IconFile,
  IconGauge,
  IconInbox,
  IconLayers,
  IconLogout,
  IconMenu,
  IconMoon,
  IconRefresh,
  IconSettings,
  IconShield,
  IconSpark,
  IconSun,
  IconTag,
  IconUsers,
  IconX,
} from '../components/icons'
import { triggerManualRefresh } from '../hooks/useRefetchOnFocus'
import { ROLE_LABEL } from '../lib/types'
import { useAuth } from '../store/auth'

const PRODUCT = 'Facet'

// Temporary kill switch — flip back to true to bring the Insights nav item
// back. The page and its API routes are untouched; this only hides the entry
// point until it's ready to be shown again.
const INSIGHTS_ENABLED = false

interface NavItem {
  to: string
  label: string
  // Either an icon or a colour dot — the six feedback-type entries use a dot
  // (matching their type colour across Create Feedback/Results), everything
  // else uses an icon.
  icon?: typeof IconGauge
  dotColor?: string
  roles?: string[]
}

// Kept in sync with FEEDBACK_TYPES in pages/CreateFeedback.tsx by hand — the
// nav needs only label/color/route, not the rest of that config (templates,
// blurbs), so importing the whole module here would pull the API/state
// machinery of the create-feedback page into every page's nav render.
const CREATE_FEEDBACK_TYPES = [
  { kind: 'client', label: 'Client Review', color: '#B4633A' },
  { kind: 'employee', label: 'Employees Review', color: '#3B82F6' },
  { kind: 'management', label: 'Management Review', color: '#8B5CF6' },
  { kind: 'product', label: 'Product Review', color: '#10B981' },
  { kind: 'service', label: 'Service Review', color: '#F59E0B' },
  { kind: 'proposal', label: 'Proposal Review', color: '#EC4899' },
]

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: IconGauge },
      ...(INSIGHTS_ENABLED
        ? [
            {
              to: '/insights',
              label: 'Insights',
              icon: IconSpark,
              roles: ['super_admin', 'client_admin', 'manager'],
            },
          ]
        : []),
    ],
  },
  {
    // Every role has these two, and they are the pages an employee opens the
    // product for, so they sit above the administrative sections.
    section: 'For me',
    items: [
      { to: '/my-feedback', label: 'My feedback', icon: IconInbox },
      { to: '/my-results', label: 'My results', icon: IconSpark },
    ],
  },
  {
    section: 'Platform',
    items: [
      {
        to: '/organizations',
        label: 'Organizations',
        icon: IconBuilding,
        roles: ['super_admin'],
      },
    ],
  },
  {
    section: 'Create Feedback',
    items: CREATE_FEEDBACK_TYPES.map((t) => ({
      to: `/create-feedback?kind=${t.kind}`,
      label: t.label,
      dotColor: t.color,
      roles: ['super_admin', 'client_admin', 'manager'],
    })),
  },
  {
    section: 'Manage Masters',
    items: [
      {
        to: '/results',
        label: 'Results',
        icon: IconFile,
        roles: ['super_admin', 'client_admin', 'manager'],
      },
      {
        to: '/categories',
        label: 'Categories',
        icon: IconTag,
        roles: ['super_admin', 'client_admin'],
      },
      {
        to: '/templates',
        label: 'Templates',
        icon: IconLayers,
        roles: ['super_admin', 'client_admin'],
      },
      { to: '/people', label: 'Users', icon: IconUsers, roles: ['super_admin', 'client_admin'] },
      {
        to: '/clients',
        label: 'Clients',
        icon: IconBriefcase,
        roles: ['client_admin', 'manager'],
      },
      {
        to: '/masters',
        label: 'Master Data',
        icon: IconTag,
        roles: ['client_admin', 'manager'],
      },
    ],
  },
  {
    section: 'Governance',
    items: [
      { to: '/reports', label: 'Reports', icon: IconFile, roles: ['super_admin', 'client_admin'] },
      {
        to: '/audit',
        label: 'Audit trail',
        icon: IconShield,
        roles: ['super_admin', 'client_admin'],
      },
      {
        to: '/settings',
        label: 'Settings',
        icon: IconSettings,
        roles: ['client_admin'],
      },
    ],
  },
]

function Initials({ name }: { name: string }) {
  const initials = name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full accent-soft-bg text-2xs font-semibold accent-text">
      {initials}
    </span>
  )
}

export function AppShell() {
  const { user, organization, logout, theme, setTheme } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)

  // Route changes close the mobile drawer; Escape does too, matching the
  // Modal component's own close behavior elsewhere in the app.
  useEffect(() => setRailOpen(false), [location.pathname])
  useEffect(() => {
    if (!railOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setRailOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [railOpen])

  if (!user) return null

  // A Super Admin literally can never have an org in this app — that is the
  // mechanism the Templates redesign relies on (super-admin-creates-with-no-org
  // IS what makes a template a global default). POST /feedback already
  // rejects with "A Super Admin must act within an organization." when
  // actor.org_id is None, so the six review-type entries would only ever
  // 404 for them. `organization` (from useAuth) mirrors actor.org_id here —
  // it is null exactly when the signed-in user has no org. Hide "Create
  // Feedback" for an org-less Super Admin; Templates' own "New template" is
  // untouched — a Super Admin creating templates is intentional and correct.
  //
  // "For me" (My feedback / My results) is about the signed-in user's own
  // standing as a reviewee/reviewer within an org — an org-less Super Admin
  // isn't a member of any org's feedback graph, so both pages would only
  // ever show empty state. Same gate as Create Feedback.
  const hideOrgScopedNav = user.role === 'super_admin' && !organization

  const visible = NAV.filter(
    (group) => !(hideOrgScopedNav && (group.section === 'Create Feedback' || group.section === 'For me')),
  )
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.roles || item.roles.includes(user.role)),
    }))
    .filter((group) => group.items.length > 0)

  const tenantName = organization?.name ?? 'Platform'
  const logo = organization?.branding?.logo_url

  return (
    <div className="flex min-h-screen">
      {/* Mobile scrim — catches the tap-outside-to-close and dims the page
          behind the drawer. Desktop never renders it (rail is static there). */}
      {railOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink-950/50 lg:hidden"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar. Follows the app's light/dark theme like every other
          surface, rather than staying permanently dark — a white rail in
          light mode is what makes the workspace feel airy instead of
          console-like. Static on desktop; an off-canvas drawer below lg. */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-ink-200 bg-white',
          'dark:border-ink-800 dark:bg-ink-900',
          'transition-transform duration-200 ease-out lg:translate-x-0',
          railOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-ink-200 px-4 dark:border-ink-800">
          <span className="accent-bg flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white">
            <FacetMark size={18} />
          </span>
          <span className="flex-1 text-base font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            {PRODUCT}
          </span>
          <button
            type="button"
            onClick={() => setRailOpen(false)}
            className="rounded-md p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-800 dark:hover:bg-ink-800 dark:hover:text-white lg:hidden"
            aria-label="Close menu"
          >
            <IconX width={16} height={16} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-4">
          {visible.map((group) => (
            <div key={group.section} className="mb-5">
              <p className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-[0.1em] text-ink-400 dark:text-ink-500">
                {group.section}
              </p>
              {group.items.map((item) => {
                // Items that carry a query string (the six feedback-type
                // entries) need an exact pathname+search match, not a prefix
                // check — otherwise every one of them would light up
                // together the moment you're anywhere under /create-feedback.
                // A bare /create-feedback (no kind yet) is treated as the
                // default 'employee' type, matching CreateFeedback.tsx's own
                // fallback.
                const active = item.to.includes('?')
                  ? `${location.pathname}${location.search}` === item.to ||
                    (location.pathname === '/create-feedback' &&
                      !location.search &&
                      item.to.endsWith('kind=employee'))
                  : item.to === '/'
                    ? location.pathname === '/'
                    : location.pathname.startsWith(item.to)
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={clsx(
                      'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-base transition-colors',
                      active
                        ? 'accent-soft-bg accent-text font-semibold'
                        : 'text-ink-500 hover:bg-ink-100 hover:text-ink-800 dark:text-ink-400 dark:hover:bg-ink-800/60 dark:hover:text-ink-100',
                    )}
                  >
                    {item.icon ? (
                      <item.icon width={16} height={16} className="shrink-0" />
                    ) : (
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: item.dotColor }}
                        aria-hidden="true"
                      />
                    )}
                    {item.label}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-ink-200 px-4 py-3 dark:border-ink-800">
          <p className="text-2xs uppercase tracking-[0.1em] text-ink-400 dark:text-ink-500">
            Signed in as
          </p>
          <p className="truncate text-sm font-medium text-ink-900 dark:text-ink-100">
            {user.full_name}
          </p>
          <p className="truncate text-2xs text-ink-400 dark:text-ink-500">{user.email}</p>
          <div className="mt-1.5">
            <Chip value={user.role}>{ROLE_LABEL[user.role]}</Chip>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-56">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-ink-200 bg-white/85 px-4 backdrop-blur-md dark:border-ink-800 dark:bg-ink-950/85 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setRailOpen(true)}
              className="btn-ghost -ml-1.5 p-2 lg:hidden"
              aria-label="Open menu"
            >
              <IconMenu />
            </button>
            {/* The tenant's own mark, not ours: this is their workspace. */}
            {logo ? (
              <img
                src={logo}
                alt={tenantName}
                className="h-7 max-w-[120px] object-contain"
              />
            ) : (
              <span className="flex h-7 w-7 items-center justify-center rounded accent-soft-bg text-2xs font-bold accent-text">
                {tenantName.slice(0, 2).toUpperCase()}
              </span>
            )}
            <div className="min-w-0">
              <p className="truncate text-base font-semibold text-ink-900 dark:text-ink-50">
                {tenantName}
              </p>
              {user.role === 'super_admin' && (
                <p className="truncate text-2xs text-ink-400">Platform administration</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={triggerManualRefresh}
              className="btn-ghost p-2"
              aria-label="Refresh this page's data"
              title="Refresh"
            >
              <IconRefresh />
            </button>
            <button
              type="button"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="btn-ghost p-2"
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? <IconSun /> : <IconMoon />}
            </button>

            <div className="relative">
              <button
                type="button"
                onClick={() => setMenuOpen((state) => !state)}
                className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-ink-100 dark:hover:bg-ink-800"
              >
                <Initials name={user.full_name} />
              </button>
              {menuOpen &&
                createPortal(
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
                    <div className="fixed right-4 top-14 z-40 mt-1.5 w-60 rounded-lg border border-ink-200 bg-white p-1.5 shadow-lift dark:border-ink-700 dark:bg-ink-900 sm:right-6">
                      <div className="px-2.5 py-2">
                        <p className="text-sm font-medium text-ink-900 dark:text-ink-50">
                          {user.full_name}
                        </p>
                        <p className="truncate text-2xs text-ink-400">{user.email}</p>
                        <div className="mt-1.5">
                          <Chip value={user.role}>{ROLE_LABEL[user.role]}</Chip>
                        </div>
                      </div>
                      <NavLink
                        to="/security"
                        onClick={() => setMenuOpen(false)}
                        className="flex items-center gap-2 rounded px-2.5 py-2 text-sm text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
                      >
                        <IconShield width={15} height={15} />
                        Security settings
                      </NavLink>
                      <button
                        type="button"
                        onClick={() => logout()}
                        className="flex w-full items-center gap-2 rounded px-2.5 py-2 text-left text-sm text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
                      >
                        <IconLogout width={15} height={15} />
                        Sign out
                      </button>
                    </div>
                  </>,
                  document.body,
                )}
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {/* Keyed by user id so a login/logout in the same tab remounts the
              whole page tree instead of leaving the previous user's fetched
              state on screen until a manual reload or window refocus. */}
          <Outlet key={user.id} />
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
  backTo,
  backLabel = 'Back',
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  backTo?: string
  backLabel?: string
}) {
  return (
    <div className="mb-5">
      {backTo && (
        <Link
          to={backTo}
          className="mb-3 -ml-1.5 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-sm text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-800 dark:text-ink-400 dark:hover:bg-ink-800 dark:hover:text-ink-100"
        >
          <IconArrowLeft width={14} height={14} />
          {backLabel}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold text-ink-900 dark:text-white">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-ink-500 dark:text-ink-400">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}