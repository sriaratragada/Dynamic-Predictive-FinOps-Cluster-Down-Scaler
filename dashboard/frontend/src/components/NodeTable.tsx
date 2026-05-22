import type { CapacityData, SavingsData } from '../api'

interface Props {
  capacity: CapacityData | null
  savings: SavingsData | null
}

function utilizationClass(pct: number) {
  if (pct >= 80) return 'fill-red'
  if (pct >= 50) return 'fill-amber'
  return 'fill-green'
}

function fmtCores(n: number) {
  return n.toFixed(2)
}

export default function NodeTable({ capacity, savings }: Props) {
  const nodes = capacity?.nodes ?? []
  const hourlyRate = savings?.hourly_rate_per_node ?? 0

  return (
    <div className="panel">
      <div className="panel-title">Node Details</div>

      {nodes.length === 0 ? (
        <div className="empty-state">No node data available</div>
      ) : (
        <>
          <div style={{ marginBottom: 10, fontSize: 12, color: 'var(--muted)' }}>
            Cluster: {capacity!.total_used_cores.toFixed(1)} / {capacity!.total_allocatable_cores.toFixed(1)} cores
            &nbsp;({capacity!.cluster_utilisation_pct.toFixed(1)}% utilised)
          </div>
          <table className="node-table">
            <thead>
              <tr>
                <th>Node</th>
                <th>CPU Usage</th>
                <th>Allocatable</th>
                <th>Utilisation</th>
                <th>Status</th>
                <th>Savings Rate</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map(node => (
                <tr key={node.name} className={node.cordoned ? 'cordoned' : ''}>
                  <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{node.name}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div className="progress-bar">
                        <div
                          className={`progress-fill ${utilizationClass(node.utilisation_pct)}`}
                          style={{ width: `${Math.min(node.utilisation_pct, 100)}%` }}
                        />
                      </div>
                      <span style={{ fontSize: 12, color: 'var(--muted)', minWidth: 60 }}>
                        {fmtCores(node.used_cpu_cores)} cores
                      </span>
                    </div>
                  </td>
                  <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                    {fmtCores(node.allocatable_cpu_cores)} cores
                  </td>
                  <td>
                    <span style={{
                      color: node.utilisation_pct >= 80
                        ? 'var(--red)'
                        : node.utilisation_pct >= 50
                          ? 'var(--amber)'
                          : 'var(--green)',
                      fontWeight: 600,
                      fontSize: 13,
                    }}>
                      {node.utilisation_pct.toFixed(1)}%
                    </span>
                  </td>
                  <td>
                    <span className={`status-indicator ${node.cordoned ? 'dot-amber' : 'dot-green'}`}>
                      <span className={`dot ${node.cordoned ? 'dot-amber' : 'dot-green'}`} />
                      {node.cordoned ? 'Cordoned' : 'Ready'}
                    </span>
                  </td>
                  <td style={{ color: node.cordoned ? 'var(--green)' : 'var(--muted)', fontSize: 12 }}>
                    {node.cordoned && hourlyRate > 0
                      ? `$${hourlyRate.toFixed(3)}/hr saved`
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
