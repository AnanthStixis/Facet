import clsx from 'clsx'
import type { ReportColumn } from '../lib/types'
import { Chip, EmptyState, Skeleton } from './ui'
import { IconSearch } from './icons'

const formatDateTime = (value: string, timezone?: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: timezone,
  }).format(date)
}

function Cell({
  column,
  value,
  timezone,
}: {
  column: ReportColumn
  value: unknown
  timezone?: string
}) {
  if (value === null || value === undefined || value === '') {
    return <span className="text-ink-300 dark:text-ink-600">&mdash;</span>
  }
  if (column.kind === 'datetime') {
    return (
      <span className="whitespace-nowrap tabular text-ink-600 dark:text-ink-300">
        {formatDateTime(String(value), timezone)}
      </span>
    )
  }
  if (column.kind === 'badge') {
    // Audit actions arrive as "auth.login_failed"; the namespace is useful
    // context but the verb is what the reader is scanning for.
    const raw = String(value)
    const [namespace, verb] = raw.includes('.') ? raw.split('.') : [null, raw]
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap">
        {namespace && <span className="text-2xs uppercase text-ink-400">{namespace}</span>}
        <Chip value={verb}>{verb.replace(/_/g, ' ')}</Chip>
      </span>
    )
  }
  if (column.kind === 'number') {
    return <span className="tabular">{Number(value).toLocaleString()}</span>
  }
  if (typeof value === 'boolean') {
    return <span>{value ? 'Yes' : 'No'}</span>
  }
  return <span className="text-ink-700 dark:text-ink-200">{String(value)}</span>
}

export function DataTable({
  columns,
  rows,
  loading,
  timezone,
  emptyTitle = 'Nothing to show',
  emptyBody,
}: {
  columns: ReportColumn[]
  rows: Record<string, unknown>[]
  loading?: boolean
  timezone?: string
  emptyTitle?: string
  emptyBody?: string
}) {
  // Full skeleton only on the very first load, when there is nothing to show
  // yet. Every later refetch (typing in search, changing a filter, paging)
  // keeps the existing rows on screen — dimmed, not replaced — so the table
  // does not flash empty and repopulate on every keystroke. That flash is
  // what "flickering" actually was: a full unmount/remount of the table.
  if (loading && rows.length === 0) {
    return (
      <div className="space-y-2 p-5">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<IconSearch width={19} height={19} />}
        title={emptyTitle}
        body={emptyBody ?? 'Try widening the date range or clearing a filter.'}
      />
    )
  }

  return (
    // Wide tables scroll inside their own container so the page body never
    // scrolls sideways.
    <div className="max-h-[calc(100vh-19rem)] overflow-auto">
      <table
        className={clsx('data-table transition-opacity duration-150', loading && 'opacity-50')}
      >
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={clsx(column.align === 'right' && 'text-right')}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={(row.id as string) ?? index}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={clsx(column.align === 'right' && 'text-right')}
                >
                  <Cell column={column} value={row[column.key]} timezone={timezone} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)

  return (
    <div className="flex items-center justify-between gap-4 border-t border-ink-200 px-5 py-3 text-sm dark:border-ink-800">
      <p className="text-ink-500 dark:text-ink-400">
        <span className="tabular font-medium text-ink-700 dark:text-ink-200">
          {from}&ndash;{to}
        </span>{' '}
        of <span className="tabular">{total.toLocaleString()}</span>
      </p>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          className="btn-secondary px-2.5 py-1"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <span className="px-1.5 text-xs text-ink-500">
          {page} / {pages}
        </span>
        <button
          type="button"
          className="btn-secondary px-2.5 py-1"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
