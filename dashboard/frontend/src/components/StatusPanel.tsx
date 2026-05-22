import type { StatusData } from '../api'

interface Props {
  status: StatusData | null
  mode: 'active' | 'idle' | 'prewarm'
}

const MODE_LABELS: Record<string, string> = {
  active:  'ACTIVE',
  idle:    'IDLE',
  prewarm: 'PRE-WARMING',
}

export default function StatusPanel({ status, mode }: Props) {
  const modeClass = `mode-badge mode-${mode}`

  return (
    <div className="panel">
      <div className="panel-title">Cluster Status</div>

      <div className={modeClass}>
        <span className="dot" style={{ background: 'currentColor' }} />
        {MODE_LABELS[mode] ?? mode.toUpperCase()}
      </div>

      <div className="status-row">
        <span className="status-label">Scaled down</span>
        <span className="status-value">
          {status ? (status.scaled_down ? 'Yes' : 'No') : '—'}
        </span>
      </div>

      <div className="status-row">
        <span className="status-label">Cordoned nodes</span>
        <span className="status-value">
          {status ? status.cordoned_node_count : '—'}
        </span>
      </div>

      <div className="status-row">
        <span className="status-label">Scaled deployments</span>
        <span className="status-value">
          {status ? status.deployment_count : '—'}
        </span>
      </div>

      {status && status.cordoned_nodes.length > 0 && (
        <div className="node-chips">
          {status.cordoned_nodes.map(n => (
            <span key={n} className="chip chip-amber">{n}</span>
          ))}
        </div>
      )}

      {status && status.deployments_scaled.length > 0 && (
        <div className="node-chips" style={{ marginTop: 10 }}>
          {status.deployments_scaled.map(d => (
            <span key={d.key} className="chip chip-blue">
              {d.key} ({d.original_replicas})
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
