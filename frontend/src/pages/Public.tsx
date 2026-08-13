import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { FacetMark } from '../components/Logo'
import { IconCheck, IconShield } from '../components/icons'
import { Banner, Field, Spinner } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { TIMEZONES, TIMEZONE_FIELD_ENABLED } from '../lib/timezones'
import { useAuth } from '../store/auth'

function PublicFrame({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-50 px-4 py-12 dark:bg-ink-950">
      <div className="w-full max-w-lg animate-fade-up">
        <Link to="/login" className="mb-7 flex items-center gap-2.5">
          <span className="accent-text">
            <FacetMark size={26} />
          </span>
          <span className="text-lg font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            Facet
          </span>
        </Link>
        <div className="surface p-7">
          <h1 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            {title}
          </h1>
          <p className="mt-1.5 text-sm text-ink-500 dark:text-ink-400">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  )
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PHONE_RE = /^[+()0-9][0-9()\-.\s]{5,}$/

export function Register() {
  const [form, setForm] = useState({
    name: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [done, setDone] = useState<string | null>(null)

  if (done) {
    return (
      <PublicFrame title="Registration received" subtitle="Nothing further is needed from you right now.">
        <Banner tone="success">{done}</Banner>
        <p className="mt-5 text-sm text-ink-500 dark:text-ink-400">
          No account has been created yet. Once a platform administrator approves the
          organization, your primary contact receives a single-use link to set a
          password.
        </p>
        <Link to="/login" className="btn-secondary mt-6 inline-flex px-3 py-1.5">
          Back to sign in
        </Link>
      </PublicFrame>
    )
  }

  return (
    <PublicFrame
      title="Request access"
      subtitle="Register your organization. A platform administrator reviews every request before any account is created."
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          setError(null)

          const validation: Record<string, string> = {}
          if (form.name.trim().length < 2) {
            validation.name = 'Enter your organization name.'
          }
          if (form.contact_name.trim().length < 2) {
            validation.contact_name = 'Enter your name.'
          }
          if (!EMAIL_RE.test(form.contact_email.trim())) {
            validation.contact_email = 'Enter a valid work email.'
          }
          if (!PHONE_RE.test(form.contact_phone.trim())) {
            validation.contact_phone = 'Enter a valid phone number.'
          }
          if (!form.timezone) {
            validation.timezone = 'Choose a time zone.'
          }
          if (Object.keys(validation).length > 0) {
            setFieldErrors(validation)
            return
          }

          setBusy(true)
          setFieldErrors({})
          try {
            const result = await api.post<{ message: string }>('/orgs/register', form)
            setDone(result.message)
          } catch (caught) {
            if (caught instanceof ApiError) {
              setError(caught.message)
              setFieldErrors(caught.fieldErrors())
            } else {
              setError('Could not submit the registration.')
            }
          } finally {
            setBusy(false)
          }
        }}
      >
        {error && (
          <Banner tone="error" className="mb-4">
            {error}
          </Banner>
        )}
        <div className="space-y-4">
          <Field
            label="Organization name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            error={fieldErrors.name}
            required
            autoFocus
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Your name"
              value={form.contact_name}
              onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
              error={fieldErrors.contact_name}
              required
            />
            <Field
              label="Work email"
              type="email"
              value={form.contact_email}
              onChange={(event) => setForm({ ...form, contact_email: event.target.value })}
              error={fieldErrors.contact_email}
              required
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Phone"
              type="tel"
              value={form.contact_phone}
              onChange={(event) => setForm({ ...form, contact_phone: event.target.value })}
              error={fieldErrors.contact_phone}
              required
            />
            {/* Timezone is detected from the browser and sent silently with
                the form either way — TIMEZONE_FIELD_ENABLED only controls
                whether it's shown as an editable field at all. */}
            {TIMEZONE_FIELD_ENABLED && (
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                  Time zone
                </span>
                <select
                  className="field"
                  value={form.timezone}
                  onChange={(event) => setForm({ ...form, timezone: event.target.value })}
                  required
                >
                  <option value="" disabled>
                    Choose a time zone…
                  </option>
                  {[...new Set([form.timezone, ...TIMEZONES])].filter(Boolean).map((zone) => (
                    <option key={zone} value={zone}>
                      {zone}
                    </option>
                  ))}
                </select>
                {fieldErrors.timezone ? (
                  <span className="mt-1 block text-xs text-critical">{fieldErrors.timezone}</span>
                ) : (
                  /* Reports and exports resolve date ranges in this zone, so it is
                     captured up front rather than guessed later. */
                  <span className="mt-1 block text-xs text-ink-400">
                    Used for every date range in reports and exports.
                  </span>
                )}
              </label>
            )}
          </div>
        </div>

        <button type="submit" className="btn-primary mt-6 w-full py-2.5" disabled={busy}>
          {busy && <Spinner />}
          Submit for review
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-ink-500 dark:text-ink-400">
        Already have an account?{' '}
        <Link to="/login" className="accent-text font-medium hover:underline">
          Sign in
        </Link>
      </p>
    </PublicFrame>
  )
}

function SetPasswordForm({
  missingTokenTitle,
  missingTokenSubtitle,
  missingTokenBody,
  title,
  subtitle,
  endpoint,
  submitLabel,
  navigateTo,
}: {
  missingTokenTitle: string
  missingTokenSubtitle: string
  missingTokenBody: string
  title: string
  subtitle: string
  endpoint: string
  submitLabel: string
  navigateTo: string
}) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { logout } = useAuth()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  if (!token) {
    return (
      <PublicFrame title={missingTokenTitle} subtitle={missingTokenSubtitle}>
        <Banner tone="error">{missingTokenBody}</Banner>
      </PublicFrame>
    )
  }

  const mismatch = confirm.length > 0 && password !== confirm

  return (
    <PublicFrame title={title} subtitle={subtitle}>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          if (mismatch) return
          setBusy(true)
          setError(null)
          setFieldErrors({})
          try {
            await api.post(endpoint, { token, password })
            // /accept-invite and /reset-password are public routes, so
            // App.tsx force-displays phase as 'anonymous' here regardless of
            // whether this browser's cookie actually still holds a live
            // session underneath (an admin previewing their own invite link,
            // or — as happened in testing — an earlier account left signed
            // in). That means `phase` can never be trusted on this page to
            // decide whether a logout is needed — it's always unconditionally
            // called instead. For the common case (nobody was ever signed in
            // here), this 401s harmlessly and is swallowed below; the whole
            // point is catching the *other* case, where skipping this would
            // let /login's own boot() check silently restore that old
            // session and bounce back to its dashboard instead of showing a
            // login form for the person who just set this password.
            await logout().catch(() => undefined)
            navigate(navigateTo)
          } catch (caught) {
            if (caught instanceof ApiError) {
              setError(caught.message)
              setFieldErrors(caught.fieldErrors())
            } else {
              setError('Could not complete this request.')
            }
          } finally {
            setBusy(false)
          }
        }}
      >
        {error && (
          <Banner tone="error" className="mb-4">
            {error}
          </Banner>
        )}
        <div className="space-y-4">
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={fieldErrors.password}
            required
            autoFocus
            hint="At least 6 characters. Length matters more than symbols."
          />
          <Field
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            error={mismatch ? 'The two passwords do not match.' : undefined}
            required
          />
        </div>

        <ul className="mt-4 space-y-1.5 text-xs text-ink-500 dark:text-ink-400">
          <li className="flex items-center gap-1.5">
            <IconCheck width={13} height={13} className="accent-text" />
            Stored using argon2id — never in plain text, never recoverable.
          </li>
          <li className="flex items-center gap-1.5">
            <IconShield width={13} height={13} className="accent-text" />
            Checked against known breach corpora without ever leaving this server in full.
          </li>
        </ul>

        <button
          type="submit"
          className="btn-primary mt-6 w-full py-2.5"
          disabled={busy || mismatch}
        >
          {busy && <Spinner />}
          {submitLabel}
        </button>
      </form>
    </PublicFrame>
  )
}

export function AcceptInvite() {
  return (
    <SetPasswordForm
      missingTokenTitle="Invitation link is incomplete"
      missingTokenSubtitle="This link is missing its token."
      missingTokenBody="Open the link exactly as it appears in your invitation email, or ask your administrator to send a new one."
      title="Set your password"
      subtitle="This link works once and then stops working. Choose a password only you know."
      endpoint="/auth/accept-invite"
      submitLabel="Activate my account"
      navigateTo="/login?activated=1"
    />
  )
}

export function ResetPassword() {
  return (
    <SetPasswordForm
      missingTokenTitle="Reset link is incomplete"
      missingTokenSubtitle="This link is missing its token."
      missingTokenBody="Open the link exactly as it appears in your reset email, or ask your administrator to send a new one."
      title="Reset your password"
      subtitle="This link works once and then stops working. Every other session on your account was signed out when it was sent."
      endpoint="/auth/reset-password"
      submitLabel="Set new password"
      navigateTo="/login?reset=1"
    />
  )
}