import type { SavingsData } from '../api'
import { useAnimatedValue } from '../hooks/useAnimatedValue'

interface Props {
  savings: SavingsData | null
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
