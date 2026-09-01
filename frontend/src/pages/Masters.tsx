import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { SearchBox } from '../components/filters'
import { Pagination } from '../components/DataTable'
import { IconEdit, IconTrash } from '../components/icons'
import { Banner, Chip, ConfirmDialog, EmptyState, Field, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

const PAGE_SIZE = 15

interface MasterRow {
  id: string
  name: string
  is_active: boolean
  created_by: string | null
  created_at: string
  // Only present for Department — the one master list with a shared,
  // Super-Admin-authored tier alongside each org's own rows.
  scope?: 'global' | 'org'
}

interface MasterPage {
  items: MasterRow[]
  total: number
  page: number
  page_size: number
}

interface ListConfig {
  key: string
  label: string
  plural: string
  path: string
}

const LISTS: ListConfig[] = [
  { key: 'departments', label: 'Department', plural: 'Departments', path: '/masters/departments' },
  { key: 'job-titles', label: 'Job Title', plural: 'Job Titles', path: '/masters/job-titles' },
  { key: 'cycle-names', label: 'Cycle Name', plural: 'Cycle Names', path: '/masters/cycle-names' },
  { key: 'products', label: 'Product', plural: 'Products', path: '/masters/products' },
  { key: 'services', label: 'Service', plural: 'Services', path: '/masters/services' },
]

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Create/edit popup — same name field either way, only the verb changes. */
function MasterRowModal({
  list,
  row,
  onCancel,
  onSaved,
}: {
  list: ListConfig
  row: MasterRow | null
  onCancel: () => void
  onSaved: (message: string, row: MasterRow) => void
}) {
  const isEdit = !!row
  const [name, setName] = useState(row?.name ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const saved = isEdit
        ? await api.patch<MasterRow>(`${list.path}/${row.id}`, { name: trimmed })
        : await api.post<MasterRow>(list.path, { name: trimmed })
      onSaved(isEdit ? `'${saved.name}' saved.` : `'${saved.name}' added.`, saved)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : `Could not save this ${list.label.toLowerCase()}.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={isEdit ? `Edit '${row.name}'` : `New ${list.label.toLowerCase()}`} onClose={onCancel}>
      <form onSubmit={submit}>
        {error && (
          <Banner tone="error" className="mb-3">
            {error}
          </Banner>
        )}
        <Field label="Name" value={name} onChange={(event) => setName(event.target.value)} autoFocus required />
        <div className="mt-5 flex gap-2 border-t border-ink-200 pt-4 dark:border-ink-700">
          <button type="submit" className="btn-primary px-3 py-1.5" disabled={busy || !name.trim()}>
            {busy && <Spinner />}
            {isEdit ? 'Save' : 'Add'}
          </button>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

function MasterListPanel({ list }: { list: ListConfig }) {
  const toast = useToast()
  const isSuperAdmin = useAuth((state) => state.user?.role === 'super_admin')
  // Scope (global vs org) only exists on Department rows, and only tells an
  // org Admin anything useful — a Super Admin's own list IS the global
  // list, so every row would carry it and the column would be dead weight.
  const showScopeColumn = list.key === 'departments' && !isSuperAdmin
  const [data, setData] = useState<MasterPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<MasterRow | 'new' | null>(null)
  const [deleting, setDeleting] = useState<MasterRow | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [toggleBusy, setToggleBusy] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
    if (search) query.set('q', search)
    api
      .get<MasterPage>(`${list.path}?${query}`)
      .then(setData)
      .catch(() => setData({ items: [], total: 0, page: 1, page_size: PAGE_SIZE }))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    setPage(1)
  }, [list.path])

  useEffect(() => {
    const timer = setTimeout(load, search ? 220 : 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.path, search, page])

  const toggleActive = async (row: MasterRow) => {
    setToggleBusy(row.id)
    try {
      const updated = await api.patch<MasterRow>(`${list.path}/${row.id}`, { is_active: !row.is_active })
      setData((state) =>
        state ? { ...state, items: state.items.map((r) => (r.id === row.id ? updated : r)) } : state,
      )
      toast.show(
        'success',
        updated.is_active ? 'Enabled' : 'Disabled',
        `'${updated.name}' is now ${updated.is_active ? 'active' : 'disabled'}.`,
      )
    } catch (caught) {
      toast.show('critical', 'Could not change', caught instanceof ApiError ? caught.message : `Could not change this ${list.label.toLowerCase()}.`)
    } finally {
      setToggleBusy(null)
    }
  }

  return (
    <div className="surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-200 p-4 dark:border-ink-800">
        <div className="min-w-[220px] flex-1">
          <SearchBox
            value={search}
            onChange={(value) => {
              setSearch(value)
              setPage(1)
            }}
            placeholder={`Search ${list.plural.toLowerCase()}`}
          />
        </div>
        <button type="button" className="btn-primary px-3 py-1.5" onClick={() => setEditing('new')}>
          Add {list.label.toLowerCase()}
        </button>
      </div>

      {loading && !data ? (
        <div className="space-y-2 p-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title={`No ${list.plural.toLowerCase()} yet`}
          body={`Add one above — it'll show up in the ${list.label} dropdown wherever it's used.`}
        />
      ) : (
        <div className={clsx('overflow-x-auto transition-opacity duration-150', loading && 'opacity-50')}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Created By</th>
                <th>Created Date</th>
                <th className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                // A global row is Super-Admin-authored, shared platform
                // data — an org Admin can see and pick it (that's the
                // point), but can't rename, disable, or delete something
                // every other org relies on too.
                const isGlobal = row.scope === 'global'
                const canManage = !isGlobal || isSuperAdmin
                return (
                  <tr key={row.id}>
                    <td className="font-medium text-ink-900 dark:text-ink-50">
                      <div className="leading-tight">{row.name}</div>
                      {showScopeColumn && isGlobal && (
                        <span className="mt-1 inline-flex items-center rounded-full bg-ink-100 px-1.5 py-0 text-[9px] font-bold leading-[14px] uppercase tracking-[0.04em] text-ink-500 dark:bg-ink-800 dark:text-ink-400">
                          Global
                        </span>
                      )}
                    </td>
                    <td>
                      <Chip value={row.is_active ? 'active' : 'disabled'} />
                    </td>
                    <td className="text-ink-600 dark:text-ink-300">{row.created_by ?? '—'}</td>
                    <td className="text-ink-600 dark:text-ink-300">{formatDate(row.created_at)}</td>
                    <td>
                      <span className="flex flex-nowrap items-center justify-end gap-2 whitespace-nowrap">
                        <Switch
                          checked={row.is_active}
                          disabled={toggleBusy === row.id || !canManage}
                          ariaLabel={row.is_active ? `Disable ${row.name}` : `Enable ${row.name}`}
                          onChange={() => toggleActive(row)}
                        />
                        {canManage && (
                          <>
                            <button
                              type="button"
                              className="btn-secondary p-1.5"
                              aria-label={`Edit ${row.name}`}
                              title="Edit"
                              onClick={() => setEditing(row)}
                            >
                              <IconEdit width={15} height={15} />
                            </button>
                            <button
                              type="button"
                              className="btn-ghost p-1.5 text-critical"
                              aria-label={`Delete ${row.name}`}
                              title="Delete"
                              onClick={() => setDeleting(row)}
                            >
                              <IconTrash width={15} height={15} />
                            </button>
                          </>
                        )}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > 0 && (
        <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
      )}

      {editing && (
        <MasterRowModal
          list={list}
          row={editing === 'new' ? null : editing}
          onCancel={() => setEditing(null)}
          onSaved={(message) => {
            setEditing(null)
            toast.show('success', 'Saved', message)
            load()
          }}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete '${deleting.name}'?`}
          body="This can't be undone. Anyone who already picked this value keeps it as free text."
          confirmLabel="Delete"
          tone="critical"
          busy={deleteBusy}
          onConfirm={async () => {
            setDeleteBusy(true)
            try {
              await api.delete(`${list.path}/${deleting.id}`)
              setDeleting(null)
              load()
            } catch (caught) {
              toast.show('critical', 'Could not delete', caught instanceof ApiError ? caught.message : 'Could not delete this entry.')
            } finally {
              setDeleteBusy(false)
            }
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  )
}

export function Masters() {
  const [tab, setTab] = useState<ListConfig>(LISTS[0])

  return (
    <>
      <PageHeader title="Manage Masters" />

      <div className="surface mb-5 flex flex-wrap gap-1.5 p-1.5">
        {LISTS.map((list) => (
          <button
            key={list.key}
            type="button"
            onClick={() => setTab(list)}
            className={clsx(
              'rounded-md px-3.5 py-2 text-sm font-medium transition-colors',
              tab.key === list.key
                ? 'bg-ink-900 text-white dark:bg-white dark:text-ink-900'
                : 'text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800',
            )}
          >
            {list.plural}
          </button>
        ))}
      </div>

      <MasterListPanel key={tab.key} list={tab} />
    </>
  )
}