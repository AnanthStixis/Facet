import { useEffect, useRef, useState } from 'react'
import { IconTrash } from '../components/icons'
import { Banner, Card, Chip, ConfirmDialog, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { EmailTemplateKind, EmailTemplateLibrary, EmailTemplateOut } from '../lib/types'
import { useAuth } from '../store/auth'

// Kept in sync with AppShell.tsx's CREATE_FEEDBACK_TYPES by hand, same as
// that file's own note about feedback.py's kind list — this page only needs
// label/color, not the rest of that config.
const KIND_META: Record<EmailTemplateKind, { label: string; color: string }> = {
  client: { label: 'Client Review', color: '#B4633A' },
  employee: { label: 'Employees Review', color: '#3B82F6' },
  management: { label: 'Management Review', color: '#8B5CF6' },
  product: { label: 'Product Review', color: '#10B981' },
  service: { label: 'Service Review', color: '#F59E0B' },
  proposal: { label: 'Proposal Review', color: '#EC4899' },
}
const KIND_ORDER: EmailTemplateKind[] = [
  'client',
  'employee',
  'management',
  'product',
  'service',
  'proposal',
]

interface Draft {
  name: string
  subject_template: string
  heading: string
  body_text: string
}

function toDraft(source: EmailTemplateOut): Draft {
  return {
    name: source.name,
    subject_template: source.subject_template,
    heading: source.heading,
    body_text: source.body_text,
  }
}

const EMPTY_DRAFT: Draft = { name: '', subject_template: '', heading: '', body_text: '' }


// ---------------------------------------------------------------------------
// Placeholder insert chips — friendly label in, correct {token} out.
//
// The admin never types a raw token (and so can't misspell one into a silent
// send-time failure); they click a labelled chip and the exact token lands at
// the cursor. Which chips appear depends on the review kind, because the two
// send paths fill different context (verified against services/email.py):
//   internal (employee, management):      first_name, org_name, subject_label, cycle_name
//   external (client/product/service/proposal): first_name, org_name, subject_label, deadline
//
// TEMPORARY SOURCE. This is a second copy of a list the backend already holds
// inline (in those two send dicts). It stays here only until the backend
// exposes it as one source of truth (planned GET
// /email-templates/{kind}/placeholders). When that lands, replace chipsForKind
// with a fetch — nothing else here changes, since the UI below only ever
// consumes {token,label} pairs.
// ---------------------------------------------------------------------------
interface PlaceholderChip {
  token: string
  label: string
}

// AFTER
// The one place a placeholder token maps to its friendly label. Both the
// insert chips and the read-only humanizer below read from this, so a label
// is defined once and can't drift between the editor and the list views.
const TOKEN_LABELS: Record<string, string> = {
  '{first_name}': "Recipient's first name",
  '{org_name}': 'Organization name',
  '{subject_label}': 'Feedback topic',
  '{cycle_name}': 'Name of this review round',
  '{deadline}': 'Feedback deadline',
}

const chip = (token: string): PlaceholderChip => ({ token, label: TOKEN_LABELS[token] ?? token })

// Replace every known {token} in read-only text with its friendly label, so
// list/summary views never show raw {cycle_name} syntax to an admin. The
// stored value is never changed — this is display-only.
function humanizeTokens(text: string): string {
  return text.replace(/\{[a-zA-Z_]+\}/g, (match) => {
    const label = TOKEN_LABELS[match]
    return label ? `[${label}]` : match
  })
}

const SHARED_CHIPS: PlaceholderChip[] = [chip('{first_name}'), chip('{org_name}'), chip('{subject_label}')]
const INTERNAL_KINDS: EmailTemplateKind[] = ['employee', 'management']

function chipsForKind(kind: EmailTemplateKind): PlaceholderChip[] {
  // {deadline} is intentionally not offered as a chip — the expiry date is
  // always appended automatically below the message, so letting an admin
  // insert it into the body would be redundant and contradictory.
  return INTERNAL_KINDS.includes(kind)
    ? [...SHARED_CHIPS, chip('{cycle_name}')]
    : [...SHARED_CHIPS]
}

// Insert `token` at the field's caret (not the end), then restore focus with
// the caret just past what was inserted. requestAnimationFrame is required:
// the value change is a React state update, so at onClick time the DOM node
// still holds the old text and selection — we reposition on the next frame,
// after React has committed the new value.
function insertToken(
  el: HTMLInputElement | HTMLTextAreaElement | null,
  value: string,
  onChange: (next: string) => void,
  token: string,
) {
  if (!el) {
    onChange(value + token)
    return
  }
  const start = el.selectionStart ?? value.length
  const end = el.selectionEnd ?? value.length
  onChange(value.slice(0, start) + token + value.slice(end))
  const caret = start + token.length
  requestAnimationFrame(() => {
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

function PlaceholderChips({
  kind,
  getEl,
  value,
  onChange,
}: {
  kind: EmailTemplateKind
  getEl: () => HTMLInputElement | HTMLTextAreaElement | null
  value: string
  onChange: (next: string) => void
}) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-ink-400">Insert:</span>
      {chipsForKind(kind).map((chip) => (
        <button
          key={chip.token}
          type="button"
          title={`Inserts ${chip.token}`}
          onClick={() => insertToken(getEl(), value, onChange, chip.token)}
          className="rounded-full border border-ink-200 px-2 py-0.5 text-xs text-ink-600 transition hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800"
        >
          + {chip.label}
        </button>
      ))}
    </div>
  )
}

function TemplateForm({
  meta,
  draft,
  setDraft,
  readOnly,
  kind,
}: {
  meta: { label: string; color: string }
  draft: Draft
  setDraft: (draft: Draft) => void
  readOnly: boolean
  kind: EmailTemplateKind
}) {
  const toast = useToast()
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<{ subject: string; html: string } | null>(null)
  const subjectRef = useRef<HTMLInputElement>(null)
  const headingRef = useRef<HTMLInputElement>(null)
  const messageRef = useRef<HTMLTextAreaElement>(null)
  const [touched, setTouched] = useState<{ name: boolean; subject: boolean; body: boolean }>({
    name: false,
    subject: false,
    body: false,
  })
  const markTouched = (field: 'name' | 'subject' | 'body') =>
    setTouched((prev) => ({ ...prev, [field]: true }))
  const errors = {
    name: touched.name && !draft.name.trim() ? 'Template name is required' : '',
    subject: touched.subject && !draft.subject_template.trim() ? 'Subject is required' : '',
    body: touched.body && !draft.body_text.trim() ? 'Message is required' : '',
  }

  const runPreview = async () => {
    setPreviewing(true)
    try {
      const rendered = await api.post<{ subject: string; html: string }>(
        `/email-templates/${kind}/preview`,
        {
          subject_template: draft.subject_template,
          heading: draft.heading,
          body_text: draft.body_text,
        },
      )
      setPreview(rendered)
    } catch (caught) {
      toast.show(
        'critical',
        'Could not render the preview',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <>
      <div className="mb-4 flex items-center gap-2 text-sm text-ink-500 dark:text-ink-400">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: meta.color }}
          aria-hidden="true"
        />
        {meta.label}
      </div>

      <div className="space-y-5">
        {!readOnly && (
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
              Template name <span className="text-red-500">*</span>
            </span>
            <input
              className={`field${errors.name ? ' border-red-400' : ''}`}
              maxLength={150}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              onBlur={() => markTouched('name')}
              aria-invalid={errors.name ? true : undefined}
              placeholder="e.g. Formal pitch"
            />
            {errors.name && (
              <span className="mt-1 block text-xs text-red-500">{errors.name}</span>
            )}
          </label>
        )}

        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Subject <span className="text-red-500">*</span>
          </span>
          <input
            className={`field${errors.subject ? ' border-red-400' : ''}`}
            maxLength={200}
            ref={subjectRef}
            placeholder="e.g. Please share your feedback"
            value={draft.subject_template}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, subject_template: event.target.value })}
            onBlur={() => markTouched('subject')}
            aria-invalid={errors.subject ? true : undefined}
          />
          {errors.subject && (
            <span className="mt-1 block text-xs text-red-500">{errors.subject}</span>
          )}
          {!readOnly && (
            <PlaceholderChips
              kind={kind}
              getEl={() => subjectRef.current}
              value={draft.subject_template}
              onChange={(next) => setDraft({ ...draft, subject_template: next })}
            />
          )}
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Heading (optional)
          </span>
          <input
            className="field"
            maxLength={200}
            ref={headingRef}
            placeholder="e.g. Share your feedback"
            value={draft.heading}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, heading: event.target.value })}
          />
          {!readOnly && (
            <PlaceholderChips
              kind={kind}
              getEl={() => headingRef.current}
              value={draft.heading}
              onChange={(next) => setDraft({ ...draft, heading: next })}
            />
          )}
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Message <span className="text-red-500">*</span>
          </span>
          <textarea
            className={`field resize-y${errors.body ? ' border-red-400' : ''}`}
            rows={6}
            maxLength={4000}
            ref={messageRef}
            placeholder="Type the email message here…"
            value={draft.body_text}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, body_text: event.target.value })}
            onBlur={() => markTouched('body')}
            aria-invalid={errors.body ? true : undefined}
          />
          {errors.body && (
            <span className="mt-1 block text-xs text-red-500">{errors.body}</span>
          )}
          <span className="mt-1 block text-xs text-ink-400">
            The link, expiry date, and footer are always added automatically below this.
          </span>
          {!readOnly && (
            <PlaceholderChips
              kind={kind}
              getEl={() => messageRef.current}
              value={draft.body_text}
              onChange={(next) => setDraft({ ...draft, body_text: next })}
            />
          )}
        </label>
      </div>

      <div className="mt-4">
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-sm"
          disabled={previewing}
          onClick={runPreview}
        >
          {previewing && <Spinner />}
          Preview
        </button>
      </div>

      {preview && (
        <Modal
          title="Email preview"
          hint={`Subject: ${preview.subject}`}
          onClose={() => setPreview(null)}
          className="max-w-2xl"
        >
          <iframe
            title="Email preview"
            srcDoc={preview.html}
            className="h-[520px] w-full rounded-md border border-ink-200 bg-white dark:border-ink-700"
          />
        </Modal>
      )}
    </>
  )
}

function GlobalEditModal({
  kind,
  initial,
  onClose,
  onSaved,
}: {
  kind: EmailTemplateKind
  initial: EmailTemplateOut
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(toDraft(initial))
  const [saving, setSaving] = useState(false)
  const meta = KIND_META[kind]

  const save = async () => {
    setSaving(true)
    try {
      await api.put(`/email-templates/${kind}`, draft)
      toast.show('success', 'Platform default saved')
      onSaved()
      onClose()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not save the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Edit platform default" onClose={onClose} className="max-w-xl">
      <TemplateForm meta={meta} draft={draft} setDraft={setDraft} readOnly={false} kind={kind} />
      <div className="mt-5 flex items-center justify-end gap-2">
        <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          disabled={saving || !draft.subject_template.trim() || !draft.body_text.trim()}
          onClick={save}
        >
          {saving && <Spinner />}
          Save
        </button>
      </div>
    </Modal>
  )
}

function OrgTemplateModal({
  kind,
  mode,
  initial,
  onClose,
  onSaved,
}: {
  kind: EmailTemplateKind
  mode: 'create' | 'edit' | 'view'
  initial: EmailTemplateOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(initial ? toDraft(initial) : EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const meta = KIND_META[kind]
  const readOnly = mode === 'view'

  const save = async () => {
    setSaving(true)
    try {
      if (mode === 'create') {
        await api.post('/email-templates', { kind, ...draft })
        toast.show('success', 'Template added')
      } else if (mode === 'edit' && initial) {
        await api.put(`/email-templates/item/${initial.id}`, draft)
        toast.show('success', 'Template saved')
      }
      onSaved()
      onClose()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not save the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={mode === 'create' ? 'Add email template' : (initial?.name ?? 'Template')}
      onClose={onClose}
      className="max-w-xl"
    >
      <TemplateForm meta={meta} draft={draft} setDraft={setDraft} readOnly={readOnly} kind={kind} />
      <div className="mt-5 flex items-center justify-end gap-2">
        <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={onClose}>
          {readOnly ? 'Close' : 'Cancel'}
        </button>
        {!readOnly && (
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            disabled={saving || !draft.name.trim() || !draft.subject_template.trim() || !draft.body_text.trim()}
            onClick={save}
          >
            {saving && <Spinner />}
            Save
          </button>
        )}
      </div>
    </Modal>
  )
}

function SuperAdminView() {
  const [items, setItems] = useState<EmailTemplateOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<EmailTemplateKind | null>(null)

  const load = () => {
    setError(null)
    api
      .get<EmailTemplateOut[]>('/email-templates')
      .then(setItems)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Failed to load'))
  }

  useEffect(load, [])

  const byKind = new Map((items ?? []).map((item) => [item.kind, item]))

  return (
    <>
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}
      <Card padded={false}>
        {items === null ? (
          <div className="space-y-3 p-5">
            {KIND_ORDER.map((kind) => (
              <Skeleton key={kind} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Review kind</th>
                <th>Subject</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {KIND_ORDER.map((kind) => {
                const meta = KIND_META[kind]
                const source = byKind.get(kind)
                if (!source) return null
                return (
                  <tr key={kind}>
                    <td>
                      <span className="flex items-center gap-2 font-medium text-ink-900 dark:text-ink-50">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: meta.color }}
                          aria-hidden="true"
                        />
                        {meta.label}
                      </span>
                    </td>
                    <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                      {humanizeTokens(source.subject_template)}
                    </td>
                    <td>
                      <div className="flex items-center justify-end">
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1 text-xs"
                          onClick={() => setEditing(kind)}
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      {editing && byKind.get(editing) && (
        <GlobalEditModal
          kind={editing}
          initial={byKind.get(editing)!}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </>
  )
}

function OrgAdminView() {
  const toast = useToast()
  const [kind, setKind] = useState<EmailTemplateKind>('client')
  const [library, setLibrary] = useState<EmailTemplateLibrary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [modal, setModal] = useState<
    { mode: 'create' } | { mode: 'edit' | 'view'; template: EmailTemplateOut } | null
  >(null)
  const [deleting, setDeleting] = useState<EmailTemplateOut | null>(null)
  const [activating, setActivating] = useState<EmailTemplateOut | null>(null)

  const load = () => {
    setError(null)
    api
      .get<EmailTemplateLibrary>(`/email-templates/library?kind=${kind}`)
      .then(setLibrary)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Failed to load'))
  }

  useEffect(load, [kind])

  const anyOrgActive = (library?.org_templates ?? []).some((t) => t.is_active)

  // Deactivating never affects another row, so it applies immediately.
  // Activating replaces whichever template was active — that side effect
  // is confirmed first rather than just happening (and un-happening) as a
  // flicker the moment the switch is clicked.
  const deactivate = async (template: EmailTemplateOut) => {
    setBusyId(template.id)
    try {
      await api.post(`/email-templates/item/${template.id}/deactivate`)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not update the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  const confirmActivate = async () => {
    if (!activating) return
    setBusyId(activating.id)
    try {
      await api.post(`/email-templates/item/${activating.id}/activate`)
      setActivating(null)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not activate the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    setBusyId(deleting.id)
    try {
      await api.delete(`/email-templates/item/${deleting.id}`)
      toast.show('success', 'Template deleted')
      setDeleting(null)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not delete the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Review Type
          </span>
          <select
            className="field w-64"
            value={kind}
            onChange={(event) => setKind(event.target.value as EmailTemplateKind)}
          >
            {KIND_ORDER.map((k) => (
              <option key={k} value={k}>
                {KIND_META[k].label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          onClick={() => setModal({ mode: 'create' })}
        >
          Add template
        </button>
      </div>

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <Card padded={false}>
        {library === null ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Subject</th>
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <span className="font-medium text-ink-900 dark:text-ink-50">
                    {library.global_template.name}
                  </span>
                  <span className="ml-2">
                    <Chip value="info">Platform default</Chip>
                  </span>
                </td>
                <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                  {humanizeTokens(library.global_template.subject_template)}
                </td>
                <td>
                  <Chip value={anyOrgActive ? 'disabled' : 'active'}>
                    {anyOrgActive ? 'Not in use' : 'Active'}
                  </Chip>
                </td>
                <td>
                  <div className="flex items-center justify-end">
                    <button
                      type="button"
                      className="btn-secondary px-2.5 py-1 text-xs"
                      onClick={() => setModal({ mode: 'view', template: library.global_template })}
                    >
                      View
                    </button>
                  </div>
                </td>
              </tr>

              {library.org_templates.map((template) => (
                <tr key={template.id}>
                  <td className="font-medium text-ink-900 dark:text-ink-50">{template.name}</td>
                  <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                    {humanizeTokens(template.subject_template)}
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={template.is_active}
                        disabled={busyId === template.id}
                        ariaLabel={`Toggle ${template.name} active`}
                        onChange={() =>
                          template.is_active ? deactivate(template) : setActivating(template)
                        }
                      />
                      {busyId === template.id && <Spinner />}
                    </div>
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="btn-secondary px-2.5 py-1 text-xs"
                        onClick={() => setModal({ mode: 'edit', template })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn-ghost p-1.5 text-critical"
                        aria-label={`Delete ${template.name}`}
                        onClick={() => setDeleting(template)}
                      >
                        <IconTrash width={15} height={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {library.org_templates.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-sm text-ink-400">
                    No templates of your own for this type yet — "Add template" to create one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      {modal?.mode === 'create' && (
        <OrgTemplateModal
          kind={kind}
          mode="create"
          initial={library?.global_template ?? null}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}
      {modal && modal.mode !== 'create' && (
        <OrgTemplateModal
          kind={kind}
          mode={modal.mode}
          initial={modal.template}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}

      {activating && (
        <ConfirmDialog
          title="Activate this template?"
          body="Are you sure you want to activate this template?"
          confirmLabel="Activate"
          busy={busyId === activating.id}
          onConfirm={confirmActivate}
          onCancel={() => setActivating(null)}
        />
      )}

      {deleting && (
        <Modal title="Delete template?" onClose={() => setDeleting(null)} className="max-w-sm" centered>
          <p className="text-sm text-ink-600 dark:text-ink-300">
            Are you sure you want to delete this template?
          </p>
          <div className="mt-5 flex items-center justify-end gap-2">
            <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setDeleting(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger px-3 py-1.5 text-sm"
              disabled={busyId === deleting.id}
              onClick={confirmDelete}
            >
              {busyId === deleting.id && <Spinner />}
              Delete
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

export function EmailTemplates() {
  const { user } = useAuth()
  const isPlatform = user?.role === 'super_admin'

  return (
    <>
      <PageHeader
        title="Email Templates"
        description={
          isPlatform
            ? ''
            : "Select a review type to view its templates. Only one template can be active at a time"
        }
      />
      {isPlatform ? <SuperAdminView /> : <OrgAdminView />}
    </>
  )
}