import { useCallback, useEffect, useState } from 'react'
import { fetchStatus, fetchCapacity, fetchHistory, fetchSavings, fetchConfig, fetchEvents, fetchControllerStatus, subscribeToStream } from './api'
import type { StatusData, CapacityData, HistoryData, SavingsData, ConfigData, EventsData, ControllerStatus } from './api'
import MetricsBar          from './components/MetricsBar'
import NodeTopology        from './components/NodeTopology'
import DemandCapacityChart from './components/DemandCapacityChart'
import SettingsPanel       from './components/SettingsPanel'
import AuditLog            from './components/AuditLog'
import DashboardConfig     from './components/DashboardConfig'
import Nav                 from './components/Nav'
import ClusterPage         from './components/ClusterPage'
import FeaturesPage        from './components/FeaturesPage'
import PoliciesPage        from './components/PoliciesPage'
import CommandBar          from './components/CommandBar'
import OnboardingBanner    from './components/OnboardingBanner'
import type { Page }       from './components/Nav'
import { usePrewarm }      from './hooks/usePrewarm'

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
  prophet_shadow_mode:          false,
  poll_interval_seconds:        30,
  node_utilisation_threshold:   0.10,
  namespace_filter:             '',
  min_replica_floor:            0,
  enable_prewarm:               false,
  prewarm_service_url:          '',
  openai_api_key_set:           false,
  openai_base_url:              'https://api.openai.com/v1',
  enable_hpa_synergy:           false,
  hpa_spike_headroom_pct:       30,
  hpa_spike_lookahead_minutes:  15,
  enable_spot_migration:        false,
  spot_max_price_pct:           80,
  spot_eligible_label:          'finops.io/priority=low',
  override_mode:                '',
  override_until:               '',
  exclude_deployments:          '',
  dry_run:                      false,
  webhook_url:                  '',
}

export default function App() {
  const [page,     setPage]     = useState<Page>('controller')
  const [status,   setStatus]   = useState<StatusData | null>(null)
  const [capacity, setCapacity] = useState<CapacityData | null>(null)
  const [history,  setHistory]  = useState<HistoryData | null>(null)
  const [savings,  setSavings]  = useState<SavingsData | null>(null)
  const [events,   setEvents]   = useState<EventsData | null>(null)
  const [config,   setConfig]   = useState<ConfigData>(DEFAULT_CONFIG)
  const [error,    setError]    = useState<string | null>(null)
  const [historyHours,  setHistoryHours]  = useState(24)
  const [lastUpdated,   setLastUpdated]   = useState<Date | null>(null)
  const [settingsOpen,  setSettingsOpen]  = useState(false)
  const [controllerStatus, setControllerStatus] = useState<ControllerStatus | null>(null)

  usePrewarm(config.enable_prewarm, config.prewarm_service_url)

  const pollInterval = config.poll_interval_seconds * 1000

  // One-time fetches on mount (SSE takes over status/controller after first push)
  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {/* keep DEFAULT_CONFIG */})
    fetchStatus().then(setStatus).catch(() => {})
    fetchControllerStatus().then(setControllerStatus).catch(() => {})
  }, [])

  // Full refresh for heavy data only — status and controller come via SSE
  const refresh = useCallback(async (hours = historyHours) => {
    try {
      const [c, h, sv, ev] = await Promise.all([
        fetchCapacity(), fetchHistory(hours), fetchSavings(), fetchEvents(),
      ])
      setCapacity(c); setHistory(h); setSavings(sv); setEvents(ev)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch data')
    }
  }, [historyHours])

  // SSE — real-time status, controller, and savings summary; drives lastUpdated
  useEffect(() => {
    const close = subscribeToStream(
      (payload) => {
        if (payload.status) setStatus(payload.status)
        if (payload.controller) setControllerStatus(payload.controller)
        setLastUpdated(new Date())
        setError(null)
      },
      () => {
        // SSE dropped — mark stale so the user notices, polling will still refresh heavy data
        setError('Live stream disconnected — reconnecting...')
      },
    )
    return close
  }, [])

  // Polling fallback for heavy data (capacity, history, events, full savings)
  useEffect(() => {
    refresh()
    const id = setInterval(() => refresh(), pollInterval)
    return () => clearInterval(id)
  }, [refresh, pollInterval])

  const handleHoursChange  = (h: number) => { setHistoryHours(h); refresh(h) }
  const handleConfigSaved  = (cfg: ConfigData) => { setConfig(cfg); refresh() }

  const clusterUtil  = capacity?.cluster_utilisation_pct ?? 0
  const clusterColor = clusterUtil >= 80 ? 'var(--red)' : clusterUtil >= 50 ? 'var(--amber)' : 'var(--green)'
  const scaled       = status?.scaled_down ?? false

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
          <div className="header-logo-mark">FINOPS<span>/</span>SCALER</div>
          <div className="header-logo-sub">dynamic predictive down-scaler</div>
        </div>

        {status && (
          <div className={`header-badge header-badge--${scaled ? 'idle' : 'active'}`}>
            <span style={{ fontSize: 7 }}>●</span>
            {scaled ? 'HIBERNATING' : 'ACTIVE'}
          </div>
        )}

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
          <button className="settings-btn" onClick={() => setSettingsOpen(true)} aria-label="Settings">
            ⚙ Settings
          </button>
        </div>
      </header>

      {/* ── Navigation ── */}
      <Nav
        page={page}
        onChange={setPage}
        config={config}
        controllerStatus={controllerStatus}
      />

      {/* ── Error banner ── */}
      {error && <div className="error-banner">{error}</div>}

      {/* ══════════════════════════════════════════════
          PAGE: Controller
      ══════════════════════════════════════════════ */}
      {page === 'controller' && (
        <div key="controller">
          <OnboardingBanner
            config={config}
            controllerStatus={controllerStatus}
            onNavigate={p => setPage(p as Page)}
          />

          <MetricsBar savings={savings} status={status} />

          <CommandBar
            config={config}
            status={status}
            controllerStatus={controllerStatus}
            onControllerChange={s => { setControllerStatus(s); refresh() }}
            onConfigSaved={handleConfigSaved}
          />

          <DashboardConfig
            config={config}
            status={status}
            onSaved={handleConfigSaved}
          />

          <div data-reveal="2">
            <div className="section-label">Node Topology</div>
            <NodeTopology capacity={capacity} status={status} savings={savings} />
          </div>

          <div data-reveal="3" style={{ marginTop: 20 }}>
            <DemandCapacityChart
              history={history}
              hours={historyHours}
              onHoursChange={handleHoursChange}
            />
          </div>

          <div data-reveal="4" style={{ marginTop: 20 }}>
            <AuditLog events={events} />
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════
          PAGE: Cluster
      ══════════════════════════════════════════════ */}
      {page === 'cluster' && (
        <div key="cluster" style={{ paddingTop: 24 }}>
          <ClusterPage
            config={config}
            controllerStatus={controllerStatus}
            onConnected={s => { setControllerStatus(s); refresh(); setPage('controller') }}
            onConfigChange={setConfig}
            onControllerChange={s => { setControllerStatus(s); refresh() }}
          />
        </div>
      )}

      {/* ══════════════════════════════════════════════
          PAGE: Features
      ══════════════════════════════════════════════ */}
      {page === 'features' && (
        <div key="features" style={{ paddingTop: 24 }}>
          <FeaturesPage config={config} onSaved={handleConfigSaved} />
        </div>
      )}

      {/* ══════════════════════════════════════════════
          PAGE: Policies (CRD)
      ══════════════════════════════════════════════ */}
      {page === 'policies' && (
        <div key="policies" style={{ paddingTop: 24 }}>
          <PoliciesPage />
        </div>
      )}

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
