import type { SavingsData, StatusData } from '../api'
import { useAnimatedValue } from '../hooks/useAnimatedValue'

interface Props {
  savings: SavingsData | null
  status:  StatusData  | null
}

function fmt(n: number, decimals = 2) {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

interface TileProps {
  value: string
  label: string
  active?: boolean
  accentColor?: string
  dimColor?: string
}

function Tile({ value, label, active, accentColor, dimColor }: TileProps) {
  return (
    <div
      className={`metrics-tile${active ? ' metrics-tile--active' : ''}`}
      style={{
        ['--tile-accent' as string]: active ? accentColor : 'transparent',
        ['--tile-dim' as string]:    active ? dimColor    : 'transparent',
        ['--tile-color' as string]:  active ? accentColor : 'var(--text)',
      }}
    >
      <div className="metrics-tile-value">{value}</div>
      <div className="metrics-tile-label">{label}</div>
    </div>
  )
}

export default function MetricsBar({ savings, status }: Props) {
  const totalRaw  = savings?.total_saved_usd ?? 0
  const monthRaw  = savings?.this_month_usd  ?? 0
  const cordoned  = savings?.currently_cordoned_count ?? 0
  const rateRaw   = (savings?.hourly_rate_per_node ?? 0) * cordoned

  const total = useAnimatedValue(totalRaw)
  const month = useAnimatedValue(monthRaw)
  const rate  = useAnimatedValue(rateRaw)

  const cordonedActive = cordoned > 0

  return (
    <div className="metrics-bar" data-reveal="1">
      <Tile
        value={`$${fmt(total)}`}
        label="Total Saved"
        active
        accentColor="var(--green)"
        dimColor="var(--green-dim)"
      />
      <Tile
        value={`$${fmt(month)}`}
        label="This Month"
      />
      <Tile
        value={`$${fmt(rate, 3)}/hr`}
        label="Saving Rate"
        active={cordonedActive}
        accentColor="var(--accent)"
        dimColor="var(--accent-dim)"
      />
      <Tile
        value={String(cordoned)}
        label="Nodes Cordoned"
        active={cordonedActive}
        accentColor="var(--amber)"
        dimColor="var(--amber-dim)"
      />
    </div>
  )
}
