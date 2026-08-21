import { useEffect, useState } from 'react'
import { Pagination } from '../components/DataTable'
import { IconEdit, IconTag } from '../components/icons'
import { Banner, Card, Chip, EmptyState, Field, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
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
  sort_order: number
  applies_to: string[]
  is_enabled: boolean
  is_global: boolean
  created_by: string | null
  created_at: string
}

const FEEDBACK_TYPE_LABEL: Record<string, string> = {
  employee: 'Employees',
  manager: 'Management',
  client: 'Client',
  team: 'Team',
  department: 'Department',
  product: 'Product',
  service: 'Service',
  proposal: 'Proposal Review',
}
const FEEDBACK_TYPES = Object.keys(FEEDBACK_TYPE_LABEL)

/**
 * One popup for both create and edit, same house style as Templates.tsx's
 * TemplateModal / Organizations.tsx's OrgFormModal: no inline Card-based
 * form, no helper-text paragraph under the title or fields.
 *
 * `key` is not a field here at all — the backend derives it from `name` on
 * create and resolves any clash itself, so there's nothing for a person to
 * type or fix. It's still stored and returned by the API (CategoryMeta.key),
 * just not shown anywhere in this UI — no create field, no table column —
 * and still has no endpoint to change it later.
 *
 * Icon and sort order are deliberately not fields here — the client asked
 * for the create/edit popup to hold only name, description and enabled
 * state. The backend columns (icon, sort_order) stay untouched and keep
 * their server-side defaults; this is a UI simplification only.
 */
function CategoryModal({
  category,
  onCancel,
  onSaved,
}: {
  category: CategoryMeta | null
  onCancel: () => void
  onSaved: (message: string, item: CategoryMeta) => void
}) {
  const isEdit = !!category
  const [name, setName] = useState(category?.name ?? '')
  const [description, setDescription] = useState(category?.description ?? '')
  const [appliesTo, setAppliesTo] = useState<string[]>(category?.applies_to ?? [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const validateField = (field: 'name' | 'description', value: string) => {
    setFieldErrors((current) => {
      const next = { ...current }
      if (!value.trim()) {
        next[field] = field === 'name' ? 'Name is required.' : 'Description is required.'
      } else {
        delete next[field]
      }
      return next
    })
  }

  const toggleType = (type: string) => {
    setAppliesTo((current) =>
      current.includes(type) ? current.filter((t) => t !== type) : [...current, type],
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      let saved: CategoryMeta
      if (isEdit) {
        saved = await api.patch<CategoryMeta>(`/catalog/categories/${category.id}`, {
          name,
          description: description || null,
          applies_to: appliesTo,
        })
      } else {
        const created = await api.post<{ id: string; name: string }>('/catalog/categories', {
          name,
          description,
          applies_to: appliesTo,
        })
        saved = {
          id: created.id,
          // The server derives the key from the name now — not sent or
          // known here, and irrelevant to this row's own toast either
          // way; the caller's reload() right after this fetches the real
          // one along with everything else.
          key: '',
          name: created.name,
          description,
          icon: null,
          sort_order: 100,
          applies_to: appliesTo,
          is_enabled: true,
          is_global: false, // patched by the caller's reload; irrelevant to the toast either way
          created_by: null,
          created_at: new Date().toISOString(),
        }
      }
      onSaved(isEdit ? `'${saved.name}' saved.` : `'${saved.name}' created.`, saved)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError(isEdit ? 'Could not save those changes.' : 'Could not create the category.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={isEdit ? `Edit '${category.name}'` : 'New category'} onClose={onCancel}>
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
                    <Field
            label="Name"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              if (fieldErrors.name) validateField('name', event.target.value)
            }}
            onBlur={(event) => validateField('name', event.target.value)}
            error={fieldErrors.name}
            required
            autoFocus
          />
          <Field
            label="Description"
            value={description}
            onChange={(event) => {
              setDescription(event.target.value)
              if (fieldErrors.description) validateField('description', event.target.value)
            }}
            onBlur={(event) => validateField('description', event.target.value)}
            error={fieldErrors.description}
            required
            className="sm:col-span-2"
          />
        </div>

        <div className="mt-3">
          <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
            Applies to feedback types
          </span>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {FEEDBACK_TYPES.map((type) => (
              <label key={type} className="flex items-center gap-1.5 text-sm text-ink-700 dark:text-ink-200">
                <input
                  type="checkbox"
                  checked={appliesTo.includes(type)}
                  onChange={() => toggleType(type)}
                />
                {FEEDBACK_TYPE_LABEL[type]}
              </label>
            ))}
          </div>
          <span className="mt-1 block text-xs text-ink-400">
            Leave all unchecked to make this category available for every feedback type.
          </span>
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

const PAGE_SIZE = 10

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function Categories() {
  const toast = useToast()
  const { user } = useAuth()
  const isPlatform = user?.role === 'super_admin'
  const [categories, setCategories] = useState<CategoryMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [modalCategory, setModalCategory] = useState<CategoryMeta | null | 'new'>(null)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const reload = () => {
    api
      .get<CategoryMeta[]>('/catalog/categories/manage')
      .then((result) => setCategories(result))
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Could not load categories.'))
  }

  useEffect(reload, [])
  useRefetchOnFocus(reload)

  // Same instant-patch-from-response pattern as Templates.tsx's
  // patchTemplate / Organizations.tsx's patchOrg — the row updates the
  // moment the mutating request's own response comes back, not whenever the
  // follow-up reload() happens to land.
  const patchCategory = (updated: CategoryMeta) => {
    setCategories((current) => {
      if (!current) return current
      const exists = current.some((c) => c.id === updated.id)
      const next = exists ? current.map((c) => (c.id === updated.id ? updated : c)) : [...current, updated]
      return next.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
    })
  }

  const toggle = async (category: CategoryMeta) => {
    setTogglingId(category.id)
    try {
      const updated = await api.patch<CategoryMeta>(`/catalog/categories/${category.id}`, {
        is_enabled: !category.is_enabled,
      })
      patchCategory(updated)
      toast.show(
        'success',
        'Category updated',
        updated.is_enabled ? `'${category.name}' is enabled again.` : `'${category.name}' was disabled.`,
      )
    } catch (caught) {
      toast.show('critical', 'Action failed', caught instanceof ApiError ? caught.message : 'Could not change this category.')
    } finally {
      setTogglingId(null)
    }
  }

  const pageCount = categories ? Math.max(1, Math.ceil(categories.length / PAGE_SIZE)) : 1
  const currentPage = Math.min(page, pageCount)
  const pageItems = (categories ?? []).slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  return (
    <>
      <PageHeader
        title="Categories"
        actions={
          <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setModalCategory('new')}>
            Create category
          </button>
        }
      />

      {error && (
        <Banner tone="error" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Banner>
      )}

      {modalCategory && (
        <CategoryModal
          category={modalCategory === 'new' ? null : modalCategory}
          onCancel={() => setModalCategory(null)}
          onSaved={(message, item) => {
            toast.show('success', modalCategory === 'new' ? 'Category created' : 'Category saved', message)
            setModalCategory(null)
            patchCategory(item)
            reload()
          }}
        />
      )}

      {!categories ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : categories.length === 0 ? (
        <EmptyState icon={<IconTag width={19} height={19} />} title="No categories yet" body="Create your first category to get started." />
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Scope</th>
                  <th>Description</th>
                  <th>Applies to</th>
                  <th>Status</th>
                  <th>Created by</th>
                  <th>Created</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((category) => {
                  // A Client Admin now sees global categories alongside
                  // their own (see list_categories_for_management), but
                  // update_category still only lets the owning scope
                  // touch a row — a Super Admin can edit a global one, a
                  // Client Admin can edit their own org's, and neither
                  // can reach into the other's. Disabling here matches
                  // that boundary instead of letting a click land on a
                  // 404 from a row that's clearly right there on screen.
                  const editable = isPlatform ? category.is_global : !category.is_global
                  return (
                  <tr key={category.id}>
                    <td className="font-medium text-ink-900 dark:text-ink-50">{category.name}</td>
                    <td className="text-ink-600 dark:text-ink-300">
                      {category.is_global ? 'Global' : 'This organization'}
                    </td>
                    <td className="max-w-xs text-ink-500 dark:text-ink-400">{category.description ?? '—'}</td>
                    <td className="max-w-xs text-ink-500 dark:text-ink-400">
                      {category.applies_to.length === 0
                        ? 'All types'
                        : category.applies_to.map((t) => FEEDBACK_TYPE_LABEL[t] ?? t).join(', ')}
                    </td>
                    <td>
                      <Chip value={category.is_enabled ? 'enabled' : 'disabled'} />
                    </td>
                    <td className="text-ink-600 dark:text-ink-300">{category.created_by ?? '—'}</td>
                    <td className="text-ink-600 dark:text-ink-300">{formatDate(category.created_at)}</td>
                    <td>
                      <div className="flex items-center justify-end gap-3">
                        <Switch
                          checked={category.is_enabled}
                          disabled={togglingId === category.id || !editable}
                          ariaLabel={category.is_enabled ? `Disable ${category.name}` : `Enable ${category.name}`}
                          onChange={() => toggle(category)}
                        />
                        <button
                          type="button"
                          className="btn-secondary p-1.5"
                          aria-label={`Edit ${category.name}`}
                          title={editable ? 'Edit' : 'Only its owning organization can edit this category'}
                          disabled={!editable}
                          onClick={() => setModalCategory(category)}
                        >
                          <IconEdit width={15} height={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {categories.length > 0 && (
            <Pagination page={currentPage} pageSize={PAGE_SIZE} total={categories.length} onPage={setPage} />
          )}
        </Card>
      )}
    </>
  )
}