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

export default function DemandCapacityChart({ history, hours, onHoursChange }: Props) {
  const data = history
    ? history.cpu_used.map((pt, i) => ({
        t: pt.t,
        used: +pt.v.toFixed(2),
        capacity: +(history.cpu_capacity[i]?.v ?? 0).toFixed(2),
      }))
    : []

  const scaledownLines = history?.scaledown_events ?? []
  const scaleupLines   = history?.scaleup_events ?? []

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
        <div className="empty-state">No history data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#334155" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={ts => fmtTime(ts, hours)}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              minTickGap={60}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              unit=" CPU"
            />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              labelFormatter={ts => fmtTime(Number(ts), hours)}
              formatter={(v: number, name: string) => [
                `${v} cores`,
                name === 'used' ? 'CPU Used' : 'Total Capacity',
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: 12, color: '#94a3b8', paddingTop: 8 }}
              formatter={(v) => v === 'used' ? 'CPU Used' : 'Total Capacity'}
            />
            <Area
              type="monotone"
              dataKey="used"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="rgba(59,130,246,0.15)"
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              type="monotone"
              dataKey="capacity"
              stroke="#ef4444"
              strokeWidth={1.5}
              strokeDasharray="6 3"
              dot={false}
            />
            {scaledownLines.map(ts => (
              <ReferenceLine
                key={`down-${ts}`}
                x={ts}
                stroke="#f59e0b"
                strokeDasharray="4 2"
                label={{ value: '▼', fill: '#f59e0b', fontSize: 10, position: 'top' }}
              />
            ))}
            {scaleupLines.map(ts => (
              <ReferenceLine
                key={`up-${ts}`}
                x={ts}
                stroke="#22c55e"
                strokeDasharray="4 2"
                label={{ value: '▲', fill: '#22c55e', fontSize: 10, position: 'top' }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
