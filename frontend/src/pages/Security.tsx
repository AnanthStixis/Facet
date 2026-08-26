import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Banner, Card, Field, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { IconLock } from '../components/icons'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'

interface ActiveSession {
  id: string
  device_label: string | null
  user_agent: string | null
  ip_address: string | null
  created_at: string
  last_used_at: string | null
  is_current: boolean
}

const deviceName = (userAgent: string | null) => {
  if (!userAgent) return 'Unknown device'
  const browser =
    /Edg\//.test(userAgent) ? 'Edge'
    : /Chrome\//.test(userAgent) ? 'Chrome'
    : /Firefox\//.test(userAgent) ? 'Firefox'
    : /Safari\//.test(userAgent) ? 'Safari'
    : 'Browser'
  const os =
    /Windows/.test(userAgent) ? 'Windows'
    : /Mac OS/.test(userAgent) ? 'macOS'
    : /Android/.test(userAgent) ? 'Android'
    : /iPhone|iPad/.test(userAgent) ? 'iOS'
    : /Linux/.test(userAgent) ? 'Linux'
    : ''
  return [browser, os].filter(Boolean).join(' on ')
}

function PasswordSection() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  return (
    <Card
      title="Password"
      hint="Changing your password signs out every other device you are signed in on."
    >
      <form
        className="max-w-sm"
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setFieldErrors({})
          try {
            const result = await api.post<{ message: string }>('/auth/password', {
              current_password: current,
              new_password: next,
            })
            toast.show('success', 'Password changed', result.message)
            setCurrent('')
            setNext('')
          } catch (caught) {
            if (caught instanceof ApiError) {
              const fields = caught.fieldErrors()
              if (Object.keys(fields).length === 0) {
                toast.show('critical', 'The password could not be changed', caught.message)
              }
              setFieldErrors(fields)
            } else {
              toast.show('critical', 'The password could not be changed')
            }
          } finally {
              setBusy(false)
          }
        }}
      >
        <div className="space-y-3">
          <Field
            label="Current password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            required
          />
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            error={fieldErrors.password}
            hint="At least 6 characters. A long passphrase beats a short complex one."
            required
          />
        </div>
        <button type="submit" className="btn-primary mt-4 px-3 py-1.5" disabled={busy}>
          {busy && <Spinner />}
          Update password
        </button>
      </form>
    </Card>
  )
}

function SessionsSection() {
  const [sessions, setSessions] = useState<ActiveSession[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .get<ActiveSession[]>('/auth/sessions')
      .then(setSessions)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load sessions.'),
      )
  }

  useEffect(load, [])

  return (
    <Card
      title="Active sessions"
      hint="Each sign-in on each device. Revoking one ends it immediately."
      padded={false}
    >
      {error && (
        <div className="p-5">
          <Banner tone="error">{error}</Banner>
        </div>
      )}
      <ul className="divide-y divide-ink-200 dark:divide-ink-800">
        {sessions.map((session) => (
          <li key={session.id} className="flex items-center justify-between gap-4 px-5 py-3">
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-sm font-medium text-ink-900 dark:text-ink-50">
                {deviceName(session.user_agent)}
                {session.is_current && (
                  <span className="chip accent-soft-bg accent-text">This device</span>
                )}
              </p>
              <p className="truncate text-2xs text-ink-400">
                {session.ip_address ?? 'Unknown IP'} &middot; last used{' '}
                {session.last_used_at
                  ? new Date(session.last_used_at).toLocaleString()
                  : 'never'}
              </p>
            </div>
            {!session.is_current && (
              <button
                type="button"
                className="btn-secondary px-2.5 py-1 text-xs"
                onClick={async () => {
                  await api.delete(`/auth/sessions/${session.id}`)
                  setSessions((current) => current.filter((s) => s.id !== session.id))
                }}
              >
                Revoke
              </button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function Security() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  return (
    <>
      <PageHeader
        title="Security"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Your password and the devices currently signed in."
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <PasswordSection />
        </div>
        <div className="flex flex-col gap-5">
          <SessionsSection />
          {/* <Card title="How your session is protected">
            <ul className="space-y-2.5 text-sm text-ink-600 dark:text-ink-300">
              {[
                'Access tokens last 15 minutes, so a stolen one has a short life.',
                'Refresh tokens rotate on every use and are held in a cookie script cannot read.',
                'Replaying an old refresh token destroys the whole session family — the attacker and you are both signed out, so you notice.',
                'Every sign-in, failure, and revocation is written to an append-only audit trail.',
              ].map((line) => (
                <li key={line} className="flex items-start gap-2">
                  <IconLock width={14} height={14} className="mt-0.5 shrink-0 accent-text" />
                  {line}
                </li>
              ))}
            </ul>
          </Card> */}
        </div>
      </div>
    </>
  )
}