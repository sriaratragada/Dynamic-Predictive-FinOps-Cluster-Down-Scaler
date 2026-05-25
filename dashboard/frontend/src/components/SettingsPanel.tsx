import { useEffect, useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { saveConfig, stopController } from '../api'

interface Props {
  config: ConfigData
  onClose: () => void
  onSaved: (cfg: ConfigData) => void
  controllerStatus?: ControllerStatus | null
  onControllerChange?: (s: ControllerStatus) => void
}

type Toast = { msg: string; kind: 'success' | 'error' } | null

export default function SettingsPanel({ config, onClose, onSaved, controllerStatus, onControllerChange }: Props) {
  const [draft, setDraft] = useState<ConfigData>({ ...config })
  const [saving, setSaving] = useState(false)
  const [toast, setToast]   = useState<Toast>(null)
  const [stopping, setStopping] = useState(false)

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

  function showToast(msg: string, kind: 'success' | 'error') {
    setToast({ msg, kind })
    setTimeout(() => setToast(null), 3000)
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
            Settings
            {dirty && <span className="dirty-badge" title="Unsaved changes" />}
          </span>
          <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {/* ── Body ── */}
        <div className="drawer-body">

          {/* ── Controller status (compact, shown when connected) ── */}
          {controllerStatus?.connected && (
            <div className="settings-ctrl-status">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                <span className={`settings-ctrl-dot settings-ctrl-dot--${controllerStatus.running ? 'running' : 'stopped'}`} />
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-2)' }}>
                  {controllerStatus.running ? 'Controller running' : 'Controller stopped'}
                </span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  · {controllerStatus.cluster_host}
                </span>
              </div>
              <button
                className="btn-ghost"
                style={{ padding: '3px 10px', fontSize: 11, flexShrink: 0 }}
                disabled={stopping}
                onClick={handleStop}
              >
                {stopping ? '…' : 'Stop'}
              </button>
            </div>
          )}

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
