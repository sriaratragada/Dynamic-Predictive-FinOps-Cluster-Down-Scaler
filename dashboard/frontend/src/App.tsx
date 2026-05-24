import { useCallback, useEffect, useState } from 'react'
import { fetchStatus, fetchCapacity, fetchHistory, fetchSavings, fetchConfig, fetchEvents, fetchControllerStatus } from './api'
import type { StatusData, CapacityData, HistoryData, SavingsData, ConfigData, EventsData, ControllerStatus } from './api'
import MetricsBar          from './components/MetricsBar'
import NodeTopology        from './components/NodeTopology'
import DemandCapacityChart from './components/DemandCapacityChart'
import SettingsPanel       from './components/SettingsPanel'
import DemoBanner          from './components/DemoBanner'
import AuditLog            from './components/AuditLog'
import ConnectCard         from './components/ConnectCard'
import ScheduleStrip       from './components/ScheduleStrip'

const DEFAULT_CONFIG: ConfigData = {
  prometheus_url:               'http://prometheus:9090',
  demo_mode:                    true,
  cloud_provider:               'manual',
  instance_type:                '',
  aws_region:                   '',
  node_hourly_cost:             0.192,
  business_hours_start:         '07:00',
  business_hours_end:           '19:00',
  business_days:                '0,1,2,3,4',
  timezone:                     'UTC',
  prewarm_minutes:              15,
  enable_metric_override:       false,
  enable_prophet:               false,
  prophet_training_weeks:       4,
  prophet_idle_threshold_cores: 0.5,
  prophet_retrain_hours:        6,
  poll_interval_seconds:        30,
  node_utilisation_threshold:   0.10,
  namespace_filter:             '',
  min_replica_floor:            0,
  enable_prewarm:               false,
}

export default function App() {
  const [status,   setStatus]   = useState<StatusData | null>(null)
  const [capacity, setCapacity] = useState<CapacityData | null>(null)
  const [history,  setHistory]  = useState<HistoryData | null>(null)
  const [savings,  setSavings]  = useState<SavingsData | null>(null)
  const [events,   setEvents]   = useState<EventsData | null>(null)
  const [config,   setConfig]   = useState<ConfigData>(DEFAULT_CONFIG)
  const [error,    setError]    = useState<string | null>(null)
  const [historyHours,  setHistoryHours]  = useState(24)
  const [lastUpdated,   setLastUpdated]   = useState<Date | null>(null)
  const [settingsOpen,       setSettingsOpen]       = useState(false)
  const [controllerStatus,   setControllerStatus]   = useState<ControllerStatus | null>(null)

  const pollInterval = config.poll_interval_seconds * 1000

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {/* keep DEFAULT_CONFIG */})
  }, [])

  const refresh = useCallback(async (hours = historyHours) => {
    try {
      const [s, c, h, sv, ev] = await Promise.all([
        fetchStatus(),
        fetchCapacity(),
        fetchHistory(hours),
        fetchSavings(),
        fetchEvents(),
      ])
      setStatus(s); setCapacity(c); setHistory(h)
      setSavings(sv); setEvents(ev)
      setError(null)
      setLastUpdated(new Date())
      // Poll controller status alongside cluster data
      fetchControllerStatus().then(setControllerStatus).catch(() => {})
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch data')
    }
  }, [historyHours])

  useEffect(() => {
    refresh()
    const id = setInterval(() => refresh(), pollInterval)
    return () => clearInterval(id)
  }, [refresh, pollInterval])

  const handleHoursChange = (h: number) => { setHistoryHours(h); refresh(h) }

  const handleConfigSaved = (cfg: ConfigData) => { setConfig(cfg); refresh() }

  // Cluster utilisation for the header hairline
  const clusterUtil  = capacity?.cluster_utilisation_pct ?? 0
  const clusterColor = clusterUtil >= 80 ? 'var(--red)' : clusterUtil >= 50 ? 'var(--amber)' : 'var(--green)'

  // Header mode badge
  const scaled = status?.scaled_down ?? false
  const modeLabel = scaled ? 'HIBERNATING' : 'ACTIVE'
  const modeCls   = scaled ? 'idle' : 'active'

  return (
    <div
      className="app"
      style={{
        ['--cluster-util'       as string]: `${clusterUtil}%`,
        ['--cluster-util-color' as string]: clusterColor,
      }}
    >
      {/* ── Header ── */}
      <header className="header" data-reveal="0">
        <div className="header-logo">
          <div className="header-logo-mark">
            FINOPS<span>/</span>SCALER
          </div>
          <div className="header-logo-sub">dynamic predictive down-scaler</div>
        </div>

        {status && (
          <div className={`header-badge header-badge--${modeCls}`}>
            <span style={{ fontSize: 7 }}>●</span>
            {modeLabel}
          </div>
        )}

        {/* Controller loop badge — only when connected via web-service mode */}
        {controllerStatus?.connected && (
          <div
            className={`header-badge header-badge--${controllerStatus.running ? 'active' : 'idle'}`}
            title={controllerStatus.cluster_host}
            style={{ cursor: 'default' }}
          >
            <span style={{ fontSize: 7 }}>{controllerStatus.running ? '⟳' : '■'}</span>
            CTRL {controllerStatus.running ? 'RUNNING' : 'STOPPED'}
          </div>
        )}

        <div className="header-meta">
          {lastUpdated && (
            <span className="header-time">
              {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          <div className="live-dot" />
          <button
            className="settings-btn"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
          >
            ⚙ Settings
          </button>
        </div>
      </header>

      {/* ── Demo Banner ── */}
      {config.demo_mode && (
        <DemoBanner onOpenSettings={() => setSettingsOpen(true)} />
      )}

      {/* ── Error ── */}
      {error && <div className="error-banner">{error}</div>}

      {/* ── Connect Card (shown when not in demo mode and not connected) ── */}
      {!config.demo_mode && !controllerStatus?.connected && (
        <ConnectCard
          onConnected={s => { setControllerStatus(s); refresh() }}
        />
      )}

      {/* ── Metrics Bar ── */}
      <MetricsBar savings={savings} status={status} />

      {/* ── Schedule Strip ── */}
      <ScheduleStrip
        config={config}
        status={status}
        onEdit={() => setSettingsOpen(true)}
      />

      {/* ── Node Topology ── */}
      <div data-reveal="2">
        <div className="section-label">Node Topology</div>
        <NodeTopology capacity={capacity} status={status} savings={savings} />
      </div>

      {/* ── Demand / Capacity Chart ── */}
      <div data-reveal="3" style={{ marginTop: 20 }}>
        <DemandCapacityChart
          history={history}
          hours={historyHours}
          onHoursChange={handleHoursChange}
        />
      </div>

      {/* ── Audit Log ── */}
      <div data-reveal="4" style={{ marginTop: 20 }}>
        <AuditLog events={events} />
      </div>

      {/* ── Settings Drawer ── */}
      {settingsOpen && (
        <SettingsPanel
          config={config}
          onClose={() => setSettingsOpen(false)}
          onSaved={handleConfigSaved}
          controllerStatus={controllerStatus}
          onControllerChange={s => { setControllerStatus(s); refresh() }}
        />
      )}
    </div>
  )
}
