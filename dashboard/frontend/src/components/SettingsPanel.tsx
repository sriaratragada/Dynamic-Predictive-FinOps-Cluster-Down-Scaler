import { useEffect, useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { connectCluster, fetchControllerStatus, saveConfig, stopController } from '../api'
import Toggle from './Toggle'

interface Props {
  config: ConfigData
  onClose: () => void
  onSaved: (cfg: ConfigData) => void
  controllerStatus?: ControllerStatus | null
  onControllerChange?: (s: ControllerStatus) => void
}

type Toast = { msg: string; kind: 'success' | 'error' } | null

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

export default function SettingsPanel({ config, onClose, onSaved, controllerStatus, onControllerChange }: Props) {
  const [draft, setDraft] = useState<ConfigData>({ ...config })
  const [saving, setSaving] = useState(false)
  const [toast, setToast]   = useState<Toast>(null)
  const [kubeconfig,  setKubeconfig]  = useState('')
  const [connecting,  setConnecting]  = useState(false)
  const [stopping,    setStopping]    = useState(false)

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

  async function handleConnect() {
    if (!kubeconfig.trim()) return
    setConnecting(true)
    try {
      const status = await connectCluster(kubeconfig.trim())
      onControllerChange?.(status)
      showToast('Connected — controller loop started', 'success')
      setKubeconfig('')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Connection failed', 'error')
    } finally {
      setConnecting(false)
    }
  }

  async function handleStop() {
    setStopping(true)
    try {
      const status = await stopController()
      onControllerChange?.(status)
      showToast('Controller loop stopped', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Stop failed', 'error')
    } finally {
      setStopping(false)
    }
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

          {/* Cluster Connect */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// CLUSTER</span>
              Cluster Connection
            </div>

            {/* Status row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 9,
                  fontWeight: 600,
                  letterSpacing: 1,
                  padding: '2px 8px',
                  borderRadius: 2,
                  border: '1px solid',
                  ...(controllerStatus?.connected
                    ? { color: 'var(--green)', borderColor: 'rgba(48,209,88,0.35)', background: 'var(--green-dim)' }
                    : { color: 'var(--text-3)', borderColor: 'var(--border)', background: 'var(--surface-2)' }),
                }}
              >
                {controllerStatus?.connected ? '● CONNECTED' : '○ DISCONNECTED'}
              </span>
              {controllerStatus?.connected && (
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                  {controllerStatus.cluster_host}
                </span>
              )}
            </div>

            {controllerStatus?.connected ? (
              <>
                <div className="settings-toggle-row" style={{ paddingTop: 4, paddingBottom: 4 }}>
                  <div className="settings-toggle-info">
                    <div className="settings-toggle-title">Controller Loop</div>
                    <div className="settings-toggle-desc">
                      {controllerStatus.running
                        ? `Running · last tick ${controllerStatus.last_tick ? new Date(controllerStatus.last_tick).toLocaleTimeString() : 'never'}`
                        : `Stopped · last action: ${controllerStatus.last_action}`}
                    </div>
                    {controllerStatus.error && (
                      <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 3, fontFamily: "'JetBrains Mono', monospace" }}>
                        {controllerStatus.error}
                      </div>
                    )}
                  </div>
                  <button
                    className="btn-ghost"
                    style={{ padding: '4px 12px', fontSize: 11, flexShrink: 0 }}
                    disabled={stopping}
                    onClick={handleStop}
                  >
                    {stopping ? 'Stopping…' : 'Stop Loop'}
                  </button>
                </div>
                <div className="settings-hint" style={{ marginTop: 8 }}>
                  To connect a different cluster, paste a new kubeconfig below and click Connect.
                </div>
              </>
            ) : (
              <div className="settings-hint" style={{ marginBottom: 10 }}>
                Paste your <code style={{ fontFamily: "'JetBrains Mono', monospace", background: 'var(--surface-3)', padding: '1px 4px', borderRadius: 2 }}>~/.kube/config</code> to activate the live controller loop.
                The schedule, scale-down targets, and all other settings below are applied immediately.
              </div>
            )}

            <div className="settings-field">
              <label className="settings-label">kubeconfig YAML</label>
              <textarea
                className="settings-input"
                rows={6}
                value={kubeconfig}
                onChange={e => setKubeconfig(e.target.value)}
                placeholder={"apiVersion: v1\nkind: Config\nclusters:\n- cluster:\n    server: https://...\n  name: my-cluster\n..."}
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, resize: 'vertical', lineHeight: 1.5 }}
              />
              <div className="settings-hint">
                Credentials are used only for direct Kubernetes API calls — never stored on disk or sent anywhere else.
              </div>
            </div>

            <button
              className="btn-primary"
              style={{ width: '100%', marginTop: 8 }}
              disabled={!kubeconfig.trim() || connecting}
              onClick={handleConnect}
            >
              {connecting ? 'Connecting…' : controllerStatus?.connected ? 'Reconnect' : 'Validate & Connect'}
            </button>
          </section>

          {/* Connection */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// CONN</span>
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
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
              />
              {draft.demo_mode && (
                <div className="settings-hint">Disabled in demo mode</div>
              )}
            </div>
          </section>

          {/* Cloud & Pricing */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// CLOUD</span>
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
              <span className="settings-section-icon">// SCHED</span>
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
              <span className="settings-section-icon">// PRED</span>
              Prediction
            </div>

            <div className="settings-toggle-row">
              <div className="settings-toggle-info">
                <div className="settings-toggle-title">AI Pre-Warm Engine</div>
                <div className="settings-toggle-desc">
                  Boot Knative AI containers on user-intent signals — eliminates cold-start delay.
                  Enable only on high-conversion AI feature pages.
                </div>
              </div>
              <Toggle
                checked={draft.enable_prewarm}
                onChange={v => set('enable_prewarm', v)}
              />
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
              <span className="settings-section-icon">// UI</span>
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
              <label className="settings-label">Node Utilisation Threshold (%)</label>
              <input
                className="settings-input"
                type="number"
                min="0"
                max="100"
                step="1"
                value={Math.round(draft.node_utilisation_threshold * 100)}
                onChange={e => set('node_utilisation_threshold', (parseFloat(e.target.value) || 10) / 100)}
              />
              <div className="settings-hint">Nodes below this CPU % are eligible for cordoning</div>
            </div>

            <div className="settings-field">
              <label className="settings-label">Namespace Filter</label>
              <input
                className="settings-input"
                value={draft.namespace_filter}
                onChange={e => set('namespace_filter', e.target.value)}
                placeholder="all namespaces"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
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
