import { useEffect, useState } from 'react'
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

function TextAreaField({
  label,
  hint,
  value,
  onChange,
  rows = 5,
  maxLength,
}: {
  label: string
  hint?: string
  value: string
  onChange: (value: string) => void
  rows?: number
  maxLength?: number
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
        {label}
      </span>
      <textarea
        className="field resize-y"
        rows={rows}
        maxLength={maxLength}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <span className="mt-1 block text-xs text-ink-400">{hint}</span>}
    </label>
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

      <div className="space-y-4">
        {!readOnly && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Template name
            </span>
            <input
              className="field"
              maxLength={150}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder="e.g. Formal pitch"
            />
          </label>
        )}

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Subject
          </span>
          <input
            className="field"
            maxLength={200}
            value={draft.subject_template}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, subject_template: event.target.value })}
          />
          <span className="mt-1 block text-xs text-ink-400">
            Placeholders: {'{org_name}'}, {'{subject_label}'}
          </span>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Heading (optional)
          </span>
          <input
            className="field"
            maxLength={200}
            value={draft.heading}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, heading: event.target.value })}
          />
        </label>

        <TextAreaField
          label="Message"
          hint={
            'Placeholders: {org_name}, {subject_label}, {first_name}. ' +
            'The link, expiry date, and footer are always added automatically below this.'
          }
          rows={6}
          maxLength={4000}
          value={draft.body_text}
          onChange={(value) => setDraft({ ...draft, body_text: value })}
        />
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
          className="max-w-xl"
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
                      {source.subject_template}
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
  const currentlyActive = (library?.org_templates ?? []).find((t) => t.is_active) ?? null

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
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Review kind
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
                  {library.global_template.subject_template}
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
                    {template.subject_template}
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
                    No templates of your own for this kind yet — "Add template" to create one.
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
          body={
            currentlyActive
              ? `"${activating.name}" will become the active ${KIND_META[kind].label} template. ` +
                `"${currentlyActive.name}" is currently active and will be deactivated.`
              : `"${activating.name}" will become the active ${KIND_META[kind].label} template, ` +
                'replacing the platform default for your organization.'
          }
          confirmLabel="Activate"
          busy={busyId === activating.id}
          onConfirm={confirmActivate}
          onCancel={() => setActivating(null)}
        />
      )}

      {deleting && (
        <Modal title="Delete template?" onClose={() => setDeleting(null)} className="max-w-sm" centered>
          <p className="text-sm text-ink-600 dark:text-ink-300">
            Delete "{deleting.name}"? {deleting.is_active && 'It is currently active — sends will fall back to the platform default.'}
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
            ? 'The default invite email sent for each kind of review. Every organization starts from these until it customizes its own.'
            : "Pick a review kind to see the platform default and your organization's own templates for it. Only one of your templates can be active per kind — activating one deactivates whichever was active before."
        }
      />
      {isPlatform ? <SuperAdminView /> : <OrgAdminView />}
    </>
  )
}
