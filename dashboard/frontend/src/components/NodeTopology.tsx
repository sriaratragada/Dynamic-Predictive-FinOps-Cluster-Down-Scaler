import { useCallback, useEffect, useRef, useState } from 'react'
import type { CapacityData, SavingsData, StatusData } from '../api'

interface Props {
  capacity: CapacityData | null
  status:   StatusData   | null
  savings:  SavingsData  | null
}

interface SimNode {
  id:          string
  x:           number
  y:           number
  vx:          number
  vy:          number
  name:        string
  displayName: string
  cpuUsed:     number
  cpuTotal:    number
  utilPct:     number
  cordoned:    boolean
  isCP:        boolean
  dragging:    boolean
}

interface Edge { source: string; target: string }
interface Tooltip { node: SimNode; x: number; y: number }

// ── Force constants ──────────────────────────────────────────────────────────
const REPULSION  = 5500
const SPRING_K   = 0.045
const REST_LEN   = 170
const DAMPING    = 0.76
const GRAVITY    = 0.0012
const STOP_SPEED = 0.04
const MARGIN     = 72
const R_WORKER   = 38
const R_CP       = 54

const isCP  = (n: string) => /control-plane|master|-cp-|controlplane/i.test(n)
const trunc = (s: string, n = 18) => s.length > n ? s.slice(0, n) + '…' : s

// ── Edge builder ─────────────────────────────────────────────────────────────
function buildEdges(nodes: SimNode[]): Edge[] {
  const cps     = nodes.filter(n => n.isCP)
  const workers = nodes.filter(n => !n.isCP)
  if (cps.length > 0) {
    const out: Edge[] = []
    cps.forEach(c => workers.forEach(w => out.push({ source: c.id, target: w.id })))
    cps.forEach((c, i) => cps.slice(i + 1).forEach(c2 => out.push({ source: c.id, target: c2.id })))
    return out
  }
  // No CP: fully-connected mesh (fine for ≤ 10 nodes)
  const out: Edge[] = []
  nodes.forEach((a, i) => nodes.slice(i + 1).forEach(b => out.push({ source: a.id, target: b.id })))
  return out
}

// ── One physics step – returns true if still moving ──────────────────────────
function stepPhysics(nodes: SimNode[], edges: Edge[], W: number, H: number): boolean {
  let moving = false
  nodes.forEach(n => {
    if (n.dragging) return
    let fx = (W / 2 - n.x) * GRAVITY
    let fy = (H / 2 - n.y) * GRAVITY

    nodes.forEach(o => {
      if (o.id === n.id) return
      const dx = n.x - o.x || 0.01
      const dy = n.y - o.y || 0.01
      const d2 = Math.max(dx * dx + dy * dy, 0.01)
      const d  = Math.sqrt(d2)
      fx += (dx / d) * (REPULSION / d2)
      fy += (dy / d) * (REPULSION / d2)
    })

    edges.forEach(e => {
      if (e.source !== n.id && e.target !== n.id) return
      const oid = e.source === n.id ? e.target : e.source
      const o   = nodes.find(x => x.id === oid)
      if (!o) return
      const dx = o.x - n.x
      const dy = o.y - n.y
      const d  = Math.sqrt(dx * dx + dy * dy) || 1
      const f  = SPRING_K * (d - REST_LEN)
      fx += (dx / d) * f
      fy += (dy / d) * f
    })

    n.vx = (n.vx + fx) * DAMPING
    n.vy = (n.vy + fy) * DAMPING
    n.x  = Math.max(MARGIN, Math.min(W - MARGIN, n.x + n.vx))
    n.y  = Math.max(MARGIN, Math.min(H - MARGIN, n.y + n.vy))
    if (Math.abs(n.vx) + Math.abs(n.vy) > STOP_SPEED) moving = true
  })
  return moving
}

// ── Component ────────────────────────────────────────────────────────────────
export default function NodeTopology({ capacity, status: _status, savings }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const nodesRef     = useRef<SimNode[]>([])
  const edgesRef     = useRef<Edge[]>([])
  const rafRef       = useRef<number>(0)
  const settledRef   = useRef(false)

  const FIXED_H = 460
  const [dims,    setDims]    = useState({ w: 900, h: FIXED_H })
  const [nodes,   setNodes]   = useState<SimNode[]>([])
  const [edges,   setEdges]   = useState<Edge[]>([])
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const [tilt,    setTilt]    = useState({ x: 0, y: 0 })
  const [dragId,  setDragId]  = useState<string | null>(null)

  // ── Build sim-nodes from capacity data (preserve existing positions) ───────
  useEffect(() => {
    if (!capacity?.nodes?.length) return
    setNodes(prev => {
      const prevMap = new Map(prev.map(n => [n.id, n]))
      const count = capacity.nodes.length
      const r = Math.min(dims.w, dims.h) * 0.27
      const next: SimNode[] = capacity.nodes.map((nd, i) => {
        const ex  = prevMap.get(nd.name)
        const ang = (i / count) * Math.PI * 2 - Math.PI / 2
        return {
          id:          nd.name,
          x:           ex?.x  ?? dims.w / 2 + Math.cos(ang) * r,
          y:           ex?.y  ?? dims.h / 2 + Math.sin(ang) * r,
          vx:          ex?.vx ?? (Math.random() - 0.5) * 4,
          vy:          ex?.vy ?? (Math.random() - 0.5) * 4,
          name:        nd.name,
          displayName: trunc(nd.name),
          cpuUsed:     nd.used_cpu_cores,
          cpuTotal:    nd.allocatable_cpu_cores,
          utilPct:     nd.utilisation_pct,
          cordoned:    nd.cordoned,
          isCP:        isCP(nd.name),
          dragging:    false,
        }
      })
      nodesRef.current = next
      settledRef.current = false
      return next
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capacity])

  // ── Build edges whenever node count changes ───────────────────────────────
  useEffect(() => {
    if (nodes.length === 0) return
    const e = buildEdges(nodes)
    edgesRef.current = e
    setEdges(e)
    settledRef.current = false
  }, [nodes.length])

  // ── Physics RAF (stops automatically when settled) ────────────────────────
  useEffect(() => {
    cancelAnimationFrame(rafRef.current)
    function frame() {
      if (settledRef.current) return
      const ns = nodesRef.current.map(n => ({ ...n }))
      const still = !stepPhysics(ns, edgesRef.current, dims.w, dims.h)
      nodesRef.current = ns
      setNodes([...ns])
      if (still) { settledRef.current = true }
      else        { rafRef.current = requestAnimationFrame(frame) }
    }
    rafRef.current = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(rafRef.current)
  }, [dims, edges.length])

  // ── ResizeObserver ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([e]) => {
      const { width } = e.contentRect
      setDims(d => ({ ...d, w: Math.max(width, 300) }))
      settledRef.current = false
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Mouse tilt (3-D parallax) ─────────────────────────────────────────────
  const onContainerMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (dragId || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const cx = (e.clientX - rect.left) / rect.width  - 0.5
    const cy = (e.clientY - rect.top)  / rect.height - 0.5
    setTilt({ x: cx * 10, y: -cy * 7 })
  }, [dragId])

  const onContainerMouseLeave = useCallback(() => setTilt({ x: 0, y: 0 }), [])

  // ── Drag handlers ─────────────────────────────────────────────────────────
  const onNodeMouseDown = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    setDragId(id)
    setNodes(prev => {
      const ns = prev.map(n => n.id === id ? { ...n, dragging: true, vx: 0, vy: 0 } : n)
      nodesRef.current = ns
      return ns
    })
  }, [])

  const onSVGMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!dragId || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const x = Math.max(MARGIN, Math.min(dims.w - MARGIN, e.clientX - rect.left))
    const y = Math.max(MARGIN, Math.min(dims.h - MARGIN, e.clientY - rect.top))
    setNodes(prev => {
      const ns = prev.map(n => n.id === dragId ? { ...n, x, y } : n)
      nodesRef.current = ns
      return ns
    })
  }, [dragId, dims])

  const onSVGMouseUp = useCallback(() => {
    if (!dragId) return
    setNodes(prev => {
      const ns = prev.map(n => n.id === dragId ? { ...n, dragging: false } : n)
      nodesRef.current = ns
      settledRef.current = false
      return ns
    })
    setDragId(null)
  }, [dragId])

  // ── Color helpers ─────────────────────────────────────────────────────────
  function nodeColor(n: SimNode): string {
    if (n.isCP)           return '#2997ff'
    if (n.cordoned)       return '#ff9f0a'
    if (n.utilPct >= 80)  return '#ff453a'
    if (n.utilPct >= 50)  return '#ff9f0a'
    return '#30d158'
  }

  function glowFilter(n: SimNode): string {
    if (n.isCP)           return 'url(#glow-blue)'
    if (n.cordoned)       return 'url(#glow-amber)'
    if (n.utilPct >= 80)  return 'url(#glow-red)'
    return 'url(#glow-green)'
  }

  // ── Skeleton loading state ────────────────────────────────────────────────
  if (!capacity?.nodes?.length) {
    return (
      <div className="topology-3d-wrapper" style={{ height: FIXED_H, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="topo-skeleton">
          {[0, 1, 2].map(i => (
            <div key={i} className="topo-skeleton-node" style={{ animationDelay: `${i * 0.28}s` }} />
          ))}
        </div>
      </div>
    )
  }

  // ── Full render ───────────────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      className="topology-3d-wrapper"
      onMouseMove={onContainerMouseMove}
      onMouseLeave={onContainerMouseLeave}
      style={{ cursor: dragId ? 'grabbing' : 'grab', height: FIXED_H, overflow: 'hidden' }}
    >
      {/* Stats bar */}
      <div className="topo-stat-bar">
        <span>{capacity.nodes.length} nodes</span>
        <span className="topo-stat-sep">·</span>
        <span>
          {capacity.nodes.reduce((a, n) => a + n.used_cpu_cores, 0).toFixed(1)} /
          {' '}{capacity.nodes.reduce((a, n) => a + n.allocatable_cpu_cores, 0).toFixed(0)} cores
        </span>
        <span className="topo-stat-sep">·</span>
        <span style={{ color: capacity.nodes.some(n => n.cordoned) ? '#ff9f0a' : 'var(--text-3)' }}>
          {capacity.nodes.filter(n => n.cordoned).length} cordoned
        </span>
        <span className="topo-stat-sep topo-stat-hint-sep">·</span>
        <span className="topo-stat-hint">drag nodes to rearrange</span>
      </div>

      <svg
        width={dims.w}
        height={dims.h}
        onMouseMove={onSVGMouseMove}
        onMouseUp={onSVGMouseUp}
        onMouseLeave={onSVGMouseUp}
        style={{
          display: 'block',
          transform: `perspective(1100px) rotateY(${tilt.x}deg) rotateX(${tilt.y}deg)`,
          transition: dragId ? 'none' : 'transform 0.14s cubic-bezier(0.25,0,0.5,1)',
          transformOrigin: '50% 50%',
        }}
      >
        <defs>
          {/* Glow filters */}
          {([
            ['glow-green', '#30d158'],
            ['glow-amber', '#ff9f0a'],
            ['glow-blue',  '#2997ff'],
            ['glow-red',   '#ff453a'],
          ] as [string, string][]).map(([id, color]) => (
            <filter key={id} id={id} x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur in="SourceAlpha" stdDeviation="9" result="blur" />
              <feFlood floodColor={color} floodOpacity="0.5" result="fc" />
              <feComposite in="fc" in2="blur" operator="in" result="glow" />
              <feMerge>
                <feMergeNode in="glow" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          ))}

          {/* Depth shadow */}
          <filter id="depth-shadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="3" dy="6" stdDeviation="8" floodColor="#000" floodOpacity="0.7" />
          </filter>

          {/* Cordon diagonal hatch */}
          <pattern id="ch" patternUnits="userSpaceOnUse" width="10" height="10" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="10" stroke="#ff9f0a" strokeWidth="1.5" opacity="0.22" />
          </pattern>
        </defs>

        {/* ── Edges ── */}
        {edges.map((e, i) => {
          const src = nodes.find(n => n.id === e.source)
          const tgt = nodes.find(n => n.id === e.target)
          if (!src || !tgt) return null
          const active = !src.cordoned && !tgt.cordoned
          const isMain = src.isCP || tgt.isCP
          const stroke = active ? 'rgba(41,151,255,0.22)' : 'rgba(255,159,10,0.12)'
          const dur    = (1.6 + (i % 5) * 0.45).toFixed(2)
          const dur2   = (parseFloat(dur) * 0.55).toFixed(2)

          return (
            <g key={`e-${e.source}-${e.target}`}>
              {/* Halo */}
              <line x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={stroke} strokeWidth={isMain ? 6 : 4} opacity={0.3} />
              {/* Core */}
              <line x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={stroke} strokeWidth={isMain ? 1.5 : 0.75} />
              {/* Data-flow particles */}
              {active && (
                <>
                  <circle r={2.5} fill="#2997ff" opacity={0.85}>
                    <animateMotion dur={`${dur}s`} repeatCount="indefinite"
                      path={`M ${src.x},${src.y} L ${tgt.x},${tgt.y}`} />
                  </circle>
                  <circle r={1.5} fill="#f5f5f7" opacity={0.45}>
                    <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${dur2}s`}
                      path={`M ${src.x},${src.y} L ${tgt.x},${tgt.y}`} />
                  </circle>
                </>
              )}
            </g>
          )
        })}

        {/* ── Nodes ── */}
        {nodes.map(n => {
          const R       = n.isCP ? R_CP : R_WORKER
          const color   = nodeColor(n)
          const arcR    = R - 7
          const circ    = 2 * Math.PI * arcR
          const arcFill = circ * n.utilPct / 100

          return (
            <g
              key={n.id}
              transform={`translate(${n.x},${n.y})`}
              style={{ cursor: 'pointer' }}
              onMouseDown={e => onNodeMouseDown(e, n.id)}
              onMouseEnter={() => setTooltip({ node: n, x: n.x, y: n.y })}
              onMouseLeave={() => { if (!dragId) setTooltip(null) }}
            >
              {/* Depth shadow (simulates Z lift) */}
              <circle r={R} fill="rgba(0,0,0,0.55)" cx={4} cy={7} filter="url(#depth-shadow)" />

              {/* Ambient glow rings */}
              <circle r={R + 12} fill="none" stroke={color} strokeWidth={1} opacity={0.07} />
              <circle r={R + 22} fill="none" stroke={color} strokeWidth={0.5} opacity={0.03} />

              {/* Cordon hatch fill */}
              {n.cordoned && <circle r={R} fill="url(#ch)" />}

              {/* Main circle */}
              <circle
                r={R}
                fill={n.isCP ? 'rgba(41,151,255,0.06)' : 'rgba(14,14,14,0.96)'}
                stroke={color}
                strokeWidth={n.isCP || n.cordoned ? 1.5 : 1}
                filter={glowFilter(n)}
              />

              {/* CPU arc – track */}
              <circle r={arcR} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth={3.5} />
              {/* CPU arc – fill */}
              <circle
                r={arcR} fill="none"
                stroke={color} strokeWidth={3.5}
                strokeDasharray={`${arcFill} ${circ - arcFill}`}
                strokeDashoffset={circ * 0.25}
                strokeLinecap="round"
                style={{ transition: 'stroke-dasharray 0.8s ease' }}
              />

              {/* CP role label */}
              {n.isCP && (
                <text y={-10} textAnchor="middle"
                  fontFamily="'JetBrains Mono',monospace" fontSize={8} fontWeight={700}
                  fill="#2997ff" letterSpacing={2.5} opacity={0.9}
                >CP</text>
              )}

              {/* Utilisation % */}
              <text y={n.isCP ? 8 : 5} textAnchor="middle"
                fontFamily="'Outfit',sans-serif"
                fontSize={n.isCP ? 22 : 15}
                fontWeight={800}
                fill={n.cordoned ? '#ff9f0a' : '#f5f5f7'}
              >{Math.round(n.utilPct)}%</text>

              {/* Cores */}
              <text y={n.isCP ? 24 : 19} textAnchor="middle"
                fontFamily="'JetBrains Mono',monospace" fontSize={8}
                fill="rgba(255,255,255,0.28)"
              >{n.cpuUsed.toFixed(1)}/{n.cpuTotal.toFixed(0)}c</text>

              {/* Node name (below) */}
              <text y={R + 18} textAnchor="middle"
                fontFamily="'JetBrains Mono',monospace" fontSize={9}
                fill={n.cordoned ? 'rgba(255,159,10,0.65)' : 'rgba(255,255,255,0.3)'}
              >{n.displayName}</text>

              {/* Cordoned badge */}
              {n.cordoned && (
                <g transform={`translate(0,${R + 27})`}>
                  <rect x={-30} y={0} width={60} height={13} rx={1}
                    fill="rgba(255,159,10,0.1)" stroke="rgba(255,159,10,0.28)" strokeWidth={0.75} />
                  <text y={10} textAnchor="middle"
                    fontFamily="'JetBrains Mono',monospace" fontSize={7} fontWeight={600}
                    fill="#ff9f0a" letterSpacing={1.2}
                  >CORDONED</text>
                </g>
              )}
            </g>
          )
        })}
      </svg>

      {/* ── Tooltip ── */}
      {tooltip && (() => {
        const { node: n, x, y } = tooltip
        const ttX = x > dims.w - 250 ? x - 240 : x + 24
        const ttY = Math.max(8, Math.min(y - 50, dims.h - 150))
        return (
          <div className="topo-tooltip" style={{ left: ttX, top: ttY }}>
            <div className="topo-tt-name">{n.name}</div>
            <div className="topo-tt-row"><span>CPU</span><span>{n.cpuUsed.toFixed(2)} / {n.cpuTotal.toFixed(1)} cores</span></div>
            <div className="topo-tt-row">
              <span>Util</span>
              <span style={{ color: nodeColor(n) }}>{Math.round(n.utilPct)}%</span>
            </div>
            <div className="topo-tt-row">
              <span>State</span>
              <span style={{ color: n.cordoned ? '#ff9f0a' : '#30d158' }}>
                {n.cordoned ? 'CORDONED' : 'READY'}
              </span>
            </div>
            {n.isCP && <div className="topo-tt-row"><span>Role</span><span style={{ color: '#2997ff' }}>Control Plane</span></div>}
            {n.cordoned && savings?.hourly_rate_per_node != null && (
              <div className="topo-tt-row">
                <span>Saving</span>
                <span style={{ color: '#30d158' }}>${savings.hourly_rate_per_node.toFixed(3)}/hr</span>
              </div>
            )}
            <div className="topo-tt-hint">drag to rearrange</div>
          </div>
        )
      })()}
    </div>
  )
}
