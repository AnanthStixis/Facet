/**
 * A slowly drawn constellation of the feedback graph: nodes for people, teams,
 * products and proposals, linked into one figure. It states the positioning
 * before a single word is read — every relationship has more than one side,
 * and the platform shows all of them at once.
 *
 * Shared by the sign-in screen and the marketing home page so the same
 * artwork means the same thing everywhere it appears, rather than two
 * hand-maintained copies drifting apart.
 */
export function GraphArtwork() {
  const nodes = [
    { x: 50, y: 18, r: 4.5, kind: 'internal', label: 'Manager' },
    { x: 22, y: 34, r: 3.5, kind: 'internal', label: 'Peer' },
    { x: 78, y: 32, r: 3.5, kind: 'internal', label: 'Team' },
    { x: 50, y: 50, r: 6.5, kind: 'core', label: 'Person' },
    { x: 18, y: 68, r: 4, kind: 'external', label: 'Client' },
    { x: 50, y: 82, r: 4, kind: 'external', label: 'Proposal' },
    { x: 82, y: 66, r: 4, kind: 'external', label: 'Product' },
  ]
  const links: [number, number][] = [
    [0, 3], [1, 3], [2, 3], [3, 4], [3, 5], [3, 6], [4, 5], [5, 6], [1, 0], [0, 2],
  ]

  return (
    <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden="true">
      {links.map(([from, to], index) => (
        <line
          key={index}
          x1={nodes[from].x}
          y1={nodes[from].y}
          x2={nodes[to].x}
          y2={nodes[to].y}
          stroke="#8A93A0"
          strokeOpacity={0.4}
          strokeWidth={0.35}
          strokeDasharray="60"
          strokeDashoffset="60"
          style={{
            animation: `dash 1.5s ${0.25 + index * 0.07}s cubic-bezier(.3,.8,.3,1) forwards`,
          }}
        />
      ))}
      {nodes.map((node, index) => (
        <g
          key={node.label}
          style={{ animation: `pop .6s ${0.6 + index * 0.08}s cubic-bezier(.2,.9,.3,1) both` }}
        >
          {node.kind === 'core' && (
            <circle cx={node.x} cy={node.y} r={node.r + 4} fill="none" stroke="#2F6F62" strokeOpacity={0.3} strokeWidth={0.4} />
          )}
          <circle
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill={
              node.kind === 'external'
                ? '#C08A2E'
                : node.kind === 'core'
                  ? '#2F6F62'
                  : '#3572B0'
            }
            fillOpacity={node.kind === 'core' ? 1 : 0.88}
          />
          <text
            x={node.x}
            y={node.y - node.r - 2.4}
            textAnchor="middle"
            fill="#5A6472"
            fillOpacity={0.85}
            style={{ fontSize: '2.6px', letterSpacing: '0.28px', textTransform: 'uppercase' }}
          >
            {node.label}
          </text>
        </g>
      ))}
      <style>{`
        @keyframes dash { to { stroke-dashoffset: 0; } }
        @keyframes pop { from { opacity: 0; transform: scale(.4); transform-origin: center; } to { opacity: 1; transform: scale(1); } }
      `}</style>
    </svg>
  )
}