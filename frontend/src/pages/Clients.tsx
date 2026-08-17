import { useEffect, useState } from 'react'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconBriefcase, IconEdit, IconTrash } from '../components/icons'
import { Banner, Card, Chip, ConfirmDialog, EmptyState, Field, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, downloadFile, uploadFile } from '../lib/api'
import type { Paged } from '../lib/types'

interface ContactMeta {
  id: string
  email: string
  full_name: string
  company: string | null
  job_title: string | null
  phone: string | null
  tags: string[]
  unsubscribed_at: string | null
  created_at: string
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** One popup for both create and edit, same house style as Templates.tsx's
 * TemplateModal / Categories.tsx's CategoryModal. */
function ContactModal({
  contact,
  onCancel,
  onSaved,
}: {
  contact: ContactMeta | null
  onCancel: () => void
  onSaved: (message: string, item: ContactMeta) => void
}) {
  const isEdit = !!contact
  const [fullName, setFullName] = useState(contact?.full_name ?? '')
  const [email, setEmail] = useState(contact?.email ?? '')
  const [company, setCompany] = useState(contact?.company ?? '')
  const [jobTitle, setJobTitle] = useState(contact?.job_title ?? '')
  const [phone, setPhone] = useState(contact?.phone ?? '')
  const [tags, setTags] = useState(contact?.tags.join(', ') ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    const body = {
      full_name: fullName,
      email,
      company: company || null,
      job_title: jobTitle || null,
      phone: phone || null,
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    }
    try {
      const saved = isEdit
        ? await api.patch<ContactMeta>(`/contacts/${contact.id}`, body)
        : await api.post<ContactMeta>('/contacts', body)
      onSaved(isEdit ? `'${saved.full_name}' saved.` : `'${saved.full_name}' added.`, saved)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError(isEdit ? 'Could not save this client.' : 'Could not add this client.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={isEdit ? `Edit '${contact.full_name}'` : 'New client'} onClose={onCancel}>
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            error={fieldErrors.full_name}
            required
            autoFocus
          />
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            error={fieldErrors.email}
            required
          />
          <Field
            label="Company (optional)"
            value={company}
            onChange={(event) => setCompany(event.target.value)}
          />
          <Field
            label="Job title (optional)"
            value={jobTitle}
            onChange={(event) => setJobTitle(event.target.value)}
          />
          <Field
            label="Phone (optional)"
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
        </div>
        <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            {isEdit ? 'Save' : 'Submit'}
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Icon-only edit/toggle/delete, same pattern as Templates.tsx's
 * TemplateActions / People.tsx's row actions. */
function ContactActions({
  contact,
  onEdit,
  onChanged,
  onError,
  onDeleted,
}: {
  contact: ContactMeta
  onEdit: (contact: ContactMeta) => void
  onChanged: (message: string, updated: ContactMeta) => void
  onError: (message: string) => void
  onDeleted: (message: string, id: string) => void
}) {
  const [busy, setBusy] = useState<'toggle' | 'delete' | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const toggle = async () => {
    setBusy('toggle')
    try {
      const updated = await api.patch<ContactMeta>(`/contacts/${contact.id}`, {
        unsubscribed: !contact.unsubscribed_at,
      })
      onChanged(
        updated.unsubscribed_at
          ? `'${contact.full_name}' was unsubscribed.`
          : `'${contact.full_name}' can receive feedback requests again.`,
        updated,
      )
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not change this client.')
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    setBusy('delete')
    try {
      await api.delete(`/contacts/${contact.id}`)
      onDeleted(`'${contact.full_name}' deleted.`, contact.id)
      setConfirmingDelete(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not delete this client.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <span className="flex flex-nowrap items-center justify-end gap-2 whitespace-nowrap">
        <Switch
          checked={!contact.unsubscribed_at}
          disabled={busy === 'toggle'}
          ariaLabel={contact.unsubscribed_at ? `Resubscribe ${contact.full_name}` : `Unsubscribe ${contact.full_name}`}
          onChange={toggle}
        />
        <button
          type="button"
          className="btn-secondary p-1.5"
          aria-label={`Edit ${contact.full_name}`}
          title="Edit"
          onClick={() => onEdit(contact)}
        >
          <IconEdit width={15} height={15} />
        </button>
        <button
          type="button"
          className="btn-ghost p-1.5 text-critical"
          aria-label={`Delete ${contact.full_name}`}
          title="Delete"
          onClick={() => setConfirmingDelete(true)}
        >
          <IconTrash width={15} height={15} />
        </button>
      </span>
      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this client?"
          body={`'${contact.full_name}' will be removed. This can't be undone.`}
          confirmLabel="Delete"
          tone="critical"
          busy={busy === 'delete'}
          onConfirm={remove}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </>
  )
}

interface BulkResult {
  imported: number
  skipped: { row: number; email?: string; reason: string }[]
  total_rows: number
}

const MAX_BULK_ROWS = 100

function countCsvRows(text: string): number {
  return text
    .split(/\r?\n/)
    .slice(1)
    .filter((line) => line.trim().length > 0).length
}

/** Same shape as People.tsx's BulkInvitePanel — a starter CSV download, then
 * an upload that gets a client-side row-count confirmation before it fires. */
function BulkImportPanel({ onDone }: { onDone: (result: BulkResult) => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<{ file: File; rowCount: number } | null>(null)

  const runUpload = async (file: File) => {
    setBusy(true)
    try {
      const result = await uploadFile<BulkResult>('/contacts/bulk', file)
      onDone(result)
      setOpen(false)
      setPending(null)
    } catch (caught) {
      toast.show(
        'critical',
        'Bulk import failed',
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
        Bulk import
      </button>
    )
  }

  return (
    <Card
      className="mb-5"
      title="Bulk import from a spreadsheet"
      hint="Upload a CSV with full_name and email columns (company, job_title, tags are optional). Up to 100 rows per file."
    >
      {busy ? (
        <div className="space-y-2">
          <div className="h-2 w-full overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
            <div className="accent-bg h-full w-full origin-left animate-pulse" />
          </div>
          <p className="text-sm text-ink-500 dark:text-ink-400">
            Importing {pending?.rowCount ?? ''} client{pending?.rowCount === 1 ? '' : 's'}…
          </p>
        </div>
      ) : pending ? (
        <div>
          <p className="mb-3 text-sm text-ink-700 dark:text-ink-200">
            <strong>{pending.rowCount}</strong> client{pending.rowCount === 1 ? '' : 's'} found in{' '}
            <span className="font-medium">{pending.file.name}</span>. Import all of them?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-sm"
              onClick={() => void runUpload(pending.file)}
            >
              Yes, import {pending.rowCount}
            </button>
            <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={() => setPending(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-sm"
            onClick={() => downloadFile('/contacts/bulk/template', 'client_import_template.csv')}
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
                    `This file has ${rowCount} rows. Bulk import is limited to ${MAX_BULK_ROWS} at a time — split it into smaller files.`,
                  )
                  return
                }
                setPending({ file, rowCount })
              }}
            />
          </label>
          <button type="button" className="btn-ghost px-2.5 py-1.5 text-sm" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      )}
    </Card>
  )
}

const PAGE_SIZE = 10

export function Clients() {
  const toast = useToast()
  const [contacts, setContacts] = useState<ContactMeta[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [modalContact, setModalContact] = useState<ContactMeta | null | 'new'>(null)

  const reload = () => {
    const query = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) })
    if (search) query.set('search', search)
    api
      .get<Paged<ContactMeta>>(`/contacts?${query}`)
      .then((result) => {
        setContacts(result.items)
        setTotal(result.total)
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load clients.'))
  }

  useEffect(reload, [search, page])
  useRefetchOnFocus(reload)

  // Instant-patch-from-response, same pattern as Templates.tsx/Categories.tsx/
  // Organizations.tsx — the row updates the moment the mutating request's own
  // response comes back, not whenever the background reload() happens to land.
  const patchContact = (updated: ContactMeta) => {
    setContacts((current) => {
      if (!current) return current
      const exists = current.some((c) => c.id === updated.id)
      const next = exists ? current.map((c) => (c.id === updated.id ? updated : c)) : [updated, ...current]
      return next
    })
    if (!contacts?.some((c) => c.id === updated.id)) setTotal((current) => current + 1)
  }

  const removeContact = (id: string) => {
    setContacts((current) => (current ? current.filter((c) => c.id !== id) : current))
    setTotal((current) => Math.max(0, current - 1))
  }

  return (
    <>
      <PageHeader title="Clients" />

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="max-w-xs flex-1">
            <SearchBox
              value={search}
              onChange={(value) => {
                setSearch(value)
                setPage(1)
              }}
              placeholder="Search clients"
            />
          </div>
          <div className="ml-auto flex gap-2">
            <BulkImportPanel
              onDone={(result) => {
                toast.show(
                  'success',
                  'Clients imported',
                  `${result.imported} imported${result.skipped.length ? `, ${result.skipped.length} skipped` : ''}.`,
                )
                reload()
              }}
            />
            <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setModalContact('new')}>
              New client
            </button>
          </div>
        </div>

        {error && (
          <div className="px-5 py-3">
            <Banner tone="error" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          </div>
        )}

        {modalContact && (
          <ContactModal
            contact={modalContact === 'new' ? null : modalContact}
            onCancel={() => setModalContact(null)}
            onSaved={(message, item) => {
              toast.show('success', modalContact === 'new' ? 'Client added' : 'Client saved', message)
              setModalContact(null)
              patchContact(item)
            }}
          />
        )}

        {!contacts ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-12 w-full rounded-md" />
            ))}
          </div>
        ) : contacts.length === 0 ? (
          <EmptyState
            icon={<IconBriefcase width={19} height={19} />}
            title="No clients yet"
            body="Add your first client, or import a list from a CSV."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Company</th>
                  <th>Job title</th>
                  <th>Tags</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((contact) => (
                  <tr key={contact.id}>
                    <td className="font-medium text-ink-900 dark:text-ink-50">{contact.full_name}</td>
                    <td className="text-ink-600 dark:text-ink-300">{contact.email}</td>
                    <td className="text-ink-600 dark:text-ink-300">{contact.company ?? '—'}</td>
                    <td className="text-ink-600 dark:text-ink-300">{contact.job_title ?? '—'}</td>
                    <td className="text-ink-600 dark:text-ink-300">
                      {contact.tags.length ? contact.tags.join(', ') : '—'}
                    </td>
                    <td>
                      <Chip value={contact.unsubscribed_at ? 'unsubscribed' : 'active'} />
                    </td>
                    <td className="text-ink-600 dark:text-ink-300">{formatDate(contact.created_at)}</td>
                    <td>
                      <ContactActions
                        contact={contact}
                        onEdit={setModalContact}
                        onChanged={(message, updated) => {
                          toast.show('success', 'Client updated', message)
                          patchContact(updated)
                        }}
                        onError={(message) => toast.show('critical', 'Action failed', message)}
                        onDeleted={(message, id) => {
                          toast.show('success', 'Client deleted', message)
                          removeContact(id)
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > 0 && <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />}
      </Card>
    </>
  )
}
