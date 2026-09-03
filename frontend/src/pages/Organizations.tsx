import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { Banner, Card, Chip, ConfirmDialog, EmptyState, Field, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { IconBuilding, IconEdit, IconEye } from '../components/icons'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, uploadFile } from '../lib/api'
import { COUNTRIES } from '../lib/countries'
import { TIMEZONES, TIMEZONE_FIELD_ENABLED } from '../lib/timezones'
import type { OrgDetail, Paged } from '../lib/types'

type Pending = { id: string; action: 'approve' | 'reject' | 'suspend' } | null

const STATUS_TABS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Awaiting review' },
  { value: 'active', label: 'Active' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'rejected', label: 'Rejected' },
]

function ApprovalForm({
  org,
  onDone,
  onCancel,
}: {
  org: OrgDetail
  onDone: (updated: OrgDetail) => void
  onCancel: () => void
}) {
  const toast = useToast()
  const [fullName, setFullName] = useState(org.contact_name)
  const [email, setEmail] = useState(org.contact_email)
  const [plan, setPlan] = useState('starter')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    try {
      const updated = await api.post<OrgDetail>(`/orgs/${org.id}/approve`, {
        admin_full_name: fullName,
        admin_email: email,
        plan,
      })
      onDone(updated)
    } catch (caught) {
      toast.show(
        'critical',
        'Approval failed',
        caught instanceof ApiError ? caught.message : 'Approval failed.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60"
    >
      <p className="mb-3 text-sm text-ink-600 dark:text-ink-300">
        Approving provisions the workspace and emails a single-use invitation to the
        first Admin. No password is ever sent by email.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Admin name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          required
        />
        <Field
          label="Admin email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Plan
          </span>
          <select
            className="field"
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
          >
            <option value="starter">Starter — up to 50 employees, 1 admin</option>
            <option value="growth">Growth — up to 150 employees, 3 admins</option>
            <option value="enterprise">Enterprise — unlimited</option>
          </select>
        </label>
      </div>
      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
          {busy && <Spinner />}
          Approve and invite
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

// Handles both creation and editing in one popup: same fields, same
// component, only the submit label and the admin-invite/logo section (which
// only make sense once, at creation) differ.
function OrgFormModal({
  org,
  onCancel,
  onDone,
}: {
  org: OrgDetail | null
  onCancel: () => void
  onDone: (message: string, updated: OrgDetail) => void
}) {
  const isEdit = !!org
  const [form, setForm] = useState({
    name: org?.name ?? '',
    contact_name: org?.contact_name ?? '',
    contact_email: org?.contact_email ?? '',
    contact_phone: org?.contact_phone ?? '',
    country: org?.country ?? '',
    timezone: org?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC',
    plan: org?.plan ?? 'starter',
    admin_full_name: '',
    admin_email: '',
  })
  const toast = useToast()
  const [logo, setLogo] = useState<File | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const setFieldError = (field: string, message: string | null) => {
    setFieldErrors((prev) => {
      const next = { ...prev }
      if (message) next[field] = message
      else delete next[field]
      return next
    })
  }

  // Field-level, not just on submit: checked again on submit below as a
  // final guard in case the input never blurred (e.g. a form filled by
  // pasting and hitting Enter).
  const validatePhone = (value: string) => {
    const ok = value.length === 10
    setFieldError('contact_phone', ok ? null : 'Enter a 10-digit phone number.')
    return ok
  }

  const DUPLICATE_EMAIL_MESSAGE = 'This email is already in use by another account.'
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

  // Only meaningful on create — editing an existing org's contact email
  // legitimately matches an already-existing user (its own admin) all the
  // time, so this only ever runs for a brand-new org's fields.
  const isEmailTaken = async (value: string): Promise<boolean> => {
    if (!value || !EMAIL_RE.test(value)) return false
    try {
      const result = await api.get<{ available: boolean }>(
        `/orgs/check-email?email=${encodeURIComponent(value)}`,
      )
      return !result.available
    } catch {
      return false // best-effort — the submit-time uniqueness check still catches it
    }
  }

  // A blur check still in flight and the submit-time re-check both hit the
  // same endpoint for the same field — without this, whichever happened to
  // land second would silently overwrite the other's result, and the error
  // message could flash in, clear, then flash back in. Each field's own
  // generation counter means only the most recent check for that field is
  // ever allowed to touch state.
  const emailCheckSeq = useRef<Record<string, number>>({})

  const checkFieldEmail = async (field: 'contact_email' | 'admin_email', value: string) => {
    if (isEdit) return
    const seq = (emailCheckSeq.current[field] = (emailCheckSeq.current[field] ?? 0) + 1)
    const taken = await isEmailTaken(value)
    if (emailCheckSeq.current[field] !== seq) return
    setFieldError(field, taken ? DUPLICATE_EMAIL_MESSAGE : null)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!validatePhone(form.contact_phone)) return
    // Authoritative at submit time, not just relying on whatever a prior
    // blur happened to leave in state — a field that was never blurred (form
    // filled by paste + Enter) would otherwise sail through unchecked. Busy
    // only flips on once this resolves clean, so a duplicate-email rejection
    // never shows a spinner that immediately vanishes.
    if (!isEdit) {
      const contactSeq = (emailCheckSeq.current.contact_email = (emailCheckSeq.current.contact_email ?? 0) + 1)
      const adminSeq = (emailCheckSeq.current.admin_email = (emailCheckSeq.current.admin_email ?? 0) + 1)
      const [contactTaken, adminTaken] = await Promise.all([
        isEmailTaken(form.contact_email),
        isEmailTaken(form.admin_email),
      ])
      const errors: Record<string, string> = {}
      if (emailCheckSeq.current.contact_email === contactSeq && contactTaken) {
        errors.contact_email = DUPLICATE_EMAIL_MESSAGE
      }
      if (emailCheckSeq.current.admin_email === adminSeq && adminTaken) {
        errors.admin_email = DUPLICATE_EMAIL_MESSAGE
      }
      if (Object.keys(errors).length) {
        setFieldErrors((prev) => ({ ...prev, ...errors }))
        return
      }
    }
    setBusy(true)
    setFieldErrors({})
    try {
      let orgId = org?.id
      let saved: OrgDetail
      if (isEdit) {
        saved = await api.patch<OrgDetail>(`/orgs/${org.id}`, {
          name: form.name,
          contact_name: form.contact_name,
          contact_email: form.contact_email,
          contact_phone: form.contact_phone || null,
          country: form.country || null,
          timezone: form.timezone,
          plan: form.plan,
        })
      } else {
        saved = await api.post<OrgDetail>('/orgs', {
          name: form.name,
          contact_name: form.contact_name,
          contact_email: form.contact_email,
          contact_phone: form.contact_phone || null,
          country: form.country || null,
          timezone: form.timezone,
          admin_full_name: form.admin_full_name,
          admin_email: form.admin_email,
          plan: form.plan,
        })
        orgId = saved.id
      }
      if (logo && orgId) {
        // Best-effort: the org is already saved at this point, so a logo
        // upload failure should not be reported as a save failure — it can
        // always be retried from here later.
        try {
          await uploadFile(`/orgs/${orgId}/logo`, logo)
        } catch {
          // ignored — see comment above
        }
      }
      onDone(
        isEdit
          ? `${form.name}'s profile was updated.`
          : `${form.name} created and active. The client admin has been invited.`,
        saved,
      )
    } catch (caught) {
      const title = isEdit ? 'Save failed' : 'Creation failed'
      if (caught instanceof ApiError) {
        toast.show('critical', title, caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        toast.show('critical', title, isEdit ? 'Could not save those changes.' : 'Could not create the organization.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={isEdit ? org.name : 'Create organization'}
      hint={isEdit ? 'Everything about this organization, in one place.' : undefined}
      onClose={onCancel}
    >
      <form onSubmit={submit}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field
            label="Organization name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            error={fieldErrors.name}
            required
            autoFocus={!isEdit}
          />
          <Field
            label="Primary contact name"
            value={form.contact_name}
            onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
            error={fieldErrors.contact_name}
            required
          />
          <Field
            label="Primary contact email"
            type="email"
            value={form.contact_email}
            onChange={(event) => {
              setForm({ ...form, contact_email: event.target.value })
              if (fieldErrors.contact_email) setFieldError('contact_email', null)
            }}
            onBlur={(event) => void checkFieldEmail('contact_email', event.target.value)}
            error={fieldErrors.contact_email}
            required
          />
          <Field
            label="Phone"
            type="tel"
            inputMode="numeric"
            maxLength={10}
            value={form.contact_phone}
            onChange={(event) =>
              setForm({ ...form, contact_phone: event.target.value.replace(/\D/g, '').slice(0, 10) })
            }
            onBlur={(event) => validatePhone(event.target.value)}
            error={fieldErrors.contact_phone}
            required
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Country
            </span>
            <select
              className="field"
              value={form.country}
              onChange={(event) => setForm({ ...form, country: event.target.value })}
            >
              <option value="">— select —</option>
              {COUNTRIES.map((country) => (
                <option key={country.code} value={country.code}>
                  {country.name}
                </option>
              ))}
            </select>
          </label>
          {!isEdit && (
            <>
              <Field
                label="Admin name"
                value={form.admin_full_name}
                onChange={(event) => setForm({ ...form, admin_full_name: event.target.value })}
                error={fieldErrors.admin_full_name}
                required
              />
              <Field
                label="Admin email"
                type="email"
                value={form.admin_email}
                onChange={(event) => {
                  setForm({ ...form, admin_email: event.target.value })
                  if (fieldErrors.admin_email) setFieldError('admin_email', null)
                }}
                onBlur={(event) => void checkFieldEmail('admin_email', event.target.value)}
                error={fieldErrors.admin_email}
                required
              />
            </>
          )}
          {TIMEZONE_FIELD_ENABLED && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Time zone
              </span>
              <select
                className="field"
                value={form.timezone}
                onChange={(event) => setForm({ ...form, timezone: event.target.value })}
              >
                {[...new Set([form.timezone, ...TIMEZONES])].map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Plan
            </span>
            <select
              className="field max-w-[260px]"
              value={form.plan}
              onChange={(event) => setForm({ ...form, plan: event.target.value })}
            >
              <option value="starter">Starter — up to 50 employees, 1 admin</option>
              <option value="growth">Growth — up to 150 employees, 3 admins</option>
              <option value="enterprise">Enterprise — unlimited</option>
            </select>
          </label>
        </div>

        <div className="mt-4">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Logo (optional)
          </span>
          <div className="flex items-center gap-4">
            {(logoPreview || org?.branding?.logo_url) && (
              <img
                src={logoPreview ?? org?.branding?.logo_url ?? undefined}
                alt=""
                className="h-20 w-20 shrink-0 rounded-lg border border-ink-200 object-contain dark:border-ink-700"
              />
            )}
            <input
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp"
              className="field py-2 text-sm"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null
                if (!file) return
                setLogo(file)
                if (logoPreview) URL.revokeObjectURL(logoPreview)
                setLogoPreview(URL.createObjectURL(file))
              }}
            />
          </div>
        </div>

        {/* Edit-only, per the client's explicit instruction — never shown on
            the create-org popup. */}
        {isEdit && <InviteAdminSection org={org} />}

        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
            {busy && <Spinner />}
            {isEdit ? 'Update' : 'Submit'}
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

// Read-only, fired by the eye icon in the row actions — shows the fields a
// Super Admin actually needs at a glance. Status appears exactly once, in
// the modal's own header, rather than repeated in the body.
function OrgDetailModal({ org, onClose }: { org: OrgDetail; onClose: () => void }) {
  const formatDate = (value?: string | null) =>
    value
      ? new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
      : '—'

  const countryName = COUNTRIES.find((c) => c.code === org.country)?.name ?? org.country ?? '—'

  const fields: { label: string; value: React.ReactNode }[] = [
    { label: 'Organization name', value: org.name },
    { label: 'Primary contact name', value: org.contact_name },
    { label: 'Primary contact email', value: org.contact_email },
    { label: 'Country', value: countryName },
    { label: 'Plan', value: org.plan.charAt(0).toUpperCase() + org.plan.slice(1) },
    { label: 'Users', value: org.user_count },
    { label: 'Created', value: formatDate(org.created_at) },
    { label: 'Approved', value: formatDate(org.approved_at) },
  ]

  return (
    <Modal
      title={
        <span className="inline-flex items-center gap-2">
          {org.name}
          <Chip value={org.status} />
        </span>
      }
      hint="Organization details"
      onClose={onClose}
    >
      {org.branding?.logo_url && (
        <img
          src={org.branding.logo_url}
          alt=""
          className="mb-4 h-14 w-14 rounded-lg border border-ink-200 object-contain dark:border-ink-700"
        />
      )}

      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map((f) => (
          <div key={f.label}>
            <p className="text-xs font-medium uppercase tracking-[0.04em] text-ink-400 dark:text-ink-500">
              {f.label}
            </p>
            <p className="mt-0.5 text-sm font-medium text-ink-900 dark:text-ink-50">{f.value}</p>
          </div>
        ))}
      </div>

      {(org.rejection_reason || org.suspension_reason) && (
        <div className="mt-5 border-t border-ink-200 pt-4 dark:border-ink-700">
          {org.rejection_reason && (
            <p className="text-sm text-critical">Rejected: {org.rejection_reason}</p>
          )}
          {org.suspension_reason && (
            <p className="text-sm text-caution">Suspended: {org.suspension_reason}</p>
          )}
        </div>
      )}

      <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}

// Edit-only: a Super Admin can add another Client Admin to an org that is
// already active, from that org's Edit popup specifically. Never rendered
// in create mode — see the `isEdit` gate where this is used below. Also
// gated defensively on `org.status === 'active'`, matching the backend's
// own check, since the Edit popup can still be opened for a suspended org.
function InviteAdminSection({ org }: { org: OrgDetail }) {
  const toast = useToast()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  if (org.status !== 'active') return null

  // Not a <form>: this section lives inside OrgFormModal's own <form>, and
  // HTML does not allow a nested <form> — the browser would misattribute
  // submit events between the two. This button submits directly instead.
  const submit = async () => {
    setBusy(true)
    setFieldErrors({})
    try {
      await api.post(`/orgs/${org.id}/invite-admin`, { full_name: fullName, email })
      toast.show('success', 'Admin invited', `An invitation was emailed to ${email}.`)
      setFullName('')
      setEmail('')
    } catch (caught) {
      if (caught instanceof ApiError) {
        toast.show('critical', 'Could not create Admin', caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        toast.show('critical', 'Could not create Admin', 'That did not work.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 border-t border-ink-200 pt-4 dark:border-ink-700">
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
        Add another Admin
      </span>
      <div className="grid gap-3 sm:grid-cols-3 sm:items-end">
        <Field
          label="Name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          error={fieldErrors.full_name}
          required
        />
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={fieldErrors.email}
          required
        />
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-sm"
          disabled={busy || !fullName.trim() || !email.trim()}
          onClick={() => void submit()}
        >
          {busy && <Spinner />}
          Create Admin
        </button>
      </div>
    </div>
  )
}

function ReasonForm({
  label,
  confirmLabel,
  tone,
  required = true,
  onSubmit,
  onCancel,
}: {
  label: string
  confirmLabel: string
  tone: 'critical' | 'neutral'
  required?: boolean
  onSubmit: (reason: string) => Promise<void>
  onCancel: () => void
}) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault()
        setBusy(true)
        try {
          await onSubmit(reason)
        } catch (caught) {
          toast.show(
            'critical',
            'Action failed',
            caught instanceof ApiError ? caught.message : 'That did not work.',
          )
          setBusy(false)
        }
      }}
      className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60"
    >
      <Field
        label={label}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        required={required}
        minLength={required ? 3 : undefined}
        placeholder="Recorded in the audit trail"
      />
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className={tone === 'critical' ? 'btn-danger px-3 py-1.5 text-sm' : 'btn-primary px-3 py-1.5 text-sm'}
        >
          {busy && <Spinner />}
          {confirmLabel}
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

const PAGE_SIZE = 15

export function Organizations() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const status = params.get('status') ?? ''
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paged<OrgDetail> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editOrgId, setEditOrgId] = useState<string | null>(null)
  const [viewOrgId, setViewOrgId] = useState<string | null>(null)
  const [reactivatingId, setReactivatingId] = useState<string | null>(null)
  // Captured from the reason form, then held here while the confirmation
  // dialog is open — the actual suspend API call only fires once that's
  // confirmed, not the moment a reason is typed in.
  const [confirmSuspend, setConfirmSuspend] = useState<{ org: OrgDetail; reason: string } | null>(null)
  const [suspending, setSuspending] = useState(false)

  // Guards against an out-of-order response overwriting a newer one. Without
  // this, rejecting an org and immediately switching tabs could have the
  // stale "pending" request (fired by finish()) resolve after the new tab's
  // request and silently overwrite it — the list would then look wrong until
  // a manual reload happened to fire the requests in the right order.
  const requestSeq = useRef(0)

  const load = () => {
    const seq = ++requestSeq.current
    setLoading(true)
    const query = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) })
    if (status) query.set('status', status)
    if (search) query.set('search', search)
    api
      .get<Paged<OrgDetail>>(`/orgs?${query}`)
      .then((result) => {
        if (seq !== requestSeq.current) return
        setData(result)
        setError(null)
      })
      .catch((caught) => {
        if (seq !== requestSeq.current) return
        setError(caught instanceof ApiError ? caught.message : 'Could not load organizations.')
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoading(false)
      })
  }

  useEffect(load, [status, search, page])
  useRefetchOnFocus(load)

  // Applied immediately from whatever the mutating request itself returned,
  // rather than waiting on the follow-up load() below — that request goes
  // out in parallel and reconciles anything this missed, but the row updates
  // the instant the action's own response comes back, not whenever the
  // second request happens to land.
  const patchOrg = (updated: OrgDetail) => {
    setData((current) =>
      current
        ? { ...current, items: current.items.map((o) => (o.id === updated.id ? updated : o)) }
        : current,
    )
  }

  const finish = (message: string, updated?: OrgDetail) => {
    setPending(null)
    if (updated) patchOrg(updated)
    toast.show('success', 'Done', message)
    load()
  }

  return (
    <>
      <PageHeader
        title="Organizations"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        actions={
          <button
            type="button"
            className="btn-primary px-3 py-1.5"
            onClick={() => setShowCreateModal(true)}
          >
            Create organization
          </button>
        }
      />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {showCreateModal && (
        <OrgFormModal
          org={null}
          onCancel={() => setShowCreateModal(false)}
          onDone={(message, updated) => {
            setShowCreateModal(false)
            finish(message, updated)
          }}
        />
      )}

      {editOrgId && data && (
        <>
          {data.items
            .filter((org) => org.id === editOrgId)
            .map((org) => (
              <OrgFormModal
                key={org.id}
                org={org}
                onCancel={() => setEditOrgId(null)}
                onDone={(message, updated) => {
                  setEditOrgId(null)
                  finish(message, updated)
                }}
              />
            ))}
        </>
      )}

      {viewOrgId && data && (
        <>
          {data.items
            .filter((org) => org.id === viewOrgId)
            .map((org) => (
              <OrgDetailModal key={org.id} org={org} onClose={() => setViewOrgId(null)} />
            ))}
        </>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="flex flex-wrap gap-1">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params)
                  if (tab.value) next.set('status', tab.value)
                  else next.delete('status')
                  setParams(next)
                  setPage(1)
                }}
                className={
                  status === tab.value
                    ? 'rounded-md accent-soft-bg px-2.5 py-1 text-xs font-medium accent-text'
                    : 'rounded-md px-2.5 py-1 text-xs text-ink-500 hover:bg-ink-100 dark:hover:bg-ink-800'
                }
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="ml-auto min-w-[200px]">
            <SearchBox
              value={search}
              onChange={(value) => {
                setSearch(value)
                setPage(1)
              }}
              placeholder="Search organizations"
            />
          </div>
        </div>

        {loading && !data ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={<IconBuilding width={19} height={19} />}
            title="No organizations here"
            body="Nothing matches this filter."
          />
        ) : (
          <ul
            className={clsx(
              'divide-y divide-ink-200 transition-opacity duration-150 dark:divide-ink-800',
              loading && 'opacity-50',
            )}
          >
            {data.items.map((org) => (
              <li key={org.id} className="px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-semibold text-ink-900 dark:text-ink-50">
                        {org.name}
                      </span>
                      <Chip value={org.status} />
                      {org.registration_source === 'self_service' && (
                        <span className="text-2xs uppercase tracking-[0.08em] text-ink-400">
                          Self-registered
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">
                      {org.contact_name} &middot; {org.contact_email} &middot;{' '}
                      <Link
                        to={`/people?org_id=${org.id}`}
                        state={{ orgName: org.name, from: 'organizations' }}
                        className="underline decoration-dotted underline-offset-2 hover:text-ink-800 dark:hover:text-ink-100"
                      >
                        <span className="tabular">{org.user_count}</span> user
                        {org.user_count === 1 ? '' : 's'}
                      </Link>
                    </p>
                    {org.rejection_reason && (
                      <p className="mt-1 text-xs text-critical">
                        Rejected: {org.rejection_reason}
                      </p>
                    )}
                    {org.suspension_reason && (
                      <p className="mt-1 text-xs text-caution">
                        Suspended: {org.suspension_reason}
                      </p>
                    )}
                  </div>

                  {/* Inline confirm and cancel rather than a modal. */}
                  <div className="flex shrink-0 flex-wrap items-center gap-3">
                                        {(org.status === 'pending' || org.status === 'rejected') && (
                      <>
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          onClick={() => setPending({ id: org.id, action: 'approve' })}
                        >
                          Approve
                        </button>
                        {org.status === 'pending' && (
                          <button
                            type="button"
                            className="btn-secondary px-3 py-1.5 text-sm"
                            onClick={() => setPending({ id: org.id, action: 'reject' })}
                          >
                            Reject
                          </button>
                        )}
                      </>
                    )}
                    {(org.status === 'active' || org.status === 'suspended') && (
                      <span className="flex items-center gap-2 text-xs text-ink-500 dark:text-ink-400">
                        {org.status === 'active' ? 'Active' : 'Suspended'}
                        <Switch
                          checked={org.status === 'active'}
                          disabled={reactivatingId === org.id}
                          ariaLabel={org.status === 'active' ? `Suspend ${org.name}` : `Reactivate ${org.name}`}
                          onChange={() => {
                            if (org.status === 'active') {
                              // Suspension has real consequences (kills every
                              // session in the org) — worth a reason. Turning
                              // it back on doesn't, so the toggle just acts,
                              // the way a switch is expected to behave.
                              setPending({ id: org.id, action: 'suspend' })
                              return
                            }
                            setReactivatingId(org.id)
                            api
                              .post<OrgDetail>(`/orgs/${org.id}/reactivate`, {})
                              .then((updated) => finish(`${org.name} is active again.`, updated))
                              .catch((caught) => {
                                toast.show(
                                  'critical',
                                  'Reactivation failed',
                                  caught instanceof ApiError ? caught.message : 'That did not work.',
                                )
                              })
                              .finally(() => setReactivatingId(null))
                          }}
                        />
                      </span>
                    )}
                    <button
                      type="button"
                      className="btn-secondary p-1.5"
                      aria-label={`View ${org.name}`}
                      title="View"
                      onClick={() => setViewOrgId(org.id)}
                    >
                      <IconEye width={15} height={15} />
                    </button>
                    {org.status !== 'rejected' && (
                      <button
                        type="button"
                        className="btn-secondary p-1.5"
                        aria-label={`Edit ${org.name}`}
                        title="Edit"
                        onClick={() => setEditOrgId(org.id)}
                      >
                        <IconEdit width={15} height={15} />
                      </button>
                    )}
                  </div>
                </div>

                {pending?.id === org.id && pending.action === 'approve' && (
                  <ApprovalForm
                    org={org}
                    onCancel={() => setPending(null)}
                    onDone={(updated) =>
                      finish(`${org.name} approved and the client admin invited.`, updated)
                    }
                  />
                )}
                {pending?.id === org.id && pending.action === 'reject' && (
                  <ReasonForm
                    label="Reason for rejection"
                    confirmLabel="Reject registration"
                    tone="critical"
                    onCancel={() => setPending(null)}
                    onSubmit={async (reason) => {
                      const updated = await api.post<OrgDetail>(`/orgs/${org.id}/reject`, { reason })
                      finish(`${org.name} was rejected.`, updated)
                    }}
                  />
                )}
                                {pending?.id === org.id && pending.action === 'suspend' && (
                  <ReasonForm
                    label="Reason for suspension"
                    confirmLabel="Suspend organization"
                    tone="critical"
                    onCancel={() => setPending(null)}
                    onSubmit={async (reason) => {
                      setPending(null)
                      setConfirmSuspend({ org, reason })
                    }}
                  />
                )}
                {confirmSuspend?.org.id === org.id && (
                  <ConfirmDialog
                    title={`Suspend ${org.name}?`}
                    body={`All users${org.user_count === 1 ? '' : 's'} will be signed out immediately and won't be able to sign back in until the organization is reactivated.`}
                    confirmLabel="Suspend "
                    tone="critical"
                    busy={suspending}
                    onConfirm={async () => {
                      setSuspending(true)
                      try {
                        const updated = await api.post<OrgDetail>(`/orgs/${org.id}/suspend`, {
                          reason: confirmSuspend.reason,
                        })
                        setConfirmSuspend(null)
                        finish(`${org.name} suspended. All of its sessions were revoked.`, updated)
                      } catch (caught) {
                        toast.show(
                          'critical',
                          'Suspension failed',
                          caught instanceof ApiError ? caught.message : 'That did not work.',
                        )
                      } finally {
                        setSuspending(false)
                      }
                    }}
                    onCancel={() => setConfirmSuspend(null)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        {data && data.total > 0 && (
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            onPage={setPage}
          />
        )}
      </Card>
    </>
  )
}