import { useEffect, useState, useCallback } from 'react'
import { fetchStatus, fetchCapacity, fetchHistory, fetchSavings } from './api'
import type { StatusData, CapacityData, HistoryData, SavingsData } from './api'
import StatusPanel from './components/StatusPanel'
import DollarsSavedPanel from './components/DollarsSavedPanel'
import DemandCapacityChart from './components/DemandCapacityChart'
import NodeTable from './components/NodeTable'

const POLL_INTERVAL = 30_000

export default function App() {
  const [status, setStatus]     = useState<StatusData | null>(null)
  const [capacity, setCapacity] = useState<CapacityData | null>(null)
  const [history, setHistory]   = useState<HistoryData | null>(null)
  const [savings, setSavings]   = useState<SavingsData | null>(null)
  const [error, setError]       = useState<string | null>(null)
  const [historyHours, setHistoryHours] = useState(24)
  const [lastUpdated, setLastUpdated]   = useState<Date | null>(null)

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
    const id = setInterval(() => refresh(), POLL_INTERVAL)
    return () => clearInterval(id)
  }, [refresh])

  const handleHoursChange = (h: number) => {
    setHistoryHours(h)
    refresh(h)
  }

  const mode = status
    ? status.scaled_down
      ? 'idle'
      : 'active'
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
    </div>
  )
}
