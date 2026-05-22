import { useEffect, useState, useCallback } from 'react'
import { fetchStatus, fetchCapacity, fetchHistory, fetchSavings, fetchConfig } from './api'
import type { StatusData, CapacityData, HistoryData, SavingsData, ConfigData } from './api'
import StatusPanel from './components/StatusPanel'
import DollarsSavedPanel from './components/DollarsSavedPanel'
import DemandCapacityChart from './components/DemandCapacityChart'
import NodeTable from './components/NodeTable'
import SettingsPanel from './components/SettingsPanel'

const DEFAULT_POLL_MS = 30_000

export default function App() {
  const [status,   setStatus]   = useState<StatusData | null>(null)
  const [capacity, setCapacity] = useState<CapacityData | null>(null)
  const [history,  setHistory]  = useState<HistoryData | null>(null)
  const [savings,  setSavings]  = useState<SavingsData | null>(null)
  const [config,   setConfig]   = useState<ConfigData | null>(null)
  const [error,    setError]    = useState<string | null>(null)
  const [historyHours, setHistoryHours] = useState(24)
  const [lastUpdated,  setLastUpdated]  = useState<Date | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const pollInterval = config ? config.poll_interval_seconds * 1000 : DEFAULT_POLL_MS

  // Load config once on mount
  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {/* use defaults */})
  }, [])

  const refresh = useCallback(async (hours = historyHours) => {
    try {
      const [s, c, h, sv] = await Promise.all([
        fetchStatus(),
        fetchCapacity(),
        fetchHistory(hours),
        fetchSavings(),
      ])
      setStatus(s)
      setCapacity(c)
      setHistory(h)
      setSavings(sv)
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

  const handleHoursChange = (h: number) => {
    setHistoryHours(h)
    refresh(h)
  }

  const handleConfigSaved = (cfg: ConfigData) => {
    setConfig(cfg)
    // Re-fetch data immediately so savings / provider info reflects the change
    refresh()
  }

  const mode = status
    ? status.scaled_down ? 'idle' : 'active'
    : 'active'

  return (
    <div className="app">
      <header className="header">
        <h1>FinOps Down-Scaler</h1>
        <div className="header-meta">
          {lastUpdated && (
            <span>Updated {lastUpdated.toLocaleTimeString()}</span>
          )}
          <div className="live-dot" />
          <span>Live</span>
          <button
            className="settings-btn"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
          >
            ⚙ Settings
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="grid">
        <div className="status-panel">
          <StatusPanel status={status} mode={mode} />
        </div>
        <div className="savings-panel">
          <DollarsSavedPanel savings={savings} />
        </div>
        <div className="chart-panel">
          <DemandCapacityChart
            history={history}
            hours={historyHours}
            onHoursChange={handleHoursChange}
          />
        </div>
        <div className="table-panel">
          <NodeTable capacity={capacity} savings={savings} />
        </div>
      </div>

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
