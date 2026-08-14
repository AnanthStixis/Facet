import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Banner, Card, Field, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { IconLock, IconShield } from '../components/icons'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

interface EnrolStart {
  secret: string
  otpauth_uri: string
  qr_svg: string
}

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

function MfaSection() {
  const { user, boot } = useAuth()
  const [enrol, setEnrol] = useState<EnrolStart | null>(null)
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  if (recovery) {
    return (
      <Card
        title="Save your recovery codes"
        hint="Shown once. Only hashes are stored, so these cannot be shown again."
      >
        <Banner tone="warning" className="mb-4">
          Store these somewhere safe now. Each code works once, and they are the only
          way back in if you lose your authenticator.
        </Banner>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {recovery.map((item) => (
            <li
              key={item}
              className="rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-center font-mono text-sm tracking-wider text-ink-800 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-100"
            >
              {item}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-sm"
            onClick={() => navigator.clipboard?.writeText(recovery.join('\n'))}
          >
            Copy all
          </button>
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            onClick={() => {
              setRecovery(null)
              void boot()
            }}
          >
            I have saved them
          </button>
        </div>
      </Card>
    )
  }

  if (user?.mfa_enabled) {
    return (
      <Card title="Two-factor authentication">
        <p className="flex items-center gap-2 text-sm text-positive">
          <IconShield width={16} height={16} />
          Enabled. A code from your authenticator is required at every sign-in.
        </p>
      </Card>
    )
  }

  return (
    <Card
      title="Two-factor authentication"
      hint="Strongly recommended for anyone who can administer a workspace."
    >
      {!enrol ? (
        <>
          <p className="mb-4 text-sm text-ink-600 dark:text-ink-300">
            A password alone can be phished or reused. A second factor means a stolen
            password is not enough on its own.
          </p>
          <button
            type="button"
            className="btn-primary px-3 py-1.5"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                setEnrol(await api.post<EnrolStart>('/auth/mfa/enrol'))
              } catch (caught) {
                toast.show(
                  'critical',
                  'Could not start setup',
                  caught instanceof ApiError ? caught.message : undefined,
                )
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy && <Spinner />}
            Set up two-factor
          </button>
        </>
      ) : (
        <form
          className="grid gap-5 sm:grid-cols-[auto_minmax(0,1fr)]"
          onSubmit={async (event) => {
            event.preventDefault()
            setBusy(true)
            try {
              const result = await api.post<{ recovery_codes: string[] }>(
                '/auth/mfa/enrol/confirm',
                { code },
              )
              setRecovery(result.recovery_codes)
            } catch (caught) {
              toast.show(
                'critical',
                'That code was not accepted',
                caught instanceof ApiError ? caught.message : undefined,
              )
            } finally {
              setBusy(false)
            }
          }}
        >
          <div
            className="h-40 w-40 rounded-lg bg-white p-2 [&_svg]:h-full [&_svg]:w-full"
            dangerouslySetInnerHTML={{ __html: enrol.qr_svg }}
          />
          <div>
            <ol className="mb-3 list-decimal space-y-1 pl-4 text-sm text-ink-600 dark:text-ink-300">
              <li>Scan the code with Google Authenticator, 1Password, or Authy.</li>
              <li>Enter the 6-digit code it shows.</li>
            </ol>
            <p className="mb-3 text-xs text-ink-400">
              Cannot scan? Enter this key manually:{' '}
              <code className="font-mono text-ink-600 dark:text-ink-300">{enrol.secret}</code>
            </p>
            <Field
              label="Code from your app"
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
              maxLength={6}
              required
              className="max-w-[160px] text-center font-mono text-xl tracking-[0.25em]"
            />
            <div className="mt-3 flex gap-2">
              <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
                {busy && <Spinner />}
                Confirm and enable
              </button>
              <button
                type="button"
                className="btn-secondary px-3 py-1.5"
                onClick={() => setEnrol(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </form>
      )}
    </Card>
  )
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
                  load()
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
        description="Your password, second factor, and the devices currently signed in."
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <MfaSection />
          <PasswordSection />
        </div>
        <div className="flex flex-col gap-5">
          <SessionsSection />
          <Card title="How your session is protected">
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
          </Card>
        </div>
      </div>
    </>
  )
}