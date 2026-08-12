import clsx from 'clsx'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { FacetMark } from '../components/Logo'
import { Chip } from '../components/ui'
import {
  IconArrowLeft,
  IconBuilding,
  IconClock,
  IconFile,
  IconGauge,
  IconInbox,
  IconLayers,
  IconLogout,
  IconMoon,
  IconSend,
  IconSettings,
  IconShield,
  IconSpark,
  IconSun,
  IconUsers,
} from '../components/icons'
import { useAuth } from '../store/auth'

const PRODUCT = 'Facet'

interface NavItem {
  to: string
  label: string
  icon: typeof IconGauge
  roles?: string[]
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: IconGauge },
      {
        to: '/insights',
        label: 'Insights',
        icon: IconSpark,
        roles: ['super_admin', 'client_admin', 'manager'],
      },
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
    section: 'Manage',
    items: [
      {
        to: '/cycles',
        label: 'Review cycles',
        icon: IconClock,
        roles: ['super_admin', 'client_admin', 'manager'],
      },
      {
        to: '/campaigns',
        label: 'Client campaigns',
        icon: IconSend,
        roles: ['super_admin', 'client_admin', 'manager'],
      },
      {
        to: '/proposals',
        label: 'Proposals',
        icon: IconFile,
        roles: ['super_admin', 'client_admin', 'manager'],
      },
      { to: '/people', label: 'People', icon: IconUsers, roles: ['super_admin', 'client_admin'] },
      {
        to: '/templates',
        label: 'Templates',
        icon: IconLayers,
        roles: ['super_admin', 'client_admin'],
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

  if (!user) return null

  const visible = NAV.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.roles || item.roles.includes(user.role)),
  })).filter((group) => group.items.length > 0)

  const tenantName = organization?.name ?? 'Platform'
  const logo = organization?.branding?.logo_url

  return (
    <div className="flex min-h-screen">
      {/* Sidebar. Ink-dark in both themes, so the workspace chrome stays
          constant and the content area is what changes. */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-ink-800 bg-ink-900 lg:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-ink-800 px-4">
          <span className="accent-text">
            <FacetMark size={22} />
          </span>
          <span className="text-base font-semibold tracking-[-0.02em] text-white">
            {PRODUCT}
          </span>
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-4">
          {visible.map((group) => (
            <div key={group.section} className="mb-5">
              <p className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-[0.1em] text-ink-500">
                {group.section}
              </p>
              {group.items.map((item) => {
                const active =
                  item.to === '/'
                    ? location.pathname === '/'
                    : location.pathname.startsWith(item.to)
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={clsx(
                      'relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-base transition-colors',
                      active
                        ? 'bg-ink-800 font-medium text-white'
                        : 'text-ink-400 hover:bg-ink-800/60 hover:text-ink-100',
                    )}
                  >
                    {active && (
                      <span className="accent-bg absolute inset-y-1.5 left-0 w-0.5 rounded-full" />
                    )}
                    <item.icon width={16} height={16} className="shrink-0" />
                    {item.label}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-ink-800 px-4 py-3">
          <p className="text-2xs uppercase tracking-[0.1em] text-ink-500">Signed in as</p>
          <p className="truncate text-sm font-medium text-ink-100">{user.full_name}</p>
          <p className="truncate text-2xs text-ink-500">{user.email}</p>
          <div className="mt-1.5">
            <Chip value={user.role} />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-56">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-ink-200 bg-white/85 px-4 backdrop-blur-md dark:border-ink-800 dark:bg-ink-950/85 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
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
              <p className="truncate text-2xs text-ink-400">
                {user.role === 'super_admin'
                  ? 'Platform administration'
                  : (organization?.timezone ?? '')}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
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
                          <Chip value={user.role} />
                        </div>
                        <p className="mt-1.5 flex items-center gap-1.5 text-2xs">
                          <span
                            className={clsx(
                              'h-1.5 w-1.5 rounded-full',
                              user.mfa_enabled ? 'bg-positive' : 'bg-caution',
                            )}
                          />
                          {user.mfa_enabled
                            ? 'Two-factor enabled'
                            : 'Two-factor not enabled'}
                        </p>
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