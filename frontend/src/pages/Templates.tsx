import { useEffect, useState } from 'react'
import { SearchBox } from '../components/filters'
import { IconLayers, IconShield } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Modal, Skeleton, Spinner } from '../components/ui'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

interface CategoryMeta {
  id: string
  key: string
  name: string
  description: string | null
  icon: string | null
  is_global: boolean
  templates: {
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
  }[]
}

const DOMAIN_LABEL: Record<string, string> = {
  employee: 'Person',
  manager: 'Manager',
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

type TemplateMeta = CategoryMeta['templates'][number]

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
  latest: { id: string; version: number; status: string; definition: DefinitionDoc } | null
}

let keyCounter = 0
const nextKey = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${keyCounter++}`

/**
 * Clone and publish controls.
 *
 * Provided (vendor-authored) templates are shared by every tenant, so they are
 * never editable in place — the only supported route to customisation is a
 * clone, and the button says exactly that rather than failing later.
 */
function TemplateActions({
  template,
  onChanged,
  onError,
  onEdit,
  onDeleted,
}: {
  template: TemplateMeta
  onChanged: (message: string) => void
  onError: (message: string) => void
  onEdit: (templateId: string) => void
  onDeleted?: (message: string) => void
}) {
  const [busy, setBusy] = useState<'clone' | 'publish' | 'delete' | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const run = async (action: 'clone' | 'publish') => {
    setBusy(action)
    onError('')
    try {
      if (action === 'clone') {
        const result = await api.post<{ name: string }>(
          `/catalog/templates/${template.id}/clone`,
          {},
        )
        onChanged(`'${result.name}' created as a draft in your organization.`)
      } else {
        const result = await api.post<{ version: number }>(
          `/catalog/templates/${template.id}/publish`,
          {},
        )
        onChanged(
          `'${template.name}' v${result.version} published. It can now back a review cycle.`,
        )
      }
      setConfirming(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'That did not work.')
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    setBusy('delete')
    onError('')
    try {
      await api.delete(`/catalog/templates/${template.id}`)
      onDeleted?.(`'${template.name}' deleted.`)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not delete this template.')
      setConfirmingDelete(false)
    } finally {
      setBusy(null)
    }
  }

  if (template.scope === 'global') {
    return (
      <button
        type="button"
        className="btn-secondary px-3 py-1.5 text-sm"
        disabled={busy === 'clone'}
        onClick={() => run('clone')}
      >
        {busy === 'clone' && <Spinner />}
        Clone to customise
      </button>
    )
  }

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        className="btn-secondary px-3 py-1.5 text-sm"
        onClick={() => onEdit(template.id)}
      >
        {template.status === 'draft' ? 'Edit draft' : 'Edit (new version)'}
      </button>
      {template.status === 'draft' &&
        (confirming ? (
          <span className="flex gap-1.5">
            <button
              type="button"
              className="btn-primary px-2.5 py-1.5 text-sm"
              disabled={busy === 'publish'}
              onClick={() => run('publish')}
            >
              {busy === 'publish' && <Spinner />}
              Confirm publish
            </button>
            <button
              type="button"
              className="btn-secondary px-2.5 py-1.5 text-sm"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            onClick={() => setConfirming(true)}
          >
            Publish
          </button>
        ))}
      {template.status !== 'draft' && (
        <span className="text-2xs uppercase tracking-[0.08em] text-ink-400">
          v{template.version} published
        </span>
      )}
      {onDeleted &&
        (confirmingDelete ? (
          <span className="flex gap-1.5">
            <button
              type="button"
              className="btn-danger px-2.5 py-1.5 text-sm"
              disabled={busy === 'delete'}
              onClick={remove}
            >
              {busy === 'delete' && <Spinner />}
              Confirm delete
            </button>
            <button
              type="button"
              className="btn-secondary px-2.5 py-1.5 text-sm"
              onClick={() => setConfirmingDelete(false)}
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn-ghost px-2.5 py-1.5 text-sm text-critical"
            onClick={() => setConfirmingDelete(true)}
          >
            Delete
          </button>
        ))}
    </span>
  )
}

function CreateTemplateForm({
  categories,
  defaultCategoryId,
  onCancel,
  onCreated,
}: {
  categories: CategoryMeta[]
  defaultCategoryId?: string
  onCancel: () => void
  onCreated: (templateId: string) => void
}) {
  const [form, setForm] = useState({
    name: '',
    category_id: defaultCategoryId ?? categories[0]?.id ?? '',
    target_type: 'employee',
    description: '',
    is_anonymous: false,
    min_responses_to_reveal: 4,
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
      const result = await api.post<{ id: string; name: string }>('/catalog/templates', {
        name: form.name,
        category_id: form.category_id,
        target_type: form.target_type,
        description: form.description || null,
        is_anonymous: form.is_anonymous,
        min_responses_to_reveal: form.min_responses_to_reveal,
      })
      onCreated(result.id)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('Could not create the template.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-5" title="New template" hint="Starts with one placeholder question — add and edit questions in the editor that opens next.">
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="Template name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            error={fieldErrors.name}
            required
            autoFocus
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              Category
            </span>
            <select
              className="field"
              value={form.category_id}
              onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              required
            >
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
              About
            </span>
            <select
              className="field"
              value={form.target_type}
              onChange={(event) => setForm({ ...form, target_type: event.target.value })}
            >
              {Object.entries(DOMAIN_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <Field
            label="Description (optional)"
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
          <input
            type="checkbox"
            checked={form.is_anonymous}
            onChange={(event) => setForm({ ...form, is_anonymous: event.target.checked })}
          />
          Anonymous — reviewer identity is never recorded, even to the org
        </label>
        <div className="mt-2 max-w-[220px]">
          <Field
            label="Minimum responses to reveal"
            type="number"
            min={0}
            max={50}
            value={form.min_responses_to_reveal}
            onChange={(event) =>
              setForm({ ...form, min_responses_to_reveal: Number(event.target.value) })
            }
            hint="0 shows results as soon as the first response arrives."
          />
        </div>
        <div className="mt-4 flex gap-2">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy}>
            {busy && <Spinner />}
            Create and edit questions
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
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
        <Field
          label="Question text"
          value={question.text}
          onChange={(event) => onChange({ ...question, text: event.target.value })}
          required
        />
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Type
          </span>
          <select
            className="field"
            value={question.type}
            onChange={(event) => {
              const type = event.target.value
              onChange({
                ...question,
                type,
                options: type === 'choice' ? question.options.length ? question.options : ['Option 1', 'Option 2'] : [],
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
            <input
              type="checkbox"
              checked={question.required}
              onChange={(event) => onChange({ ...question, required: event.target.checked })}
            />
            Required
          </label>
          <button
            type="button"
            className="btn-ghost px-2 py-1.5 text-xs text-critical"
            onClick={onRemove}
          >
            Remove
          </button>
        </div>
      </div>
      {question.type === 'choice' && (
        <div className="mt-2">
          <Field
            label="Options (comma-separated)"
            value={question.options.join(', ')}
            onChange={(event) =>
              onChange({
                ...question,
                options: event.target.value.split(',').map((v) => v.trim()).filter(Boolean),
              })
            }
            hint="Between 2 and 12 options."
          />
        </div>
      )}
    </div>
  )
}

/** Section/question editing UI shared between the draft editor and the
 * clone-with-customisation popup — the same building blocks, whether the
 * definition being edited belongs to an org-owned draft or to a not-yet-cloned
 * copy of a provided template. */
function SectionsEditor({
  sections,
  onChange,
}: {
  sections: SectionDef[]
  onChange: (sections: SectionDef[]) => void
}) {
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
        questions: [
          { key: nextKey('question'), text: '', type: 'scale', required: true, options: [] },
        ],
      },
    ])
  }

  const removeSection = (index: number) => {
    onChange(sections.filter((_, i) => i !== index))
  }

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
              <button
                type="button"
                className="btn-ghost px-2 py-1.5 text-xs text-critical"
                onClick={() => removeSection(sectionIndex)}
              >
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
                    updateSection(sectionIndex, {
                      ...section,
                      questions: section.questions.filter((_, i) => i !== questionIndex),
                    })
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
                  questions: [
                    ...section.questions,
                    { key: nextKey('question'), text: '', type: 'scale', required: true, options: [] },
                  ],
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

function TemplateEditor({ templateId, onClose, onSaved }: { templateId: string; onClose: () => void; onSaved: (message: string) => void }) {
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isAnonymous, setIsAnonymous] = useState(false)
  const [minResponses, setMinResponses] = useState(4)
  const [definition, setDefinition] = useState<DefinitionDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<TemplateDetail>(`/catalog/templates/${templateId}`)
      .then((result) => {
        setDetail(result)
        setName(result.name)
        setDescription(result.description ?? '')
        setIsAnonymous(result.is_anonymous)
        setMinResponses(result.min_responses_to_reveal)
        setDefinition(
          result.latest?.definition ?? {
            intro: '',
            scale: { min: 1, max: 5, labels: {} },
            sections: [],
            closing: { comment_prompt: 'Anything else you would like to add?', comment_required: false },
          },
        )
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load the template.'))
  }, [templateId])

  const save = async () => {
    if (!definition) return
    setBusy(true)
    setError(null)
    try {
      await api.put(`/catalog/templates/${templateId}/draft`, {
        definition,
        name,
        description: description || null,
        is_anonymous: isAnonymous,
        min_responses_to_reveal: minResponses,
      })
      onSaved(`Draft of '${name}' saved.`)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not save the draft.')
    } finally {
      setBusy(false)
    }
  }

  if (!detail || !definition) {
    return (
      <Modal title="Loading template" onClose={onClose}>
        {error ? <Banner tone="error">{error}</Banner> : <Skeleton className="h-40 w-full" />}
      </Modal>
    )
  }

  return (
    <Modal
      title={`Editing '${detail.name}'`}
      hint={
        detail.latest?.status === 'published'
          ? `v${detail.latest.version} is published and immutable — saving starts v${detail.latest.version + 1} as a new draft.`
          : 'Editing the current draft.'
      }
      onClose={onClose}
    >
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" value={name} onChange={(event) => setName(event.target.value)} required />
        <Field
          label="Description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
        <input type="checkbox" checked={isAnonymous} onChange={(event) => setIsAnonymous(event.target.checked)} />
        Anonymous
      </label>
      <div className="mt-2 max-w-[220px]">
        <Field
          label="Minimum responses to reveal"
          type="number"
          min={0}
          max={50}
          value={minResponses}
          onChange={(event) => setMinResponses(Number(event.target.value))}
          hint="0 shows results as soon as the first response arrives."
        />
      </div>

      <SectionsEditor
        sections={definition.sections}
        onChange={(sections) => setDefinition({ ...definition, sections })}
      />

      <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
        <button type="button" className="btn-primary px-3 py-1.5" disabled={busy} onClick={save}>
          {busy && <Spinner />}
          Save draft
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}

interface ManagedCategory {
  id: string
  key: string
  name: string
  description: string | null
  icon: string | null
  sort_order: number
  is_enabled: boolean
  is_global: boolean
}

function NewCategoryForm({
  isSuperAdmin,
  onCancel,
  onCreated,
}: {
  isSuperAdmin: boolean
  onCancel: () => void
  onCreated: () => void
}) {
  const [form, setForm] = useState({ key: '', name: '', description: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      await api.post('/catalog/categories', {
        key: form.key.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'),
        name: form.name,
        description: form.description || null,
      })
      onCreated()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('Could not create the category.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 rounded-lg border border-ink-200 p-3.5 dark:border-ink-700">
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Category name"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          error={fieldErrors.name}
          required
          autoFocus
        />
        <Field
          label="Key (lowercase, no spaces)"
          value={form.key}
          onChange={(event) => setForm({ ...form, key: event.target.value })}
          error={fieldErrors.key}
          placeholder="e.g. exit_interviews"
          required
        />
        <Field
          label="Description (optional)"
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </div>
      <p className="mt-2 text-2xs text-ink-400">
        {isSuperAdmin
          ? 'Visible to every organization on the platform.'
          : 'Visible only inside your organization.'}
      </p>
      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn-primary px-3 py-1.5 text-sm" disabled={busy}>
          {busy && <Spinner />}
          Create category
        </button>
        <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function CategoryManager({
  isSuperAdmin,
  onChanged,
}: {
  isSuperAdmin: boolean
  onChanged: () => void
}) {
  const [categories, setCategories] = useState<ManagedCategory[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const reload = () => {
    api
      .get<ManagedCategory[]>('/catalog/categories/manage')
      .then(setCategories)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load categories.'),
      )
  }

  useEffect(reload, [])
  useRefetchOnFocus(reload)

  const toggle = async (category: ManagedCategory) => {
    setBusyId(category.id)
    setError(null)
    try {
      await api.patch(`/catalog/categories/${category.id}`, { is_enabled: !category.is_enabled })
      reload()
      onChanged()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not update the category.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Card
      className="mb-5"
      title="Categories"
      hint={
        isSuperAdmin
          ? 'Platform-wide categories every organization sees. Disabling one hides it (and its templates) from every tenant.'
          : "Your organization's categories. Disabling one hides it from your template library."
      }
      action={
        !creating && (
          <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={() => setCreating(true)}>
            New category
          </button>
        )
      }
    >
      {error && (
        <Banner tone="error" className="mb-3">
          {error}
        </Banner>
      )}
      {creating && (
        <NewCategoryForm
          isSuperAdmin={isSuperAdmin}
          onCancel={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            reload()
            onChanged()
          }}
        />
      )}
      {!categories ? (
        <Skeleton className="mt-3 h-16 w-full" />
      ) : categories.length === 0 ? (
        <p className="mt-3 text-sm text-ink-500">
          No categories yet. Create one above before you can add a template.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-ink-200 dark:divide-ink-800">
          {categories.map((category) => (
            <li key={category.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="flex items-center gap-2">
                  <span className="text-sm font-medium text-ink-900 dark:text-ink-50">
                    {category.name}
                  </span>
                  <span className="text-2xs text-ink-400">{category.key}</span>
                  {!category.is_enabled && <Chip value="disabled" />}
                </p>
                {category.description && (
                  <p className="text-xs text-ink-500 dark:text-ink-400">{category.description}</p>
                )}
              </div>
              <button
                type="button"
                className="btn-secondary px-3 py-1.5 text-xs"
                disabled={busyId === category.id}
                onClick={() => toggle(category)}
              >
                {busyId === category.id && <Spinner />}
                {category.is_enabled ? 'Disable' : 'Enable'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/**
 * View a provided template, customise it, and clone it — all in one place.
 *
 * The provided template itself is never touched: this loads its definition
 * into a local, editable copy, and "Clone" first creates the org-owned copy
 * (an exact clone, same as the plain clone button) and then immediately saves
 * whatever was changed here as that copy's draft. Two calls, one user action —
 * the alternative (a bespoke "clone with a definition" endpoint) would only
 * save a network round trip at the cost of a second way to create a template
 * that the plain clone path does not have.
 */
function ViewCloneModal({
  template,
  onClose,
  onCloned,
}: {
  template: TemplateMeta
  onClose: () => void
  onCloned: (message: string) => void
}) {
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [name, setName] = useState(`${template.name} (copy)`)
  const [description, setDescription] = useState('')
  const [isAnonymous, setIsAnonymous] = useState(false)
  const [minResponses, setMinResponses] = useState(4)
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
        setMinResponses(result.min_responses_to_reveal)
        setDefinition(
          result.latest?.definition ?? {
            intro: '',
            scale: { min: 1, max: 5, labels: {} },
            sections: [],
            closing: { comment_prompt: 'Anything else you would like to add?', comment_required: false },
          },
        )
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load the template.'))
  }, [template.id])

  const cloneWithChanges = async () => {
    if (!definition) return
    setBusy(true)
    setError(null)
    try {
      const cloned = await api.post<{ id: string; name: string }>(
        `/catalog/templates/${template.id}/clone`,
        { name },
      )
      await api.put(`/catalog/templates/${cloned.id}/draft`, {
        definition,
        name,
        description: description || null,
        is_anonymous: isAnonymous,
        min_responses_to_reveal: minResponses,
      })
      onCloned(`'${name}' created as a draft in your organization.`)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not clone this template.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={template.name}
      hint="Provided template. Changes here are saved to your own copy when you clone it — the original is never modified."
      onClose={onClose}
    >
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
            <Field
              label="Name for your copy"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
            <Field
              label="Description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
            <input
              type="checkbox"
              checked={isAnonymous}
              onChange={(event) => setIsAnonymous(event.target.checked)}
            />
            Anonymous
          </label>
          <div className="mt-2 max-w-[220px]">
            <Field
              label="Minimum responses to reveal"
              type="number"
              min={0}
              max={50}
              value={minResponses}
              onChange={(event) => setMinResponses(Number(event.target.value))}
              hint="0 shows results as soon as the first response arrives."
            />
          </div>

          <SectionsEditor
            sections={definition.sections}
            onChange={(sections) => setDefinition({ ...definition, sections })}
          />

          <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
            <button
              type="button"
              className="btn-primary px-3 py-1.5"
              disabled={busy || !name.trim()}
              onClick={cloneWithChanges}
            >
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

export function Templates() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'client_admin' || user?.role === 'super_admin'
  const isSuperAdmin = user?.role === 'super_admin'
  const [categories, setCategories] = useState<CategoryMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>('')
  const [viewingTemplate, setViewingTemplate] = useState<TemplateMeta | null>(null)
  const [librarySearch, setLibrarySearch] = useState('')
  const [yoursSearch, setYoursSearch] = useState('')

  const reload = () => {
    api
      .get<CategoryMeta[]>('/catalog/categories')
      .then((result) => {
        setCategories(result)
        setSelectedCategoryId((current) => current || result[0]?.id || '')
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load the library.'),
      )
  }

  useEffect(reload, [])
  useRefetchOnFocus(reload)

  const selectedCategory = categories?.find((category) => category.id === selectedCategoryId) ?? null
  const libraryTemplates = (selectedCategory?.templates ?? []).filter(
    (template) =>
      template.scope === 'global' &&
      template.name.toLowerCase().includes(librarySearch.toLowerCase()),
  )
  const yourTemplates = (selectedCategory?.templates ?? []).filter(
    (template) =>
      template.scope === 'org' &&
      template.name.toLowerCase().includes(yoursSearch.toLowerCase()),
  )

  return (
    <>
      <PageHeader
        title="Template library"
        description="Ready-made questionnaires across all three feedback domains. Clone one to customise it for your organization — published versions are immutable, so editing creates the next version and never rewrites history."
        actions={
          !creating &&
          categories &&
          categories.length > 0 && (
            <button
              type="button"
              className="btn-primary px-3 py-1.5"
              onClick={() => setCreating(true)}
            >
              New template
            </button>
          )
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

      {isAdmin && <CategoryManager isSuperAdmin={isSuperAdmin} onChanged={reload} />}

      {creating && categories && (
        <CreateTemplateForm
          categories={categories}
          defaultCategoryId={selectedCategoryId}
          onCancel={() => setCreating(false)}
          onCreated={(templateId) => {
            setCreating(false)
            setEditingId(templateId)
            reload()
          }}
        />
      )}

      {editingId && (
        <TemplateEditor
          templateId={editingId}
          onClose={() => setEditingId(null)}
          onSaved={(message) => {
            setNotice(message)
            setEditingId(null)
            reload()
          }}
        />
      )}

      {!categories ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-40 w-full rounded-lg" />
          ))}
        </div>
      ) : categories.length === 0 ? (
        <EmptyState
          icon={<IconLayers width={19} height={19} />}
          title="No categories enabled"
          body="Ask a platform administrator to enable a category for your organization."
        />
      ) : (
        <>
          <Card className="mb-5">
            <label className="block max-w-sm">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Category
              </span>
              <select
                className="field"
                value={selectedCategoryId}
                onChange={(event) => {
                  setSelectedCategoryId(event.target.value)
                  setViewingTemplate(null)
                }}
              >
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
              {selectedCategory?.description && (
                <span className="mt-1 block text-xs text-ink-400">
                  {selectedCategory.description}
                </span>
              )}
            </label>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Template library" hint="Provided, ready to clone." padded={false}>
              <div className="border-b border-ink-200 px-5 py-3 dark:border-ink-800">
                <SearchBox
                  value={librarySearch}
                  onChange={setLibrarySearch}
                  placeholder="Search templates"
                />
              </div>
              <div className="max-h-[32rem] overflow-y-auto">
                {libraryTemplates.length === 0 ? (
                  <p className="px-5 py-6 text-sm text-ink-500">
                    {librarySearch ? 'No matching templates.' : 'No provided templates in this category.'}
                  </p>
                ) : (
                  <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                    {libraryTemplates.map((template) => (
                      <li key={template.id} className="px-5 py-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-ink-900 dark:text-ink-50">
                                {template.name}
                              </span>
                              <span className="text-2xs uppercase tracking-[0.08em] text-ink-400">
                                Provided
                              </span>
                            </p>
                            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-400">
                              <span>About: {DOMAIN_LABEL[template.target_type] ?? template.target_type}</span>
                              <span className="tabular">{template.question_count} questions</span>
                            </p>
                          </div>
                          <button
                            type="button"
                            className="btn-secondary px-3 py-1.5 text-sm"
                            onClick={() => setViewingTemplate(template)}
                          >
                            View
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>

            <Card title="Your templates" hint="Cloned or created for your organization." padded={false}>
              <div className="border-b border-ink-200 px-5 py-3 dark:border-ink-800">
                <SearchBox
                  value={yoursSearch}
                  onChange={setYoursSearch}
                  placeholder="Search templates"
                />
              </div>
              <div className="max-h-[32rem] overflow-y-auto">
                {yourTemplates.length === 0 ? (
                  <p className="px-5 py-6 text-sm text-ink-500">
                    {yoursSearch
                      ? 'No matching templates.'
                      : 'Nothing here yet — clone one from the library, or create a new template.'}
                  </p>
                ) : (
                  <ul className="divide-y divide-ink-200 dark:divide-ink-800">
                    {yourTemplates.map((template) => (
                      <li key={template.id} className="px-5 py-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-ink-900 dark:text-ink-50">
                                {template.name}
                              </span>
                              <Chip value={template.status ?? 'draft'} />
                            </p>
                            {template.description && (
                              <p className="mt-1 max-w-md text-sm text-ink-500 dark:text-ink-400">
                                {template.description}
                              </p>
                            )}
                            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-400">
                              <span>About: {DOMAIN_LABEL[template.target_type] ?? template.target_type}</span>
                              <span className="tabular">{template.question_count} questions</span>
                              {template.is_anonymous && (
                                <span className="flex items-center gap-1 text-internal">
                                  <IconShield width={11} height={11} />
                                  Anonymous — hidden below {template.min_responses_to_reveal} responses
                                </span>
                              )}
                            </p>
                          </div>
                          <TemplateActions
                            template={template}
                            onChanged={(message) => {
                              setNotice(message)
                              reload()
                            }}
                            onError={setError}
                            onEdit={setEditingId}
                            onDeleted={(message) => {
                              setNotice(message)
                              reload()
                            }}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>
        </>
      )}

      {viewingTemplate && (
        <ViewCloneModal
          template={viewingTemplate}
          onClose={() => setViewingTemplate(null)}
          onCloned={(message) => {
            setNotice(message)
            setViewingTemplate(null)
            reload()
          }}
        />
      )}
    </>
  )
}
