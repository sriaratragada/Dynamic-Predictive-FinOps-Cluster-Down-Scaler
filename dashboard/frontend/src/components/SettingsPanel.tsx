import { useEffect, useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { saveConfig, stopController } from '../api'
import NLConfigBar from './NLConfigBar'

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
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [savingKey, setSavingKey] = useState(false)

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

  async function handleApiKeyBlur() {
    if (!apiKeyInput) return
    setSavingKey(true)
    try {
      const saved = await saveConfig({ openai_api_key: apiKeyInput } as Partial<ConfigData> as ConfigData)
      onSaved(saved)
      setApiKeyInput('')
      showToast('API key saved', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to save API key', 'error')
    } finally {
      setSavingKey(false)
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

          {/* ── Natural-Language Config ── */}
          <NLConfigBar config={draft} onSaved={onSaved} />

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

          {/* Safelist */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// SAFE</span>
              App Safelist
            </div>
            <div className="settings-field">
              <label className="settings-label">Never scale down these deployments</label>
              <textarea
                className="settings-input"
                rows={3}
                value={draft.exclude_deployments}
                onChange={e => set('exclude_deployments', e.target.value)}
                placeholder="namespace/deployment-name, one per line or comma-separated"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, resize: 'vertical' }}
              />
              <div className="settings-hint">
                Comma-separated list. Use "namespace/name" for specific deployments or just "name" to match across all namespaces.
              </div>
            </div>
          </section>

          {/* LLM */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// LLM</span>
              Language Model
            </div>

            <div className="settings-field">
              <label className="settings-label">OpenAI API Key</label>
              <input
                className="settings-input"
                type="password"
                placeholder={draft.openai_api_key_set ? '••••••••  (key set)' : 'sk-...'}
                value={apiKeyInput}
                onChange={e => setApiKeyInput(e.target.value)}
                onBlur={handleApiKeyBlur}
                disabled={savingKey}
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
              />
              <div className="settings-hint">
                {draft.openai_api_key_set
                  ? 'API key is configured. Paste a new key to replace it.'
                  : 'Required for natural-language configuration. Saved immediately on blur.'}
              </div>
            </div>

            <div className="settings-field">
              <label className="settings-label">OpenAI Base URL</label>
              <input
                className="settings-input"
                value={draft.openai_base_url}
                onChange={e => set('openai_base_url', e.target.value)}
                placeholder="https://api.openai.com/v1"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
              />
              <div className="settings-hint">Override for Azure OpenAI, local LLMs, or compatible endpoints</div>
            </div>
          </section>

          {/* Notifications */}
          <section className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// NOTIFY</span>
              Notifications
            </div>
            <div className="settings-field">
              <label className="settings-label">Webhook URL (Slack-compatible)</label>
              <input
                className="settings-input"
                value={draft.webhook_url}
                onChange={e => set('webhook_url', e.target.value)}
                placeholder="https://hooks.slack.com/services/..."
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
              />
              <div className="settings-hint">
                Receives a JSON POST on every scale-down and scale-up event. Works with Slack Incoming Webhooks, PagerDuty, or any HTTP receiver.
              </div>
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
