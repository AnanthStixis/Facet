import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FloatingPanel, SearchBox, useDismiss } from '../components/filters'
import { IconChevronDown } from '../components/icons'
import { useToast } from '../components/Toast'
import { Banner, Card, Field, Skeleton, Spinner } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { Paged } from '../lib/types'

// A chip list truncates once it grows past this many entries — picking 50
// recipients (the case the client called out) should not turn the form into
// a scroll of cards; the rest collapse behind one "N more" toggle.
const CHIP_TRUNCATE_AT = 8

export type FeedbackKind = 'client' | 'employee' | 'management' | 'product' | 'service' | 'proposal'

interface KindConfig {
  kind: FeedbackKind
  label: string
  color: string
  targetType: string
  audience: 'internal' | 'external'
  blurb: string
  revieweeLabel: string
}

export const FEEDBACK_TYPES: KindConfig[] = [
  {
    kind: 'client',
    label: 'Client',
    color: '#B4633A',
    targetType: 'client',
    audience: 'external',
    blurb: 'How a client rates the relationship as a whole — one round, sent straight to their inbox.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'employee',
    label: 'Employees',
    color: '#3B82F6',
    targetType: 'employee',
    audience: 'internal',
    blurb: 'A 360 round about one employee — self, manager, and peers all weigh in.',
    revieweeLabel: 'Who is this about',
  },
  {
    kind: 'management',
    label: 'Management',
    color: '#8B5CF6',
    targetType: 'manager',
    audience: 'internal',
    blurb: 'Upward feedback on a manager, gathered from their direct reports.',
    revieweeLabel: 'Which manager',
  },
  {
    kind: 'product',
    label: 'Product',
    color: '#10B981',
    targetType: 'product',
    audience: 'external',
    blurb: 'How clients or users rate a product or feature they have actually used.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'service',
    label: 'Service',
    color: '#F59E0B',
    targetType: 'service',
    audience: 'external',
    blurb: 'How clients rate a service or engagement once it has been delivered.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'proposal',
    label: 'Proposal Review',
    color: '#EC4899',
    targetType: 'proposal',
    audience: 'external',
    blurb:
      'Prospect feedback on a submitted proposal or SOW — covering technical soundness, ' +
      'how clearly it was communicated, and how realistic the delivery timeline is.',
    revieweeLabel: 'Recipients',
  },
]

interface TemplateOption {
  id: string
  name: string
  status: string | null
  target_type: string
  is_anonymous: boolean
  min_responses_to_reveal: number
  is_active: boolean
}

interface Contact {
  id: string
  email: string
  full_name: string
  company: string | null
  unsubscribed_at: string | null
}

interface CreateResult {
  cycle_id: string
  status: string
  warnings: string[]
}

// Mirrors the shapes GET /catalog/templates/{id} returns (see Templates.tsx's
// own DefinitionDoc/TemplateDetail) — only the fields this panel renders.
interface PanelQuestion {
  key: string
  text: string
  type: string
  required: boolean
}

interface PanelSection {
  key: string
  title: string
  questions: PanelQuestion[]
}

interface TemplateDetail {
  id: string
  name: string
  description: string | null
  latest: { definition: { sections: PanelSection[] } } | null
}

const QUESTION_TYPE_LABEL: Record<string, string> = {
  scale: 'Rating scale',
  choice: 'Multiple choice',
  boolean: 'Yes / no',
  text: 'Free text',
}


/** "Questions in this template" side panel — rebuilds the pattern from
 * docs/mockup_simple_feedback.html's approved `.preview` panel as real
 * React/Tailwind, fetching and caching the full definition by id since the
 * `/catalog/categories` list this page's dropdown is built from only carries
 * template meta, not question text. */
function TemplateDetailPanel({ templateId }: { templateId: string | null }) {
  const cache = useRef<Map<string, TemplateDetail>>(new Map())
  const [detail, setDetail] = useState<TemplateDetail | null>(
    templateId ? (cache.current.get(templateId) ?? null) : null,
  )
  const [loading, setLoading] = useState(!!templateId && !cache.current.has(templateId))
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!templateId) {
      setDetail(null)
      setLoading(false)
      setError(false)
      return
    }
    const cached = cache.current.get(templateId)
    if (cached) {
      setDetail(cached)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(false)
    api
      .get<TemplateDetail>(`/catalog/templates/${templateId}`)
      .then((result) => {
        if (cancelled) return
        cache.current.set(templateId, result)
        setDetail(result)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [templateId])

  const questions = detail?.latest?.definition.sections.flatMap((section) => section.questions) ?? []

  return (
    <aside className="surface sticky top-6 flex max-h-[calc(100vh-3rem)] flex-col p-4">
      <p className="label-caps mb-2 shrink-0">Questions in this template</p>
      {!templateId ? (
        <p className="text-xs text-ink-400">Choose a template to see its questions here.</p>
      ) : loading ? (
        <div className="space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ) : error || !detail ? (
        <p className="text-xs text-ink-400">Could not load this template's questions.</p>
      ) : (
        <>
          <p className="shrink-0 text-base font-semibold text-ink-900 dark:text-ink-50">{detail.name}</p>
          {detail.description && (
            <p className="mt-0.5 shrink-0 text-xs text-ink-500 dark:text-ink-400">{detail.description}</p>
          )}
          <ul className="mt-3 min-h-0 flex-1 divide-y divide-ink-200 overflow-y-auto dark:divide-ink-800">
            {questions.map((question, index) => (
              <li key={question.key} className="flex gap-2 py-2 text-xs first:pt-0">
                <span className="shrink-0 tabular text-ink-400">{index + 1}.</span>
                <span className="min-w-0">
                  <span className="block text-ink-600 dark:text-ink-300">{question.text}</span>
                  <span className="mt-1 inline-block rounded bg-ink-100 px-1.5 py-0.5 text-2xs font-medium uppercase tracking-[0.04em] accent-text accent-soft-bg dark:bg-ink-800">
                    {QUESTION_TYPE_LABEL[question.type] ?? question.type}
                  </span>
                </span>
              </li>
            ))}
            {questions.length === 0 && <li className="py-2 text-xs text-ink-400">No questions yet.</li>}
          </ul>
        </>
      )}
    </aside>
  )
}

/** Selected-item chips, truncated past CHIP_TRUNCATE_AT with a "N more"
 * toggle — picking 50+ people otherwise turns the form into a wall of
 * cards. */
function ChipList({
  items,
  onRemove,
}: {
  items: { id: string; label: string }[]
  onRemove: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, CHIP_TRUNCATE_AT)
  const hidden = items.length - visible.length

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {visible.map((item) => (
        <span key={item.id} className="chip accent-soft-bg accent-text">
          {item.label}
          <button
            type="button"
            className="ml-1 opacity-70 hover:opacity-100"
            aria-label={`Remove ${item.label}`}
            onClick={() => onRemove(item.id)}
          >
            ×
          </button>
        </span>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="chip bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300"
          onClick={() => setExpanded(true)}
        >
          +{hidden} more
        </button>
      )}
      {expanded && items.length > CHIP_TRUNCATE_AT && (
        <button
          type="button"
          className="chip bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300"
          onClick={() => setExpanded(false)}
        >
          Show less
        </button>
      )}
    </div>
  )
}

interface PickableUser {
  id: string
  full_name: string
  email: string
  phone: string | null
}

/** "About" people picker: multi-select over the org's users, showing each
 * person's email and mobile number both in the results list and on their
 * selected chip — the client asked to see how to reach whoever a client
 * round is actually about. */
function UserPicker({
  selected,
  onChange,
}: {
  selected: PickableUser[]
  onChange: (users: PickableUser[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [users, setUsers] = useState<PickableUser[]>([])
  const [search, setSearch] = useState('')
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const query = new URLSearchParams({ page_size: '50' })
    if (search) query.set('search', search)
    let cancelled = false
    api
      .get<Paged<PickableUser>>(`/users?${query}`)
      .then((page) => !cancelled && setUsers(page.items))
      .catch(() => !cancelled && setUsers([]))
    return () => {
      cancelled = true
    }
  }, [search, open])

  const toggle = (user: PickableUser) => {
    onChange(
      selected.some((existing) => existing.id === user.id)
        ? selected.filter((existing) => existing.id !== user.id)
        : [...selected, user],
    )
  }

  return (
    <div className="relative" ref={triggerRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((state) => !state)}
        className={clsx(
          'field flex w-full items-center justify-between text-left',
          selected.length > 0 && 'accent-border accent-text',
        )}
      >
        <span className="truncate">
          {selected.length === 0
            ? 'Choose a person'
            : `${selected.length} selected`}
        </span>
        <IconChevronDown className="shrink-0 opacity-60" />
      </button>

      {selected.length > 0 && (
        <ChipList
          items={selected.map((user) => ({
            id: user.id,
            label: `${user.full_name} · ${user.email}${user.phone ? ` · ${user.phone}` : ''}`,
          }))}
          onRemove={(id) => onChange(selected.filter((existing) => existing.id !== id))}
        />
      )}

      <FloatingPanel anchorRef={buttonRef} panelRef={panelRef} open={open} className="w-96 p-2">
        <div className="mb-2 px-1 pt-1">
          <SearchBox value={search} onChange={setSearch} placeholder="Search people" />
        </div>
        <div className="max-h-64 overflow-y-auto">
          {users.length === 0 ? (
            <p className="px-3 py-5 text-center text-sm text-ink-500">No matches.</p>
          ) : (
            <ul>
              {users.map((user) => {
                const checked = selected.some((existing) => existing.id === user.id)
                return (
                  <li key={user.id}>
                    <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-ink-50 dark:hover:bg-ink-800/60">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-[color:var(--accent)]"
                        checked={checked}
                        onChange={() => toggle(user)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-ink-800 dark:text-ink-100">
                          {user.full_name}
                        </span>
                        <span className="block truncate text-2xs text-ink-400">
                          {user.email}
                          {user.phone ? ` · ${user.phone}` : ''}
                        </span>
                      </span>
                    </label>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </FloatingPanel>
    </div>
  )
}

interface CycleNameOption {
  id: string
  name: string
}

/** Feedback Cycle Name field: a text input with a "+" trigger next to it
 * that opens a popup listing names from the Cycle Name master, searchable,
 * with an inline "add new" — picking one fills the field, adding one both
 * fills the field and adds it to the master for next time. */
function CycleNamePicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<CycleNameOption[]>([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))
  const anchorRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const query = new URLSearchParams({ page_size: '200' })
    if (search) query.set('q', search)
    api
      .get<{ items: CycleNameOption[] }>(`/masters/cycle-names?${query}`)
      .then((page) => setOptions(page.items))
      .catch(() => setOptions([]))
  }, [search, open])

  const pick = (option: CycleNameOption) => {
    onChange(option.name)
    setOpen(false)
  }

  const addNew = async () => {
    const name = search.trim()
    if (!name) return
    setBusy(true)
    try {
      const created = await api.post<CycleNameOption>('/masters/cycle-names', { name })
      onChange(created.name)
      setOpen(false)
    } finally {
      setBusy(false)
    }
  }

  const exactMatch = options.some((o) => o.name.toLowerCase() === search.trim().toLowerCase())

  return (
    <div className="relative" ref={triggerRef}>
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
        Feedback Cycle Name
      </span>
      <div className="flex items-center gap-2">
        <input
          className="field flex-1"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required
        />
        <button
          ref={anchorRef}
          type="button"
          className="btn-secondary shrink-0 px-2.5 py-1.5 text-base leading-none"
          aria-label="Choose from cycle names"
          onClick={() => {
            setSearch('')
            setOpen((state) => !state)
          }}
        >
          +
        </button>
      </div>

      <FloatingPanel anchorRef={anchorRef} panelRef={panelRef} open={open} className="w-72 p-2">
        <div className="mb-2 px-1 pt-1">
          <SearchBox value={search} onChange={setSearch} placeholder="Search cycle names" />
        </div>
        <div className="max-h-56 overflow-y-auto">
          {options.length === 0 ? (
            <p className="px-3 py-3 text-center text-sm text-ink-500">No matches yet.</p>
          ) : (
            <ul>
              {options.map((option) => (
                <li key={option.id}>
                  <button
                    type="button"
                    className="w-full rounded-md px-2.5 py-1.5 text-left text-sm text-ink-800 hover:bg-ink-100 dark:text-ink-100 dark:hover:bg-ink-800"
                    onClick={() => pick(option)}
                  >
                    {option.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {search.trim() && !exactMatch && (
          <button
            type="button"
            className="btn-secondary mt-2 w-full px-3 py-1.5 text-sm"
            disabled={busy}
            onClick={addNew}
          >
            {busy && <Spinner />}
            Add "{search.trim()}"
          </button>
        )}
      </FloatingPanel>
    </div>
  )
}

/** Recipients as a dropdown: a trigger button showing how many are selected,
 * opening a floating panel with search, inline "new contact", and a
 * checkbox per contact for multi-select — the same collapsed/expanded
 * pattern as LookupFilter, just with checkboxes instead of single-pick. */
function ContactPicker({
  selected,
  onChange,
}: {
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const [newContact, setNewContact] = useState({ full_name: '', email: '', company: '' })
  const [chosen, setChosen] = useState<Record<string, Contact>>({})
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))
  // The panel anchors to the trigger button itself, not the wrapping div —
  // that div also holds the selected-chips row below the button, which grows
  // taller as more recipients are picked. Anchoring to the whole wrapper
  // meant the panel drifted further down (and away from the button) every
  // time a chip was added.
  const buttonRef = useRef<HTMLButtonElement>(null)

  const load = () => {
    const query = new URLSearchParams({ page_size: '200' })
    if (search) query.set('search', search)
    api
      .get<Paged<Contact>>(`/contacts?${query}`)
      .then((page) => {
        setContacts(page.items)
        setChosen((state) => {
          const next = { ...state }
          for (const contact of page.items) next[contact.id] = contact
          return next
        })
      })
      .catch(() => setContacts([]))
  }

  useEffect(() => {
    if (open) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, open])

  const toggle = (contact: Contact) => {
    setChosen((state) => ({ ...state, [contact.id]: contact }))
    onChange(
      selected.includes(contact.id)
        ? selected.filter((id) => id !== contact.id)
        : [...selected, contact.id],
    )
  }

  return (
    <div className="relative" ref={triggerRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((state) => !state)}
        className={clsx(
          'field flex w-full items-center justify-between text-left',
          selected.length > 0 && 'accent-border accent-text',
        )}
      >
        <span className="truncate">
          {selected.length === 0
            ? 'Choose recipients'
            : `${selected.length} recipient${selected.length === 1 ? '' : 's'} selected`}
        </span>
        <IconChevronDown className="shrink-0 opacity-60" />
      </button>

      {selected.length > 0 && (
        <ChipList
          items={selected.map((id) => ({ id, label: chosen[id]?.full_name ?? '…' }))}
          onRemove={(id) => onChange(selected.filter((existing) => existing !== id))}
        />
      )}

      <FloatingPanel anchorRef={buttonRef} panelRef={panelRef} open={open} className="w-80 p-2">
        <div className="mb-2 flex flex-wrap items-center gap-2 px-1 pt-1">
          <div className="min-w-[160px] flex-1">
            <SearchBox value={search} onChange={setSearch} placeholder="Search contacts" />
          </div>
          <button
            type="button"
            className="btn-secondary px-2.5 py-1.5 text-sm"
            onClick={() => setAdding((state) => !state)}
          >
            {adding ? 'Cancel' : 'New'}
          </button>
        </div>

        {adding && (
          <div className="mb-2 space-y-2 px-1">
            <Field
              label="Name"
              value={newContact.full_name}
              onChange={(event) => setNewContact({ ...newContact, full_name: event.target.value })}
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
              onChange={(event) => setNewContact({ ...newContact, company: event.target.value })}
            />
            <button
              type="button"
              className="btn-primary w-full px-3 py-1.5 text-sm"
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
                  load()
                  setChosen((state) => ({ ...state, [created.id]: created }))
                  onChange([...selected, created.id])
                } catch (caught) {
                  toast.show(
                    'critical',
                    'Could not add contact',
                    caught instanceof ApiError ? caught.message : 'Could not add the contact.',
                  )
                }
              }}
            >
              Add contact
            </button>
          </div>
        )}

        <div className="max-h-64 overflow-y-auto">
          {contacts.length === 0 ? (
            <p className="px-3 py-5 text-center text-sm text-ink-500">
              No contacts yet. Add one above.
            </p>
          ) : (
            <ul>
              {contacts.map((contact) => {
                const out = contact.unsubscribed_at !== null
                const checked = selected.includes(contact.id)
                return (
                  <li key={contact.id}>
                    <label
                      className={clsx(
                        'flex items-center gap-3 rounded-md px-2 py-1.5',
                        out ? 'opacity-50' : 'cursor-pointer hover:bg-ink-50 dark:hover:bg-ink-800/60',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-[color:var(--accent)]"
                        disabled={out}
                        checked={checked}
                        onChange={() => toggle(contact)}
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
      </FloatingPanel>
    </div>
  )
}

export function CreateFeedback() {
  const toast = useToast()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const initialKind = (params.get('kind') as FeedbackKind | null) ?? 'employee'
  const [kind, setKind] = useState<FeedbackKind>(
    FEEDBACK_TYPES.some((t) => t.kind === initialKind) ? initialKind : 'employee',
  )
  const config = FEEDBACK_TYPES.find((t) => t.kind === kind)!

  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [templateId, setTemplateId] = useState('')
  const [name, setName] = useState('')
  const [closesAt, setClosesAt] = useState('')
  const [revieweeUser, setRevieweeUser] = useState<PickableUser | null>(null)
  const revieweeId = revieweeUser?.id ?? null
  const [aboutUsers, setAboutUsers] = useState<PickableUser[]>([])
  const [targetLabel, setTargetLabel] = useState('')
  const [contactIds, setContactIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nameTouched, setNameTouched] = useState(false)

  // Clicking a type in the nav (or the in-page tab strip) only changes the
  // `kind` query param on this same route — React Router does not remount
  // the page for that, so the kind shown here has to track the URL rather
  // than only being read once at mount.
  useEffect(() => {
    const fromUrl = params.get('kind') as FeedbackKind | null
    if (fromUrl && FEEDBACK_TYPES.some((t) => t.kind === fromUrl) && fromUrl !== kind) {
      setKind(fromUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  useEffect(() => {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('kind', kind)
      return next
    })
    setTemplateId('')
    setRevieweeUser(null)
    setAboutUsers([])
    setTargetLabel('')
    setContactIds([])
    setNameTouched(false)
    setName('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  useEffect(() => {
    api
      .get<{ templates: TemplateOption[] }[]>('/catalog/categories')
      .then((categories) =>
        setTemplates(
          categories
            .flatMap((category) => category.templates)
            .filter(
              (t) => t.status === 'published' && t.target_type === config.targetType && t.is_active,
            ),
        ),
      )
      .catch(() => setTemplates([]))
  }, [config.targetType])

  const selectedTemplate = templates.find((t) => t.id === templateId) ?? null

  // Auto-suggested name, editable — mirrors the plan's
  // "${reviewee.name} — ${template.name}" pattern where a name is known.
  useEffect(() => {
    if (nameTouched) return
    if (!selectedTemplate) return
    setName(`${selectedTemplate.name} — ${new Date().toLocaleDateString()}`)
  }, [selectedTemplate, nameTouched])

  const canSubmit = (() => {
    if (!templateId || !name.trim()) return false
    if (kind === 'employee' || kind === 'management') return Boolean(revieweeId)
    if (kind === 'client') return (aboutUsers.length > 0 || targetLabel.trim()) && contactIds.length > 0
    return Boolean(targetLabel.trim()) && contactIds.length > 0
  })()

  const submit = async () => {
    setBusy(true)
    setError(null)
    const basePayload = {
      kind,
      template_id: templateId,
      closes_at: closesAt ? new Date(closesAt).toISOString() : null,
      reviewee_user_id: kind === 'employee' || kind === 'management' ? revieweeId : null,
      target_label:
        kind === 'client' || kind === 'product' || kind === 'service' || kind === 'proposal'
          ? targetLabel || null
          : null,
      contact_ids: config.audience === 'external' ? contactIds : [],
    }
    // Client feedback "about" multiple people creates one cycle per person
    // (each gets their own results), otherwise it's a single create call.
    const aboutTargets = kind === 'client' && aboutUsers.length > 0 ? aboutUsers : [null]
    try {
      const results = await Promise.all(
        aboutTargets.map((user) =>
          api.post<CreateResult>('/feedback', {
            ...basePayload,
            name: aboutTargets.length > 1 ? `${name.trim()} — ${user!.full_name}` : name.trim(),
            about_user_id: user?.id ?? null,
          }),
        ),
      )
      const warnings = results.flatMap((r) => r.warnings)
      toast.show(
        'success',
        'Feedback sent',
        warnings.length ? `'${name}' is on its way. ${warnings.join(' ')}` : `'${name}' is on its way.`,
      )
      navigate('/results')
    } catch (caught) {
      const message =
        caught instanceof ApiError ? caught.message : 'Could not create and send this feedback.'
      setError(message)
      toast.show('critical', 'Could not send', message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Create Feedback" description={config.blurb} />

      <div className="surface mb-5 flex flex-wrap gap-1.5 p-1.5">
        {FEEDBACK_TYPES.map((t) => (
          <button
            key={t.kind}
            type="button"
            onClick={() => setKind(t.kind)}
            className={clsx(
              'flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors',
              kind === t.kind
                ? 'bg-ink-900 text-white dark:bg-white dark:text-ink-900'
                : 'text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800',
            )}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: t.color }}
              aria-hidden="true"
            />
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <Banner tone="error" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Banner>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
        <div className="space-y-5">
          <Card title="Template Details">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block sm:col-span-2">
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
                {templates.length === 0 && (
                  <span className="mt-1.5 block text-xs text-caution">
                    No published template for this feedback type yet — ask an admin to publish one
                    under Templates.
                  </span>
                )}
                {selectedTemplate && (
                  <span className="mt-1.5 block text-xs text-ink-400">
                    {selectedTemplate.is_anonymous
                      ? 'This template collects anonymous responses.'
                      : 'Responses are not anonymous.'}
                  </span>
                )}
              </label>

              <CycleNamePicker
                value={name}
                onChange={(value) => {
                  setNameTouched(true)
                  setName(value)
                }}
              />

              <Field
                label="Closes on (optional)"
                type="date"
                value={closesAt}
                onChange={(event) => setClosesAt(event.target.value)}
              />
            </div>
          </Card>

          <Card title="Who's involved">
            <div className="space-y-5">
              {kind === 'client' && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    About (optional)
                  </span>
                  <UserPicker selected={aboutUsers} onChange={setAboutUsers} />
                </div>
              )}

              {(kind === 'employee' || kind === 'management') && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    {config.revieweeLabel}
                  </span>
                  <UserPicker
                    selected={revieweeUser ? [revieweeUser] : []}
                    onChange={(picked) => setRevieweeUser(picked[picked.length - 1] ?? null)}
                  />
                  {kind === 'management' && (
                    <span className="mt-1.5 block text-xs text-ink-400">
                      Their direct reports will be asked to review them.
                    </span>
                  )}
                </div>
              )}

              {(kind === 'client' || kind === 'product' || kind === 'service' || kind === 'proposal') && (
                <Field
                  label={kind === 'client' ? 'Description' : "What's this about"}
                  value={targetLabel}
                  onChange={(event) => setTargetLabel(event.target.value)}
                  placeholder={
                    kind === 'client'
                      ? 'e.g. Northwind relationship'
                      : kind === 'product'
                        ? 'e.g. Track & Trace'
                        : kind === 'service'
                          ? 'e.g. Managed Integration Service'
                          : 'e.g. Parata / NEXiA platform modernisation'
                  }
                />
              )}

              {config.audience === 'external' && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    Recipients
                  </span>
                  <ContactPicker selected={contactIds} onChange={setContactIds} />
                </div>
              )}
            </div>
          </Card>

          <Card padded={false}>
            <div className="flex items-center gap-2 px-5 py-4">
              <button
                type="button"
                className="btn-primary px-4 py-1.5"
                disabled={!canSubmit || busy}
                onClick={submit}
              >
                {busy && <Spinner />}
                Create Feedback
              </button>
            </div>
          </Card>
        </div>

        <TemplateDetailPanel templateId={selectedTemplate?.id ?? null} />
      </div>
    </>
  )
}
