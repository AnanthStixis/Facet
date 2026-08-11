import clsx from 'clsx'
import { Fragment, useEffect, useState } from 'react'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { Banner, Card, Chip, EmptyState, Field, Skeleton, Spinner } from '../components/ui'
import { IconUsers } from '../components/icons'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, downloadFile, uploadFile } from '../lib/api'
import type { Paged, Role, User } from '../lib/types'
import { useAuth } from '../store/auth'

interface InviteResult {
  user: User
  invite_url: string | null
  email_sent: boolean
}

const ROLES: { value: Role; label: string; hint: string }[] = [
  { value: 'client_admin', label: 'Client admin', hint: 'Full control of this workspace' },
  { value: 'manager', label: 'Manager', hint: 'Runs campaigns, reviews their team' },
  { value: 'employee', label: 'Employee', hint: 'Gives and receives feedback' },
]

function InvitePanel({ onInvited }: { onInvited: (result: InviteResult) => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    role: 'employee' as Role,
    job_title: '',
    department: '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  if (!open) {
    return (
      <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setOpen(true)}>
        Invite someone
      </button>
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      const result = await api.post<InviteResult>('/users', {
        ...form,
        job_title: form.job_title || null,
        department: form.department || null,
      })
      onInvited(result)
      setOpen(false)
      setForm({ full_name: '', email: '', role: 'employee', job_title: '', department: '' })
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('The invitation could not be sent.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-5" title="Invite someone" hint="They set their own password from a single-use link that expires in 72 hours.">
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
            label="Job title"
            value={form.job_title}
            onChange={(event) => setForm({ ...form, job_title: event.target.value })}
          />
          <Field
            label="Department"
            value={form.department}
            onChange={(event) => setForm({ ...form, department: event.target.value })}
          />
        </div>

        <fieldset className="mt-4">
          <legend className="mb-1.5 text-sm font-medium text-ink-700 dark:text-ink-200">
            Role
          </legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {ROLES.map((role) => (
              <label
                key={role.value}
                className={
                  form.role === role.value
                    ? 'cursor-pointer rounded-lg border-2 border-[color:var(--accent)] p-3'
                    : 'cursor-pointer rounded-lg border border-ink-200 p-3 hover:border-ink-300 dark:border-ink-700'
                }
              >
                <input
                  type="radio"
                  name="role"
                  className="sr-only"
                  checked={form.role === role.value}
                  onChange={() => setForm({ ...form, role: role.value })}
                />
                <span className="block text-sm font-medium text-ink-900 dark:text-ink-50">
                  {role.label}
                </span>
                <span className="block text-xs text-ink-500 dark:text-ink-400">
                  {role.hint}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Send invitation
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
  onDone: () => void
}) {
  const [form, setForm] = useState({
    full_name: person.full_name,
    job_title: person.job_title ?? '',
    department: person.department ?? '',
    role: person.role,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [resetBusy, setResetBusy] = useState(false)
  const [resetNotice, setResetNotice] = useState<string | null>(null)

  const resetPassword = async () => {
    setResetBusy(true)
    setError(null)
    setResetNotice(null)
    try {
      const result = await api.post<{ message: string; reset_url: string | null }>(
        `/users/${person.id}/reset-password`,
      )
      setResetNotice(
        result.reset_url ? `${result.message} ${result.reset_url}` : result.message,
      )
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not send a reset link.')
    } finally {
      setResetBusy(false)
    }
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      await api.patch(`/users/${person.id}`, {
        full_name: form.full_name,
        job_title: form.job_title || null,
        department: form.department || null,
        role: canChangeRole && form.role !== person.role ? form.role : undefined,
      })
      onDone()
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
    <tr>
      <td colSpan={6} className="bg-ink-50 p-0 dark:bg-ink-900/60">
        <form onSubmit={submit} className="p-4">
          {error && (
            <Banner tone="error" className="mb-3">
              {error}
            </Banner>
          )}
          {resetNotice && (
            <Banner tone="success" className="mb-3 break-all" onDismiss={() => setResetNotice(null)}>
              {resetNotice}
            </Banner>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field
              label="Full name"
              value={form.full_name}
              onChange={(event) => setForm({ ...form, full_name: event.target.value })}
              error={fieldErrors.full_name}
              required
            />
            <Field
              label="Job title"
              value={form.job_title}
              onChange={(event) => setForm({ ...form, job_title: event.target.value })}
            />
            <Field
              label="Department"
              value={form.department}
              onChange={(event) => setForm({ ...form, department: event.target.value })}
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
          </div>
          <div className="mt-4 flex gap-2">
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
      </td>
    </tr>
  )
}

interface BulkResult {
  invited: number
  skipped: { row: number; email?: string; reason: string }[]
  total_rows: number
}

function BulkInvitePanel({ onDone }: { onDone: (result: BulkResult) => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    <Card className="mb-5" title="Bulk invite from a spreadsheet" hint="Upload a CSV with full_name and email columns (role, job_title, department are optional). Each row is invited exactly like a single invite.">
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-sm"
          onClick={() => downloadFile('/users/bulk/template', 'user_invite_template.csv')}
        >
          Download template
        </button>
        <label className="btn-primary cursor-pointer px-3 py-1.5 text-sm">
          {busy && <Spinner />}
          Choose CSV file
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            disabled={busy}
            onChange={async (event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (!file) return
              setBusy(true)
              setError(null)
              try {
                const result = await uploadFile<BulkResult>('/users/bulk', file)
                onDone(result)
                setOpen(false)
              } catch (caught) {
                setError(caught instanceof ApiError ? caught.message : 'The upload failed.')
              } finally {
                setBusy(false)
              }
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
    </Card>
  )
}

const PAGE_SIZE = 15

export function People() {
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paged<User> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [confirmDisable, setConfirmDisable] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    const query = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) })
    if (search) query.set('search', search)
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

  useEffect(load, [search, page])
  useRefetchOnFocus(load)

  const canManage = user?.role === 'client_admin' || user?.role === 'super_admin'

  return (
    <>
      <PageHeader
        title="People"
        description="Everyone with access to this workspace. External respondents are not listed here — they never hold an account."
        actions={
          canManage && (
            <span className="flex flex-wrap items-start gap-2">
              <InvitePanel
                onInvited={(result) => {
                  setNotice(
                    result.email_sent
                      ? `Invitation sent to ${result.user.email}.`
                      : `${result.user.email} was created, but the invitation email could not be sent.`,
                  )
                  setInviteLink(result.invite_url)
                  load()
                }}
              />
              <BulkInvitePanel
                onDone={(result) => {
                  setNotice(
                    `${result.invited} of ${result.total_rows} invited.` +
                      (result.skipped.length
                        ? ` ${result.skipped.length} skipped: ${result.skipped
                            .slice(0, 5)
                            .map((row) => `row ${row.row} (${row.reason})`)
                            .join(', ')}${result.skipped.length > 5 ? ', ...' : ''}`
                        : ''),
                  )
                  setInviteLink(null)
                  load()
                }}
              />
            </span>
          )
        }
      />

      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          <div>
            {notice}
            {/* Development convenience only; the API withholds this in production,
                where the link is a bearer credential. */}
            {inviteLink && (
              <p className="mt-1 break-all font-mono text-2xs opacity-80">{inviteLink}</p>
            )}
          </div>
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <Card padded={false}>
        <div className="border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="max-w-sm">
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
                  <th>Name</th>
                  <th>Role</th>
                  <th>Department</th>
                  <th>Status</th>
                  <th>Two-factor</th>
                  {canManage && <th className="text-right">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {data.items.map((person) => (
                  <Fragment key={person.id}>
                  <tr>
                    <td>
                      <span className="block font-medium text-ink-900 dark:text-ink-50">
                        {person.full_name}
                      </span>
                      <span className="block text-2xs text-ink-400">{person.email}</span>
                    </td>
                    <td>
                      <Chip value={person.role} />
                    </td>
                    <td className="text-ink-600 dark:text-ink-300">
                      {person.department ?? '—'}
                    </td>
                    <td>
                      <Chip value={person.status} />
                    </td>
                    <td>
                      <span
                        className={
                          person.mfa_enabled
                            ? 'text-xs text-positive'
                            : 'text-xs text-ink-400'
                        }
                      >
                        {person.mfa_enabled ? 'Enabled' : 'Not enabled'}
                      </span>
                    </td>
                    {canManage && (
                      <td className="text-right">
                        {confirmDisable === person.id ? (
                          <span className="flex justify-end gap-1.5">
                            <button
                              type="button"
                              className="btn-danger px-2 py-1 text-xs"
                              onClick={async () => {
                                await api.post(`/users/${person.id}/disable`)
                                setConfirmDisable(null)
                                setNotice(`${person.email} can no longer sign in.`)
                                load()
                              }}
                            >
                              Confirm
                            </button>
                            <button
                              type="button"
                              className="btn-secondary px-2 py-1 text-xs"
                              onClick={() => setConfirmDisable(null)}
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <span className="flex justify-end gap-1.5">
                            <button
                              type="button"
                              className="btn-ghost px-2 py-1 text-xs"
                              onClick={() => setEditingId(editingId === person.id ? null : person.id)}
                            >
                              Edit
                            </button>
                            {person.id === user?.id ? (
                              <span className="text-2xs text-ink-400">You</span>
                            ) : (
                              person.status !== 'disabled' && (
                                <button
                                  type="button"
                                  className="btn-ghost px-2 py-1 text-xs"
                                  onClick={() => setConfirmDisable(person.id)}
                                >
                                  Disable
                                </button>
                              )
                            )}
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                  {editingId === person.id && (
                    <EditUserForm
                      person={person}
                      canChangeRole={person.id !== user?.id}
                      onCancel={() => setEditingId(null)}
                      onDone={() => {
                        setEditingId(null)
                        setNotice(`${person.full_name}'s details were updated.`)
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
    </>
  )
}
