import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import type { HistoryData } from '../api'

interface Props {
  history: HistoryData | null
  hours: number
  onHoursChange: (h: number) => void
}

const HOUR_OPTIONS = [6, 12, 24, 48, 168]

function fmtTime(ts: number, hours: number) {
  const d = new Date(ts)
  if (hours <= 24) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const TICK_STYLE = {
  fill: 'var(--text-3)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 10,
}

export default function DemandCapacityChart({ history, hours, onHoursChange }: Props) {
  const data = history
    ? history.cpu_used.map((pt, i) => ({
        t: pt.t,
        used:     +pt.v.toFixed(2),
        capacity: +(history.cpu_capacity[i]?.v ?? 0).toFixed(2),
      }))
    : []

  const scaledownLines = history?.scaledown_events ?? []
  const scaleupLines   = history?.scaleup_events   ?? []

  return (
    <div className="panel">
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div className="panel-title" style={{ margin: 0, flex: 1 }}>
          CPU Demand vs. Capacity
        </div>
        <div className="chart-controls">
          {HOUR_OPTIONS.map(h => (
            <button
              key={h}
              className={`chart-btn${hours === h ? ' active' : ''}`}
              onClick={() => onHoursChange(h)}
            >
              {h < 24 ? `${h}h` : h === 24 ? '24h' : h === 48 ? '2d' : '7d'}
            </button>
          ))}
        </div>
      </div>

      {data.length === 0 ? (
        <div className="empty-state">no history data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid
              stroke="var(--border)"
              strokeDasharray="1 4"
              vertical={false}
            />
            <XAxis
              dataKey="t"
              tickFormatter={ts => fmtTime(ts, hours)}
              tick={TICK_STYLE}
              axisLine={false}
              tickLine={false}
              minTickGap={60}
            />
            <YAxis
              tick={TICK_STYLE}
              axisLine={false}
              tickLine={false}
              unit=" CPU"
            />
            <Tooltip
              contentStyle={{
                background: 'var(--surface-3)',
                border: '1px solid var(--border-2)',
                borderRadius: '2px',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              labelStyle={{ color: 'var(--text-3)' }}
              labelFormatter={ts => fmtTime(Number(ts), hours)}
              formatter={(v: number, name: string) => [
                `${v} cores`,
                name === 'used' ? 'CPU Used' : 'Total Capacity',
              ]}
            />
            <Legend
              wrapperStyle={{
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
                color: 'var(--text-3)',
                paddingTop: 8,
                letterSpacing: '0.5px',
              }}
              formatter={v => v === 'used' ? 'CPU USED' : 'CAPACITY'}
            />
            <Area
              type="monotone"
              dataKey="used"
              stroke="#2997ff"
              strokeWidth={1.5}
              fill="rgba(41,151,255,0.08)"
              dot={false}
              activeDot={{ r: 3, fill: '#2997ff', stroke: 'none' }}
            />
            <Line
              type="monotone"
              dataKey="capacity"
              stroke="rgba(255,69,58,0.5)"
              strokeWidth={1}
              strokeDasharray="4 4"
              dot={false}
            />
            {scaledownLines.map(ts => (
              <ReferenceLine
                key={`down-${ts}`}
                x={ts}
                stroke="rgba(255,159,10,0.5)"
                strokeDasharray="3 2"
                label={{ value: '▼', fill: '#ff9f0a', fontSize: 9, position: 'top' }}
              />
            ))}
            {scaleupLines.map(ts => (
              <ReferenceLine
                key={`up-${ts}`}
                x={ts}
                stroke="rgba(48,209,88,0.5)"
                strokeDasharray="3 2"
                label={{ value: '▲', fill: '#30d158', fontSize: 9, position: 'top' }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
