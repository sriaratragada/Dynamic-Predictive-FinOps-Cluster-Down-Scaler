import type { EventsData } from '../api'

interface Props {
  events: EventsData | null
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function fmtHours(h: number): string {
  if (h < 1) return `${Math.round(h * 60)}m`
  return `${h.toFixed(1)}h`
}

export default function AuditLog({ events }: Props) {
  const rows = events?.events ?? []

  return (
    <div className="panel audit-panel">
      <div className="panel-header">
        <h2>Audit Log</h2>
        <span className="panel-badge">{rows.length} events</span>
      </div>

      {rows.length === 0 ? (
        <div className="audit-empty">No cordon events recorded yet</div>
      ) : (
        <div className="audit-scroll">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Node</th>
                <th>Cordoned at</th>
                <th>Released at</th>
                <th>Duration</th>
                <th className="audit-right">Saved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => (
                <tr key={i} className="audit-row">
                  <td className="audit-node">{e.node}</td>
                  <td className="audit-time">{fmtDate(e.start)}</td>
                  <td className="audit-time">{fmtDate(e.end)}</td>
                  <td className="audit-dur">{fmtHours(e.hours)}</td>
                  <td className="audit-saved">${e.saved_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
