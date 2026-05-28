import { useState, useEffect } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { wakeCluster, sleepCluster, saveConfig, exportSavings } from '../api'

interface Props {
  config: ConfigData
  status: { scaled_down: boolean } | null
  controllerStatus: ControllerStatus | null
  onControllerChange: (s: ControllerStatus) => void
  onConfigSaved: (c: ConfigData) => void
}

const OVERRIDE_PRESETS = [
  { label: '1 hour', hours: 1 },
  { label: '4 hours', hours: 4 },
  { label: 'Tomorrow 7am', getDate: () => {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    d.setHours(7, 0, 0, 0)
    return d
  }},
  { label: 'Monday 7am', getDate: () => {
    const d = new Date()
    const day = d.getDay()
    const daysUntilMon = day === 0 ? 1 : day === 1 ? 7 : 8 - day
    d.setDate(d.getDate() + daysUntilMon)
    d.setHours(7, 0, 0, 0)
    return d
  }},
  { label: 'Indefinite', hours: 0 },
]

export default function CommandBar({ config, status, controllerStatus, onControllerChange, onConfigSaved }: Props) {
  const [acting, setActing] = useState<string | null>(null)
  const [showOverride, setShowOverride] = useState(false)

  useEffect(() => {
    if (!showOverride) return
    const handler = () => setShowOverride(false)
    const timer = setTimeout(() => document.addEventListener('click', handler), 0)
    return () => { clearTimeout(timer); document.removeEventListener('click', handler) }
  }, [showOverride])

  const connected = controllerStatus?.connected ?? false
  const hibernating = status?.scaled_down ?? false
  const demoMode = config.demo_mode
  const hasOverride = !!config.override_mode
  const isDryRun = config.dry_run

  async function handleWake() {
    if (demoMode) return
    setActing('wake')
    try {
      const s = await wakeCluster()
      onControllerChange(s)
    } catch { /* ignore */ }
    finally { setActing(null) }
  }

  async function handleSleep() {
    if (demoMode) return
    setActing('sleep')
    try {
      const s = await sleepCluster()
      onControllerChange(s)
    } catch { /* ignore */ }
    finally { setActing(null) }
  }

  async function setOverride(mode: 'awake' | 'sleep', preset: typeof OVERRIDE_PRESETS[number]) {
    let until = ''
    if (preset.hours && preset.hours > 0) {
      const d = new Date(Date.now() + preset.hours * 3600_000)
      until = d.toISOString()
    } else if ('getDate' in preset && preset.getDate) {
      until = preset.getDate().toISOString()
    }

    try {
      const saved = await saveConfig({
        ...config,
        override_mode: mode,
        override_until: until,
      })
      onConfigSaved(saved)
    } catch { /* ignore */ }
    setShowOverride(false)
  }

  async function clearOverride() {
    try {
      const saved = await saveConfig({
        ...config,
        override_mode: '',
        override_until: '',
      })
      onConfigSaved(saved)
    } catch { /* ignore */ }
  }

  return (
    <div className="command-bar" data-reveal="1">
      {isDryRun && (
        <div className="command-dry-run-banner">
          <span className="command-dry-run-dot" />
          <span>DRY RUN</span> — Controller is logging actions without executing them.
          <button className="command-dry-run-off" onClick={async () => {
            const saved = await saveConfig({ ...config, dry_run: false })
            onConfigSaved(saved)
          }}>Turn off</button>
        </div>
      )}

      {hasOverride && (
        <div className={`command-override-banner command-override-banner--${config.override_mode}`}>
          <span style={{ fontWeight: 600 }}>
            {config.override_mode === 'awake' ? 'OVERRIDE: Keeping cluster awake' : 'OVERRIDE: Forcing cluster to sleep'}
          </span>
          {config.override_until && (
            <span style={{ opacity: 0.8 }}>
              {' '}until {new Date(config.override_until).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button className="command-override-clear" onClick={clearOverride}>Clear override</button>
        </div>
      )}

      <div className="command-bar-row">
        <div className="command-actions">
          {(connected || demoMode) && (
            <>
              {hibernating ? (
                <button
                  className="command-btn command-btn--wake"
                  onClick={handleWake}
                  disabled={acting !== null || demoMode}
                  title={demoMode ? 'Not available in demo mode' : 'Immediately restore all deployments and uncordon nodes'}
                >
                  {acting === 'wake' ? 'Waking…' : '↑ Wake Now'}
                </button>
              ) : (
                <button
                  className="command-btn command-btn--sleep"
                  onClick={handleSleep}
                  disabled={acting !== null || demoMode}
                  title={demoMode ? 'Not available in demo mode' : 'Immediately scale down and cordon nodes'}
                >
                  {acting === 'sleep' ? 'Sleeping…' : '↓ Sleep Now'}
                </button>
              )}

              <div className="command-override-wrap">
                <button
                  className={`command-btn command-btn--override ${hasOverride ? 'command-btn--override-active' : ''}`}
                  onClick={() => setShowOverride(!showOverride)}
                  disabled={demoMode}
                >
                  {hasOverride ? '⏱ Override active' : '⏱ Override…'}
                </button>
                {showOverride && (
                  <div className="command-override-dropdown" onClick={e => e.stopPropagation()}>
                    <div className="command-override-section">
                      <div className="command-override-title">Keep awake until…</div>
                      {OVERRIDE_PRESETS.map(p => (
                        <button key={`awake-${p.label}`} className="command-override-item" onClick={() => setOverride('awake', p)}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                    <div className="command-override-divider" />
                    <div className="command-override-section">
                      <div className="command-override-title">Force sleep until…</div>
                      {OVERRIDE_PRESETS.map(p => (
                        <button key={`sleep-${p.label}`} className="command-override-item" onClick={() => setOverride('sleep', p)}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                    {hasOverride && (
                      <>
                        <div className="command-override-divider" />
                        <button className="command-override-item command-override-item--clear" onClick={clearOverride}>
                          Clear override
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="command-right">
          <button className="command-link" onClick={exportSavings} title="Download savings history as CSV">
            ↓ Export CSV
          </button>
          <label className="command-dry-toggle" title="Log what the controller would do without actually scaling">
            <input
              type="checkbox"
              checked={config.dry_run}
              onChange={async (e) => {
                const saved = await saveConfig({ ...config, dry_run: e.target.checked })
                onConfigSaved(saved)
              }}
            />
            <span>Dry run</span>
          </label>
        </div>
      </div>
    </div>
  )
}
