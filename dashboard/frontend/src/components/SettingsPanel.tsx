import { useEffect, useState } from 'react'
import type { ConfigData } from '../api'
import { saveConfig } from '../api'
import Toggle from './Toggle'

interface Props {
  config: ConfigData
  onClose: () => void
  onSaved: (cfg: ConfigData) => void
}

type Toast = { msg: string; kind: 'success' | 'error' } | null

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

export default function SettingsPanel({ config, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<ConfigData>({ ...config })
  const [saving, setSaving] = useState(false)
  const [toast, setToast]   = useState<Toast>(null)

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent body scroll while open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const dirty = JSON.stringify(draft) !== JSON.stringify(config)

  function set<K extends keyof ConfigData>(k: K, v: ConfigData[K]) {
    setDraft(d => ({ ...d, [k]: v }))
  }

  const activeDays = new Set(
    draft.business_days.split(',').map(s => s.trim()).filter(Boolean).map(Number)
  )

  function toggleDay(i: number) {
    const next = new Set(activeDays)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    set('business_days', [...next].sort((a, b) => a - b).join(','))
  }

  function showToast(msg: string, kind: 'success' | 'error') {
    setToast({ msg, kind })
    setTimeout(() => setToast(null), 3000)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await saveConfig(draft)
      onSaved(saved)
      showToast('Settings saved', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Save failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />

      <div className="drawer" role="dialog" aria-modal aria-label="Settings">
        {/* ── Header ── */}
        <div className="drawer-header">
          <span className="drawer-title">
            Configuration
            {dirty && <span className="dirty-badge" title="Unsaved changes" />}
          </span>
          <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {/* ── Body ── */}
        <div className="drawer-body">

          {/* Connection */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">🔌</span>
              Connection
            </div>

            <div className="settings-toggle-row">
              <div className="settings-toggle-info">
                <div className="settings-toggle-title">Demo Mode</div>
                <div className="settings-toggle-desc">Synthetic data — no K8s or Prometheus needed</div>
              </div>
              <Toggle checked={draft.demo_mode} onChange={v => set('demo_mode', v)} />
            </div>

            <div className="settings-field" style={{ marginTop: 14 }}>
              <label className="settings-label">Prometheus URL</label>
              <input
                className="settings-input"
                type="url"
                value={draft.prometheus_url}
                disabled={draft.demo_mode}
                onChange={e => set('prometheus_url', e.target.value)}
                placeholder="http://prometheus:9090"
              />
              {draft.demo_mode && (
                <div className="settings-hint">Disabled in demo mode</div>
              )}
            </div>
          </section>

          {/* Cloud & Pricing */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">☁️</span>
              Cloud &amp; Pricing
            </div>

            <div className="settings-field">
              <label className="settings-label">Cloud Provider</label>
              <div className="segmented">
                {(['manual', 'aws', 'gcp'] as const).map(p => (
                  <button
                    key={p}
                    type="button"
                    className={`segmented-btn ${draft.cloud_provider === p ? 'active' : ''}`}
                    onClick={() => set('cloud_provider', p)}
                  >
                    {p === 'manual' ? 'Manual' : p.toUpperCase()}
                  </button>
                ))}
              </div>
              <div className="settings-hint">
                {draft.cloud_provider !== 'manual'
                  ? `Pricing auto-fetched from ${draft.cloud_provider.toUpperCase()} API`
                  : 'Enter a fixed rate below'}
              </div>
            </div>

            {draft.cloud_provider !== 'manual' && (
              <div className="settings-field">
                <label className="settings-label">Instance Type</label>
                <input
                  className="settings-input"
                  value={draft.instance_type}
                  onChange={e => set('instance_type', e.target.value)}
                  placeholder={draft.cloud_provider === 'aws' ? 'm5.xlarge' : 'n2-standard-4'}
                />
              </div>
            )}

            {draft.cloud_provider === 'aws' && (
              <div className="settings-field">
                <label className="settings-label">AWS Region</label>
                <input
                  className="settings-input"
                  value={draft.aws_region}
                  onChange={e => set('aws_region', e.target.value)}
                  placeholder="us-east-1"
                />
              </div>
            )}

            <div className="settings-field">
              <label className="settings-label">Node Hourly Cost (USD)</label>
              <input
                className="settings-input"
                type="number"
                min="0"
                step="0.001"
                value={draft.node_hourly_cost}
                onChange={e => set('node_hourly_cost', parseFloat(e.target.value) || 0)}
              />
              <div className="settings-hint">Fallback when provider pricing is unavailable</div>
            </div>
          </section>

          {/* Schedule */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">🗓</span>
              Schedule
              <span className="settings-controller-note">controller reference</span>
            </div>

            <div className="settings-field">
              <label className="settings-label">Business Hours</label>
              <div className="settings-input-row">
                <input
                  className="settings-input"
                  type="time"
                  value={draft.business_hours_start}
                  onChange={e => set('business_hours_start', e.target.value)}
                />
                <span className="settings-time-sep">to</span>
                <input
                  className="settings-input"
                  type="time"
                  value={draft.business_hours_end}
                  onChange={e => set('business_hours_end', e.target.value)}
                />
              </div>
            </div>

            <div className="settings-field">
              <label className="settings-label">Active Days</label>
              <div className="day-pills">
                {DAYS.map((label, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`day-pill ${activeDays.has(i) ? 'active' : ''}`}
                    onClick={() => toggleDay(i)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-field">
              <label className="settings-label">Timezone</label>
              <input
                className="settings-input"
                value={draft.timezone}
                onChange={e => set('timezone', e.target.value)}
                placeholder="UTC"
              />
              <div className="settings-hint">IANA name — e.g. America/New_York, Europe/London</div>
            </div>

            <div className="settings-field">
              <label className="settings-label">Pre-warm Minutes</label>
              <input
                className="settings-input"
                type="number"
                min="0"
                max="60"
                value={draft.prewarm_minutes}
                onChange={e => set('prewarm_minutes', parseInt(e.target.value) || 0)}
              />
              <div className="settings-hint">Scale-up begins this many minutes before the active window</div>
            </div>
          </section>

          {/* Prediction */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">🔮</span>
              Prediction
            </div>

            <div className="settings-toggle-row">
              <div className="settings-toggle-info">
                <div className="settings-toggle-title">Metric Override</div>
                <div className="settings-toggle-desc">Quiet-day detection via Prometheus baseline</div>
              </div>
              <Toggle
                checked={draft.enable_metric_override}
                onChange={v => set('enable_metric_override', v)}
              />
            </div>

            <div className="settings-toggle-row">
              <div className="settings-toggle-info">
                <div className="settings-toggle-title">Prophet ML Forecasting</div>
                <div className="settings-toggle-desc">Time-series model trained on Prometheus history</div>
              </div>
              <Toggle
                checked={draft.enable_prophet}
                onChange={v => set('enable_prophet', v)}
              />
            </div>

            {draft.enable_prophet && (
              <div className="prophet-sub">
                <div className="settings-field">
                  <label className="settings-label">Training Window (weeks)</label>
                  <input
                    className="settings-input"
                    type="number"
                    min="1"
                    max="52"
                    value={draft.prophet_training_weeks}
                    onChange={e => set('prophet_training_weeks', parseInt(e.target.value) || 4)}
                  />
                  <div className="settings-hint">Requires Prometheus to have this much history</div>
                </div>
                <div className="settings-field">
                  <label className="settings-label">Idle Threshold (cores)</label>
                  <input
                    className="settings-input"
                    type="number"
                    min="0"
                    step="0.1"
                    value={draft.prophet_idle_threshold_cores}
                    onChange={e => set('prophet_idle_threshold_cores', parseFloat(e.target.value) || 0.5)}
                  />
                  <div className="settings-hint">yhat below this → cluster is idle, scale down</div>
                </div>
                <div className="settings-field">
                  <label className="settings-label">Retrain Interval (hours)</label>
                  <input
                    className="settings-input"
                    type="number"
                    min="1"
                    value={draft.prophet_retrain_hours}
                    onChange={e => set('prophet_retrain_hours', parseInt(e.target.value) || 6)}
                  />
                </div>
              </div>
            )}
          </section>

          {/* Dashboard */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">📊</span>
              Dashboard
            </div>

            <div className="settings-field">
              <label className="settings-label">Poll Interval (seconds)</label>
              <input
                className="settings-input"
                type="number"
                min="5"
                max="300"
                value={draft.poll_interval_seconds}
                onChange={e => set('poll_interval_seconds', parseInt(e.target.value) || 30)}
              />
            </div>

            <div className="settings-field">
              <label className="settings-label">Node Utilisation Threshold</label>
              <input
                className="settings-input"
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={draft.node_utilisation_threshold}
                onChange={e => set('node_utilisation_threshold', parseFloat(e.target.value) || 0.1)}
              />
              <div className="settings-hint">Fraction of allocatable CPU below which a node is cordoned</div>
            </div>

            <div className="settings-field">
              <label className="settings-label">Namespace Filter</label>
              <input
                className="settings-input"
                value={draft.namespace_filter}
                onChange={e => set('namespace_filter', e.target.value)}
                placeholder="all namespaces"
              />
            </div>

            <div className="settings-field">
              <label className="settings-label">Min Replica Floor</label>
              <input
                className="settings-input"
                type="number"
                min="0"
                value={draft.min_replica_floor}
                onChange={e => set('min_replica_floor', parseInt(e.target.value) || 0)}
              />
              <div className="settings-hint">Minimum replicas during off-hours (0 = scale to zero)</div>
            </div>
          </section>

        </div>{/* /drawer-body */}

        {/* ── Footer ── */}
        <div className="drawer-footer">
          <button className="btn-ghost" onClick={onClose}>Discard</button>
          <button
            className="btn-primary"
            onClick={handleSave}
            disabled={!dirty || saving}
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`toast toast-${toast.kind}`}>
          <span>{toast.kind === 'success' ? '✓' : '✕'}</span>
          {toast.msg}
        </div>
      )}
    </>
  )
}
