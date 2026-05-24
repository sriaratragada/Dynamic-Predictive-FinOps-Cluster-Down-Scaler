import { useCallback, useEffect, useState } from 'react'
import { fetchStatus, fetchCapacity, fetchHistory, fetchSavings, fetchConfig, fetchEvents } from './api'
import type { StatusData, CapacityData, HistoryData, SavingsData, ConfigData, EventsData } from './api'
import MetricsBar      from './components/MetricsBar'
import NodeTopology    from './components/NodeTopology'
import DemandCapacityChart from './components/DemandCapacityChart'
import SettingsPanel   from './components/SettingsPanel'
import DemoBanner      from './components/DemoBanner'
import AuditLog        from './components/AuditLog'

const DEFAULT_POLL_MS = 30_000

export default function App() {
  const [status,   setStatus]   = useState<StatusData | null>(null)
  const [capacity, setCapacity] = useState<CapacityData | null>(null)
  const [history,  setHistory]  = useState<HistoryData | null>(null)
  const [savings,  setSavings]  = useState<SavingsData | null>(null)
  const [events,   setEvents]   = useState<EventsData | null>(null)
  const [config,   setConfig]   = useState<ConfigData | null>(null)
  const [error,    setError]    = useState<string | null>(null)
  const [historyHours,  setHistoryHours]  = useState(24)
  const [lastUpdated,   setLastUpdated]   = useState<Date | null>(null)
  const [settingsOpen,  setSettingsOpen]  = useState(false)

  const pollInterval = config ? config.poll_interval_seconds * 1000 : DEFAULT_POLL_MS

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {/* use defaults */})
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
      {config?.demo_mode && (
        <DemoBanner onOpenSettings={() => setSettingsOpen(true)} />
      )}

      {/* ── Error ── */}
      {error && <div className="error-banner">{error}</div>}

      {/* ── Metrics Bar ── */}
      <MetricsBar savings={savings} status={status} />

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
      {settingsOpen && config && (
        <SettingsPanel
          config={config}
          onClose={() => setSettingsOpen(false)}
          onSaved={handleConfigSaved}
        />
      )}
    </div>
  )
}
