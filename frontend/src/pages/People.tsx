import clsx from 'clsx'
import { Fragment, useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { LookupFilter, SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { Banner, Card, Chip, EmptyState, Field, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { IconEdit, IconEye, IconUsers } from '../components/icons'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, downloadFile, uploadFile } from '../lib/api'
import { ROLE_LABEL } from '../lib/types'
import type { LookupItem, Paged, Role, User } from '../lib/types'
import { useAuth } from '../store/auth'

interface InviteResult {
  user: User
  invite_url: string | null
  email_sent: boolean
}

interface UserFeedbackItem {
  cycle_id: string
  cycle_name: string
  kind: string
  template_name: string | null
  relationship: string
  submitted_at: string
  overall_score: number | null
  comment: string | null
}

interface TemplateOption {
  id: string
  name: string
  status: string | null
  target_type: string
  is_anonymous: boolean
}

/** Popup showing everything collected about one person, plus a way to send
 * more — the People-page counterpart to Results.tsx's per-round detail. */
function FeedbackHistoryModal({
  person,
  canSend,
  onClose,
  onSend,
}: {
  person: User
  canSend: boolean
  onClose: () => void
  onSend: () => void
}) {
  const [items, setItems] = useState<UserFeedbackItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<UserFeedbackItem[]>(`/users/${person.id}/feedback`)
      .then(setItems)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load feedback.'),
      )
  }, [person.id])

  return (
    <Modal
      title={person.full_name}
      hint="Every piece of feedback collected about this person."
      onClose={onClose}
    >
      {error && <Banner tone="error">{error}</Banner>}
      {!error && !items && <Skeleton className="h-32 w-full rounded-lg" />}
      {items && items.length === 0 && (
        <p className="py-6 text-center text-sm text-ink-500">No feedback collected yet.</p>
      )}
      {items && items.length > 0 && (
        <ul className="space-y-3">
          {items.map((item, index) => (
            <li key={index} className="rounded-lg border border-ink-200 p-3 dark:border-ink-700">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink-900 dark:text-ink-50">
                  {item.cycle_name}
                </span>
                <span className="text-2xs text-ink-400">
                  {new Date(item.submitted_at).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              </div>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-ink-400">
                <Chip value={item.kind} />
                {item.template_name && <span>{item.template_name}</span>}
                {item.overall_score !== null && (
                  <span className="tabular">Score {item.overall_score.toFixed(2)}</span>
                )}
              </p>
              {item.comment && (
                <p className="mt-1.5 text-sm text-ink-700 dark:text-ink-200">{item.comment}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onClose}>
          Close
        </button>
        {/* An org-less Super Admin can only send feedback about a Client
            Admin — they aren't part of any org's own reporting chart, so an
            Employees Review against an employee/manager row wouldn't make
            sense. A Client Admin (or anyone acting within an org) can send
            to anyone in their own org's list — org membership is what
            unlocks this, not a specific role. */}
        {canSend && (
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            onClick={() => {
              onClose()
              onSend()
            }}
          >
            Send feedback
          </button>
        )}
      </div>
    </Modal>
  )
}


/** "Manager" column cell — a compact count badge, same visual pattern as
 * the Feedback column's pill in this same table (accent when non-zero,
 * muted grey at zero), rather than the names themselves inline. Names in
 * the cell made every row's width depend on how many managers that one
 * person happened to have, which is exactly what made the column
 * inconsistent and overly wide; a fixed-width badge doesn't. Clicking opens
 * a small popup with the full list. */
/** "Manager" column cell — plain comma-joined names up to 3; beyond that,
 * the first 3 plus a "+N more" trigger opens a small, numbered popup
 * listing every manager (smaller than the app's default modal width, since
 * a short name list doesn't need it). */
function ManagerCell({ managers }: { managers: LookupItem[] }) {
  const [open, setOpen] = useState(false)

  if (managers.length === 0) {
    return <span className="text-ink-600 dark:text-ink-300">—</span>
  }

  if (managers.length <= 3) {
    return (
      <span className="text-ink-600 dark:text-ink-300">
        {managers.map((manager) => manager.label).join(', ')}
      </span>
    )
  }

  const visible = managers.slice(0, 3)
  const hidden = managers.length - visible.length

  return (
    <>
      <span className="text-ink-600 dark:text-ink-300">
        {visible.map((manager) => manager.label).join(', ')}{' '}
        <button
          type="button"
          className="accent-text font-medium hover:opacity-80"
          onClick={() => setOpen(true)}
        >
          +{hidden} more
        </button>
      </span>
      {open && (
        <Modal title="Managers" onClose={() => setOpen(false)} className="max-w-[26rem]" centered>
          <ol className="space-y-1.5">
            {managers.map((manager, index) => (
              <li key={manager.id} className="flex gap-2 text-sm text-ink-800 dark:text-ink-100">
                <span className="shrink-0 tabular text-ink-400">{index + 1}.</span>
                <span>
                  {manager.label}
                  {manager.sublabel && (
                    <span className="text-ink-400"> · {manager.sublabel}</span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </Modal>
      )}
    </>
  )
}

/** Read-only, fired by the eye icon in the row actions — every field on
 * User in one place. Status appears once, in the modal's own header, same
 * pattern as Organizations.tsx's OrgDetailModal. */
function UserDetailModal({ person, onClose }: { person: User; onClose: () => void }) {
  const formatDate = (value?: string | null) =>
    value
      ? new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
      : '—'

  const fields: { label: string; value: React.ReactNode }[] = [
    { label: 'Full name', value: person.full_name },
    { label: 'Email', value: person.email },
    { label: 'Phone', value: person.phone || '—' },
    { label: 'Role', value: ROLE_LABEL[person.role] },
    { label: 'Organization', value: person.org_name || '—' },
    { label: 'Department', value: person.department || '—' },
    { label: 'Job title', value: person.job_title || '—' },
    { label: 'Feedback received', value: person.feedback_count ?? 0 },
    { label: 'Joined', value: formatDate(person.created_at) },
    { label: 'Last signed in', value: formatDate(person.last_login_at) },
  ]

  return (
    <Modal
      title={
        <span className="inline-flex items-center gap-2">
          {person.full_name}
          <Chip value={person.status} />
        </span>
      }
      hint="User details"
      onClose={onClose}
    >
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

      <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}

/** Inline panel (not a route change) to send one Employees Review to several
 * people at once — each selected person gets their own POST /feedback call,
 * since each gets their own ReviewCycle underneath. */
function BulkSendPanel({
  people,
  onRemove,
  onDone,
  onCancel,
}: {
  people: User[]
  onRemove: (id: string) => void
  onDone: () => void
  onCancel: () => void
}) {
  const toast = useToast()
  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [templateId, setTemplateId] = useState('')
  const [name, setName] = useState('')
  const [closesAt, setClosesAt] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<{ templates: TemplateOption[] }[]>('/catalog/categories')
      .then((categories) =>
        setTemplates(
          categories
            .flatMap((category) => category.templates)
            .filter((t) => t.status === 'published' && t.target_type === 'employee'),
        ),
      )
      .catch(() => setTemplates([]))
  }, [])

  const send = async () => {
    setBusy(true)
    let sent = 0
    const failed: string[] = []
    for (const person of people) {
      try {
        await api.post('/feedback', {
          kind: 'employee',
          template_id: templateId,
          name: name.trim() || `${person.full_name} — feedback`,
          closes_at: closesAt ? new Date(closesAt).toISOString() : null,
          reviewee_user_id: person.id,
        })
        sent += 1
      } catch {
        failed.push(person.full_name)
      }
    }
    setBusy(false)
    toast.show(
      failed.length ? 'warning' : 'success',
      'Feedback sent',
      failed.length
        ? `${sent} of ${people.length} sent. Failed for: ${failed.join(', ')}.`
        : `Sent to ${sent} ${sent === 1 ? 'person' : 'people'}.`,
    )
    onDone()
  }

  return (
    <Card className="mb-4" title="Send feedback to selected people">
      <div className="mb-3 flex flex-wrap gap-1.5">
        {people.map((person) => (
          <span
            key={person.id}
            className="flex items-center gap-1.5 rounded-full bg-ink-100 py-1 pl-2.5 pr-1.5 text-xs text-ink-700 dark:bg-ink-800 dark:text-ink-200"
          >
            {person.full_name}
            <button
              type="button"
              className="rounded-full p-0.5 hover:bg-ink-200 dark:hover:bg-ink-700"
              onClick={() => onRemove(person.id)}
              aria-label={`Remove ${person.full_name}`}
            >
              &times;
            </button>
          </span>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Template
          </span>
          <select
            className="field"
            value={templateId}
            onChange={(event) => setTemplateId(event.target.value)}
          >
            <option value="">Choose a template</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <Field
          label="Name (optional)"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Defaults to each person's own name"
        />
        <Field
          label="Closes on (optional)"
          type="date"
          value={closesAt}
          onChange={(event) => setClosesAt(event.target.value)}
        />
      </div>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          disabled={busy || people.length === 0 || !templateId}
          onClick={send}
        >
          {busy && <Spinner />}
          Send to {people.length}
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Card>
  )
}

interface MasterOption {
  id: string
  name: string
}

/** Dropdown backed by a master list (Department / Job Title), with an inline
 * "Add new" that creates the master row and selects it — same idempotent
 * find-or-select flow as the cycle-name picker on Create Feedback, just as a
 * plain select instead of a search popup since these lists are usually
 * short. */
function MasterSelect({
  path,
  label,
  value,
  onChange,
}: {
  path: string
  label: string
  value: string
  onChange: (name: string) => void
}) {
  const [options, setOptions] = useState<MasterOption[]>([])
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => {
    api
      .get<{ items: MasterOption[] }>(`${path}?page_size=200`)
      .then((page) => setOptions(page.items))
      .catch(() => setOptions([]))
  }

  useEffect(load, [path])

  const addNew = async () => {
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    try {
      const created = await api.post<MasterOption>(path, { name })
      setOptions((state) =>
        state.some((o) => o.id === created.id)
          ? state
          : [...state, created].sort((a, b) => a.name.localeCompare(b.name)),
      )
      onChange(created.name)
      setNewName('')
      setAdding(false)
    } catch {
      // Duplicate name racing another tab — just pick it up from a reload.
      load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">{label}</span>
      {adding ? (
        <div className="flex items-center gap-2">
          <input
            className="field flex-1"
            autoFocus
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder={`New ${label.toLowerCase()}`}
          />
          <button
            type="button"
            className="btn-primary shrink-0 px-2.5 py-1.5 text-sm"
            disabled={busy || !newName.trim()}
            onClick={addNew}
          >
            {busy && <Spinner />}
            Add
          </button>
          <button
            type="button"
            className="btn-secondary shrink-0 px-2.5 py-1.5 text-sm"
            onClick={() => {
              setAdding(false)
              setNewName('')
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <select
            className="field flex-1"
            value={value}
            onChange={(event) => onChange(event.target.value)}
          >
            <option value="">Not set</option>
            {options.map((option) => (
              <option key={option.id} value={option.name}>
                {option.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-secondary shrink-0 px-2.5 py-1.5 text-base leading-none"
            aria-label={`Add a new ${label.toLowerCase()}`}
            onClick={() => setAdding(true)}
          >
            +
          </button>
        </div>
      )}
    </div>
  )
}

const ROLES: { value: Role; label: string; hint: string }[] = [
  { value: 'client_admin', label: 'Admin', hint: 'Full control of this workspace' },
  { value: 'manager', label: 'Manager', hint: 'Runs campaigns, reviews their team' },
  { value: 'employee', label: 'Employee', hint: 'Gives and receives feedback' },
]

const ROLE_TABS = [{ value: '', label: 'All' }, ...ROLES.map(({ value, label }) => ({ value, label }))]


function InvitePanel({ onInvited }: { onInvited: (result: InviteResult) => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    role: 'employee' as Role,
    manager_ids: [] as string[],
    job_title: '',
    department: '',
    phone: '',
  })
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  if (!open) {
    return (
      <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setOpen(true)}>
        Create
      </button>
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setFieldErrors({})
    try {
      const isOrgChartRole = form.role === 'employee' || form.role === 'manager'
      const result = await api.post<InviteResult>('/users', {
        ...form,
        manager_ids: isOrgChartRole ? form.manager_ids : [],
        job_title: form.job_title || null,
        department: form.department || null,
        phone: form.phone || null,
      })
      onInvited(result)
      setOpen(false)
      setForm({
        full_name: '',
        email: '',
        role: 'employee',
        manager_ids: [],
        job_title: '',
        department: '',
        phone: '',
      })
    } catch (caught) {
      if (caught instanceof ApiError) {
        toast.show('critical', 'Invitation failed', caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        toast.show('critical', 'Invitation failed', 'The invitation could not be sent.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-5" title="Create">
      <form onSubmit={submit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Full name"
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            error={fieldErrors.full_name}
            required
          />
          <Field
            label="Work email"
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            error={fieldErrors.email}
            required
          />
          <Field
            label="Phone (optional)"
            type="tel"
            value={form.phone}
            onChange={(event) => setForm({ ...form, phone: event.target.value })}
          />
          <MasterSelect
            path="/masters/departments"
            label="Department"
            value={form.department}
            onChange={(name) => setForm({ ...form, department: name })}
          />
          <MasterSelect
            path="/masters/job-titles"
            label="Job title"
            value={form.job_title}
            onChange={(name) => setForm({ ...form, job_title: name })}
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Role
            </span>
            <select
              className="field"
              value={form.role}
              onChange={(event) =>
                setForm({ ...form, role: event.target.value as Role, manager_ids: [] })
              }
            >
              {ROLES.map((role) => (
                <option key={role.value} value={role.value}>
                  {role.label}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-ink-500 dark:text-ink-400">
              {ROLES.find((role) => role.value === form.role)?.hint}
            </span>
          </label>
          {(form.role === 'employee' || form.role === 'manager') && (
            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Manager(s)
              </span>
              <LookupFilter
                entity="users"
                label="Choose manager(s)"
                selected={form.manager_ids}
                onChange={(ids) => setForm({ ...form, manager_ids: ids })}
              />
              <span className="mt-1.5 block text-xs text-ink-400">
                Someone can report to more than one manager — check every manager that applies.
              </span>
            </div>
          )}
        </div>

        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Submit
          </button>
          <button
            type="button"
            className="btn-secondary px-3 py-1.5"
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
        </div>
      </form>
    </Card>
  )
}

function EditUserForm({
  person,
  canChangeRole,
  onCancel,
  onDone,
}: {
  person: User
  canChangeRole: boolean
  onCancel: () => void
  onDone: (updated: User) => void
}) {
  const toast = useToast()
  const [form, setForm] = useState({
    full_name: person.full_name,
    job_title: person.job_title ?? '',
    department: person.department ?? '',
    phone: person.phone ?? '',
    role: person.role,
    manager_ids: person.manager_ids ?? [],
  })
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [resetBusy, setResetBusy] = useState(false)

  const resetPassword = async () => {
    setResetBusy(true)
    try {
      const result = await api.post<{ message: string; reset_url: string | null }>(
        `/users/${person.id}/reset-password`,
      )
      toast.show(
        'success',
        'Password reset',
        result.reset_url ? `${result.message} ${result.reset_url}` : result.message,
      )
    } catch (caught) {
      toast.show(
        'critical',
        'Password reset failed',
        caught instanceof ApiError ? caught.message : 'Could not send a reset link.',
      )
    } finally {
      setResetBusy(false)
    }
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setFieldErrors({})
    try {
      const updated = await api.patch<User>(`/users/${person.id}`, {
        full_name: form.full_name,
        job_title: form.job_title || null,
        department: form.department || null,
        phone: form.phone || null,
        role: canChangeRole && form.role !== person.role ? form.role : undefined,
        manager_ids: form.manager_ids,
      })
      onDone(updated)
    } catch (caught) {
      if (caught instanceof ApiError) {
        toast.show('critical', 'Save failed', caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        toast.show('critical', 'Save failed', 'Could not save those changes.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={person.full_name} onClose={onCancel}>
      <form onSubmit={submit}>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-500 dark:text-ink-400">
            <span>{person.email}</span>
            <span className="flex items-center gap-1">
              <Chip value={person.status} />
            </span>
            {person.created_at && (
              <span>Joined {new Date(person.created_at).toLocaleDateString()}</span>
            )}
            {person.last_login_at && (
              <span>Last signed in {new Date(person.last_login_at).toLocaleDateString()}</span>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Full name"
              value={form.full_name}
              onChange={(event) => setForm({ ...form, full_name: event.target.value })}
              error={fieldErrors.full_name}
              required
            />
            <MasterSelect
              path="/masters/job-titles"
              label="Job title"
              value={form.job_title}
              onChange={(name) => setForm({ ...form, job_title: name })}
            />
            <MasterSelect
              path="/masters/departments"
              label="Department"
              value={form.department}
              onChange={(name) => setForm({ ...form, department: name })}
            />
            <Field
              label="Phone"
              type="tel"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
            />
            {canChangeRole ? (
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                  Role
                </span>
                <select
                  className="field"
                  value={form.role}
                  onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
                >
                  {ROLES.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div>
                <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                  Role
                </span>
                <p className="text-xs text-ink-400">You cannot change your own role.</p>
              </div>
            )}
            {(form.role === 'employee' || form.role === 'manager') && (
              <div>
                <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                  Manager(s)
                </span>
                <LookupFilter
                  entity="users"
                  label="Choose manager(s)"
                  selected={form.manager_ids}
                  onChange={(ids) => setForm({ ...form, manager_ids: ids })}
                />
                <span className="mt-1.5 block text-xs text-ink-400">
                  Someone can report to more than one manager — check every manager that applies.
                </span>
              </div>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
              {busy && <Spinner />}
              Save changes
            </button>
            <button
              type="button"
              className="btn-secondary px-3 py-1.5 text-sm"
              onClick={onCancel}
            >
              Cancel
            </button>
            {person.status === 'active' && (
              <button
                type="button"
                className="btn-ghost ml-auto px-3 py-1.5 text-sm"
                disabled={resetBusy}
                onClick={resetPassword}
              >
                {resetBusy && <Spinner />}
                Send password reset link
              </button>
            )}
          </div>
      </form>
    </Modal>
  )
}

interface BulkResult {
  invited: number
  skipped: { row: number; email?: string; reason: string }[]
  total_rows: number
}

const MAX_BULK_ROWS = 100

// A rough client-side row count — good enough to confirm "how many" and to
// reject an oversized file before it ever leaves the browser. The server
// re-parses and re-validates properly; this is just for the confirmation
// prompt and an early, cheap rejection.
function countCsvRows(text: string): number {
  return text
    .split(/\r?\n/)
    .slice(1) // header
    .filter((line) => line.trim().length > 0).length
}

function BulkInvitePanel({ onDone }: { onDone: (result: BulkResult) => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<{ file: File; rowCount: number } | null>(null)

  const runUpload = async (file: File) => {
    setBusy(true)
    try {
      const result = await uploadFile<BulkResult>('/users/bulk', file)
      onDone(result)
      setOpen(false)
      setPending(null)
    } catch (caught) {
      toast.show(
        'critical',
        'Bulk invite failed',
        caught instanceof ApiError ? caught.message : 'The upload failed.',
      )
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="btn-secondary accent-soft-bg accent-text px-3 py-1.5"
        onClick={() => setOpen(true)}
      >
        Bulk invite
      </button>
    )
  }

  return (
    <Card className="mb-5" title="Bulk invite from a spreadsheet" hint="Upload a CSV with full_name and email columns (role, job_title, department are optional). Each row is invited exactly like a single invite. Up to 100 rows per file.">
      {busy ? (
        <div className="space-y-2">
          <div className="h-2 w-full overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
            <div className="accent-bg h-full w-full origin-left animate-pulse" />
          </div>
          <p className="text-sm text-ink-500 dark:text-ink-400">
            Registering {pending?.rowCount ?? ''} user{pending?.rowCount === 1 ? '' : 's'}…
          </p>
        </div>
      ) : pending ? (
        <div>
          <p className="mb-3 text-sm text-ink-700 dark:text-ink-200">
            <strong>{pending.rowCount}</strong> user{pending.rowCount === 1 ? '' : 's'} found in{' '}
            <span className="font-medium">{pending.file.name}</span>. Invite all of them?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-sm"
              onClick={() => void runUpload(pending.file)}
            >
              Yes, invite {pending.rowCount}
            </button>
            <button
              type="button"
              className="btn-secondary px-3 py-1.5 text-sm"
              onClick={() => setPending(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-sm"
            onClick={() => downloadFile('/users/bulk/template', 'user_invite_template.csv')}
          >
            Download template
          </button>
          <label className="btn-primary cursor-pointer px-3 py-1.5 text-sm">
            Choose CSV file
            <input
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={async (event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                if (!file) return
                const text = await file.text()
                const rowCount = countCsvRows(text)
                if (rowCount === 0) {
                  toast.show('critical', 'No data rows', 'That file has no data rows.')
                  return
                }
                if (rowCount > MAX_BULK_ROWS) {
                  toast.show(
                    'critical',
                    'File too large',
                    `This file has ${rowCount} rows. Bulk invite is limited to ${MAX_BULK_ROWS} at a time — split it into smaller files.`,
                  )
                  return
                }
                setPending({ file, rowCount })
              }}
            />
          </label>
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-sm"
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
        </div>
      )}
    </Card>
  )
}

const PAGE_SIZE = 15

export function People() {
  const toast = useToast()
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const { user, organization } = useAuth()
  const [params, setParams] = useSearchParams()
  const role = params.get('role') ?? ''
  const orgId = params.get('org_id') ?? ''
  const orgName = (location.state as { orgName?: string } | null)?.orgName
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paged<User> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [viewingId, setViewingId] = useState<string | null>(null)
  const [viewingFeedbackId, setViewingFeedbackId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [showSendPanel, setShowSendPanel] = useState(false)

  const load = () => {
    setLoading(true)
    const query = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) })
    if (search) query.set('search', search)
    if (role) query.set('role', role)
    if (orgId) query.set('org_id', orgId)
    api
      .get<Paged<User>>(`/users?${query}`)
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load people.'),
      )
      .finally(() => setLoading(false))
  }

  useEffect(load, [search, role, orgId, page])
  useRefetchOnFocus(load)

  // Same pattern as patchOrg (Organizations.tsx), patchTemplate (Templates.tsx)
  // and patchCategory (Categories.tsx): apply what the mutating call itself
  // returned/implies immediately, rather than waiting on load()'s separate
  // round trip to land — that one still fires in the background to reconcile
  // anything this missed (e.g. pagination shifting).
  const patchPerson = (id: string, patch: Partial<User>) => {
    setData((current) =>
      current
        ? { ...current, items: current.items.map((p) => (p.id === id ? { ...p, ...patch } : p)) }
        : current,
    )
  }

  const canManage = user?.role === 'client_admin' || user?.role === 'super_admin'
  const isPlatform = user?.role === 'super_admin'
  // A Super Admin with no org has no organization to create a user into —
  // creating/bulk-inviting only makes sense once they're linked to one
  // (they can add themselves a Client Admin from an org's own edit popup
  // instead, on the Organizations page).
  const canCreateUsers = user?.role === 'client_admin' || (user?.role === 'super_admin' && !!organization)
  // Whether the viewer is limited to sending feedback about Client Admin
  // rows only — true for an org-less Super Admin (not part of any org's own
  // chart, so only a Client Admin relationship makes sense to them). Anyone
  // acting within an org — a Client Admin, or a Super Admin who becomes
  // linked to one — can select/send to any row in their own org's list.
  const restrictedToClientAdmins = user?.role === 'super_admin' && !organization
  const canSelect = (person: User) => !restrictedToClientAdmins || person.role === 'client_admin'

  return (
    <>
      <PageHeader
        title="Users"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        actions={
          canCreateUsers && (
            <span className="flex flex-wrap items-start gap-2">
              <InvitePanel
                onInvited={(result) => {
                  toast.show(
                    'success',
                    'Invitation sent',
                    result.email_sent
                      ? `Invitation sent to ${result.user.email}.`
                      : `${result.user.email} was created, but the invitation email could not be sent.`,
                  )
                  load()
                }}
              />
              <BulkInvitePanel
                onDone={(result) => {
                  const duplicates = result.skipped.filter(
                    (row) => row.reason === 'Already exists' || row.reason === 'Duplicate in this file',
                  )
                  const otherSkipped = result.skipped.filter((row) => !duplicates.includes(row))
                  let message = `${result.invited} of ${result.total_rows} invited.`
                  if (duplicates.length) {
                    message += ` ${duplicates.length} duplicate email${duplicates.length === 1 ? '' : 's'} skipped: ${duplicates
                      .map((row) => row.email)
                      .filter(Boolean)
                      .join(', ')}.`
                  }
                  if (otherSkipped.length) {
                    message += ` ${otherSkipped.length} other row${otherSkipped.length === 1 ? '' : 's'} skipped: ${otherSkipped
                      .slice(0, 5)
                      .map((row) => `row ${row.row} (${row.reason})`)
                      .join(', ')}${otherSkipped.length > 5 ? ', ...' : ''}`
                  }
                  toast.show('success', 'Bulk invite complete', message)
                  load()
                }}
              />
            </span>
          )
        }
      />

      {orgId && (
        <div className="mb-4 flex items-center gap-2 text-sm text-ink-600 dark:text-ink-300">
          <span>
            Filtered to <strong>{orgName ?? 'this organization'}</strong>
          </span>
          <button
            type="button"
            className="text-xs text-ink-400 underline hover:text-ink-700 dark:hover:text-ink-100"
            onClick={() => {
              const next = new URLSearchParams(params)
              next.delete('org_id')
              setParams(next)
            }}
          >
            Clear filter
          </button>
        </div>
      )}

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {selectedIds.length > 0 && !showSendPanel && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-ink-200 bg-ink-50 px-4 py-2.5 dark:border-ink-700 dark:bg-ink-900/60">
          <span className="text-sm text-ink-700 dark:text-ink-200">
            {selectedIds.length} selected
          </span>
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            onClick={() => setShowSendPanel(true)}
          >
            Send feedback to {selectedIds.length}
          </button>
          <button
            type="button"
            className="btn-ghost px-2 py-1 text-xs"
            onClick={() => setSelectedIds([])}
          >
            Clear
          </button>
        </div>
      )}

      {showSendPanel && selectedIds.length > 0 && data && (
        <BulkSendPanel
          people={data.items.filter((person) => selectedIds.includes(person.id))}
          onRemove={(id) => setSelectedIds((current) => current.filter((item) => item !== id))}
          onDone={() => {
            setShowSendPanel(false)
            setSelectedIds([])
            load()
          }}
          onCancel={() => setShowSendPanel(false)}
        />
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="flex flex-wrap gap-1">
            {ROLE_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params)
                  if (tab.value) next.set('role', tab.value)
                  else next.delete('role')
                  setParams(next)
                  setPage(1)
                }}
                className={
                  role === tab.value
                    ? 'rounded-md accent-soft-bg px-2.5 py-1 text-xs font-medium accent-text'
                    : 'rounded-md px-2.5 py-1 text-xs text-ink-500 hover:bg-ink-100 dark:hover:bg-ink-800'
                }
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="ml-auto min-w-[200px] max-w-sm">
            <SearchBox
              value={search}
              onChange={(value) => {
                setSearch(value)
                setPage(1)
              }}
              placeholder="Search name, email or department"
            />
          </div>
        </div>

        {/* A skeleton only for the first load. Every later refetch (typing,
            paging) keeps the existing rows visible and just dims them, rather
            than unmounting the whole table — that unmount/remount was the
            flicker. */}
        {loading && !data ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={<IconUsers width={19} height={19} />}
            title="Nobody here yet"
            body="Invite your first colleague to get started."
          />
        ) : (
          <div className={clsx('overflow-x-auto transition-opacity duration-150', loading && 'opacity-50')}>
            <table className="data-table">
              <thead>
                <tr>
                  {canManage && (
                    <th className="w-8">
                      {/* An org-less Super Admin can only select Client
                          Admin rows (see restrictedToClientAdmins above);
                          anyone viewing within an org can select any row. */}
                      {(() => {
                        const selectableIds = data.items
                          .filter(canSelect)
                          .map((p) => p.id)
                        return selectableIds.length > 0 ? (
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[color:var(--accent)]"
                            checked={selectableIds.every((id) => selectedIds.includes(id))}
                            onChange={(event) =>
                              setSelectedIds(
                                event.target.checked
                                  ? Array.from(new Set([...selectedIds, ...selectableIds]))
                                  : selectedIds.filter((id) => !selectableIds.includes(id)),
                              )
                            }
                            aria-label="Select all Admins on this page"
                          />
                        ) : null
                      })()}
                    </th>
                  )}
                  <th>Name</th>
                  <th>Role</th>
                  <th>Manager</th>
                  {isPlatform && <th>Organization</th>}
                  <th>Department</th>
                  <th>Status</th>
                  <th>Feedback</th>
                  {canManage && <th className="text-right">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {data.items.map((person) => (
                  <Fragment key={person.id}>
                  <tr>
                    {canManage && (
                      <td>
                        {canSelect(person) && (
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[color:var(--accent)]"
                            checked={selectedIds.includes(person.id)}
                            onChange={() =>
                              setSelectedIds((current) =>
                                current.includes(person.id)
                                  ? current.filter((id) => id !== person.id)
                                  : [...current, person.id],
                              )
                            }
                            aria-label={`Select ${person.full_name}`}
                          />
                        )}
                      </td>
                    )}
                    <td>
                      <span className="block font-medium text-ink-900 dark:text-ink-50">
                        {person.full_name}
                      </span>
                      <span className="block text-2xs text-ink-400">
                        {person.email}
                        {person.phone ? ` · ${person.phone}` : ''}
                      </span>
                    </td>
                    <td>
                      <Chip value={person.role}>{ROLE_LABEL[person.role]}</Chip>
                    </td>
                    <td>
                      <ManagerCell managers={person.managers ?? []} />
                    </td>
                    {isPlatform && (
                      <td className="text-ink-600 dark:text-ink-300">
                        {person.org_name ?? '—'}
                      </td>
                    )}
                    <td className="text-ink-600 dark:text-ink-300">
                      {person.department ?? '—'}
                    </td>
                    <td>
                      <Chip value={person.status} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className={clsx(
                          'rounded-full px-2 py-0.5 text-xs font-medium',
                          person.feedback_count
                            ? 'accent-soft-bg accent-text hover:opacity-80'
                            : 'bg-ink-100 text-ink-400 hover:bg-ink-200 dark:bg-ink-800 dark:hover:bg-ink-700',
                        )}
                        onClick={() => setViewingFeedbackId(person.id)}
                      >
                        {person.feedback_count ?? 0}
                      </button>
                    </td>
                    {canManage && (
                      <td className="text-right">
                        <span className="flex items-center justify-end gap-2.5">
                          {person.id === user?.id ? (
                            <span className="text-xs text-ink-500 dark:text-ink-400">You</span>
                          ) : (
                            <Switch
                              checked={person.status !== 'disabled'}
                              ariaLabel={person.status === 'disabled' ? `Enable ${person.full_name}` : `Disable ${person.full_name}`}
                              onChange={async () => {
                                try {
                                  if (person.status === 'disabled') {
                                    await api.post(`/users/${person.id}/enable`)
                                    patchPerson(person.id, { status: 'active' })
                                    toast.show('success', 'User enabled', `${person.email} can sign in again.`)
                                  } else {
                                    await api.post(`/users/${person.id}/disable`)
                                    patchPerson(person.id, { status: 'disabled' })
                                    toast.show('success', 'User disabled', `${person.email} can no longer sign in.`)
                                  }
                                  load()
                                } catch (caught) {
                                  toast.show(
                                    'critical',
                                    'Action failed',
                                    caught instanceof ApiError ? caught.message : 'Could not change this user.',
                                  )
                                }
                              }}
                            />
                          )}
                          <button
                            type="button"
                            className="btn-secondary p-1.5"
                            aria-label={`View ${person.full_name}`}
                            title="View"
                            onClick={() => setViewingId(person.id)}
                          >
                            <IconEye width={15} height={15} />
                          </button>
                          <button
                            type="button"
                            className="btn-secondary p-1.5"
                            aria-label={`Edit ${person.full_name}`}
                            title="Edit"
                            onClick={() => setEditingId(editingId === person.id ? null : person.id)}
                          >
                            <IconEdit width={15} height={15} />
                          </button>
                        </span>
                      </td>
                    )}
                  </tr>
                  {editingId === person.id && (
                    <EditUserForm
                      person={person}
                      canChangeRole={person.id !== user?.id}
                      onCancel={() => setEditingId(null)}
                      onDone={(updated) => {
                        setEditingId(null)
                        patchPerson(person.id, updated)
                        toast.show('success', 'Person updated', `${person.full_name}'s details were updated.`)
                        load()
                      }}
                    />
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
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

      {viewingId && data && (
        (() => {
          const person = data.items.find((item) => item.id === viewingId)
          if (!person) return null
          return <UserDetailModal person={person} onClose={() => setViewingId(null)} />
        })()
      )}

      {viewingFeedbackId && data && (
        (() => {
          const person = data.items.find((item) => item.id === viewingFeedbackId)
          if (!person) return null
          return (
            <FeedbackHistoryModal
              person={person}
              canSend={canSelect(person)}
              onClose={() => setViewingFeedbackId(null)}
              onSend={() => {
                setSelectedIds([person.id])
                setShowSendPanel(true)
                // The send panel renders above the table, near the top of
                // the page — if this was opened from a person scrolled deep
                // into a long, paginated list, it would appear entirely off
                // screen without this.
                window.scrollTo({ top: 0, behavior: 'smooth' })
              }}
            />
          )
        })()
      )}
    </>
  )
}