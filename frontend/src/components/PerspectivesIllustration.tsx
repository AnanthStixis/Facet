/**
 * Six perspective cards — the actual product taxonomy (Employee, Management,
 * Client, Product, Service, Proposal), not a decorative stand-in — converging
 * on a central "360° Insights" node.
 *
 * Uses the same internal (blue) / external (amber) color coding as the hero's
 * legend and GraphArtwork, so it reads as part of this product's visual
 * system rather than a separate illustration bolted on for one section.
 */

type Perspective = {
  label: string
  kind: 'internal' | 'external'
  x: number
  y: number
}

const CENTER = { x: 200, y: 170 }

const PERSPECTIVES: Perspective[] = [
  { label: 'Employee', kind: 'internal', x: 200, y: 52 },
  { label: 'Management', kind: 'internal', x: 302, y: 111 },
  { label: 'Client', kind: 'external', x: 302, y: 229 },
  { label: 'Product', kind: 'external', x: 200, y: 288 },
  { label: 'Service', kind: 'external', x: 98, y: 229 },
  { label: 'Proposal', kind: 'external', x: 98, y: 111 },
]

const TONE = {
  internal: { fill: '#E8F0FA', stroke: '#3572B0', text: '#28588F' },
  external: { fill: '#FBF1E2', stroke: '#C08A2E', text: '#8C6420' },
}

export function PerspectivesIllustration() {
  return (
    <svg viewBox="0 0 400 340" className="h-full w-full" role="img" aria-label="Six feedback perspectives converging into one 360° insights view">
      <circle cx={CENTER.x} cy={CENTER.y} r={92} fill="none" stroke="#2F6F62" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="2 5" />

      {PERSPECTIVES.map((p, i) => (
        <line
          key={`line-${p.label}`}
          x1={CENTER.x}
          y1={CENTER.y}
          x2={p.x}
          y2={p.y}
          stroke="#AEB6C1"
          strokeOpacity={0.55}
          strokeWidth={1.1}
          strokeDasharray="70"
          strokeDashoffset="70"
          style={{ animation: `pf-draw .6s ${0.15 + i * 0.06}s cubic-bezier(.3,.7,.3,1) forwards` }}
        />
      ))}

      <g style={{ animation: 'pf-pop .5s .55s cubic-bezier(.2,.8,.3,1) both' }}>
        <rect x={CENTER.x - 59} y={CENTER.y - 32} width={118} height={64} rx={16} fill="#2F6F62" />
        <text x={CENTER.x} y={CENTER.y - 4} textAnchor="middle" fill="#FFFFFF" style={{ fontSize: '15px', fontWeight: 600 }}>
          360°
        </text>
        <text
          x={CENTER.x}
          y={CENTER.y + 15}
          textAnchor="middle"
          fill="#CFE3DD"
          style={{ fontSize: '8px', letterSpacing: '0.14em', textTransform: 'uppercase' }}
        >
          Insights
        </text>
      </g>

      {PERSPECTIVES.map((p, i) => {
        const tone = TONE[p.kind]
        return (
          <g key={p.label} style={{ animation: `pf-pop .5s ${0.35 + i * 0.06}s cubic-bezier(.2,.8,.3,1) both` }}>
            <rect
              x={p.x - 46}
              y={p.y - 18}
              width={92}
              height={36}
              rx={12}
              fill={tone.fill}
              stroke={tone.stroke}
              strokeOpacity={0.5}
              strokeWidth={1}
            />
            <text x={p.x} y={p.y + 4} textAnchor="middle" fill={tone.text} style={{ fontSize: '11px', fontWeight: 500 }}>
              {p.label}
            </text>
          </g>
        )
      })}

      <style>{`
        @keyframes pf-draw { to { stroke-dashoffset: 0; } }
        @keyframes pf-pop { from { opacity: 0; transform: scale(.85); transform-origin: center; } to { opacity: 1; transform: scale(1); } }
      `}</style>
    </svg>
  )
}