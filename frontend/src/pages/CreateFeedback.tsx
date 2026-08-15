import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FloatingPanel, LookupFilter, SearchBox, useDismiss } from '../components/filters'
import { IconChevronDown } from '../components/icons'
import { useToast } from '../components/Toast'
import { Banner, Card, Field, Skeleton, Spinner } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { Paged } from '../lib/types'

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
    blurb: 'How a client rates the relationship as a whole.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'employee',
    label: 'Employees',
    color: '#3B82F6',
    targetType: 'employee',
    audience: 'internal',
    blurb: 'A 360 round about one employee: self, manager and peers.',
    revieweeLabel: 'Who is this about',
  },
  {
    kind: 'management',
    label: 'Management',
    color: '#8B5CF6',
    targetType: 'manager',
    audience: 'internal',
    blurb: 'Upward feedback on a manager, from their direct reports.',
    revieweeLabel: 'Which manager',
  },
  {
    kind: 'product',
    label: 'Product',
    color: '#10B981',
    targetType: 'product',
    audience: 'external',
    blurb: 'How clients or users rate a product or feature.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'service',
    label: 'Service',
    color: '#F59E0B',
    targetType: 'service',
    audience: 'external',
    blurb: 'How clients rate a delivered service or engagement.',
    revieweeLabel: 'Recipients',
  },
  {
    kind: 'proposal',
    label: 'Proposal Review',
    color: '#EC4899',
    targetType: 'proposal',
    audience: 'external',
    blurb: 'Prospect feedback on a submitted proposal or SOW.',
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
        <div className="mt-2 flex flex-wrap gap-1.5">
          {selected.map((id) => {
            const contact = chosen[id]
            return (
              <span key={id} className="chip accent-soft-bg accent-text">
                {contact?.full_name ?? '…'}
                <button
                  type="button"
                  className="ml-1 opacity-70 hover:opacity-100"
                  aria-label={`Remove ${contact?.full_name ?? 'recipient'}`}
                  onClick={() => onChange(selected.filter((existing) => existing !== id))}
                >
                  ×
                </button>
              </span>
            )
          })}
        </div>
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
  const [revieweeId, setRevieweeId] = useState<string | null>(null)
  const [aboutUserId, setAboutUserId] = useState<string | null>(null)
  const [targetLabel, setTargetLabel] = useState('')
  const [contactIds, setContactIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nameTouched, setNameTouched] = useState(false)

  useEffect(() => {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('kind', kind)
      return next
    })
    setTemplateId('')
    setRevieweeId(null)
    setAboutUserId(null)
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
    if (kind === 'client') return Boolean(aboutUserId || targetLabel.trim()) && contactIds.length > 0
    return Boolean(targetLabel.trim()) && contactIds.length > 0
  })()

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<CreateResult>('/feedback', {
        kind,
        template_id: templateId,
        name: name.trim(),
        closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        reviewee_user_id: kind === 'employee' || kind === 'management' ? revieweeId : null,
        about_user_id: kind === 'client' ? aboutUserId : null,
        target_label:
          kind === 'client' || kind === 'product' || kind === 'service' || kind === 'proposal'
            ? targetLabel || null
            : null,
        contact_ids: config.audience === 'external' ? contactIds : [],
      })
      toast.show(
        'success',
        'Feedback sent',
        result.warnings.length
          ? `'${name}' is on its way. ${result.warnings.join(' ')}`
          : `'${name}' is on its way.`,
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
          <Card title="Template" hint="The questionnaire this round is built from.">
            <label className="block">
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
          </Card>

          <Card title="Who's involved" hint="Who this round is about, and who it goes to.">
            <div className="space-y-5">
              {kind === 'client' && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    About (optional)
                  </span>
                  <LookupFilter
                    entity="users"
                    label="Choose a person"
                    selected={aboutUserId ? [aboutUserId] : []}
                    onChange={(ids) => setAboutUserId(ids[ids.length - 1] ?? null)}
                  />
                </div>
              )}

              {(kind === 'employee' || kind === 'management') && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    {config.revieweeLabel}
                  </span>
                  <LookupFilter
                    entity="users"
                    label={kind === 'management' ? 'Choose a manager' : 'Choose a person'}
                    selected={revieweeId ? [revieweeId] : []}
                    onChange={(ids) => setRevieweeId(ids[ids.length - 1] ?? null)}
                  />
                  <span className="mt-1.5 block text-xs text-ink-400">
                    {kind === 'employee'
                      ? 'Reviewers are generated from the org chart: self, manager and peers.'
                      : 'Their direct reports will be asked to review them.'}
                  </span>
                </div>
              )}

              {(kind === 'client' || kind === 'product' || kind === 'service' || kind === 'proposal') && (
                <Field
                  label={kind === 'client' ? "What's this about (if not a specific person)" : "What's this about"}
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

          <Card title="Schedule" hint="Name this round and, optionally, give it a deadline.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Campaign name"
                value={name}
                onChange={(event) => {
                  setNameTouched(true)
                  setName(event.target.value)
                }}
                required
              />

              <Field
                label="Closes on (optional)"
                type="date"
                value={closesAt}
                onChange={(event) => setClosesAt(event.target.value)}
              />
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
