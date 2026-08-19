import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { DataTable, Pagination } from '../components/DataTable'
import {
  DateRangeFilter,
  ExportMenu,
  LookupFilter,
  OptionFilter,
  SearchBox,
} from '../components/filters'
import { Banner, Card } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { emptyFilters } from '../lib/types'
import type { FilterState, ReportMeta, ReportResult } from '../lib/types'
import { useAuth } from '../store/auth'

interface Option {
  value: string
  label: string
  group?: string
}

/**
 * Renders any report in the registry.
 *
 * There is exactly one of these because there is exactly one report contract
 * on the server. A new report added to the backend registry appears here, with
 * working filters and all three export formats, without a line of code.
 */
export function ReportView({
  reportKey,
  backTo,
  backLabel,
}: {
  reportKey: string
  backTo?: string
  backLabel?: string
}) {
  const { organization, user } = useAuth()
  const [meta, setMeta] = useState<ReportMeta | null>(null)
  const [result, setResult] = useState<ReportResult | null>(null)
  const [filters, setFilters] = useState<FilterState>(emptyFilters)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionOptions, setActionOptions] = useState<Option[]>([])
  const [severityOptions, setSeverityOptions] = useState<Option[]>([])

  const supports = useCallback(
    (name: string) => meta?.filters_supported.includes(name) ?? false,
    [meta],
  )

  useEffect(() => {
    setFilters(emptyFilters())
    setResult(null)
    api
      .get<ReportMeta[]>('/reports')
      .then((all) => setMeta(all.find((item) => item.key === reportKey) ?? null))
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load the report.'),
      )
  }, [reportKey])

  useEffect(() => {
    if (!supports('actions')) return
    api.get<Option[]>('/lookup-static/audit_actions').then(setActionOptions).catch(() => {})
    api.get<Option[]>('/lookup-static/severities').then(setSeverityOptions).catch(() => {})
  }, [supports])

  useEffect(() => {
    if (!meta) return
    let cancelled = false
    setLoading(true)
    api
      .post<ReportResult>(`/reports/${reportKey}/query`, filters)
      .then((data) => {
        if (!cancelled) {
          setResult(data)
          setError(null)
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : 'Could not run the report.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [meta, reportKey, filters])

  // PDF drops detail-only columns; the screen shows everything.
  const columns = useMemo(() => meta?.columns ?? [], [meta])

  const patch = (next: Partial<FilterState>) =>
    setFilters((current) => ({ ...current, page: 1, ...next }))

  const activeCount =
    (filters.search ? 1 : 0) +
    filters.actions.length +
    filters.severities.length +
    filters.actor_ids.length +
    filters.org_ids.length

  return (
    <>
      <PageHeader
        title={meta?.title ?? 'Report'}
        backTo={backTo}
        backLabel={backLabel}
        description={meta?.description}
        actions={
          meta && (
            <ExportMenu
              reportKey={reportKey}
              filters={filters}
              disabled={loading || !result || result.total === 0}
            />
          )
        }
      />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <div className="min-w-[210px] flex-1">
            <SearchBox
              value={filters.search ?? ''}
              onChange={(value) => patch({ search: value || null })}
              placeholder={`Search ${meta?.title.toLowerCase() ?? ''}`}
            />
          </div>

          {supports('date_range') && (
            <DateRangeFilter
              value={filters.date_range}
              onChange={(date_range) => patch({ date_range })}
              timezone={organization?.timezone}
            />
          )}

          {supports('actors') && (
            <LookupFilter
              entity="actors"
              label="Person"
              selected={filters.actor_ids}
              onChange={(actor_ids) => patch({ actor_ids })}
            />
          )}

          {supports('orgs') && user?.role === 'super_admin' && (
            <LookupFilter
              entity="organizations"
              label="Organization"
              selected={filters.org_ids}
              onChange={(org_ids) => patch({ org_ids })}
            />
          )}

          {supports('actions') && actionOptions.length > 0 && (
            <OptionFilter
              label="Action"
              options={actionOptions}
              selected={filters.actions}
              onChange={(actions) => patch({ actions })}
            />
          )}

          {supports('severities') && severityOptions.length > 0 && (
            <OptionFilter
              label="Severity"
              options={severityOptions}
              selected={filters.severities}
              onChange={(severities) => patch({ severities })}
            />
          )}

          {activeCount > 0 && (
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() =>
                setFilters({ ...emptyFilters(), date_range: filters.date_range })
              }
            >
              Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
            </button>
          )}
        </div>

        {/* Restating the resolved filters above the table is what makes an
            exported file defensible three months later: the same summary is
            printed into the CSV, the workbook, and the PDF. */}
        {result && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-ink-200 bg-ink-50 px-5 py-2 text-2xs text-ink-500 dark:border-ink-800 dark:bg-ink-900/60 dark:text-ink-400">
            {result.applied_filters.map(([label, value]) => (
              <span key={label}>
                <span className="uppercase tracking-[0.08em]">{label}:</span>{' '}
                <span className="text-ink-700 dark:text-ink-200">{value}</span>
              </span>
            ))}
            <span className="ml-auto tabular">
              {result.total.toLocaleString()} row{result.total === 1 ? '' : 's'}
            </span>
          </div>
        )}

        <DataTable
          columns={columns}
          rows={result?.rows ?? []}
          loading={loading}
          timezone={organization?.timezone}
          emptyTitle="No records in this window"
          emptyBody="Widen the date range or clear a filter to see more."
        />

        {result && result.total > 0 && (
          <Pagination
            page={result.page}
            pageSize={result.page_size}
            total={result.total}
            onPage={(page) => setFilters((current) => ({ ...current, page }))}
          />
        )}
      </Card>
    </>
  )
}

export function AuditPage() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  return (
    <ReportView
      reportKey="audit_trail"
      backTo={cameFromDashboard ? '/' : undefined}
      backLabel="Dashboard"
    />
  )
}