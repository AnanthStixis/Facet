import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconEdit, IconLayers, IconShield, IconTrash } from '../components/icons'
import { Banner, Card, Chip, ConfirmDialog, EmptyState, Field, InfoTooltip, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

export interface TemplateMeta {
  id: string
  name: string
  description: string | null
  target_type: string
  scope: string
  is_anonymous: boolean
  min_responses_to_reveal: number
  version: number | null
  status: string | null
  question_count: number
  editable: boolean
  is_active: boolean
  created_by: string | null
  created_at: string
}

interface CategoryMeta {
  id: string
  templates: TemplateMeta[]
}

// Distinct from CategoryMeta above (that one is the grouped /catalog/categories
// shape). This is the flat /catalog/categories/manage row shape, used only to
// populate the "Category" picker when creating a template.
interface CategoryOption {
  id: string
  name: string
  is_enabled: boolean
  applies_to: string[]
}

export const DOMAIN_LABEL: Record<string, string> = {
  employee: 'Person',
  manager: 'Manager',
  client: 'Client',
  team: 'Team',
  department: 'Department',
  product: 'Product',
  service: 'Service',
  proposal: 'Proposal',
}

const QUESTION_TYPES: { value: string; label: string }[] = [
  { value: 'scale', label: 'Rating scale' },
  { value: 'choice', label: 'Multiple choice' },
  { value: 'boolean', label: 'Yes / no' },
  { value: 'text', label: 'Free text' },
]

interface QuestionDef {
  key: string
  text: string
  type: string
  required: boolean
  options: string[]
}

interface SectionDef {
  key: string
  title: string
  questions: QuestionDef[]
}

interface DefinitionDoc {
  intro: string
  scale: { min: number; max: number; labels: Record<string, string> }
  sections: SectionDef[]
  closing: { comment_prompt: string; comment_required: boolean }
}

interface TemplateDetail {
  id: string
  name: string
  description: string | null
  scope: string
  target_type: string
  is_anonymous: boolean
  min_responses_to_reveal: number
  editable: boolean
  is_active: boolean
  created_by: string | null
  created_at: string
  question_count: number
  latest: { id: string; version: number; status: string; definition: DefinitionDoc } | null
}

let keyCounter = 0
const nextKey = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${keyCounter++}`

const blankDefinition = (): DefinitionDoc => ({
  intro: '',
  scale: { min: 1, max: 5, labels: {} },
  sections: [
    {
      key: nextKey('section'),
      title: 'General',
      questions: [{ key: nextKey('question'), text: '', type: 'scale', required: true, options: [] }],
    },
  ],
  closing: { comment_prompt: 'Anything else you would like to add?', comment_required: false },
})

/** Converts the detail endpoint's shape into the flat list-item shape, so a
 * mutation's own response (or one follow-up GET) can patch local list state
 * immediately instead of waiting on a full reload — see item 9. */
function toMeta(detail: TemplateDetail): TemplateMeta {
  return {
    id: detail.id,
    name: detail.name,
    description: detail.description,
    target_type: detail.target_type,
    scope: detail.scope,
    is_anonymous: detail.is_anonymous,
    min_responses_to_reveal: detail.min_responses_to_reveal,
    version: detail.latest?.version ?? null,
    status: detail.latest?.status ?? null,
    question_count: detail.question_count,
    editable: detail.editable,
    is_active: detail.is_active,
    created_by: detail.created_by,
    created_at: detail.created_at,
  }
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/**
 * Row-level controls.
 *
 * `template.editable` (computed on the backend by comparing the template's
 * org to the caller's) is the only thing this branches on. That one flag is
 * true for an org admin's own templates and for a super admin's global
 * templates (a super admin has no org, so a global template's null org
 * matches) — and false for a client admin looking at someone else's global
 * template, where cloning is the only option. A super admin never sees the
 * false branch, so "Clone to your org" never appears for them.
 */
export function TemplateActions({
  template,
  onChanged,
  onCloned,
  onError,
  onEdit,
  onDeleted,
}: {
  template: TemplateMeta
  onChanged: (message: string, updated: TemplateMeta) => void
  onCloned: (message: string) => void
  onError: (message: string) => void
  onEdit: (template: TemplateMeta) => void
  onDeleted: (message: string, id: string) => void
}) {
  const [busy, setBusy] = useState<'clone' | 'toggle' | 'delete' | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const clone = async () => {
    setBusy('clone')
    try {
      const result = await api.post<{ id: string; name: string }>(`/catalog/templates/${template.id}/clone`, {})
      // A clone starts as a draft (it's the vendor's content, copied for
      // editing before it becomes "yours") — but with no edits requested
      // here, there's nothing to review, so publish it immediately. Without
      // this, the clone was invisible in Create Feedback until someone
      // separately opened Edit and hit Submit, which is what actually
      // publishes a draft.
      await api.post(`/catalog/templates/${result.id}/publish`, {})
      onCloned(`'${result.name}' created in your organization and published.`)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'That did not work.')
    } finally {
      setBusy(null)
    }
  }

  const toggle = async () => {
    setBusy('toggle')
    try {
      const updated = await api.post<TemplateMeta>(`/catalog/templates/${template.id}/toggle`, {})
      onChanged(
        updated.is_active ? `'${template.name}' is active again.` : `'${template.name}' was disabled.`,
        updated,
      )
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not change this template.')
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    setBusy('delete')
    try {
      await api.delete(`/catalog/templates/${template.id}`)
      onDeleted(`'${template.name}' deleted.`, template.id)
      setConfirmingDelete(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not delete this template.')
    } finally {
      setBusy(null)
    }
  }

  if (!template.editable) {
    return (
      <button
        type="button"
        className="btn-secondary px-3 py-1.5 text-sm"
        disabled={busy === 'clone'}
        onClick={clone}
      >
        {busy === 'clone' && <Spinner />}
        Clone to customise
      </button>
    )
  }

  return (
    <>
      <span className="flex flex-nowrap items-center gap-2 whitespace-nowrap">
        <Switch
          checked={template.is_active}
          disabled={busy === 'toggle'}
          ariaLabel={template.is_active ? `Disable ${template.name}` : `Enable ${template.name}`}
          onChange={toggle}
        />
        <button
          type="button"
          className="btn-secondary p-1.5"
          aria-label={`Edit ${template.name}`}
          title="Edit"
          onClick={() => onEdit(template)}
        >
          <IconEdit width={15} height={15} />
        </button>
        <button
          type="button"
          className="btn-ghost p-1.5 text-critical"
          aria-label={`Delete ${template.name}`}
          title="Delete"
          onClick={() => setConfirmingDelete(true)}
        >
          <IconTrash width={15} height={15} />
        </button>
      </span>
      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this template?"
          body={`'${template.name}' will be removed. This can't be undone.`}
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

function AnonymityField({
  isAnonymous,
  onAnonymousChange,
}: {
  isAnonymous: boolean
  onAnonymousChange: (value: boolean) => void
}) {
  return (
    <label className="mt-3 flex items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
      <input type="checkbox" checked={isAnonymous} onChange={(event) => onAnonymousChange(event.target.checked)} />
      Anonymous
      <InfoTooltip text="Reviewer identity is never recorded, even to the organization." />
    </label>
  )
}

function ScaleLabelsEditor({
  scale,
  onChange,
}: {
  scale: { min: number; max: number; labels: Record<string, string> }
  onChange: (labels: Record<string, string>) => void
}) {
  const points = Array.from({ length: scale.max - scale.min + 1 }, (_, i) => scale.min + i)
  return (
    <div className="mt-3">
      <span className="mb-1.5 flex items-center text-sm font-medium text-ink-700 dark:text-ink-200">
        Rating scale labels (optional)
        <InfoTooltip text="Shown under each number on every rating-scale question in this template — e.g. 1 = Poor, 5 = Excellent. Leave any blank to show just the number." />
      </span>
      <div className="grid grid-cols-5 gap-2">
        {points.map((point) => (
          <label key={point} className="block">
            <span className="mb-1 block text-2xs tabular text-ink-400">{point}</span>
            <input
              className="field text-sm"
              value={scale.labels[String(point)] ?? ''}
              onChange={(event) => onChange({ ...scale.labels, [String(point)]: event.target.value })}
              placeholder={`e.g. ${point === scale.min ? 'Poor' : point === scale.max ? 'Excellent' : 'Average'}`}
            />
          </label>
        ))}
      </div>
    </div>
  )
}

function QuestionEditor({
  question,
  onChange,
  onRemove,
}: {
  question: QuestionDef
  onChange: (next: QuestionDef) => void
  onRemove: () => void
}) {
  return (
    <div className="rounded-md border border-ink-200 p-3 dark:border-ink-700">
      <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <Field label="Question text" value={question.text} onChange={(event) => onChange({ ...question, text: event.target.value })} required />
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">Type</span>
          <select
            className="field"
            value={question.type}
            onChange={(event) => {
              const type = event.target.value
              onChange({
                ...question,
                type,
                options: type === 'choice' ? (question.options.length ? question.options : ['Option 1', 'Option 2']) : [],
              })
            }}
          >
            {QUESTION_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end gap-2">
          <label className="flex items-center gap-1.5 whitespace-nowrap pb-2 text-sm text-ink-700 dark:text-ink-200">
            <input type="checkbox" checked={question.required} onChange={(event) => onChange({ ...question, required: event.target.checked })} />
            Required
          </label>
          <button type="button" className="btn-ghost px-2 py-1.5 text-xs text-critical" onClick={onRemove}>
            Remove
          </button>
        </div>
      </div>
      {question.type === 'choice' && (
        <div className="mt-2">
          <label className="block">
            <span className="mb-1.5 flex items-center text-sm font-medium text-ink-700 dark:text-ink-200">
              Options
              <InfoTooltip text="Comma-separated. Between 2 and 12 options." />
            </span>
            <input
              className="field"
              value={question.options.join(', ')}
              onChange={(event) =>
                onChange({ ...question, options: event.target.value.split(',').map((v) => v.trim()).filter(Boolean) })
              }
            />
          </label>
        </div>
      )}
    </div>
  )
}

function SectionsEditor({ sections, onChange }: { sections: SectionDef[]; onChange: (sections: SectionDef[]) => void }) {
  const updateSection = (index: number, next: SectionDef) => {
    const updated = [...sections]
    updated[index] = next
    onChange(updated)
  }

  const addSection = () => {
    onChange([
      ...sections,
      {
        key: nextKey('section'),
        title: 'New section',
        questions: [{ key: nextKey('question'), text: '', type: 'scale', required: true, options: [] }],
      },
    ])
  }

  const removeSection = (index: number) => onChange(sections.filter((_, i) => i !== index))

  return (
    <>
      <div className="mt-5 space-y-4">
        {sections.map((section, sectionIndex) => (
          <div key={section.key} className="rounded-lg border border-ink-200 p-3.5 dark:border-ink-700">
            <div className="mb-3 flex items-center gap-2">
              <input
                className="field flex-1 font-medium"
                value={section.title}
                onChange={(event) => updateSection(sectionIndex, { ...section, title: event.target.value })}
                placeholder="Section title"
              />
              <button type="button" className="btn-ghost px-2 py-1.5 text-xs text-critical" onClick={() => removeSection(sectionIndex)}>
                Remove section
              </button>
            </div>
            <div className="space-y-2">
              {section.questions.map((question, questionIndex) => (
                <QuestionEditor
                  key={question.key}
                  question={question}
                  onChange={(next) => {
                    const questions = [...section.questions]
                    questions[questionIndex] = next
                    updateSection(sectionIndex, { ...section, questions })
                  }}
                  onRemove={() =>
                    updateSection(sectionIndex, { ...section, questions: section.questions.filter((_, i) => i !== questionIndex) })
                  }
                />
              ))}
            </div>
            <button
              type="button"
              className="btn-secondary mt-2 px-2.5 py-1.5 text-xs"
              onClick={() =>
                updateSection(sectionIndex, {
                  ...section,
                  questions: [...section.questions, { key: nextKey('question'), text: '', type: 'scale', required: true, options: [] }],
                })
              }
            >
              Add question
            </button>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={addSection}>
          Add section
        </button>
      </div>
    </>
  )
}

/**
 * One popup, one Submit button: create or edit a template's name/about/
 * description/anonymous-toggle/questions together, then publish it in the
 * same action. There is no separate draft the user has to come back to.
 *
 * Backend-wise this orchestrates three existing calls (create → save draft →
 * publish) inside one submit handler. If create succeeds but a later step
 * fails, `createdId` stays set so pressing Submit again resumes at the draft
 * step instead of creating a second template — the template is left as a
 * real (if unpublished) draft in that case, never silently lost, and the
 * error message says so explicitly.
 */
export function TemplateModal({
  template,
  onCancel,
  onSaved,
  lockedTargetType,
}: {
  template: TemplateMeta | null
  onCancel: () => void
  onSaved: (message: string, item: TemplateMeta) => void
  // Fixes the feedback type and hides the picker — used by pages scoped to
  // one feedback type (e.g. Clients.tsx only ever creates 'client' templates).
  lockedTargetType?: string
}) {
  const isEdit = !!template
  const [name, setName] = useState(template?.name ?? '')
  const [targetType, setTargetType] = useState(template?.target_type ?? lockedTargetType ?? 'employee')
  const [description, setDescription] = useState(template?.description ?? '')
  const [isAnonymous, setIsAnonymous] = useState(template?.is_anonymous ?? false)
  const [definition, setDefinition] = useState<DefinitionDoc | null>(isEdit ? null : blankDefinition())
  const [loadingDetail, setLoadingDetail] = useState(isEdit)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  // Category only matters at create time — like target_type just above, it's
  // never sent again on the save/publish calls an edit makes.
  const [allCategories, setAllCategories] = useState<CategoryOption[] | null>(null)
  const [categoryId, setCategoryId] = useState('')
  useEffect(() => {
    if (isEdit) return
    api
      .get<CategoryOption[]>('/catalog/categories/manage')
      .then((result) => setAllCategories(result.filter((c) => c.is_enabled)))
      .catch(() => setAllCategories([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A category with an empty applies_to applies to every feedback type;
  // otherwise it must explicitly list this one. Re-narrowed whenever the
  // feedback type changes, and the selection is cleared/reset so a category
  // that no longer applies can never be silently submitted.
  const categories = allCategories?.filter(
    (c) => c.applies_to.length === 0 || c.applies_to.includes(targetType),
  ) ?? null
  useEffect(() => {
    if (isEdit || !categories) return
    if (!categories.some((c) => c.id === categoryId)) {
      setCategoryId(categories[0]?.id ?? '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType, allCategories])

  useEffect(() => {
    if (!template) return
    api
      .get<TemplateDetail>(`/catalog/templates/${template.id}`)
      .then((result) => {
        setName(result.name)
        setDescription(result.description ?? '')
        setIsAnonymous(result.is_anonymous)
        setDefinition(result.latest?.definition ?? blankDefinition())
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load this template.'))
      .finally(() => setLoadingDetail(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!definition) return
    if (!isEdit && !categoryId) {
      setError('Choose a category before submitting.')
      return
    }
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      let templateId = template?.id ?? createdId
      if (!templateId) {
        const created = await api.post<{ id: string; name: string }>('/catalog/templates', {
          name,
          target_type: targetType,
          description: description || null,
          is_anonymous: isAnonymous,
          category_id: categoryId || null,
        })
        templateId = created.id
        setCreatedId(created.id)
      }
      await api.put(`/catalog/templates/${templateId}/draft`, {
        definition,
        name,
        description: description || null,
        is_anonymous: isAnonymous,
      })
      await api.post(`/catalog/templates/${templateId}/publish`, {})
      const detail = await api.get<TemplateDetail>(`/catalog/templates/${templateId}`)
      onSaved(isEdit ? `'${name}' saved and published.` : `'${name}' created and published.`, toMeta(detail))
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(
          createdId
            ? `${caught.message} The template was created as a draft — fix the issue above and submit again to publish it.`
            : caught.message,
        )
        setFieldErrors(caught.fieldErrors())
      } else {
        setError(
          createdId
            ? 'Could not finish saving. The template exists as an unpublished draft — submit again to retry.'
            : 'Could not create the template.',
        )
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={isEdit ? `Edit '${template.name}'` : 'New template'} onClose={onCancel}>
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        {loadingDetail || !definition ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field
                label="Template name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                error={fieldErrors.name}
                required
                autoFocus
              />
              {!lockedTargetType && (
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    Feedback type
                    <span className="ml-0.5 text-critical" aria-hidden="true">*</span>
                  </span>
                  <select
                    className="field"
                    value={targetType}
                    disabled={isEdit}
                    required
                    onChange={(event) => setTargetType(event.target.value)}
                  >
                    {Object.entries(DOMAIN_LABEL).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!isEdit && (
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                    Category
                    <span className="ml-0.5 text-critical" aria-hidden="true">*</span>
                  </span>
                  {categories && categories.length === 0 ? (
                    <span className="block pt-2 text-xs text-ink-400">
                      No categories apply to this feedback type yet — create one on the
                      Categories page first.
                    </span>
                  ) : (
                    <select
                      className="field"
                      value={categoryId}
                      required
                      onChange={(event) => setCategoryId(event.target.value)}
                      disabled={!categories}
                    >
                      {(categories ?? []).map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              )}
            </div>
            <label className="mt-3 block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Description (optional)
              </span>
              <textarea
                className="field min-h-[7rem] resize-y"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <AnonymityField isAnonymous={isAnonymous} onAnonymousChange={setIsAnonymous} />

            {definition.sections.some((section) =>
              section.questions.some((question) => question.type === 'scale'),
            ) && (
              <ScaleLabelsEditor
                scale={definition.scale}
                onChange={(labels) => setDefinition({ ...definition, scale: { ...definition.scale, labels } })}
              />
            )}

            <SectionsEditor sections={definition.sections} onChange={(sections) => setDefinition({ ...definition, sections })} />
          </>
        )}

        <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy || loadingDetail}>
            {busy && <Spinner />}
            Submit
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** View a global template and clone it into the caller's org, with the
 * option to tweak questions before the clone is saved. Only ever reachable
 * for a template where `editable` is false — which, per the backend's
 * editable = template.org_id == actor.org_id rule, never happens for a
 * super admin (their global templates are their own). */
function ViewCloneModal({ template, onClose, onCloned }: { template: TemplateMeta; onClose: () => void; onCloned: (message: string) => void }) {
  const toast = useToast()
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [name, setName] = useState(`${template.name} (copy)`)
  const [description, setDescription] = useState('')
  const [isAnonymous, setIsAnonymous] = useState(false)
  const [definition, setDefinition] = useState<DefinitionDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<TemplateDetail>(`/catalog/templates/${template.id}`)
      .then((result) => {
        setDetail(result)
        setDescription(result.description ?? '')
        setIsAnonymous(result.is_anonymous)
        setDefinition(result.latest?.definition ?? blankDefinition())
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load the template.'))
  }, [template.id])

  const cloneWithChanges = async () => {
    if (!definition) return
    setBusy(true)
    try {
      const cloned = await api.post<{ id: string; name: string }>(`/catalog/templates/${template.id}/clone`, { name })
      await api.put(`/catalog/templates/${cloned.id}/draft`, {
        definition,
        name,
        description: description || null,
        is_anonymous: isAnonymous,
      })
      // Same as the no-edits clone path: publish immediately rather than
      // leaving it as a draft invisible to Create Feedback until someone
      // separately opens Edit and hits Submit.
      await api.post(`/catalog/templates/${cloned.id}/publish`, {})
      onCloned(`'${name}' created in your organization and published.`)
    } catch (caught) {
      toast.show('critical', 'Could not clone this template', caught instanceof ApiError ? caught.message : undefined)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={template.name} hint="Changes here are saved to your own copy when you clone it." onClose={onClose}>
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      {!detail || !definition ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name for your copy" value={name} onChange={(event) => setName(event.target.value)} required />
            <Field label="Description" value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>
          <AnonymityField isAnonymous={isAnonymous} onAnonymousChange={setIsAnonymous} />

          <SectionsEditor sections={definition.sections} onChange={(sections) => setDefinition({ ...definition, sections })} />

          <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
            <button type="button" className="btn-primary px-3 py-1.5" disabled={busy || !name.trim()} onClick={cloneWithChanges}>
              {busy && <Spinner />}
              Clone to your organization
            </button>
            <button type="button" className="btn-secondary px-3 py-1.5" onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}

const PAGE_SIZE = 10

export function Templates() {
  const toast = useToast()
  const { user } = useAuth()
  // A Super Admin's DB session bypasses row-level security (it isn't scoped
  // to a tenant), so `/catalog/categories` returns every org's templates,
  // not just global ones. Client Admins never see this problem — RLS
  // already limits them to their own org plus global rows. Filtering to
  // `scope === 'global'` here is what keeps a Super Admin's list to "the
  // platform defaults" per the client's requirement (b), and prevents a
  // "Clone to your org" button ever appearing for them (requirement c) —
  // that button only shows for a non-editable row, and a Super Admin's own
  // global templates are always editable.
  const isSuperAdmin = user?.role === 'super_admin'
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [templates, setTemplates] = useState<TemplateMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [modalTemplate, setModalTemplate] = useState<TemplateMeta | null | 'new'>(null)
  const [viewingTemplate, setViewingTemplate] = useState<TemplateMeta | null>(null)
  const [search, setSearch] = useState('')
  const [domainFilter, setDomainFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [page, setPage] = useState(1)

  const reload = () => {
    api
      .get<CategoryMeta[]>('/catalog/categories')
      .then((result) => {
        const seen = new Map<string, TemplateMeta>()
        for (const category of result) {
          for (const template of category.templates) {
            seen.set(template.id, template)
          }
        }
        const list = [...seen.values()].filter((t) => !isSuperAdmin || t.scope === 'global')
        setTemplates(list.sort((a, b) => a.name.localeCompare(b.name)))
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load templates.'))
  }

  useEffect(reload, [])
  useRefetchOnFocus(reload)

  // Applied immediately from whatever the mutating request itself returned
  // (create/edit/toggle), the same pattern Organizations.tsx's patchOrg
  // uses — the row updates the instant the action's response comes back,
  // not whenever the background reload() below happens to land.
  const patchTemplate = (updated: TemplateMeta) => {
    setTemplates((current) => {
      if (!current) return current
      const exists = current.some((t) => t.id === updated.id)
      const next = exists ? current.map((t) => (t.id === updated.id ? updated : t)) : [...current, updated]
      return next.sort((a, b) => a.name.localeCompare(b.name))
    })
  }

  const removeTemplate = (id: string) => {
    setTemplates((current) => (current ? current.filter((t) => t.id !== id) : current))
  }

  const domains = [...new Set((templates ?? []).map((t) => t.target_type))]
  const visible = (templates ?? []).filter(
    (template) =>
      (!domainFilter || template.target_type === domainFilter) &&
      (!statusFilter || (statusFilter === 'active') === template.is_active) &&
      template.name.toLowerCase().includes(search.toLowerCase()),
  )
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const pageItems = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  return (
    <>
      <PageHeader
        title="Templates"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Create and publish the questionnaires review cycles are built from."
        actions={
          <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setModalTemplate('new')}>
            New template
          </button>
        }
      />

      {error && (
        <Banner tone="error" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Banner>
      )}

      {modalTemplate && (
        <TemplateModal
          template={modalTemplate === 'new' ? null : modalTemplate}
          onCancel={() => setModalTemplate(null)}
          onSaved={(message, item) => {
            toast.show('success', modalTemplate === 'new' ? 'Template created' : 'Template saved', message)
            setModalTemplate(null)
            patchTemplate(item)
            reload()
          }}
        />
      )}

      {!templates ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full rounded-lg" />
          ))}
        </div>
      ) : templates.length === 0 ? (
        <EmptyState icon={<IconLayers width={19} height={19} />} title="No templates yet" body="Create your first template to get started." />
      ) : (
        <Card padded={false}>
          <div className="flex flex-wrap items-center gap-3 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
            <div className="max-w-xs flex-1">
              <SearchBox
                value={search}
                onChange={(value) => {
                  setSearch(value)
                  setPage(1)
                }}
                placeholder="Search templates"
              />
            </div>
            <label className="block">
              <select
                className="field"
                value={domainFilter}
                onChange={(event) => {
                  setDomainFilter(event.target.value)
                  setPage(1)
                }}
              >
                <option value="">All categories</option>
                {domains.map((domain) => (
                  <option key={domain} value={domain}>
                    {DOMAIN_LABEL[domain] ?? domain}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <select
                className="field"
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value)
                  setPage(1)
                }}
              >
                <option value="">Any status</option>
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
            </label>
          </div>
          <div className="max-h-[42rem] overflow-y-auto overflow-x-auto">
            {pageItems.length === 0 ? (
              <p className="px-5 py-6 text-sm text-ink-500">No matching templates.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Description</th>
                    <th>About</th>
                    <th>Questions</th>
                    <th>Status</th>
                    <th>Created by</th>
                    <th>Created</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((template) => (
                    <tr key={template.id}>
                      <td>
                        <span className="flex flex-wrap items-center gap-2 font-medium text-ink-900 dark:text-ink-50">
                          <span className="block max-w-[220px] truncate" title={template.name}>
                            {template.name}
                          </span>
                          {template.is_anonymous && (
                            <span className="flex items-center gap-1 text-internal" title="Anonymous">
                              <IconShield width={11} height={11} />
                            </span>
                          )}
                        </span>
                      </td>
                      <td
                        className="max-w-xs truncate text-ink-500 dark:text-ink-400"
                        title={template.description ?? undefined}
                      >
                        {template.description ?? '—'}
                      </td>
                      <td className="text-ink-600 dark:text-ink-300">
                        {DOMAIN_LABEL[template.target_type] ?? template.target_type}
                      </td>
                      <td className="tabular text-ink-600 dark:text-ink-300">{template.question_count}</td>
                      <td>
                        {template.editable ? (
                          <Chip value={template.is_active ? 'active' : 'disabled'} />
                        ) : (
                          <span className="text-2xs uppercase tracking-[0.08em] text-ink-400">Provided</span>
                        )}
                      </td>
                      <td className="text-ink-600 dark:text-ink-300">{template.created_by ?? '—'}</td>
                      <td className="text-ink-600 dark:text-ink-300">{formatDate(template.created_at)}</td>
                      <td>
                        <div className="flex justify-end">
                          {template.editable ? (
                            <TemplateActions
                              template={template}
                              onChanged={(message, updated) => {
                                toast.show('success', 'Template updated', message)
                                patchTemplate(updated)
                                reload()
                              }}
                              onCloned={(message) => {
                                toast.show('success', 'Template cloned', message)
                                reload()
                              }}
                              onError={(message) => toast.show('critical', 'Action failed', message)}
                              onEdit={setModalTemplate}
                              onDeleted={(message, id) => {
                                toast.show('success', 'Template deleted', message)
                                removeTemplate(id)
                                reload()
                              }}
                            />
                          ) : (
                            <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={() => setViewingTemplate(template)}>
                              View &amp; clone
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {visible.length > 0 && (
            <Pagination page={currentPage} pageSize={PAGE_SIZE} total={visible.length} onPage={setPage} />
          )}
        </Card>
      )}

      {viewingTemplate && (
        <ViewCloneModal
          template={viewingTemplate}
          onClose={() => setViewingTemplate(null)}
          onCloned={(message) => {
            toast.show('success', 'Template cloned', message)
            setViewingTemplate(null)
            reload()
          }}
        />
      )}
    </>
  )
}
