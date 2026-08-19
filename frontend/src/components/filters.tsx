import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { api, downloadExport } from '../lib/api'
import type { DateRangePreset, FilterState, LookupItem } from '../lib/types'
import { IconCalendar, IconChevronDown, IconDownload, IconSearch, IconX } from './icons'
import { Spinner } from './ui'

/** Close a popover when the user clicks outside its trigger or its panel, or presses Escape. */
export function useDismiss(open: boolean, close: () => void) {
  const triggerRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node
      const inTrigger = triggerRef.current?.contains(target)
      const inPanel = panelRef.current?.contains(target)
      if (!inTrigger && !inPanel) close()
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && close()
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])
  return { triggerRef, panelRef }
}

/**
 * Renders its children into `document.body`, positioned under `anchorRef`.
 *
 * A popover positioned with plain CSS `absolute` is confined to its parent's
 * stacking context — and every `Card` on this app creates one (the fade-up
 * entrance animation promotes it), so a popover opened inside one card could
 * never paint above a sibling card later in the DOM, however high its
 * z-index. Escaping into a portal, positioned in viewport coordinates from
 * the anchor's actual screen position, is what makes it float above
 * everything regardless of where in the tree it was opened.
 */
export function FloatingPanel({
  anchorRef,
  panelRef,
  open,
  className,
  width,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>
  panelRef: RefObject<HTMLDivElement | null>
  open: boolean
  className?: string
  width?: number
  children: ReactNode
}) {
  const [position, setPosition] = useState<{
    left: number
    maxHeight: number
    anchor: 'top' | 'bottom'
    offset: number
  } | null>(null)
  const observerRef = useRef<ResizeObserver | null>(null)

  // Opens below the trigger by default, but flips above it when there isn't
  // room below (e.g. a field near the bottom of the form) and there is more
  // room above — otherwise the panel spills past the viewport and visually
  // overlaps whatever sits underneath it.
  //
  // When flipped, the panel is anchored by its *bottom* edge (CSS `bottom`,
  // not a computed `top`) rather than by top = trigger.top - estimatedHeight.
  // That estimate raced the panel's real height whenever content loaded in
  // asynchronously (e.g. a contact list arriving after the panel had already
  // painted with just a "loading" placeholder) — the panel would flip using
  // the placeholder's short height, then grow downward from that stale top,
  // overlapping the trigger it was supposed to clear. Anchoring the edge
  // closest to the trigger and letting the box grow away from it (up to
  // `maxHeight`) is correct regardless of when or how much content arrives.
    const recalc = () => {
    const rect = anchorRef.current?.getBoundingClientRect()
    if (!rect) return
    const margin = 8
    const spaceBelow = window.innerHeight - rect.bottom - margin
    const spaceAbove = rect.top - margin
    const panelHeight = panelRef.current?.scrollHeight ?? 0
    const openAbove = panelHeight > spaceBelow && spaceAbove > spaceBelow

    // Horizontal overflow gets the same treatment vertical already has
    // above. A panel left-aligned to a trigger sitting near the right edge
    // of the viewport (the Export button in a page header, for instance)
    // would render most of its width off-screen — nothing here previously
    // checked for that. When the panel's actual width would overflow past
    // the right edge, anchor its *right* edge to the trigger's right edge
    // instead, so it grows leftward and stays fully on screen. Falls back
    // to the panel's default width (w-72, 288px) before it has mounted and
    // reported a real one — the same race `attachPanel` below already
    // resolves for height, resolved the same way here once it re-fires
    // this with the real measurement.
    const panelWidth = width ?? panelRef.current?.getBoundingClientRect().width ?? 288
    const spaceRight = window.innerWidth - rect.left - margin
    const left = panelWidth > spaceRight ? Math.max(margin, rect.right - panelWidth) : rect.left

    setPosition(
      openAbove
        ? { anchor: 'bottom', offset: window.innerHeight - rect.top + 6, left, maxHeight: Math.max(80, spaceAbove) }
        : { anchor: 'top', offset: rect.bottom + 6, left, maxHeight: Math.max(80, spaceBelow) },
    )
  }
  const recalcRef = useRef(recalc)
  recalcRef.current = recalc

  useEffect(() => {
    if (!open) {
      setPosition(null)
      return
    }
    recalc()
    const onScroll = () => recalcRef.current()
    const onResize = () => recalcRef.current()
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
      observerRef.current?.disconnect()
      observerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, anchorRef, panelRef])

  // A callback ref, not a plain effect — it fires synchronously the instant
  // React attaches the portal's DOM node, independent of requestAnimationFrame
  // (which browsers throttle or skip entirely on a backgrounded/non-composited
  // tab). That's what makes the very first measurement of the panel's real
  // height reliable instead of racy.
  //
  // Memoized with an empty dependency array — an inline function here would
  // get a new identity on every render (including the ones this callback
  // itself triggers via setPosition), and React detaches+reattaches a ref
  // whenever its identity changes. That turned into recalc -> setPosition ->
  // re-render -> new callback identity -> detach/reattach -> recalc again,
  // an infinite loop ("Maximum update depth exceeded").
  const attachPanel = useCallback((node: HTMLDivElement | null) => {
    ;(panelRef as { current: HTMLDivElement | null }).current = node
    observerRef.current?.disconnect()
    observerRef.current = null
    if (node) {
      recalcRef.current()
      const observer = new ResizeObserver(() => recalcRef.current())
      observer.observe(node)
      observerRef.current = observer
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!open || !position) return null

  return createPortal(
    <div
      ref={attachPanel}
      style={{
        left: position.left,
        maxHeight: position.maxHeight,
        top: position.anchor === 'top' ? position.offset : 'auto',
        bottom: position.anchor === 'bottom' ? position.offset : 'auto',
        width: width ?? undefined,
      }}
      className={clsx(
        'fixed z-50 w-72 overflow-y-auto rounded-lg border border-ink-200 bg-white p-1.5 shadow-lift dark:border-ink-700 dark:bg-ink-900',
        className,
      )}
    >
      {children}
    </div>,
    document.body,
  )
}

// --- Search ----------------------------------------------------------------

export function SearchBox({
  value,
  onChange,
  placeholder = 'Search',
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState(value)

  // Debounced, so typing does not fire a query per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (draft !== value) onChange(draft)
    }, 250)
    return () => clearTimeout(timer)
  }, [draft])

  useEffect(() => setDraft(value), [value])

  return (
    <div className="relative min-w-[200px] flex-1">
      <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
      <input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
        className="field py-1.5 pl-8 pr-8"
      />
      {draft && (
        <button
          type="button"
          onClick={() => setDraft('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-700"
        >
          <IconX width={13} height={13} />
        </button>
      )}
    </div>
  )
}

// --- Date range ------------------------------------------------------------

const PRESETS: { value: DateRangePreset; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'last_7_days', label: 'Last 7 days' },
  { value: 'last_30_days', label: 'Last 30 days' },
  { value: 'last_90_days', label: 'Last 90 days' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'this_quarter', label: 'This quarter' },
  { value: 'this_year', label: 'This year' },
]

export function DateRangeFilter({
  value,
  onChange,
  timezone,
}: {
  value: FilterState['date_range']
  onChange: (next: FilterState['date_range']) => void
  timezone?: string
}) {
  const [open, setOpen] = useState(false)
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))

  const label =
    value.preset === 'custom'
      ? `${value.start ?? '...'} to ${value.end ?? '...'}`
      : (PRESETS.find((preset) => preset.value === value.preset)?.label ?? 'Period')

  return (
    <div className="relative" ref={triggerRef}>
      <button
        type="button"
        onClick={() => setOpen((state) => !state)}
        className="btn-secondary whitespace-nowrap py-1.5"
      >
        <IconCalendar width={14} height={14} />
        {label}
        <IconChevronDown width={13} height={13} className="opacity-60" />
      </button>

      <FloatingPanel anchorRef={triggerRef} panelRef={panelRef} open={open}>
          {PRESETS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              onClick={() => {
                onChange({ preset: preset.value })
                setOpen(false)
              }}
              className={clsx(
                'flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-sm hover:bg-ink-100 dark:hover:bg-ink-800',
                value.preset === preset.value && 'accent-soft-bg accent-text font-medium',
              )}
            >
              {preset.label}
            </button>
          ))}

          <div className="mt-1.5 border-t border-ink-200 p-2 dark:border-ink-700">
            <p className="label-caps mb-1.5">Custom range</p>
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={value.start ?? ''}
                onChange={(event) =>
                  onChange({ preset: 'custom', start: event.target.value, end: value.end })
                }
                className="field py-1 text-xs"
              />
              <span className="text-xs text-ink-400">to</span>
              <input
                type="date"
                value={value.end ?? ''}
                onChange={(event) =>
                  onChange({ preset: 'custom', start: value.start, end: event.target.value })
                }
                className="field py-1 text-xs"
              />
            </div>
            {timezone && (
              // Stated explicitly because "last 30 days" is otherwise ambiguous
              // for anyone reading the export in another country.
              <p className="mt-1.5 text-2xs text-ink-400">
                Dates are interpreted in {timezone}.
              </p>
            )}
          </div>
      </FloatingPanel>
    </div>
  )
}

// --- Autocomplete multi-select --------------------------------------------

export function LookupFilter({
  entity,
  label,
  selected,
  onChange,
}: {
  entity: string
  label: string
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<LookupItem[]>([])
  const [loading, setLoading] = useState(false)
  // Remembers the label of anything picked, so a selected chip keeps its name
  // after the search text changes and the result list no longer contains it.
  const [chosen, setChosen] = useState<Record<string, LookupItem>>({})
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))

  useEffect(() => {
    if (!open) return
    let cancelled = false
    // The loading indicator only appears once the request actually starts,
    // not for the 220ms of debounce before it. Dimming the list on every
    // keystroke — before a request has even been sent — is what produced the
    // flicker on ordinary fast typing.
    const timer = setTimeout(async () => {
      if (cancelled) return
      setLoading(true)
      try {
        const results = await api.get<LookupItem[]>(
          `/lookup/${entity}?q=${encodeURIComponent(query)}`,
        )
        if (!cancelled) setItems(results)
      } catch {
        if (!cancelled) setItems([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 220)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [entity, query, open])

  const toggle = (item: LookupItem) => {
    const next = selected.includes(item.id)
      ? selected.filter((id) => id !== item.id)
      : [...selected, item.id]
    setChosen((state) => ({ ...state, [item.id]: item }))
    onChange(next)
  }

  return (
    <div className="relative" ref={triggerRef}>
      <button
        type="button"
        onClick={() => setOpen((state) => !state)}
        className={clsx(
          'btn-secondary whitespace-nowrap py-1.5',
          selected.length > 0 && 'accent-border accent-text',
        )}
      >
        {selected.length === 1 && chosen[selected[0]]
          ? chosen[selected[0]].label
          : label}
        {selected.length > 1 && (
          <span className="accent-bg ml-0.5 rounded-full px-1.5 text-2xs font-semibold text-white">
            {selected.length}
          </span>
        )}
        <IconChevronDown width={13} height={13} className="opacity-60" />
      </button>

      <FloatingPanel anchorRef={triggerRef} panelRef={panelRef} open={open}>
          <div className="relative mb-1.5">
            <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${label.toLowerCase()}`}
              className="field py-1.5 pl-8 pr-7 text-sm"
            />
            {/* A small indicator in the input itself, not a block that grows
                and shrinks the popover on every keystroke — that resizing is
                what read as flickering. The previous results stay visible and
                just dim slightly while a new query is in flight. */}
            {loading && (
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-400">
                <Spinner />
              </span>
            )}
          </div>

          <div
            className={clsx(
              'max-h-60 overflow-y-auto transition-opacity duration-150',
              loading && 'opacity-60',
            )}
          >
            {!loading && items.length === 0 && (
              <p className="px-2.5 py-3 text-xs text-ink-400">No matches.</p>
            )}
            {items.map((item) => {
              const isSelected = selected.includes(item.id)
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => toggle(item)}
                  className="flex w-full items-center gap-2.5 rounded px-2.5 py-1.5 text-left hover:bg-ink-100 dark:hover:bg-ink-800"
                >
                  <span
                    className={clsx(
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                      isSelected
                        ? 'accent-bg accent-border text-white'
                        : 'border-ink-300 dark:border-ink-600',
                    )}
                  >
                    {isSelected && (
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                        <path
                          d="m20 6-11 11-5-5"
                          stroke="currentColor"
                          strokeWidth="3.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink-800 dark:text-ink-100">
                      {item.label}
                    </span>
                    {item.sublabel && (
                      <span className="block truncate text-2xs text-ink-400">
                        {item.sublabel}
                      </span>
                    )}
                  </span>
                </button>
              )
            })}
          </div>

          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => {
                onChange([])
                setChosen({})
              }}
              className="mt-1.5 w-full border-t border-ink-200 pt-1.5 text-xs text-ink-500 hover:text-critical dark:border-ink-700"
            >
              Clear {selected.length} selected
            </button>
          )}
      </FloatingPanel>
    </div>
  )
}

// --- Static option multi-select -------------------------------------------

export function OptionFilter({
  label,
  options,
  selected,
  onChange,
}: {
  label: string
  options: { value: string; label: string; group?: string }[]
  selected: string[]
  onChange: (values: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))

  const grouped = useMemo(() => {
    const filtered = options.filter((option) =>
      option.label.toLowerCase().includes(query.toLowerCase()),
    )
    const map = new Map<string, typeof options>()
    for (const option of filtered) {
      const key = option.group ?? ''
      map.set(key, [...(map.get(key) ?? []), option])
    }
    return [...map.entries()]
  }, [options, query])

  return (
    <div className="relative" ref={triggerRef}>
      <button
        type="button"
        onClick={() => setOpen((state) => !state)}
        className={clsx(
          'btn-secondary whitespace-nowrap py-1.5',
          selected.length > 0 && 'accent-border accent-text',
        )}
      >
        {label}
        {selected.length > 0 && (
          <span className="accent-bg ml-0.5 rounded-full px-1.5 text-2xs font-semibold text-white">
            {selected.length}
          </span>
        )}
        <IconChevronDown width={13} height={13} className="opacity-60" />
      </button>

      <FloatingPanel anchorRef={triggerRef} panelRef={panelRef} open={open}>
          {options.length > 8 && (
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Filter ${label.toLowerCase()}`}
              className="field mb-1.5 py-1.5 text-sm"
            />
          )}
          <div className="max-h-64 overflow-y-auto">
            {grouped.map(([group, groupOptions]) => (
              <div key={group}>
                {group && <p className="label-caps px-2.5 pb-1 pt-2">{group}</p>}
                {groupOptions.map((option) => {
                  const isSelected = selected.includes(option.value)
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() =>
                        onChange(
                          isSelected
                            ? selected.filter((value) => value !== option.value)
                            : [...selected, option.value],
                        )
                      }
                      className={clsx(
                        'flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm hover:bg-ink-100 dark:hover:bg-ink-800',
                        isSelected && 'accent-text font-medium',
                      )}
                    >
                      <span
                        className={clsx(
                          'h-1.5 w-1.5 shrink-0 rounded-full',
                          isSelected ? 'accent-bg' : 'bg-ink-300 dark:bg-ink-600',
                        )}
                      />
                      {option.label}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mt-1.5 w-full border-t border-ink-200 pt-1.5 text-xs text-ink-500 hover:text-critical dark:border-ink-700"
            >
              Clear
            </button>
          )}
      </FloatingPanel>
    </div>
  )
}

// --- Export ----------------------------------------------------------------

const FORMATS = [
  { value: 'csv', label: 'CSV' },
  { value: 'xlsx', label: 'Excel' },
  { value: 'pdf', label: 'PDF'},
]

export function ExportMenu({
  reportKey,
  filters,
  disabled,
}: {
  reportKey: string
  filters: FilterState
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { triggerRef, panelRef } = useDismiss(open, () => setOpen(false))

  const run = async (format: string) => {
    setBusy(format)
    setError(null)
    try {
      // The exact filter object driving the table is what gets sent, which is
      // why the file can never disagree with what is on screen.
      await downloadExport(reportKey, format, filters)
      setOpen(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Export failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="relative" ref={triggerRef}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((state) => !state)}
        className="btn-primary whitespace-nowrap py-1.5"
      >
        <IconDownload width={14} height={14} />
        Export
        <IconChevronDown width={13} height={13} className="opacity-70" />
      </button>

      <FloatingPanel anchorRef={triggerRef} panelRef={panelRef} open={open} width={224}>
          <p className="label-caps px-2.5 pb-1 pt-1.5">Download</p>
          {FORMATS.map((format) => (
            <button
              key={format.value}
              type="button"
              disabled={busy !== null}
              onClick={() => run(format.value)}
              className="flex w-full items-center justify-between gap-3 rounded px-2.5 py-2 text-left hover:bg-ink-100 disabled:opacity-50 dark:hover:bg-ink-800"
            >
              <span>
                <span className="block text-sm font-medium text-ink-800 dark:text-ink-100">
                  {format.label}
                </span>
                {/* <span className="block text-2xs text-ink-400">{format.hint}</span> */}
              </span>
              {busy === format.value && <Spinner className="text-ink-400" />}
            </button>
          ))}
          {error && <p className="px-2.5 py-1.5 text-xs text-critical">{error}</p>}
      </FloatingPanel>
    </div>
  )
}
