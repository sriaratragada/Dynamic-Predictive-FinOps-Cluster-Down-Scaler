import { useLayoutEffect, useRef, useState } from 'react'
import type { CapacityData, NodeCapacity, SavingsData, StatusData } from '../api'

interface Props {
  capacity: CapacityData | null
  status:   StatusData   | null
  savings:  SavingsData  | null
}

const NODE_W   = 220
const NODE_H   = 120
const GAP      = 16
const PADDING  = 24
const BAR_X    = 12
const BAR_Y    = 44
const BAR_W    = NODE_W - 24   // 196
const BAR_H    = 8

function truncate(name: string, max = 22) {
  return name.length > max ? name.slice(0, max - 1) + '…' : name
}

function cpuColor(pct: number) {
  if (pct >= 80) return '#ff453a'
  if (pct >= 50) return '#ff9f0a'
  return '#30d158'
}

function isControlPlane(name: string) {
  return /control-plane|master|-cp-/.test(name)
}

interface TooltipState {
  node: NodeCapacity
  x: number
  y: number
}

function NodeRect({
  node,
  x,
  y,
  hourlyRate,
  onHover,
  onLeave,
}: {
  node: NodeCapacity
  x: number
  y: number
  hourlyRate: number
  onHover: (node: NodeCapacity, e: React.MouseEvent) => void
  onLeave: () => void
}) {
  const cp      = isControlPlane(node.name)
  const barFill = Math.min((node.utilisation_pct / 100) * BAR_W, BAR_W)
  const color   = cpuColor(node.utilisation_pct)
  const borderColor = node.cordoned ? '#ff9f0a' : '#2a2a2a'
  const borderWidth = node.cordoned ? 1.5 : 1

  // Status badge geometry
  const badgeW  = node.cordoned ? 80 : 60
  const badgeX  = x + NODE_W - badgeW - 10
  const badgeY  = y + 8
  const badgeH  = 18

  return (
    <g
      style={{ cursor: 'crosshair' }}
      onMouseEnter={e => onHover(node, e)}
      onMouseMove={e  => onHover(node, e)}
      onMouseLeave={onLeave}
    >
      {/* Base rect */}
      <rect
        x={x} y={y}
        width={NODE_W} height={NODE_H}
        fill="#111"
        stroke={borderColor}
        strokeWidth={borderWidth}
        rx={2}
      />

      {/* Control-plane wash */}
      {cp && (
        <rect
          x={x} y={y}
          width={NODE_W} height={NODE_H}
          fill="rgba(41,151,255,0.04)"
          rx={2}
        />
      )}

      {/* Cordon diagonal-hatch overlay */}
      {node.cordoned && (
        <rect
          className="cordon-hatch-overlay"
          x={x} y={y}
          width={NODE_W} height={NODE_H}
          fill="url(#cordon-hatch)"
          rx={2}
        />
      )}

      {/* Node name */}
      <text
        x={x + 10} y={y + 20}
        fill="#636366"
        fontFamily="'JetBrains Mono', monospace"
        fontSize={10}
        fontWeight={500}
      >
        {truncate(node.name)}
      </text>

      {/* CP badge */}
      {cp && (
        <text
          x={x + 10} y={y + 33}
          fill="#2997ff"
          fontFamily="'JetBrains Mono', monospace"
          fontSize={8}
          fontWeight={600}
          letterSpacing={1}
        >
          CTRL-PLANE
        </text>
      )}

      {/* Status badge */}
      <rect
        x={badgeX} y={badgeY}
        width={badgeW} height={badgeH}
        fill={node.cordoned ? 'rgba(255,159,10,0.15)' : 'rgba(48,209,88,0.12)'}
        stroke={node.cordoned ? 'rgba(255,159,10,0.35)' : 'rgba(48,209,88,0.3)'}
        strokeWidth={0.75}
        rx={1}
      />
      <text
        x={badgeX + badgeW / 2} y={badgeY + 12}
        textAnchor="middle"
        fill={node.cordoned ? '#ff9f0a' : '#30d158'}
        fontFamily="'JetBrains Mono', monospace"
        fontSize={9}
        fontWeight={600}
        letterSpacing={0.5}
      >
        {node.cordoned ? 'CORDONED' : 'READY'}
      </text>

      {/* CPU bar track */}
      <rect
        x={x + BAR_X} y={y + BAR_Y}
        width={BAR_W} height={BAR_H}
        fill="#1a1a1a"
        rx={1}
      />

      {/* CPU bar fill — CSS transition via inline style */}
      <rect
        x={x + BAR_X} y={y + BAR_Y}
        height={BAR_H}
        rx={1}
        style={{
          width: `${barFill}px`,
          fill: color,
          transition: 'width 0.6s ease, fill 0.3s ease',
        }}
      />

      {/* Cores / Util labels */}
      <text
        x={x + BAR_X} y={y + BAR_Y + BAR_H + 14}
        fill="#a1a1a6"
        fontFamily="'JetBrains Mono', monospace"
        fontSize={10}
      >
        {node.used_cpu_cores.toFixed(1)}/{node.allocatable_cpu_cores.toFixed(0)} cores
      </text>
      <text
        x={x + NODE_W - BAR_X} y={y + BAR_Y + BAR_H + 14}
        textAnchor="end"
        fill={color}
        fontFamily="'JetBrains Mono', monospace"
        fontSize={10}
        fontWeight={600}
      >
        {node.utilisation_pct.toFixed(1)}%
      </text>

      {/* Savings rate when cordoned */}
      {node.cordoned && hourlyRate > 0 && (
        <text
          x={x + BAR_X} y={y + NODE_H - 10}
          fill="rgba(255,159,10,0.7)"
          fontFamily="'JetBrains Mono', monospace"
          fontSize={9}
        >
          saving ${hourlyRate.toFixed(3)}/hr
        </text>
      )}
    </g>
  )
}

function SkeletonNodes() {
  return (
    <div className="node-skeleton-grid">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="node-skeleton" />
      ))}
    </div>
  )
}

export default function NodeTopology({ capacity, status, savings }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(entries => {
      setContainerWidth(entries[0].contentRect.width)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const nodes = capacity?.nodes ?? []
  const hourlyRate = savings?.hourly_rate_per_node ?? 0

  // Responsive column count
  const cols = containerWidth >= 1200 ? 5
             : containerWidth >= 960  ? 4
             : containerWidth >= 720  ? 3
             : containerWidth >= 480  ? 2
             : 1

  const rows  = Math.max(1, Math.ceil(nodes.length / cols))
  const svgH  = PADDING * 2 + rows * NODE_H + Math.max(0, rows - 1) * GAP

  function handleHover(node: NodeCapacity, e: React.MouseEvent) {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    setTooltip({ node, x: e.clientX - rect.left, y: e.clientY - rect.top })
  }

  function handleLeave() {
    setTooltip(null)
  }

  if (!capacity) return <SkeletonNodes />

  if (nodes.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '32px 0' }}>
        no nodes visible — check your cluster connection
      </div>
    )
  }

  const tooltipOnRight = tooltip && tooltip.x > containerWidth - 260
  const tooltipLeft    = tooltip
    ? tooltipOnRight ? tooltip.x - 262 : tooltip.x + 14
    : 0

  return (
    <div className="node-topology-wrap" ref={containerRef}>
      {containerWidth === 0 ? <SkeletonNodes /> : (
        <svg
          className="node-topology-svg"
          height={svgH}
          aria-label="Node topology"
        >
          <defs>
            {/* Diagonal hatch pattern for cordoned nodes */}
            <pattern
              id="cordon-hatch"
              patternUnits="userSpaceOnUse"
              width="10" height="10"
              patternTransform="rotate(45)"
            >
              <line
                x1="0" y1="0" x2="0" y2="10"
                stroke="#ff9f0a"
                strokeWidth="2"
                opacity="0.18"
              />
            </pattern>
          </defs>

          {nodes.map((node, i) => {
            const col = i % cols
            const row = Math.floor(i / cols)
            const nx  = PADDING + col * (NODE_W + GAP)
            const ny  = PADDING + row * (NODE_H + GAP)
            return (
              <NodeRect
                key={node.name}
                node={node}
                x={nx}
                y={ny}
                hourlyRate={hourlyRate}
                onHover={handleHover}
                onLeave={handleLeave}
              />
            )
          })}
        </svg>
      )}

      {tooltip && (
        <div
          className="node-tooltip"
          style={{ left: tooltipLeft, top: tooltip.y + 16 }}
        >
          <div className="node-tooltip-name">{tooltip.node.name}</div>
          <div className="node-tooltip-row">
            <span>CPU Used</span>
            <span>{tooltip.node.used_cpu_cores.toFixed(2)} / {tooltip.node.allocatable_cpu_cores.toFixed(0)} cores</span>
          </div>
          <div className="node-tooltip-row">
            <span>Utilisation</span>
            <span style={{ color: cpuColor(tooltip.node.utilisation_pct) }}>
              {tooltip.node.utilisation_pct.toFixed(1)}%
            </span>
          </div>
          {tooltip.node.cordoned && hourlyRate > 0 && (
            <div className="node-tooltip-row">
              <span>Saving rate</span>
              <span>${hourlyRate.toFixed(3)}/hr</span>
            </div>
          )}
          <div className={`node-tooltip-state node-tooltip-state--${tooltip.node.cordoned ? 'cordoned' : 'ready'}`}>
            {tooltip.node.cordoned ? '◈ CORDONED' : '◉ READY'}
          </div>
        </div>
      )}
    </div>
  )
}
