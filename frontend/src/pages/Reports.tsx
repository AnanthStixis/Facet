import { useEffect, useState } from 'react'
import { ExportMenu } from '../components/filters'
import { IconFile } from '../components/icons'
import { Banner, Card, EmptyState, Skeleton } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import { emptyFilters } from '../lib/types'
import type { ReportMeta } from '../lib/types'
import { ReportView } from './ReportView'

/**
 * The report catalogue.
 *
 * Everything here is generated from the server-side registry, so a report added
 * to the backend shows up with working filters and all three export formats
 * without any change in this file.
 */
export function Reports() {
  const [reports, setReports] = useState<ReportMeta[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<ReportMeta[]>('/reports')
      .then(setReports)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load reports.'),
      )
  }, [])

  if (selected) {
    return (
      <>
        <button
          type="button"
          className="btn-ghost mb-3 px-2 py-1 text-xs"
          onClick={() => setSelected(null)}
        >
          &larr; All reports
        </button>
        <ReportView reportKey={selected} />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Reports"
        description="Every report can be viewed on screen and downloaded as CSV, Excel, or a branded PDF — all three produced from the same query, so a file can never disagree with the screen."
      />

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      {!reports ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-36 w-full rounded-lg" />
          ))}
        </div>
      ) : reports.length === 0 ? (
        <EmptyState
          icon={<IconFile width={19} height={19} />}
          title="No reports available"
          body="Your role does not have access to any report yet."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {reports.map((report) => (
            <Card key={report.key} className="flex flex-col">
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-ink-900 dark:text-ink-50">
                  {report.title}
                </h2>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-500 dark:text-ink-400">
                  {report.description}
                </p>
                <p className="mt-3 text-2xs uppercase tracking-[0.08em] text-ink-400">
                  {report.columns.length} columns &middot;{' '}
                  {report.formats.map((format) => format.toUpperCase()).join(' / ')}
                </p>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  className="btn-primary px-3 py-1.5 text-sm"
                  onClick={() => setSelected(report.key)}
                >
                  Open
                </button>
                {/* Straight to a download with default filters, for the common
                    case where nobody wants to look at it first. */}
                <ExportMenu reportKey={report.key} filters={emptyFilters()} />
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
