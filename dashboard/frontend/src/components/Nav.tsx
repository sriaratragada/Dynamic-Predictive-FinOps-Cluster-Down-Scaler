import type { ConfigData, ControllerStatus } from '../api'

export type Page = 'controller' | 'cluster' | 'features'

interface Props {
  page:             Page
  onChange:         (p: Page) => void
  config:           ConfigData
  controllerStatus: ControllerStatus | null
}

export default function Nav({ page, onChange, config, controllerStatus }: Props) {
  const connected  = controllerStatus?.connected ?? false
  const demoMode   = config.demo_mode
  const anyFeature = config.enable_prewarm || config.enable_metric_override || config.enable_prophet

  return (
    <nav className="app-nav">
      <button
        className={`nav-tab ${page === 'controller' ? 'nav-tab--active' : ''}`}
        onClick={() => onChange('controller')}
      >
        <span className="nav-tab-tag">// MAIN</span>
        <span className="nav-tab-label">Controller</span>
      </button>

      <button
        className={`nav-tab ${page === 'cluster' ? 'nav-tab--active' : ''}`}
        onClick={() => onChange('cluster')}
      >
        <span className="nav-tab-tag">// CONN</span>
        <span className="nav-tab-label">Cluster</span>
        {demoMode ? (
          <span className="nav-tab-badge nav-tab-badge--demo">DEMO</span>
        ) : connected ? (
          <span className="nav-tab-dot nav-tab-dot--connected" />
        ) : (
          <span className="nav-tab-dot nav-tab-dot--disconnected" />
        )}
      </button>

      <button
        className={`nav-tab ${page === 'features' ? 'nav-tab--active' : ''}`}
        onClick={() => onChange('features')}
      >
        <span className="nav-tab-tag">// AI/ML</span>
        <span className="nav-tab-label">Features</span>
        {anyFeature && <span className="nav-tab-dot nav-tab-dot--feature" />}
      </button>

      {/* Right: cluster status chip */}
      <div className="nav-status-chip">
        {demoMode ? (
          <span className="nav-chip nav-chip--demo">
            <span className="nav-chip-dot" />
            DEMO MODE
          </span>
        ) : connected && controllerStatus ? (
          <span className={`nav-chip nav-chip--${controllerStatus.running ? 'live' : 'stopped'}`}>
            <span className="nav-chip-dot" />
            {controllerStatus.running ? controllerStatus.cluster_host : 'STOPPED'}
          </span>
        ) : (
          <span className="nav-chip nav-chip--offline">
            <span className="nav-chip-dot" />
            NOT CONNECTED
          </span>
        )}
      </div>
    </nav>
  )
}
