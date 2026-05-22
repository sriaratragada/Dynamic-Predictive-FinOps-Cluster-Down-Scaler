import { useEffect, useRef, useState } from 'react'
import type { SavingsData } from '../api'

interface Props {
  savings: SavingsData | null
}

function useAnimatedValue(target: number, duration = 600): number {
  const [display, setDisplay] = useState(target)
  const startRef = useRef<number | null>(null)
  const fromRef  = useRef(target)
  const frameRef = useRef<number>(0)

  useEffect(() => {
    const from = fromRef.current
    if (from === target) return
    startRef.current = null

    const animate = (ts: number) => {
      if (startRef.current === null) startRef.current = ts
      const elapsed = ts - startRef.current
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(from + (target - from) * eased)
      if (progress < 1) frameRef.current = requestAnimationFrame(animate)
      else fromRef.current = target
    }

    frameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameRef.current)
  }, [target, duration])

  return display
}

function fmt(n: number, decimals = 2) {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export default function DollarsSavedPanel({ savings }: Props) {
  const total   = useAnimatedValue(savings?.total_saved_usd ?? 0)
  const week    = useAnimatedValue(savings?.this_week_usd ?? 0)
  const month   = useAnimatedValue(savings?.this_month_usd ?? 0)
  const running = useAnimatedValue(savings?.active_cordon_running_cost ?? 0)

  return (
    <div className="panel">
      <div className="panel-title">Cost Savings</div>

      <div className="savings-grid">
        <div className="savings-card" style={{ gridColumn: '1 / -1' }}>
          <div className="savings-main large">${fmt(total)}</div>
          <div className="savings-sub">All Time Saved</div>
        </div>

        <div className="savings-card">
          <div className="savings-main">${fmt(week)}</div>
          <div className="savings-sub">This Week</div>
        </div>

        <div className="savings-card">
          <div className="savings-main">${fmt(month)}</div>
          <div className="savings-sub">This Month</div>
        </div>

        <div className="savings-card">
          <div className="savings-main" style={{ fontSize: 22 }}>
            {savings ? savings.currently_cordoned_count : '—'}
          </div>
          <div className="savings-sub">Nodes Cordoned</div>
        </div>
      </div>

      <div className="savings-footer">
        {savings && (
          <>
            <span className="provider-badge">
              {savings.cloud_provider.toUpperCase()}
              &nbsp;{savings.instance_type}
              &nbsp;@&nbsp;${savings.hourly_rate_per_node.toFixed(3)}/hr
            </span>
            {savings.region && (
              <span style={{ color: 'var(--muted)' }}>{savings.region}</span>
            )}
          </>
        )}
        {savings && savings.currently_cordoned_count > 0 && (
          <span className="running-cost">
            +${fmt(running)} accruing
          </span>
        )}
      </div>
    </div>
  )
}
