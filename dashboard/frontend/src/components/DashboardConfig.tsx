import { useEffect, useRef, useState } from 'react'
import type { ConfigData, StatusData } from '../api'
import { saveConfig } from '../api'

interface Props {
  config:  ConfigData
  status:  StatusData | null
  onSaved: (cfg: ConfigData) => void
}

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
type Toast = { msg: string; kind: 'success' | 'error' } | null

function parseDays(str: string): Set<number> {
  return new Set(str.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)))
}

function getNextEvent(config: ConfigData, status: StatusData | null): string {
  if (!status) return ''
  try {
    const partsArr = new Intl.DateTimeFormat('en-US', {
      timeZone: config.timezone || 'UTC',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(new Date())
    const parts   = Object.fromEntries(partsArr.map(p => [p.type, p.value]))
    const nowMins = parseInt(parts.hour) * 60 + parseInt(parts.minute)

    const [sh, sm] = config.business_hours_start.split(':').map(Number)
    const [eh, em] = config.business_hours_end.split(':').map(Number)
    const startMins = sh * 60 + sm
    const endMins   = eh * 60 + em
    const prewarm   = config.prewarm_minutes ?? 15

    const diff = (target: number) => {
      const d = target > nowMins ? target - nowMins : target + 1440 - nowMins
      const h = Math.floor(d / 60), m = d % 60
      return h > 0 ? `${h}h ${m}m` : `${m}m`
    }

    return status.scaled_down
      ? `scale-up in ${diff(startMins - prewarm)}`
      : `scale-down in ${diff(endMins)}`
  } catch { return '' }
}

export default function DashboardConfig({ config, status, onSaved }: Props) {
  const [draft,   setDraft]   = useState<ConfigData>({ ...config })
  const [saving,  setSaving]  = useState(false)
  const [toast,   setToast]   = useState<Toast>(null)
  const savedRef = useRef(config)

  // Sync draft when config changes externally (e.g. ConnectCard), but not if user has edits
  useEffect(() => {
    const isDirty = JSON.stringify(draft) !== JSON.stringify(savedRef.current)
    if (!isDirty) setDraft({ ...config })
    savedRef.current = config
  }, [config]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty      = JSON.stringify(draft) !== JSON.stringify(config)
  const activeDays = parseDays(draft.business_days)
  const next       = getNextEvent(config, status)
  const hibernating = status?.scaled_down ?? false

  function set<K extends keyof ConfigData>(k: K, v: ConfigData[K]) {
    setDraft(d => ({ ...d, [k]: v }))
  }

  function toggleDay(i: number) {
    const next = new Set(activeDays)
    next.has(i) ? next.delete(i) : next.add(i)
    set('business_days', [...next].sort((a, b) => a - b).join(','))
  }

  function showToast(msg: string, kind: 'success' | 'error') {
    setToast({ msg, kind })
    setTimeout(() => setToast(null), 2500)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await saveConfig(draft)
      onSaved(saved)
      showToast('Configuration saved', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Save failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="dash-config" data-reveal="1">

        {/* ── Status bar ── */}
        {status && (
          <div className="dash-config-status">
            <div className={`dash-config-state dash-config-state--${hibernating ? 'idle' : 'active'}`}>
              <span className="dash-config-state-dot" />
              {hibernating ? 'HIBERNATING' : 'ACTIVE'}
            </div>
            {next && (
              <span className="dash-config-next">{next}</span>
            )}
            {dirty && (
              <span className="dash-config-dirty-pill">● unsaved</span>
            )}
          </div>
        )}

        {/* ── 3-column config grid ── */}
        <div className="dash-config-grid dash-config-grid--2col">

          {/* ── Schedule ── */}
          <div className="dash-config-section">
            <div className="dash-config-header">
              <span className="dash-config-tag">// SCHED</span>
              <span className="dash-config-title">Schedule</span>
            </div>

            <div className="dash-config-field">
              <div className="dash-config-label">Active days</div>
              <div className="dash-day-pills">
                {DAYS.map((label, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`dash-day-pill ${activeDays.has(i) ? 'active' : ''}`}
                    onClick={() => toggleDay(i)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="dash-config-field">
              <div className="dash-config-label">Business hours</div>
              <div className="dash-time-row">
                <input
                  className="dash-time-input"
                  type="time"
                  value={draft.business_hours_start}
                  onChange={e => set('business_hours_start', e.target.value)}
                />
                <span className="dash-time-sep">→</span>
                <input
                  className="dash-time-input"
                  type="time"
                  value={draft.business_hours_end}
                  onChange={e => set('business_hours_end', e.target.value)}
                />
              </div>
            </div>

            <div className="dash-config-field">
              <div className="dash-config-label">Timezone</div>
              <input
                className="dash-config-input"
                value={draft.timezone}
                onChange={e => set('timezone', e.target.value)}
                placeholder="UTC"
                spellCheck={false}
              />
            </div>

            <div className="dash-config-field">
              <div className="dash-config-label">Pre-warm (min)</div>
              <input
                className="dash-config-input dash-config-input--short"
                type="number"
                min="0"
                max="60"
                value={draft.prewarm_minutes}
                onChange={e => set('prewarm_minutes', parseInt(e.target.value) || 0)}
              />
            </div>
          </div>

          <div className="dash-config-divider" />

          {/* ── Cloud & Pricing ── */}
          <div className="dash-config-section">
            <div className="dash-config-header">
              <span className="dash-config-tag">// CLOUD</span>
              <span className="dash-config-title">Cloud &amp; Pricing</span>
            </div>

            <div className="dash-config-field">
              <div className="dash-config-label">Provider</div>
              <div className="dash-segmented">
                {(['manual', 'aws', 'gcp'] as const).map(p => (
                  <button
                    key={p}
                    type="button"
                    className={`dash-segmented-btn ${draft.cloud_provider === p ? 'active' : ''}`}
                    onClick={() => set('cloud_provider', p)}
                  >
                    {p === 'manual' ? 'Manual' : p.toUpperCase()}
                  </button>
                ))}
              </div>
              <div className="dash-config-hint">
                {draft.cloud_provider !== 'manual'
                  ? `Pricing fetched from ${draft.cloud_provider.toUpperCase()} API`
                  : 'Enter a fixed rate below'}
              </div>
            </div>

            {draft.cloud_provider !== 'manual' && (
              <div className="dash-config-field">
                <div className="dash-config-label">Instance type</div>
                <input
                  className="dash-config-input"
                  value={draft.instance_type}
                  onChange={e => set('instance_type', e.target.value)}
                  placeholder={draft.cloud_provider === 'aws' ? 'm5.xlarge' : 'n2-standard-4'}
                />
              </div>
            )}

            {draft.cloud_provider === 'aws' && (
              <div className="dash-config-field">
                <div className="dash-config-label">AWS region</div>
                <input
                  className="dash-config-input"
                  value={draft.aws_region}
                  onChange={e => set('aws_region', e.target.value)}
                  placeholder="us-east-1"
                />
              </div>
            )}

            <div className="dash-config-field">
              <div className="dash-config-label">Node cost ($/hr)</div>
              <input
                className="dash-config-input dash-config-input--short"
                type="number"
                min="0"
                step="0.001"
                value={draft.node_hourly_cost}
                onChange={e => set('node_hourly_cost', parseFloat(e.target.value) || 0)}
              />
              <div className="dash-config-hint">Fallback when provider pricing unavailable</div>
            </div>
          </div>

        </div>{/* /dash-config-grid */}

        {/* ── Save bar — appears when dirty ── */}
        {dirty && (
          <div className="dash-config-save-bar">
            <button
              className="btn-ghost"
              style={{ padding: '6px 16px', fontSize: 12 }}
              onClick={() => setDraft({ ...config })}
            >
              Discard
            </button>
            <button
              className="btn-primary"
              style={{ padding: '6px 20px', fontSize: 12 }}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>

      {toast && (
        <div className={`toast toast-${toast.kind}`}>
          <span>{toast.kind === 'success' ? '✓' : '✕'}</span>
          {toast.msg}
        </div>
      )}
    </>
  )
}
