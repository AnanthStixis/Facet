import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { Banner, Card, Chip, EmptyState, Field, Modal, Skeleton, Spinner } from '../components/ui'
import { IconBuilding } from '../components/icons'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, uploadFile } from '../lib/api'
import { TIMEZONES } from '../lib/timezones'
import type { OrgDetail, Paged } from '../lib/types'

type Pending = { id: string; action: 'approve' | 'reject' | 'suspend' | 'reactivate' } | null

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
  onDone: (inviteUrl: string | null) => void
  onCancel: () => void
}) {
  const [fullName, setFullName] = useState(org.contact_name)
  const [email, setEmail] = useState(org.contact_email)
  const [seatLimit, setSeatLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<OrgDetail>(`/orgs/${org.id}/approve`, {
        admin_full_name: fullName,
        admin_email: email,
        seat_limit: seatLimit ? Number(seatLimit) : null,
      })
      onDone(result.invite_url ?? null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Approval failed.')
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
        first Client Admin. No password is ever sent by email.
      </p>
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Client admin name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          required
        />
        <Field
          label="Client admin email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <Field
          label="Seat limit (optional)"
          type="number"
          min={1}
          value={seatLimit}
          onChange={(event) => setSeatLimit(event.target.value)}
          placeholder="Unlimited"
        />
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

function EditOrgForm({
  org,
  onCancel,
  onDone,
}: {
  org: OrgDetail
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const [form, setForm] = useState({
    name: org.name,
    contact_name: org.contact_name,
    contact_email: org.contact_email,
    contact_phone: org.contact_phone ?? '',
    country: org.country ?? '',
    timezone: org.timezone,
    seat_limit: org.seat_limit ? String(org.seat_limit) : '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      await api.patch(`/orgs/${org.id}`, {
        name: form.name,
        contact_name: form.contact_name,
        contact_email: form.contact_email,
        contact_phone: form.contact_phone || null,
        country: form.country || null,
        timezone: form.timezone,
        seat_limit: form.seat_limit ? Number(form.seat_limit) : null,
      })
      onDone(`${form.name}'s profile was updated.`)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('Could not save those changes.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={org.name} hint="Everything about this organization, in one place." onClose={onCancel}>
      <form onSubmit={submit}>
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field
          label="Organization name"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          error={fieldErrors.name}
          required
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
          onChange={(event) => setForm({ ...form, contact_email: event.target.value })}
          error={fieldErrors.contact_email}
          required
        />
        <Field
          label="Phone"
          value={form.contact_phone}
          onChange={(event) => setForm({ ...form, contact_phone: event.target.value })}
        />
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
        <Field
          label="Seat limit (optional)"
          type="number"
          min={1}
          value={form.seat_limit}
          onChange={(event) => setForm({ ...form, seat_limit: event.target.value })}
          placeholder="Unlimited"
        />
      </div>
      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
          {busy && <Spinner />}
          Save changes
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
      </form>
    </Modal>
  )
}

function ProvisionForm({
  onDone,
  onCancel,
}: {
  onDone: (name: string, inviteUrl: string | null) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState({
    name: '',
    slug: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    country: '',
    timezone: 'UTC',
    admin_full_name: '',
    admin_email: '',
    seat_limit: '',
  })
  const [logo, setLogo] = useState<File | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/

  const validators = {
    name: (v: string) => {
      if (!v.trim()) return 'Organization name is required.'
      if (v.trim().length < 2) return 'Must be at least 2 characters.'
      return null
    },
    slug: (v: string) => {
      if (!v) return null
      if (!SLUG_RE.test(v)) return 'Lowercase letters, digits and hyphens, 3-64 characters.'
      return null
    },
    contact_name: (v: string) => {
      if (!v.trim()) return 'Primary contact name is required.'
      if (v.trim().length < 2) return 'Must be at least 2 characters.'
      return null
    },
    contact_email: (v: string) => {
      if (!v.trim()) return 'Primary contact email is required.'
      if (!EMAIL_RE.test(v.trim())) return 'Enter a valid email address.'
      return null
    },
    admin_full_name: (v: string) => {
      if (!v.trim()) return 'Client admin name is required.'
      if (v.trim().length < 2) return 'Must be at least 2 characters.'
      return null
    },
    admin_email: (v: string) => {
      if (!v.trim()) return 'Client admin email is required.'
      if (!EMAIL_RE.test(v.trim())) return 'Enter a valid email address.'
      return null
    },
  } satisfies Record<string, (value: string) => string | null>

  type ValidatedField = keyof typeof validators

  const validateField = (field: ValidatedField, value: string) => {
    const message = validators[field](value)
    setFieldErrors((current) => {
      if (!message) {
        if (!(field in current)) return current
        const next = { ...current }
        delete next[field]
        return next
      }
      return { ...current, [field]: message }
    })
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()

    const errors: Record<string, string> = {}
    for (const field of Object.keys(validators) as ValidatedField[]) {
      const message = validators[field](form[field])
      if (message) errors[field] = message
    }
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      setError('Some fields need attention before this can be submitted.')
      return
    }

    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      const created = await api.post<OrgDetail>('/orgs', {
        name: form.name,
        slug: form.slug || null,
        contact_name: form.contact_name,
        contact_email: form.contact_email,
        contact_phone: form.contact_phone || null,
        country: form.country || null,
        timezone: form.timezone,
        admin_full_name: form.admin_full_name,
        admin_email: form.admin_email,
        seat_limit: form.seat_limit ? Number(form.seat_limit) : null,
      })
      if (logo) {
        // Best-effort: the org is already provisioned at this point, so a
        // logo upload failure should not be reported as a provisioning
        // failure — it can always be added later from the org's branding page.
        try {
          await uploadFile(`/orgs/${created.id}/logo`, logo)
        } catch {
          // ignored — see comment above
        }
      }
      onDone(form.name, created.invite_url ?? null)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('Provisioning failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-5" title="Provision an organization" hint="For a tenant that has already been vetted directly — this skips the approval queue and activates immediately.">
      <form onSubmit={submit} noValidate>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field
            label="Organization name"
            value={form.name}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, name: value })
              if (fieldErrors.name) validateField('name', value)
            }}
            onBlur={(event) => validateField('name', event.target.value)}
            error={fieldErrors.name}
            required
            autoFocus
            maxLength={200}
          />
          <Field
            label="Slug (optional)"
            value={form.slug}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, slug: value })
              if (fieldErrors.slug) validateField('slug', value)
            }}
            onBlur={(event) => validateField('slug', event.target.value)}
            error={fieldErrors.slug}
            placeholder="auto-generated from the name"
            maxLength={80}
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Time zone
            </span>
            <select
              className="field"
              value={form.timezone}
              onChange={(event) => setForm({ ...form, timezone: event.target.value })}
            >
              {TIMEZONES.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </label>
          <Field
            label="Primary contact name"
            value={form.contact_name}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, contact_name: value })
              if (fieldErrors.contact_name) validateField('contact_name', value)
            }}
            onBlur={(event) => validateField('contact_name', event.target.value)}
            error={fieldErrors.contact_name}
            required
            maxLength={150}
          />
          <Field
            label="Primary contact email"
            type="email"
            value={form.contact_email}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, contact_email: value })
              if (fieldErrors.contact_email) validateField('contact_email', value)
            }}
            onBlur={(event) => validateField('contact_email', event.target.value)}
            error={fieldErrors.contact_email}
            required
          />
          <Field
            label="Phone (optional)"
            value={form.contact_phone}
            onChange={(event) => setForm({ ...form, contact_phone: event.target.value })}
            maxLength={40}
          />
          <Field
            label="Client admin name"
            value={form.admin_full_name}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, admin_full_name: value })
              if (fieldErrors.admin_full_name) validateField('admin_full_name', value)
            }}
            onBlur={(event) => validateField('admin_full_name', event.target.value)}
            error={fieldErrors.admin_full_name}
            required
            hint="Receives the single-use activation link."
            maxLength={150}
          />
          <Field
            label="Client admin email"
            type="email"
            value={form.admin_email}
            onChange={(event) => {
              const value = event.target.value
              setForm({ ...form, admin_email: value })
              if (fieldErrors.admin_email) validateField('admin_email', value)
            }}
            onBlur={(event) => validateField('admin_email', event.target.value)}
            error={fieldErrors.admin_email}
            required
          />
          <Field
            label="Seat limit (optional)"
            type="number"
            min={1}
            value={form.seat_limit}
            onChange={(event) => setForm({ ...form, seat_limit: event.target.value })}
            placeholder="Unlimited"
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Logo (optional)
            </span>
            <div className="flex items-center gap-2">
              {logoPreview && (
                <img
                  src={logoPreview}
                  alt=""
                  className="h-9 w-9 shrink-0 rounded object-contain"
                />
              )}
              <input
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,image/webp"
                className="field py-1.5"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null
                  setLogo(file)
                  if (logoPreview) URL.revokeObjectURL(logoPreview)
                  setLogoPreview(file ? URL.createObjectURL(file) : null)
                }}
              />
            </div>
          </label>
        </div>
        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Provision and invite
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  )
}

function ReasonForm({
  label,
  confirmLabel,
  tone,
  onSubmit,
  onCancel,
}: {
  label: string
  confirmLabel: string
  tone: 'critical' | 'neutral'
  onSubmit: (reason: string) => Promise<void>
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await onSubmit(reason)
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : 'That did not work.')
          setBusy(false)
        }
      }}
      className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60"
    >
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <Field
        label={label}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        required
        minLength={3}
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
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paged<OrgDetail> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [provisioning, setProvisioning] = useState(false)
  const [editOrgId, setEditOrgId] = useState<string | null>(null)
  const [logoOrgId, setLogoOrgId] = useState<string | null>(null)
  const [logoPreviewUrl, setLogoPreviewUrl] = useState<string | null>(null)
  const [logoBusy, setLogoBusy] = useState(false)
  const [logoError, setLogoError] = useState<string | null>(null)

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

  const finish = (message: string, inviteUrl?: string | null) => {
    setPending(null)
    setNotice(message)
    setInviteLink(inviteUrl ?? null)
    load()
  }

  return (
    <>
      <PageHeader
        title="Organizations"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Every tenant on the platform. Self-registered organizations stay blocked until they are approved here."
        actions={
          !provisioning && (
            <button
              type="button"
              className="btn-primary px-3 py-1.5"
              onClick={() => setProvisioning(true)}
            >
              Provision organization
            </button>
          )
        }
      />

      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          <div>
            {notice}
            {/* Development convenience only; withheld in production, where
                the link is a bearer credential. Shown as a labelled link
                rather than the raw URL, so the token itself is not sitting
                in plain text on screen. */}
            {inviteLink && (
              <p className="mt-1">
                <button type="button" onClick={() => window.open(inviteLink, '_blank', 'noopener,noreferrer')} className="text-2xs font-medium underline">View invitation</button>
              </p>
            )}
          </div>
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {provisioning && (
        <ProvisionForm
          onCancel={() => setProvisioning(false)}
          onDone={(name, inviteUrl) => {
            setProvisioning(false)
            setNotice(`${name} provisioned and active. The client admin has been invited.`)
            setInviteLink(inviteUrl ?? null)
            load()
          }}
        />
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
                      {org.contact_name} &middot; {org.contact_email} &middot; {org.timezone}
                      {' '}&middot; <span className="tabular">{org.user_count}</span> user
                      {org.user_count === 1 ? '' : 's'}
                    </p>
                    {org.rejection_reason && (
                      <p className="mt-1 text-xs text-critical">
                        Rejected: {org.rejection_reason}
                      </p>
                    )}
                  </div>

                  {/* Inline confirm and cancel rather than a modal. */}
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {org.status === 'pending' && (
                      <>
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          onClick={() => setPending({ id: org.id, action: 'approve' })}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-3 py-1.5 text-sm"
                          onClick={() => setPending({ id: org.id, action: 'reject' })}
                        >
                          Reject
                        </button>
                      </>
                    )}
                    {org.status === 'active' && (
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-sm"
                        onClick={() => setPending({ id: org.id, action: 'suspend' })}
                      >
                        Suspend
                      </button>
                    )}
                    {org.status === 'suspended' && (
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-sm"
                        onClick={() => setPending({ id: org.id, action: 'reactivate' })}
                      >
                        Reactivate
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-secondary px-3 py-1.5 text-sm"
                      onClick={() => {
                        setLogoError(null)
                        setLogoOrgId(logoOrgId === org.id ? null : org.id)
                      }}
                    >
                      {org.branding?.logo_url ? 'Change logo' : 'Upload logo'}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary px-3 py-1.5 text-sm"
                      onClick={() => setEditOrgId(editOrgId === org.id ? null : org.id)}
                    >
                      Edit
                    </button>
                  </div>
                </div>

                {editOrgId === org.id && (
                  <EditOrgForm
                    org={org}
                    onCancel={() => setEditOrgId(null)}
                    onDone={(message) => {
                      setEditOrgId(null)
                      finish(message)
                    }}
                  />
                )}

                {logoOrgId === org.id && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-ink-200 bg-ink-50 p-3 dark:border-ink-700 dark:bg-ink-900/60">
                    {(logoPreviewUrl || org.branding?.logo_url) && (
                      <img
                        src={logoPreviewUrl ?? org.branding?.logo_url ?? undefined}
                        alt=""
                        className={clsx(
                          'h-8 w-8 shrink-0 rounded object-contain',
                          logoBusy && 'opacity-60',
                        )}
                      />
                    )}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/svg+xml,image/webp"
                      className="field max-w-xs py-1.5 text-sm"
                      disabled={logoBusy}
                      onChange={async (event) => {
                        const file = event.target.files?.[0]
                        if (!file) return
                        const localPreview = URL.createObjectURL(file)
                        setLogoPreviewUrl(localPreview)
                        setLogoBusy(true)
                        setLogoError(null)
                        try {
                          await uploadFile(`/orgs/${org.id}/logo`, file)
                          setLogoOrgId(null)
                          finish(`Logo updated for ${org.name}.`)
                        } catch (caught) {
                          setLogoError(
                            caught instanceof ApiError ? caught.message : 'Logo upload failed.',
                          )
                        } finally {
                          setLogoBusy(false)
                          setLogoPreviewUrl(null)
                          URL.revokeObjectURL(localPreview)
                        }
                      }}
                    />
                    {logoBusy && <Spinner />}
                    <button
                      type="button"
                      className="btn-secondary px-2.5 py-1 text-xs"
                      onClick={() => setLogoOrgId(null)}
                    >
                      Cancel
                    </button>
                    {logoError && <p className="w-full text-xs text-critical">{logoError}</p>}
                  </div>
                )}

                {pending?.id === org.id && pending.action === 'approve' && (
                  <ApprovalForm
                    org={org}
                    onCancel={() => setPending(null)}
                    onDone={(inviteUrl) =>
                      finish(`${org.name} approved and the admin invited.`, inviteUrl)
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
                      await api.post(`/orgs/${org.id}/reject`, { reason })
                      finish(`${org.name} was rejected.`)
                    }}
                  />
                )}
                {pending?.id === org.id && pending.action === 'suspend' && (
                  <ReasonForm
                    label="Reason for suspension"
                    confirmLabel="Suspend and sign everyone out"
                    tone="critical"
                    onCancel={() => setPending(null)}
                    onSubmit={async (reason) => {
                      await api.post(`/orgs/${org.id}/suspend`, { reason })
                      finish(`${org.name} suspended. All of its sessions were revoked.`)
                    }}
                  />
                )}
                {pending?.id === org.id && pending.action === 'reactivate' && (
                  <ReasonForm
                    label="Reason for reactivation"
                    confirmLabel="Reactivate"
                    tone="neutral"
                    onCancel={() => setPending(null)}
                    onSubmit={async (reason) => {
                      await api.post(`/orgs/${org.id}/reactivate`, { reason })
                      finish(`${org.name} is active again.`)
                    }}
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
