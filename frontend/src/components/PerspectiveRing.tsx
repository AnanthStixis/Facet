import { useMemo, useState } from 'react'
import type { CoverageSlice } from '../lib/types'

/**
 * The product's signature visual.
 *
 * Two concentric arcs: the inner ring is the internal relationship graph
 * (people, teams, departments), the outer ring is the external one (products,
 * services, proposals). Seeing both on one dial is the whole pitch - every
 * competitor can draw one ring or the other, because their employee and
 * customer feedback live in separate products.
 *
 * Segment length is proportional to how many reviewable entities of that kind
 * exist, so a lopsided dial is itself the insight: an organization with a full
 * inner ring and an empty outer one is measuring its staff and ignoring its
 * clients.
 */

interface Props {
  coverage: CoverageSlice[]
  size?: number
}

interface Arc {
  slice: CoverageSlice
  path: string
  color: string
  midAngle: number
}

// One fixed, genuinely distinguishable colour per target type — not tints of a
// single hue. Shades of the same colour (the previous approach) are close to
// indistinguishable at a 12px stroke width, and worse for anyone with a colour
// vision deficiency. Domain (internal vs external) is still conveyed by ring
// radius and by the legend grouping, so colour is free to identify the type.
const TARGET_COLORS: Record<string, string> = {
  employee: '#0072B2',
  manager: '#56B4E9',
  team: '#009E73',
  department: '#B4A300',
  product: '#E69F00',
  service: '#D55E00',
  proposal: '#CC79A7',
}
const FALLBACK_COLORS = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#D55E00']

const GAP_DEGREES = 3

function polar(cx: number, cy: number, radius: number, degrees: number) {
  const radians = ((degrees - 90) * Math.PI) / 180
  return { x: cx + radius * Math.cos(radians), y: cy + radius * Math.sin(radians) }
}

function arcPath(
  cx: number,
  cy: number,
  radius: number,
  startAngle: number,
  endAngle: number,
) {
  const start = polar(cx, cy, radius, endAngle)
  const end = polar(cx, cy, radius, startAngle)
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 0 ${end.x} ${end.y}`
}

function buildRing(slices: CoverageSlice[], radius: number, centre: number): Arc[] {
  const populated = slices.filter((slice) => slice.count > 0)
  if (populated.length === 0) return []
  const total = populated.reduce((sum, slice) => sum + slice.count, 0)
  const usable = 360 - GAP_DEGREES * populated.length

  let cursor = 0
  return populated.map((slice, index) => {
    const sweep = (slice.count / total) * usable
    const start = cursor
    const end = cursor + sweep
    cursor = end + GAP_DEGREES
    return {
      slice,
      path: arcPath(centre, centre, radius, start, end),
      color:
        TARGET_COLORS[slice.target_type] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length],
      midAngle: (start + end) / 2,
    }
  })
}

export function PerspectiveRing({ coverage, size = 260 }: Props) {
  const [hovered, setHovered] = useState<CoverageSlice | null>(null)
  const centre = size / 2

  const { internal, external, totals } = useMemo(() => {
    const internalSlices = coverage.filter((slice) => slice.domain === 'internal')
    const externalSlices = coverage.filter((slice) => slice.domain === 'external')
    return {
      internal: buildRing(internalSlices, size * 0.29, centre),
      external: buildRing(externalSlices, size * 0.42, centre),
      totals: {
        internal: internalSlices.reduce((sum, s) => sum + s.count, 0),
        external: externalSlices.reduce((sum, s) => sum + s.count, 0),
      },
    }
  }, [coverage, size, centre])

  const grandTotal = totals.internal + totals.external
  const active = hovered

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center sm:gap-7">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label="Feedback coverage across internal and external relationships"
        className="shrink-0 overflow-visible"
      >
        {/* Track rings, so an empty domain still reads as a domain that exists. */}
        {[size * 0.29, size * 0.42].map((radius) => (
          <circle
            key={radius}
            cx={centre}
            cy={centre}
            r={radius}
            fill="none"
            className="stroke-ink-100 dark:stroke-ink-800"
            strokeWidth={radius === size * 0.29 ? 12 : 14}
          />
        ))}

        {[...internal, ...external].map((arc, index) => {
          const isInternal = arc.slice.domain === 'internal'
          const dimmed = active && active.target_type !== arc.slice.target_type
          return (
            <path
              key={`${arc.slice.target_type}-${index}`}
              d={arc.path}
              fill="none"
              stroke={arc.color}
              strokeWidth={isInternal ? 12 : 14}
              strokeLinecap="round"
              opacity={dimmed ? 0.25 : 1}
              className="cursor-pointer transition-opacity duration-200"
              onMouseEnter={() => setHovered(arc.slice)}
              onMouseLeave={() => setHovered(null)}
            />
          )
        })}

        <text
          x={centre}
          y={centre - 6}
          textAnchor="middle"
          className="fill-ink-900 text-[26px] font-semibold dark:fill-white"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {active ? active.count : grandTotal}
        </text>
        <text
          x={centre}
          y={centre + 13}
          textAnchor="middle"
          className="fill-ink-400 text-[10px] font-semibold uppercase tracking-[0.12em]"
        >
          {active ? active.label : 'Relationships'}
        </text>
      </svg>

      <div className="w-full min-w-0 space-y-4">
        {(
          [
            ['internal', 'Internal', totals.internal, internal],
            ['external', 'External', totals.external, external],
          ] as const
        ).map(([key, label, total, arcs]) => (
          <div key={key}>
            <div className="mb-1.5 flex items-baseline justify-between">
              <span className="label-caps">{label}</span>
              <span className="text-sm font-semibold text-ink-700 dark:text-ink-200">
                {total}
              </span>
            </div>
            {arcs.length === 0 ? (
              <p className="text-xs text-ink-400">
                Nothing configured yet.
              </p>
            ) : (
              <div className="flex flex-wrap gap-x-3.5 gap-y-1.5">
                {arcs.map((arc) => (
                  <button
                    key={arc.slice.target_type}
                    type="button"
                    onMouseEnter={() => setHovered(arc.slice)}
                    onMouseLeave={() => setHovered(null)}
                    className="group flex items-center gap-1.5 text-xs text-ink-500 transition-colors hover:text-ink-900 dark:text-ink-400 dark:hover:text-ink-100"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: arc.color }}
                    />
                    {arc.slice.label}
                    <span className="tabular font-semibold text-ink-700 dark:text-ink-200">
                      {arc.slice.count}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Compact 14-day activity bars. */
export function Sparkbars({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((point) => point.count))
  return (
    <div className="flex h-14 items-end gap-1" aria-label="Activity over the last 14 days">
      {data.map((point) => (
        <div key={point.date} className="group relative flex-1">
          <div
            className="w-full rounded-sm accent-bg transition-opacity"
            style={{
              height: `${Math.max(3, (point.count / max) * 52)}px`,
              opacity: point.count === 0 ? 0.15 : 0.35 + (point.count / max) * 0.65,
            }}
          />
          <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded bg-ink-900 px-2 py-1 text-2xs font-medium text-white group-hover:block dark:bg-ink-700">
            {point.count} on {point.date.slice(5)}
          </div>
        </div>
      ))}
    </div>
  )
}
