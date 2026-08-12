import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconCheck, IconClock, IconLock, IconSearch, IconUsers } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Skeleton, Spinner } from '../components/ui'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, downloadFile, uploadFile } from '../lib/api'
import type { Paged } from '../lib/types'

interface Delivery {
  total: number
  pending: number
  sent: number
  opened: number
  submitted: number
  unsubscribed: number
  revoked: number
  response_rate_pct: number
  open_rate_pct: number
}

interface Campaign {
  id: string
  name: string
  description: string | null
  status: string
  audience: string
  is_anonymous: boolean
  min_responses_to_reveal: number
  template_name: string | null
  template_version: number | null
  target_id: string | null
  target_label: string | null
  target_type: string | null
  closes_at: string | null
  created_at: string
  delivery: Delivery
}

interface Recipient {
  id: string
  contact_name: string
  contact_email: string
  company: string | null
  target_label: string
  status: string
  batch: string | null
  sent_at: string | null
  first_opened_at: string | null
  submitted_at: string | null
  open_count: number
  expires_at: string
}

interface Contact {
  id: string
  email: string
  full_name: string
  company: string | null
  unsubscribed_at: string | null
}

interface Target {
  id: string
  label: string
  target_type: string
}

interface TemplateOption {
  id: string
  name: string
  status: string | null
  target_type: string
  is_anonymous: boolean
}

/**
 * The delivery funnel.
 *
 * Sent → opened → submitted, as proportions of what was actually delivered.
 * Measuring response rate against the whole list instead would count
 * undelivered invitations as refusals and make every campaign look worse than
 * it was.
 */
function Funnel({ delivery }: { delivery: Delivery }) {
  const stages = [
    { label: 'Sent', value: delivery.sent, tone: 'bg-ink-300 dark:bg-ink-700' },
    { label: 'Opened', value: delivery.opened, tone: 'bg-internal' },
    { label: 'Responded', value: delivery.submitted, tone: 'accent-bg' },
  ]
  const peak = Math.max(1, delivery.sent)

  return (
    <div className="flex flex-wrap items-end gap-4">
      {stages.map((stage) => (
        <div key={stage.label} className="min-w-20">
          <p className="tabular text-2xl font-semibold text-ink-900 dark:text-ink-50">
            {stage.value}
          </p>
          <p className="label-caps">{stage.label}</p>
          <div className="mt-1 h-1 w-16 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
            <div
              className={clsx('h-full', stage.tone)}
              style={{ width: `${(stage.value / peak) * 100}%` }}
            />
          </div>
        </div>
      ))}
      <div className="ml-auto text-right">
        <p className="tabular text-2xl font-semibold accent-text">
          {delivery.response_rate_pct}%
        </p>
        <p className="label-caps">Response rate</p>
      </div>
    </div>
  )
}

function CreateCampaign({ onCreated }: { onCreated: (campaign: Campaign) => void }) {
  const [open, setOpen] = useState(false)
  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [contactSearch, setContactSearch] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [newContact, setNewContact] = useState({ full_name: '', email: '', company: '' })
  const [form, setForm] = useState({
    name: '',
    template_id: '',
    about: '',
    closes_at: '',
    open_immediately: true,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadContacts = () => {
    const query = new URLSearchParams({ page_size: '200' })
    if (contactSearch) query.set('search', contactSearch)
    api
      .get<Paged<Contact>>(`/contacts?${query}`)
      .then((page) => setContacts(page.items))
      .catch(() => setContacts([]))
  }

  useEffect(() => {
    if (!open) return
    api
      .get<{ templates: TemplateOption[] }[]>('/catalog/categories')
      .then((categories) =>
        setTemplates(
          categories
            .flatMap((category) => category.templates)
            .filter(
              (template) =>
                template.status === 'published' &&
                // External campaigns are about things and services, not about
                // colleagues — a person-scoped template here would be a
                // guaranteed 422 after the form is filled in.
                ['product', 'service', 'proposal'].includes(template.target_type),
            ),
        ),
      )
      .catch(() => setTemplates([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    loadContacts()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contactSearch])

  const reset = () => {
    setOpen(false)
    setForm({ name: '', template_id: '', about: '', closes_at: '', open_immediately: true })
    setSelected([])
    setContactSearch('')
  }

  if (!open) {
    return (
      <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setOpen(true)}>
        New campaign
      </button>
    )
  }

  // One form: name, questionnaire, who it's about (typed, not picked from a
  // list that starts empty), and recipients — then create the campaign, add
  // whoever was checked, and open it, all from a single submit. The old
  // multi-step draft → add recipients → open flow is still reachable by
  // leaving "Open immediately" unchecked and using Recipients/Open on the
  // card afterwards, for anyone who wants to stage it instead.
  return (
    <Card
      className="mb-5"
      title="New campaign"
      hint="Ask clients, customers or prospects for feedback by email. They never need an account."
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setError(null)
          try {
            const campaign = await api.post<Campaign>('/campaigns', {
              name: form.name,
              template_id: form.template_id,
              target_label: form.about,
              closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : null,
            })
            if (selected.length > 0 && campaign.target_id) {
              await api.post(`/campaigns/${campaign.id}/recipients`, {
                target_id: campaign.target_id,
                contact_ids: selected,
              })
            }
            // A campaign with nobody on it yet cannot be opened — the API
            // rejects that, correctly, so only attempt it when there is
            // actually someone to send to.
            const finalCampaign =
              form.open_immediately && selected.length > 0
                ? await api.post<Campaign>(`/campaigns/${campaign.id}/open`)
                : campaign
            onCreated(finalCampaign)
            reset()
          } catch (caught) {
            setError(caught instanceof ApiError ? caught.message : 'Could not create the campaign.')
          } finally {
            setBusy(false)
          }
        }}
      >
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="Campaign name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="Q4 2026 Client Experience"
            required
            minLength={3}
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Questionnaire
            </span>
            <select
              className="field"
              required
              value={form.template_id}
              onChange={(event) => setForm({ ...form, template_id: event.target.value })}
            >
              <option value="">Choose a template</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <Field
            label="What's this about"
            value={form.about}
            onChange={(event) => setForm({ ...form, about: event.target.value })}
            placeholder="e.g. Larkspur Bank engagement"
            hint="A product, service or proposal name. Reuses an existing one with the same name."
            required
            minLength={1}
          />
          <Field
            label="Closes on (optional)"
            type="date"
            value={form.closes_at}
            onChange={(event) => setForm({ ...form, closes_at: event.target.value })}
            hint="Leave blank to collect feedback with no deadline."
          />
        </div>

        <div className="mt-4">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Recipients (optional — add now or later from the campaign card)
          </span>
          <div className="rounded-lg border border-ink-200 bg-ink-50 p-3 dark:border-ink-700 dark:bg-ink-900/60">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <div className="min-w-[200px] flex-1">
                <SearchBox
                  value={contactSearch}
                  onChange={setContactSearch}
                  placeholder="Search contacts"
                />
              </div>
              <button
                type="button"
                className="btn-secondary px-2.5 py-1.5 text-sm"
                onClick={() => setAdding((state) => !state)}
              >
                {adding ? 'Cancel' : 'New contact'}
              </button>
            </div>

            {adding && (
              <div className="mb-2 grid gap-2 sm:grid-cols-4">
                <Field
                  label="Name"
                  value={newContact.full_name}
                  onChange={(event) =>
                    setNewContact({ ...newContact, full_name: event.target.value })
                  }
                />
                <Field
                  label="Email"
                  type="email"
                  value={newContact.email}
                  onChange={(event) => setNewContact({ ...newContact, email: event.target.value })}
                />
                <Field
                  label="Company"
                  value={newContact.company}
                  onChange={(event) =>
                    setNewContact({ ...newContact, company: event.target.value })
                  }
                />
                <div className="flex items-end">
                  <button
                    type="button"
                    className="btn-primary px-3 py-1.5 text-sm"
                    disabled={!newContact.full_name.trim() || !newContact.email.trim()}
                    onClick={async () => {
                      try {
                        const created = await api.post<Contact>('/contacts', {
                          full_name: newContact.full_name,
                          email: newContact.email,
                          company: newContact.company || null,
                        })
                        setNewContact({ full_name: '', email: '', company: '' })
                        setAdding(false)
                        loadContacts()
                        setSelected((current) => [...current, created.id])
                      } catch (caught) {
                        setError(
                          caught instanceof ApiError ? caught.message : 'Could not add the contact.',
                        )
                      }
                    }}
                  >
                    Add contact
                  </button>
                </div>
              </div>
            )}

            <div className="max-h-52 overflow-y-auto rounded-md border border-ink-200 bg-white dark:border-ink-700 dark:bg-ink-900">
              {contacts.length === 0 ? (
                <p className="px-4 py-5 text-center text-sm text-ink-500">
                  No contacts yet. Add one above.
                </p>
              ) : (
                <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                  {contacts.map((contact) => {
                    const out = contact.unsubscribed_at !== null
                    const checked = selected.includes(contact.id)
                    return (
                      <li key={contact.id}>
                        <label
                          className={clsx(
                            'flex items-center gap-3 px-3.5 py-2',
                            out
                              ? 'opacity-50'
                              : 'cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-800/60',
                          )}
                        >
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[color:var(--accent)]"
                            disabled={out}
                            checked={checked}
                            onChange={() =>
                              setSelected((current) =>
                                checked
                                  ? current.filter((id) => id !== contact.id)
                                  : [...current, contact.id],
                              )
                            }
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-ink-800 dark:text-ink-100">
                              {contact.full_name}
                            </span>
                            <span className="block truncate text-2xs text-ink-400">
                              {contact.email}
                              {contact.company ? ` · ${contact.company}` : ''}
                            </span>
                          </span>
                          {out && (
                            <span className="chip bg-ink-200 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
                              Unsubscribed
                            </span>
                          )}
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        <label className="mt-4 flex items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[color:var(--accent)]"
            checked={form.open_immediately}
            disabled={selected.length === 0}
            onChange={(event) => setForm({ ...form, open_immediately: event.target.checked })}
          />
          Open immediately (invitations can be sent right after)
          {selected.length === 0 && (
            <span className="text-xs text-ink-400">— pick at least one recipient first</span>
          )}
        </label>

        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            {form.open_immediately && selected.length > 0 ? 'Create and open' : 'Create as draft'}
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={reset}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  )
}

function RecipientPicker({
  campaign,
  onDone,
}: {
  campaign: Campaign
  onDone: (message: string) => void
}) {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [batch, setBatch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newContact, setNewContact] = useState({ full_name: '', email: '', company: '' })
  const [bulkBusy, setBulkBusy] = useState(false)

  const load = () => {
    const query = new URLSearchParams({ page_size: '200' })
    if (search) query.set('search', search)
    api
      .get<Paged<Contact>>(`/contacts?${query}`)
      .then((page) => setContacts(page.items))
      .catch(() => setContacts([]))
  }

  useEffect(load, [search])

  return (
    <div className="mt-4 rounded-lg border border-ink-200 bg-ink-50 p-4 dark:border-ink-700 dark:bg-ink-900/60">
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-[200px] flex-1">
          <SearchBox value={search} onChange={setSearch} placeholder="Search contacts" />
        </div>
        <input
          className="field max-w-[160px]"
          value={batch}
          onChange={(event) => setBatch(event.target.value)}
          placeholder="Batch (e.g. cohort 1)"
        />
        <button
          type="button"
          className="btn-secondary px-2.5 py-1.5 text-sm"
          onClick={() => setAdding((state) => !state)}
        >
          {adding ? 'Cancel' : 'New contact'}
        </button>
        <button
          type="button"
          className="btn-secondary px-2.5 py-1.5 text-sm"
          onClick={() => downloadFile('/contacts/bulk/template', 'contact_import_template.csv')}
        >
          Download CSV template
        </button>
        <label className="btn-secondary cursor-pointer px-2.5 py-1.5 text-sm">
          {bulkBusy && <Spinner />}
          Bulk import CSV
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            disabled={bulkBusy}
            onChange={async (event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (!file) return
              setBulkBusy(true)
              setError(null)
              try {
                const result = await uploadFile<{
                  imported: number
                  skipped: { row: number; email?: string; reason: string }[]
                  total_rows: number
                }>('/contacts/bulk', file)
                onDone(
                  `${result.imported} of ${result.total_rows} contacts imported.` +
                    (result.skipped.length ? ` ${result.skipped.length} skipped.` : ''),
                )
                load()
              } catch (caught) {
                setError(caught instanceof ApiError ? caught.message : 'The upload failed.')
              } finally {
                setBulkBusy(false)
              }
            }}
          />
        </label>
      </div>

      {adding && (
        <form
          className="mb-3 grid gap-2 sm:grid-cols-4"
          onSubmit={async (event) => {
            event.preventDefault()
            setError(null)
            try {
              await api.post('/contacts', {
                full_name: newContact.full_name,
                email: newContact.email,
                company: newContact.company || null,
              })
              setNewContact({ full_name: '', email: '', company: '' })
              setAdding(false)
              load()
            } catch (caught) {
              setError(caught instanceof ApiError ? caught.message : 'Could not add the contact.')
            }
          }}
        >
          <Field
            label="Name"
            value={newContact.full_name}
            onChange={(event) => setNewContact({ ...newContact, full_name: event.target.value })}
            required
          />
          <Field
            label="Email"
            type="email"
            value={newContact.email}
            onChange={(event) => setNewContact({ ...newContact, email: event.target.value })}
            required
          />
          <Field
            label="Company"
            value={newContact.company}
            onChange={(event) => setNewContact({ ...newContact, company: event.target.value })}
          />
          <div className="flex items-end">
            <button type="submit" className="btn-primary px-3 py-1.5 text-sm">
              Add contact
            </button>
          </div>
        </form>
      )}

      <div className="max-h-64 overflow-y-auto rounded-md border border-ink-200 bg-white dark:border-ink-700 dark:bg-ink-900">
        {contacts.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-ink-500">
            No contacts yet. Add one above.
          </p>
        ) : (
          <ul className="divide-y divide-ink-200 dark:divide-ink-800">
            {contacts.map((contact) => {
              const out = contact.unsubscribed_at !== null
              const checked = selected.includes(contact.id)
              return (
                <li key={contact.id}>
                  <label
                    className={clsx(
                      'flex items-center gap-3 px-3.5 py-2',
                      out ? 'opacity-50' : 'cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-800/60',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[color:var(--accent)]"
                      disabled={out}
                      checked={checked}
                      onChange={() =>
                        setSelected((current) =>
                          checked
                            ? current.filter((id) => id !== contact.id)
                            : [...current, contact.id],
                        )
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-ink-800 dark:text-ink-100">
                        {contact.full_name}
                      </span>
                      <span className="block truncate text-2xs text-ink-400">
                        {contact.email}
                        {contact.company ? ` · ${contact.company}` : ''}
                      </span>
                    </span>
                    {/* An unsubscribe is honoured at the point of selection,
                        not silently dropped later at send time. */}
                    {out && (
                      <span className="chip bg-ink-200 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
                        Unsubscribed
                      </span>
                    )}
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          disabled={busy || selected.length === 0 || !campaign.target_id}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              const result = await api.post<{
                added: number
                skipped_existing: number
                skipped_unsubscribed: number
                warnings: string[]
              }>(`/campaigns/${campaign.id}/recipients`, {
                target_id: campaign.target_id,
                contact_ids: selected,
                batch: batch || null,
              })
              setSelected([])
              onDone(
                `${result.added} recipient(s) added` +
                  (result.skipped_existing ? `, ${result.skipped_existing} already invited` : '') +
                  (result.skipped_unsubscribed
                    ? `, ${result.skipped_unsubscribed} unsubscribed`
                    : '') +
                  '.',
              )
            } catch (caught) {
              setError(caught instanceof ApiError ? caught.message : 'Could not add recipients.')
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy && <Spinner />}
          Add {selected.length || ''} recipient{selected.length === 1 ? '' : 's'}
        </button>
        {!campaign.target_id && (
          <span className="text-xs text-caution">
            This campaign has no subject recorded yet.
          </span>
        )}
      </div>
    </div>
  )
}

function RecipientList({ campaign }: { campaign: Campaign }) {
  const [rows, setRows] = useState<Recipient[] | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const load = () => {
    api
      .get<Recipient[]>(`/campaigns/${campaign.id}/recipients`)
      .then(setRows)
      .catch(() => setRows([]))
  }

  useEffect(load, [campaign.id])

  if (!rows) return <Skeleton className="mt-4 h-32 w-full" />

  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-ink-200 dark:border-ink-700">
      <table className="data-table">
        <thead>
          <tr>
            <th>Recipient</th>
            <th>Company</th>
            <th>Batch</th>
            <th>Status</th>
            <th>Opens</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <span className="block text-ink-900 dark:text-ink-50">{row.contact_name}</span>
                <span className="block text-2xs text-ink-400">{row.contact_email}</span>
              </td>
              <td className="text-ink-600 dark:text-ink-300">{row.company ?? '—'}</td>
              <td className="text-2xs text-ink-400">{row.batch ?? '—'}</td>
              <td>
                <Chip value={row.status} />
              </td>
              <td className="tabular">{row.open_count}</td>
              <td className="text-right">
                {row.status === 'submitted' ? (
                  <span className="flex items-center justify-end gap-1 text-2xs text-positive">
                    <IconCheck width={12} height={12} />
                    Done
                  </span>
                ) : row.status === 'revoked' ? (
                  <span className="text-2xs text-ink-400">Revoked</span>
                ) : confirming === row.id ? (
                  <span className="flex justify-end gap-1.5">
                    <button
                      type="button"
                      className="btn-danger px-2 py-1 text-xs"
                      onClick={async () => {
                        await api.post(
                          `/campaigns/${campaign.id}/recipients/${row.id}/revoke`,
                        )
                        setConfirming(null)
                        load()
                      }}
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      className="btn-secondary px-2 py-1 text-xs"
                      onClick={() => setConfirming(null)}
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn-secondary px-2 py-1 text-xs"
                    onClick={() => setConfirming(row.id)}
                  >
                    {row.status === 'pending' ? 'Remove' : 'Revoke link'}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PAGE_SIZE = 15

export function Campaigns() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [panel, setPanel] = useState<{ id: string; view: 'recipients' | 'list' } | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [sending, setSending] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const load = () => {
    api
      .get<Campaign[]>('/campaigns')
      .then(setCampaigns)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load campaigns.'),
      )
  }

  useEffect(load, [])
  useRefetchOnFocus(load)

  const act = async (campaign: Campaign, action: 'open' | 'close') => {
    setError(null)
    try {
      await api.post(`/campaigns/${campaign.id}/${action}`)
      setConfirming(null)
      setNotice(
        action === 'open'
          ? `'${campaign.name}' is open. Send the invitations when you are ready.`
          : `'${campaign.name}' is closed.`,
      )
      load()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That did not work.')
    }
  }

  const send = async (campaign: Campaign, resend: boolean) => {
    setSending(campaign.id)
    setError(null)
    try {
      const result = await api.post<{
        sent: number
        failed: number
        skipped: number
      }>(`/campaigns/${campaign.id}/send`, { resend })
      setNotice(
        `${result.sent} invitation(s) sent` +
          (result.skipped ? `, ${result.skipped} skipped (unsubscribed)` : '') +
          (result.failed ? `, ${result.failed} failed` : '') +
          '.',
      )
      load()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Sending failed.')
    } finally {
      setSending(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Client campaigns"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Ask clients, customers and prospects for feedback by email. Each person gets a personal one-time link — no account, no password."
        actions={
          <CreateCampaign
            onCreated={(campaign) => {
              setNotice(
                campaign.status === 'draft'
                  ? `'${campaign.name}' created as a draft.`
                  : `'${campaign.name}' is open. Add recipients and send when ready.`,
              )
              setPanel({ id: campaign.id, view: 'recipients' })
              load()
            }}
          />
        }
      />

      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          {notice}
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Banner>
      )}

      {!campaigns ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-32 w-full rounded-lg" />
          ))}
        </div>
      ) : campaigns.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconSearch width={19} height={19} />}
            title="No campaigns yet"
            body="Create one to collect feedback from outside your organization."
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {campaigns.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((campaign) => (
            <Card key={campaign.id}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold text-ink-900 dark:text-ink-50">
                      {campaign.name}
                    </span>
                    <Chip value={campaign.status} />
                    {campaign.is_anonymous && (
                      <span className="chip accent-soft-bg accent-text flex items-center gap-1">
                        <IconLock width={10} height={10} />
                        Hidden below {campaign.min_responses_to_reveal}
                      </span>
                    )}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500 dark:text-ink-400">
                    {campaign.target_label && <span>About {campaign.target_label}</span>}
                    <span>
                      {campaign.template_name}
                      {campaign.template_version ? ` v${campaign.template_version}` : ''}
                    </span>
                    {campaign.closes_at && (
                      <span className="flex items-center gap-1">
                        <IconClock width={12} height={12} />
                        Closes {new Date(campaign.closes_at).toLocaleDateString()}
                      </span>
                    )}
                  </p>
                </div>

                <div className="flex shrink-0 flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-secondary px-3 py-1.5 text-sm"
                    onClick={() =>
                      setPanel(
                        panel?.id === campaign.id && panel.view === 'recipients'
                          ? null
                          : { id: campaign.id, view: 'recipients' },
                      )
                    }
                  >
                    <IconUsers width={14} height={14} />
                    Recipients
                  </button>
                  {campaign.delivery.total > 0 && (
                    <button
                      type="button"
                      className="btn-secondary px-3 py-1.5 text-sm"
                      onClick={() =>
                        setPanel(
                          panel?.id === campaign.id && panel.view === 'list'
                            ? null
                            : { id: campaign.id, view: 'list' },
                        )
                      }
                    >
                      Delivery
                    </button>
                  )}

                  {campaign.status === 'draft' &&
                    (confirming === campaign.id ? (
                      <span className="flex gap-1.5">
                        <button
                          type="button"
                          className="btn-primary px-2.5 py-1.5 text-sm"
                          onClick={() => act(campaign, 'open')}
                        >
                          Confirm open
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1.5 text-sm"
                          onClick={() => setConfirming(null)}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn-primary px-3 py-1.5 text-sm"
                        onClick={() => setConfirming(campaign.id)}
                      >
                        Open campaign
                      </button>
                    ))}

                  {campaign.status === 'draft' &&
                    (deleting === campaign.id ? (
                      <span className="flex gap-1.5">
                        <button
                          type="button"
                          className="btn-danger px-2.5 py-1.5 text-sm"
                          onClick={async () => {
                            try {
                              await api.delete(`/campaigns/${campaign.id}`)
                              setDeleting(null)
                              setNotice(`'${campaign.name}' deleted.`)
                              load()
                            } catch (caught) {
                              setError(
                                caught instanceof ApiError ? caught.message : 'Could not delete that campaign.',
                              )
                              setDeleting(null)
                            }
                          }}
                        >
                          Confirm delete
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1.5 text-sm"
                          onClick={() => setDeleting(null)}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn-ghost px-3 py-1.5 text-sm"
                        onClick={() => setDeleting(campaign.id)}
                      >
                        Delete
                      </button>
                    ))}

                  {campaign.status === 'open' && (
                    <>
                      {campaign.delivery.pending > 0 ? (
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-sm"
                          disabled={sending === campaign.id}
                          onClick={() => send(campaign, false)}
                        >
                          {sending === campaign.id && <Spinner />}
                          Send {campaign.delivery.pending} invitation
                          {campaign.delivery.pending === 1 ? '' : 's'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn-secondary px-3 py-1.5 text-sm"
                          disabled={sending === campaign.id}
                          onClick={() => send(campaign, true)}
                          title="Re-sending issues a fresh link and invalidates the previous one"
                        >
                          {sending === campaign.id && <Spinner />}
                          Chase non-responders
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-sm"
                        onClick={() => act(campaign, 'close')}
                      >
                        Close
                      </button>
                    </>
                  )}
                </div>
              </div>

              {campaign.delivery.total > 0 && (
                <div className="mt-4 border-t border-ink-200 pt-4 dark:border-ink-800">
                  <Funnel delivery={campaign.delivery} />
                </div>
              )}

              {panel?.id === campaign.id && panel.view === 'recipients' && (
                <RecipientPicker
                  campaign={campaign}
                  onDone={(message) => {
                    setNotice(message)
                    load()
                  }}
                />
              )}
              {panel?.id === campaign.id && panel.view === 'list' && (
                <RecipientList campaign={campaign} />
              )}
            </Card>
          ))}
        </div>
      )}
      {campaigns && campaigns.length > 0 && (
        <div className="mt-1 surface">
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={campaigns.length}
            onPage={setPage}
          />
        </div>
      )}
    </>
  )
}
