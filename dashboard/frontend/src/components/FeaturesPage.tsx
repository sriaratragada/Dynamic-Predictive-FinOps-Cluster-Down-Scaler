import { useEffect, useState } from 'react'
import type { ConfigData, PrewarmHistoryEntry, PrewarmSnippet, ShadowLogEntry, SpotStatus } from '../api'
import { saveConfig, fetchPrewarmHistory, fetchPrewarmSnippet, fetchShadowLog, fetchSpotStatus } from '../api'
import Toggle from './Toggle'

interface Props {
  config:  ConfigData
  onSaved: (cfg: ConfigData) => void
}

type Toast = { msg: string; kind: 'success' | 'error' } | null

function Pipeline({ steps }: { steps: string[] }) {
  return (
    <div className="feature-pipeline">
      {steps.map((step, i) => (
        <span key={i} className="feature-pipeline-wrap">
          <span className="feature-pipeline-step">{step}</span>
          {i < steps.length - 1 && <span className="feature-pipeline-arrow">→</span>}
        </span>
      ))}
    </div>
  )
}

export default function FeaturesPage({ config, onSaved }: Props) {
  const [draft,  setDraft]  = useState<ConfigData>({ ...config })
  const [saving, setSaving] = useState<string | null>(null)
  const [toast,  setToast]  = useState<Toast>(null)
  const [spotStatus, setSpotStatus] = useState<SpotStatus | null>(null)
  const [snippet, setSnippet] = useState<PrewarmSnippet | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (draft.enable_spot_migration) {
      fetchSpotStatus().then(setSpotStatus).catch(() => {})
    }
  }, [draft.enable_spot_migration])
  const [prewarmHistory, setPrewarmHistory] = useState<PrewarmHistoryEntry[]>([])
  const [shadowLog, setShadowLog] = useState<ShadowLogEntry[]>([])

  useEffect(() => {
    if (!draft.enable_prewarm) return
    const load = () => { fetchPrewarmHistory().then(d => setPrewarmHistory(d.history)).catch(() => {}) }
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [draft.enable_prewarm])

  useEffect(() => {
    if (!draft.enable_prewarm || !draft.prewarm_service_url) return
    fetchPrewarmSnippet().then(setSnippet).catch(() => {})
  }, [draft.enable_prewarm, draft.prewarm_service_url])

  useEffect(() => {
    if (!draft.enable_prophet || !draft.prophet_shadow_mode) return
    const load = () => { fetchShadowLog().then(d => setShadowLog(d.entries)).catch(() => {}) }
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  }, [draft.enable_prophet, draft.prophet_shadow_mode])

  function showToast(msg: string, kind: 'success' | 'error') {
    setToast({ msg, kind })
    setTimeout(() => setToast(null), 3000)
  }

  function set<K extends keyof ConfigData>(k: K, v: ConfigData[K]) {
    setDraft(d => ({ ...d, [k]: v }))
  }

  async function saveFeature(key: string, updates: Partial<ConfigData>) {
    setSaving(key)
    try {
      const next  = { ...draft, ...updates }
      const saved = await saveConfig(next)
      setDraft(saved)
      onSaved(saved)
      showToast('Saved', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Save failed', 'error')
    } finally {
      setSaving(null)
    }
  }

  async function toggleFeature(key: keyof ConfigData, next: boolean) {
    set(key, next as ConfigData[typeof key])
    await saveFeature(key, { [key]: next })
  }

  function copySnippet() {
    if (!snippet) return
    navigator.clipboard.writeText(snippet.snippet).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const urlConfigured = !!draft.prewarm_service_url?.trim()

  return (
    <div className="features-page">

      <div className="features-page-intro">
        <div className="features-page-tag">// AI/ML &amp; INFRASTRUCTURE</div>
        <h1 className="features-page-title">Feature Toggles</h1>
        <p className="features-page-desc">
          Five intelligence layers that sit on top of the base schedule.
          Toggle independently — start with one, add others as confidence grows.
        </p>
      </div>

      {/* ── Row 1: 3 cards ──────────────────────────────────── */}
      <div className="features-grid">

        {/* Pre-Warm */}
        <article className="feature-card feature-card--blue">
          <div className="feature-card-accent" />
          <div className="feature-card-header">
            <div className="feature-card-identity">
              <span className="feature-badge feature-badge--blue">AI</span>
              <div>
                <div className="feature-name">AI Pre-Warm Engine</div>
                <div className="feature-subtitle">Zero cold-start for Knative AI services</div>
              </div>
            </div>
            <div className="feature-toggle-area">
              <span className={`feature-status ${draft.enable_prewarm ? 'feature-status--on' : 'feature-status--off'}`}>
                {draft.enable_prewarm ? 'ENABLED' : 'DISABLED'}
              </span>
              <Toggle checked={draft.enable_prewarm} onChange={v => toggleFeature('enable_prewarm', v)} />
            </div>
          </div>
          <div className="feature-lead">
            Detects user-intent signals and proactively boots Knative containers before inference requests arrive.
          </div>
          {draft.enable_prewarm && (
            <div className="feature-config">
              <div className="feature-config-label">// CONFIG</div>

              <div className="feature-prophet-field" style={{ marginBottom: 12 }}>
                <label className="feature-config-field-label">Knative Service URL</label>
                <input
                  className="feature-number-input"
                  type="text"
                  style={{ width: '100%' }}
                  placeholder="http://model-api.default.svc.cluster.local"
                  value={draft.prewarm_service_url}
                  onChange={e => set('prewarm_service_url', e.target.value)}
                />
              </div>

              <div className="feature-config-row" style={{ marginBottom: 12 }}>
                <span className="feature-config-field-label">Status</span>
                <span className="feature-config-value" style={{
                  color: urlConfigured ? 'var(--green)' : 'var(--red)',
                  fontWeight: 600,
                }}>
                  {urlConfigured ? '● Configured' : '○ Not configured'}
                </span>
              </div>

              {urlConfigured && snippet && (
                <div style={{ marginBottom: 14 }}>
                  <div className="feature-config-label" style={{ marginBottom: 6 }}>// FOR YOUR APP</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 8, fontFamily: 'Outfit, sans-serif', lineHeight: 1.5 }}>
                    Drop this into any page where you want pre-warming. The script detects hover and focus events and pings your Knative service 60–90s before the user submits.
                  </div>
                  <div style={{ position: 'relative' }}>
                    <pre style={{
                      background: 'var(--surface-2)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)',
                      padding: '10px 12px',
                      fontSize: 10,
                      fontFamily: 'JetBrains Mono, monospace',
                      color: 'var(--text-2)',
                      overflowX: 'auto',
                      whiteSpace: 'pre',
                      margin: 0,
                      lineHeight: 1.5,
                      maxHeight: 180,
                    }}>
                      {snippet.snippet}
                    </pre>
                    <button
                      onClick={copySnippet}
                      style={{
                        position: 'absolute', top: 6, right: 6,
                        padding: '4px 10px',
                        background: copied ? 'var(--green-dim)' : 'var(--surface-3)',
                        border: `1px solid ${copied ? 'rgba(48,209,88,0.4)' : 'var(--border)'}`,
                        borderRadius: 'var(--radius)',
                        color: copied ? 'var(--green)' : 'var(--text-3)',
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 9, fontWeight: 600, letterSpacing: '0.5px',
                        cursor: 'pointer',
                      }}
                    >
                      {copied ? 'COPIED' : 'COPY'}
                    </button>
                  </div>
                </div>
              )}

              {prewarmHistory.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div className="feature-config-label" style={{ marginBottom: 8 }}>// RECENT SIGNALS</div>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                          <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-2)', fontWeight: 500 }}>Signal</th>
                          <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-2)', fontWeight: 500 }}>Time</th>
                          <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-2)', fontWeight: 500 }}>Result</th>
                        </tr>
                      </thead>
                      <tbody>
                        {prewarmHistory.slice(-10).reverse().map((entry, i) => (
                          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                            <td style={{ padding: '5px 8px', color: 'var(--text)' }}>{entry.signal}</td>
                            <td style={{ padding: '5px 8px', color: 'var(--text-2)' }}>
                              {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </td>
                            <td style={{ padding: '5px 8px' }}>
                              <span style={{
                                color: entry.result === 'cold' ? 'var(--accent)' :
                                       entry.result === 'warm' ? 'var(--green)' :
                                       entry.result === 'debounced' ? 'var(--amber)' : 'var(--text-2)',
                              }}>
                                {entry.result}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <button
                className="btn-primary"
                style={{ marginTop: 14, padding: '7px 20px', fontSize: 12 }}
                disabled={saving === 'prewarm'}
                onClick={() => saveFeature('prewarm', {
                  prewarm_service_url: draft.prewarm_service_url,
                })}
              >
                {saving === 'prewarm' ? 'Saving…' : 'Save Pre-Warm config'}
              </button>
            </div>
          )}
        </article>

        {/* Metric Override */}
        <article className="feature-card feature-card--amber">
          <div className="feature-card-accent" />
          <div className="feature-card-header">
            <div className="feature-card-identity">
              <span className="feature-badge feature-badge--amber">SMART</span>
              <div>
                <div className="feature-name">Metric Override</div>
                <div className="feature-subtitle">Prevent false hibernation on quiet days</div>
              </div>
            </div>
            <div className="feature-toggle-area">
              <span className={`feature-status ${draft.enable_metric_override ? 'feature-status--on' : 'feature-status--off'}`}>
                {draft.enable_metric_override ? 'ENABLED' : 'DISABLED'}
              </span>
              <Toggle checked={draft.enable_metric_override} onChange={v => toggleFeature('enable_metric_override', v)} />
            </div>
          </div>
          <div className="feature-lead">
            Cross-checks the schedule against live Prometheus metrics before committing to a scale-down.
          </div>
          {draft.enable_metric_override && (
            <div className="feature-config feature-config--amber">
              <div className="feature-config-label">// CONFIG</div>
              <div className="feature-config-row">
                <span className="feature-config-field-label">Baseline window</span>
                <span className="feature-config-value">7 days (fixed)</span>
              </div>
              <div className="feature-config-row">
                <span className="feature-config-field-label">Metric query</span>
                <code className="feature-config-code">rate(container_cpu_usage_seconds_total[5m])</code>
              </div>
              <div className="feature-config-hint">
                No additional configuration required. Override activates automatically when the schedule would trigger a scale-down.
              </div>
            </div>
          )}
        </article>

        {/* Prophet ML */}
        <article className="feature-card feature-card--green">
          <div className="feature-card-accent" />
          <div className="feature-card-header">
            <div className="feature-card-identity">
              <span className="feature-badge feature-badge--green">ML</span>
              <div>
                <div className="feature-name">Prophet ML Forecasting</div>
                <div className="feature-subtitle">Learned time-series forecast replaces fixed clock</div>
              </div>
            </div>
            <div className="feature-toggle-area">
              <span className={`feature-status ${draft.enable_prophet ? 'feature-status--on' : 'feature-status--off'}`}>
                {draft.enable_prophet ? 'ENABLED' : 'DISABLED'}
              </span>
              <Toggle checked={draft.enable_prophet} onChange={v => toggleFeature('enable_prophet', v)} />
            </div>
          </div>
          <div className="feature-lead">
            Learns your cluster's actual usage patterns from Prometheus history, then forecasts 48h ahead to decide when to scale.
          </div>
          {draft.enable_prophet && (
            <div className="feature-config feature-config--green">
              <div className="feature-config-label">// CONFIG</div>
              <div className="feature-prophet-fields" style={{ gridTemplateColumns: '1fr' }}>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Training window</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="1" max="52"
                      value={draft.prophet_training_weeks}
                      onChange={e => set('prophet_training_weeks', parseInt(e.target.value) || 4)} />
                    <span className="feature-number-unit">weeks</span>
                  </div>
                </div>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Idle threshold</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="0" step="0.1"
                      value={draft.prophet_idle_threshold_cores}
                      onChange={e => set('prophet_idle_threshold_cores', parseFloat(e.target.value) || 0.5)} />
                    <span className="feature-number-unit">cores (yhat)</span>
                  </div>
                </div>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Retrain interval</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="1"
                      value={draft.prophet_retrain_hours}
                      onChange={e => set('prophet_retrain_hours', parseInt(e.target.value) || 6)} />
                    <span className="feature-number-unit">hours</span>
                  </div>
                </div>
              </div>
              <button
                className="btn-primary"
                style={{ marginTop: 14, padding: '7px 20px', fontSize: 12 }}
                disabled={saving === 'prophet'}
                onClick={() => saveFeature('prophet', {
                  prophet_training_weeks:       draft.prophet_training_weeks,
                  prophet_idle_threshold_cores: draft.prophet_idle_threshold_cores,
                  prophet_retrain_hours:        draft.prophet_retrain_hours,
                })}
              >
                {saving === 'prophet' ? 'Saving…' : 'Save Prophet config'}
              </button>

              {/* Shadow Mode */}
              <div style={{
                marginTop: 16, padding: 12,
                border: '1px solid rgba(48, 209, 88, 0.15)', borderRadius: 8,
                background: 'rgba(48, 209, 88, 0.03)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', fontFamily: 'Outfit, sans-serif' }}>Shadow Mode</div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 1 }}>Log predictions without acting</div>
                  </div>
                  <Toggle checked={draft.prophet_shadow_mode} onChange={v => toggleFeature('prophet_shadow_mode', v)} />
                </div>

                {draft.prophet_shadow_mode && shadowLog.length > 0 && (
                  <div style={{ marginTop: 10, overflowX: 'auto' }}>
                    <div style={{ fontSize: 10, color: 'var(--green)', fontFamily: 'JetBrains Mono, monospace', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      // SHADOW LOG
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                          <th style={{ textAlign: 'left', padding: '5px 6px', color: 'var(--text-2)', fontWeight: 500 }}>Time</th>
                          <th style={{ textAlign: 'center', padding: '5px 6px', color: 'var(--text-2)', fontWeight: 500 }}>Prophet</th>
                          <th style={{ textAlign: 'center', padding: '5px 6px', color: 'var(--text-2)', fontWeight: 500 }}>Schedule</th>
                          <th style={{ textAlign: 'center', padding: '5px 6px', color: 'var(--text-2)', fontWeight: 500 }}>Agree</th>
                          <th style={{ textAlign: 'right', padding: '5px 6px', color: 'var(--text-2)', fontWeight: 500 }}>yhat</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shadowLog.slice(-10).reverse().map((entry, i) => (
                          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                            <td style={{ padding: '4px 6px', color: 'var(--text-2)' }}>
                              {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </td>
                            <td style={{ padding: '4px 6px', textAlign: 'center', color: entry.prophet_says_idle ? 'var(--amber)' : 'var(--green)' }}>
                              {entry.prophet_says_idle ? 'IDLE' : 'ACTIVE'}
                            </td>
                            <td style={{ padding: '4px 6px', textAlign: 'center', color: entry.schedule_says_idle ? 'var(--amber)' : 'var(--green)' }}>
                              {entry.schedule_says_idle ? 'IDLE' : 'ACTIVE'}
                            </td>
                            <td style={{ padding: '4px 6px', textAlign: 'center' }}>
                              {entry.agreement
                                ? <span style={{ color: 'var(--green)' }}>✓</span>
                                : <span style={{ color: 'var(--red)' }}>✕</span>}
                            </td>
                            <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--text)' }}>
                              {entry.predicted_yhat.toFixed(3)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </article>
      </div>

      {/* ── Row 2: 2 cards centered ─────────────────────────── */}
      <div className="features-grid-bottom">

        {/* HPA Synergy */}
        <article className="feature-card feature-card--purple">
          <div className="feature-card-accent" />
          <div className="feature-card-header">
            <div className="feature-card-identity">
              <span className="feature-badge feature-badge--purple">HPA</span>
              <div>
                <div className="feature-name">Predictive HPA Synergy</div>
                <div className="feature-subtitle">Scale capacity ahead of traffic spikes</div>
              </div>
            </div>
            <div className="feature-toggle-area">
              <span className={`feature-status ${draft.enable_hpa_synergy ? 'feature-status--on' : 'feature-status--off'}`}>
                {draft.enable_hpa_synergy ? 'ENABLED' : 'DISABLED'}
              </span>
              <Toggle checked={draft.enable_hpa_synergy} onChange={v => toggleFeature('enable_hpa_synergy', v)} />
            </div>
          </div>
          <div className="feature-lead">
            Uses Prophet's forecast to detect incoming traffic spikes and proactively raises HPA maxReplicas before the surge.
          </div>
          {draft.enable_hpa_synergy && (
            <div className="feature-config feature-config--purple">
              <div className="feature-config-label">// CONFIG</div>
              <div className="feature-prophet-fields" style={{ gridTemplateColumns: '1fr' }}>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Headroom</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="0" max="200"
                      value={draft.hpa_spike_headroom_pct}
                      onChange={e => set('hpa_spike_headroom_pct', parseInt(e.target.value) || 30)} />
                    <span className="feature-number-unit">% above predicted</span>
                  </div>
                </div>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Lookahead</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="5" max="60"
                      value={draft.hpa_spike_lookahead_minutes}
                      onChange={e => set('hpa_spike_lookahead_minutes', parseInt(e.target.value) || 15)} />
                    <span className="feature-number-unit">minutes</span>
                  </div>
                </div>
              </div>
              <button
                className="btn-primary"
                style={{ marginTop: 14, padding: '7px 20px', fontSize: 12 }}
                disabled={saving === 'hpa_synergy'}
                onClick={() => saveFeature('hpa_synergy', {
                  hpa_spike_headroom_pct:      draft.hpa_spike_headroom_pct,
                  hpa_spike_lookahead_minutes: draft.hpa_spike_lookahead_minutes,
                })}
              >
                {saving === 'hpa_synergy' ? 'Saving...' : 'Save HPA Synergy config'}
              </button>
            </div>
          )}
        </article>

        {/* Spot Migration */}
        <article className="feature-card feature-card--spot">
          <div className="feature-card-accent" />
          <div className="feature-card-header">
            <div className="feature-card-identity">
              <span className="feature-badge feature-badge--spot">SPOT</span>
              <div>
                <div className="feature-name">Spot Instance Migration</div>
                <div className="feature-subtitle">Move low-priority workloads to spot for savings</div>
              </div>
            </div>
            <div className="feature-toggle-area">
              <span className={`feature-status ${draft.enable_spot_migration ? 'feature-status--on' : 'feature-status--off'}`}>
                {draft.enable_spot_migration ? 'ENABLED' : 'DISABLED'}
              </span>
              <Toggle checked={draft.enable_spot_migration} onChange={v => toggleFeature('enable_spot_migration', v)} />
            </div>
          </div>
          <div className="feature-lead">
            Identifies low-priority workloads and migrates them to spot instances with automatic fallback on interruption.
          </div>
          {draft.enable_spot_migration && (
            <div className="feature-config feature-config--spot">
              <div className="feature-config-label">// CONFIG</div>
              <div className="feature-prophet-fields" style={{ gridTemplateColumns: '1fr' }}>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Max spot price</label>
                  <div className="feature-prophet-input-row">
                    <input className="feature-number-input" type="number" min="10" max="100"
                      value={draft.spot_max_price_pct}
                      onChange={e => set('spot_max_price_pct', parseInt(e.target.value) || 80)} />
                    <span className="feature-number-unit">% of on-demand</span>
                  </div>
                </div>
                <div className="feature-prophet-field">
                  <label className="feature-config-field-label">Eligible label</label>
                  <input className="feature-number-input" type="text" style={{ width: '100%' }}
                    value={draft.spot_eligible_label}
                    onChange={e => set('spot_eligible_label', e.target.value)} />
                </div>
              </div>
              <button
                className="btn-primary"
                style={{ marginTop: 14, padding: '7px 20px', fontSize: 12 }}
                disabled={saving === 'spot'}
                onClick={() => saveFeature('spot', {
                  spot_max_price_pct:  draft.spot_max_price_pct,
                  spot_eligible_label: draft.spot_eligible_label,
                })}
              >
                {saving === 'spot' ? 'Saving...' : 'Save Spot config'}
              </button>

              {spotStatus && (
                <div className="spot-status-grid">
                  <div className="spot-stat">
                    <div className="spot-stat-value">{spotStatus.on_demand_nodes}</div>
                    <div className="spot-stat-label">On-Demand</div>
                  </div>
                  <div className="spot-stat">
                    <div className="spot-stat-value spot-stat-value--spot">{spotStatus.spot_nodes}</div>
                    <div className="spot-stat-label">Spot</div>
                  </div>
                  <div className="spot-stat">
                    <div className="spot-stat-value">{spotStatus.spot_eligible_workloads}</div>
                    <div className="spot-stat-label">Eligible</div>
                  </div>
                  <div className="spot-stat">
                    <div className="spot-stat-value spot-stat-value--savings">
                      ${spotStatus.estimated_hourly_savings.toFixed(4)}
                    </div>
                    <div className="spot-stat-label">Est. savings/hr</div>
                  </div>
                  <div className="spot-stat">
                    <div className="spot-stat-value">{spotStatus.migrations_today}</div>
                    <div className="spot-stat-label">Migrations today</div>
                  </div>
                  <div className="spot-stat">
                    <div className="spot-stat-value">{spotStatus.recent_interruptions}</div>
                    <div className="spot-stat-label">Interruptions</div>
                  </div>
                </div>
              )}
            </div>
          )}
        </article>
      </div>

      {toast && (
        <div className={`toast toast-${toast.kind}`}>
          <span>{toast.kind === 'success' ? '✓' : '✕'}</span>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
