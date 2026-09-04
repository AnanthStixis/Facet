import clsx from 'clsx'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { BrandLogo } from '../components/Logo'
import { IconArrowLeft } from '../components/icons'
// import { IconCheck, IconShield } from '../components/icons'
import { Banner, Field, InfoTooltip, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
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
        <Link
          to="/home"
          className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-ink-500 hover:text-ink-900 dark:text-ink-400 dark:hover:text-white"
        >
          <IconArrowLeft width={16} height={16} />
          Back to home
        </Link>
        <Link to="/home" className="mb-7 flex items-center">
          <BrandLogo height={28} />
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

// Display names, and monthly/yearly prices, match the marketing site's
// pricing cards (Basic/Standard/Enterprise) — `value` is the real thing
// the backend's OrgPlan understands and is what actually gets sent, same
// split as Home.tsx's TIERS array. Yearly price is ~2 months free versus
// paying monthly (10x monthly rather than 12x).
const PLAN_OPTIONS = [
  {
    value: 'starter',
    name: 'Basic',
    description: 'Up to 50 employees, 1 admin',
    monthlyPrice: '₹2,499',
    yearlyPrice: '₹24,990',
  },
  {
    value: 'growth',
    name: 'Standard',
    description: 'Up to 150 employees, 3 admins',
    monthlyPrice: '₹7,999',
    yearlyPrice: '₹79,990',
  },
  {
    value: 'enterprise',
    name: 'Enterprise',
    description: 'Unlimited employees and admins',
    monthlyPrice: '₹14,999',
    yearlyPrice: '₹149,990',
  },
]

// Same three tiers, used on the "Request access" form. No prices here —
// nothing is being purchased at this step. This is the applicant telling
// the Super Admin what they're after; the Admin sets the real plan and
// seat count when they approve (see OrgApprovalRequest on the backend).
const LICENSE_OPTIONS = PLAN_OPTIONS.map(({ value, name, description }) => ({
  value,
  name,
  description,
}))

type BillingCycle = 'monthly' | 'yearly'

export function Register() {
  const [params] = useSearchParams()
  // The License section only appears when this form was reached via a
  // pricing card's "Get Started" (Home.tsx sends ?plan=starter|growth|
  // enterprise there). The nav's "Register here" and the hero's plain
  // "Get Started" link to /register with no query string, and get the
  // simple form with no License step at all.
  const requestedPlanParam = params.get('plan')
  const showLicense = LICENSE_OPTIONS.some((option) => option.value === requestedPlanParam)

  const [form, setForm] = useState({
    name: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    requested_plan: showLicense ? requestedPlanParam! : 'starter',
  })
  const [busy, setBusy] = useState(false)
  const toast = useToast()
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
            const payload = showLicense ? form : { ...form, requested_plan: undefined }
            const result = await api.post<{ message: string }>('/orgs/register', payload)
            setDone(result.message)
          } catch (caught) {
            if (caught instanceof ApiError) {
              toast.show('critical', 'Could not submit the registration', caught.message)
              setFieldErrors(caught.fieldErrors())
            } else {
              toast.show('critical', 'Could not submit the registration')
            }
          } finally {
            setBusy(false)
          }
        }}
      >
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
          {showLicense && (
            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                License
              </span>
              <div className="grid gap-3 sm:grid-cols-3">
                {LICENSE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setForm({ ...form, requested_plan: option.value })}
                    className={clsx(
                      'rounded-lg border p-3 text-left transition-colors',
                      form.requested_plan === option.value
                        ? 'accent-border accent-soft-bg'
                        : 'border-ink-200 hover:border-ink-300 dark:border-ink-700 dark:hover:border-ink-600',
                    )}
                  >
                    <p
                      className={clsx(
                        'text-sm font-semibold',
                        form.requested_plan === option.value
                          ? 'accent-text'
                          : 'text-ink-900 dark:text-ink-50',
                      )}
                    >
                      {option.name}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">
                      {option.description}
                    </p>
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-ink-400 dark:text-ink-500">
                This is the license you're requesting. A platform administrator confirms
                your plan and seat count when they approve your organization.
              </p>
            </div>
          )}
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

export function Signup() {
  const [params] = useSearchParams()
  // Coming from a specific pricing card ("Get Started" on Home.tsx) carries
  // ?plan=starter|growth|enterprise — falls back to Basic for a direct
  // /signup visit, or an unrecognised value, rather than defaulting to
  // Enterprise silently.
  const requestedPlan = params.get('plan')
  const initialPlan = PLAN_OPTIONS.some((option) => option.value === requestedPlan)
    ? requestedPlan!
    : 'starter'
  const [form, setForm] = useState({
    name: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    password: '',
    plan: initialPlan,
  })
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [done, setDone] = useState<string | null>(null)
  const [billingCycle, setBillingCycle] = useState<BillingCycle>('monthly')

  const mismatch = confirm.length > 0 && form.password !== confirm

  if (done) {
    return (
      <PublicFrame title="Account created" subtitle="You're all set.">
        <Banner tone="success">{done}</Banner>
        <Link to="/login" className="btn-primary mt-6 inline-flex px-3 py-1.5">
          Sign in
        </Link>
      </PublicFrame>
    )
  }

  return (
    <PublicFrame
      title="Create your account"
      subtitle="Set up your organization and sign in immediately — no approval, no waiting."
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault()

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
          if (form.password.length < 6) {
            validation.password = 'At least 6 characters.'
          }
          if (mismatch) {
            validation.confirm = 'The two passwords do not match.'
          }
          if (Object.keys(validation).length > 0) {
            setFieldErrors(validation)
            return
          }

          setBusy(true)
          setFieldErrors({})
          try {
            const result = await api.post<{ message: string }>('/auth/self-register', form)
            setDone(result.message)
          } catch (caught) {
            if (caught instanceof ApiError) {
              toast.show('critical', 'Could not create your account', caught.message)
              setFieldErrors(caught.fieldErrors())
            } else {
              toast.show('critical', 'Could not create your account')
            }
          } finally {
            setBusy(false)
          }
        }}
      >
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
                {fieldErrors.timezone && (
                  <span className="mt-1 block text-xs text-critical">{fieldErrors.timezone}</span>
                )}
              </label>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Password"
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
              error={fieldErrors.password}
              required
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
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-sm font-medium text-ink-700 dark:text-ink-200">Plan</span>
              <div className="inline-flex rounded-md border border-ink-200 p-0.5 dark:border-ink-700">
                <button
                  type="button"
                  onClick={() => setBillingCycle('monthly')}
                  className={clsx(
                    'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                    billingCycle === 'monthly'
                      ? 'accent-bg text-white'
                      : 'text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200',
                  )}
                >
                  Monthly
                </button>
                <button
                  type="button"
                  onClick={() => setBillingCycle('yearly')}
                  className={clsx(
                    'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                    billingCycle === 'yearly'
                      ? 'accent-bg text-white'
                      : 'text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200',
                  )}
                >
                  Yearly
                </button>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {PLAN_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setForm({ ...form, plan: option.value })}
                  className={clsx(
                    'rounded-lg border p-3 text-left transition-colors',
                    form.plan === option.value
                      ? 'accent-border accent-soft-bg'
                      : 'border-ink-200 hover:border-ink-300 dark:border-ink-700 dark:hover:border-ink-600',
                  )}
                >
                  <p
                    className={clsx(
                      'flex items-center text-sm font-semibold',
                      form.plan === option.value
                        ? 'accent-text'
                        : 'text-ink-900 dark:text-ink-50',
                    )}
                  >
                    {option.name}
                    <InfoTooltip text={option.description} />
                  </p>
                  <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">
                    {billingCycle === 'monthly' ? option.monthlyPrice : option.yearlyPrice}
                    <span className="text-ink-400 dark:text-ink-500">
                      {billingCycle === 'monthly' ? '/mo' : '/yr'}
                    </span>
                  </p>
                </button>
              ))}
            </div>
          </div>
        </div>

        <button type="submit" className="btn-primary mt-6 w-full py-2.5" disabled={busy || mismatch}>
          {busy && <Spinner />}
          Create account
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
  const toast = useToast()
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
              toast.show('critical', 'Could not complete this request', caught.message)
              setFieldErrors(caught.fieldErrors())
            } else {
              toast.show('critical', 'Could not complete this request')
            }
          } finally {
            setBusy(false)
          }
        }}
      >
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