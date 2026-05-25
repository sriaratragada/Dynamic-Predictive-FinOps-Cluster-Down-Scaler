import { useState } from 'react'
import type { ConfigData } from '../api'
import { saveConfig } from '../api'
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

  return (
    <div className="features-page">

      <div className="features-page-intro">
        <div className="features-page-tag">// AI/ML</div>
        <h1 className="features-page-title">Predictive Features</h1>
        <p className="features-page-desc">
          Three optional intelligence layers that sit on top of the base schedule.
          Each can be toggled independently — start with one, add others as confidence grows.
        </p>
      </div>

      {/* ═══════════════════════════════════════════════════════
          Feature 1 — AI Pre-Warm
      ════════════════════════════════════════════════════════ */}
      <article className="feature-card feature-card--blue">
        <div className="feature-card-accent" />

        <div className="feature-card-header">
          <div className="feature-card-identity">
            <span className="feature-badge feature-badge--blue">AI</span>
            <div>
              <div className="feature-name">AI Pre-Warm Engine</div>
              <div className="feature-subtitle">
                Zero cold-start on Knative AI containers
              </div>
            </div>
          </div>
          <div className="feature-toggle-area">
            <span className={`feature-status ${draft.enable_prewarm ? 'feature-status--on' : 'feature-status--off'}`}>
              {draft.enable_prewarm ? 'ENABLED' : 'DISABLED'}
            </span>
            <Toggle
              checked={draft.enable_prewarm}
              onChange={v => toggleFeature('enable_prewarm', v)}
            />
          </div>
        </div>

        <div className="feature-lead">
          Pre-start Knative AI containers on user-intent signals — so the model is warm
          and serving at full speed before the first real request arrives.
        </div>

        <div className="feature-body">
          <div className="feature-col">
            <div className="feature-col-heading">How it works</div>
            <p className="feature-col-text">
              The controller monitors configurable intent signals: page-load events,
              API preflight calls, hover dwell-time, or custom webhook pings. When signals
              fire above threshold, Knative AI containers are booted <strong>60–90 seconds early</strong>.
              By the time a real inference request arrives, the container is warm —
              completely eliminating cold-start latency.
            </p>
            <Pipeline steps={['Intent signal', 'Threshold check', 'Boot container', 'Warm serve']} />
          </div>

          <div className="feature-col">
            <div className="feature-col-heading">When to use</div>
            <ul className="feature-use-list">
              <li>AI inference endpoints with <strong>&gt;200ms cold-start delay</strong></li>
              <li>High-conversion pages backed by ML models where latency = revenue</li>
              <li>Knative services with high variance in startup time</li>
              <li>Any flow where a loading spinner on first inference hurts UX</li>
            </ul>
            <div className="feature-note">
              <span className="feature-note-label">Note</span>
              Enable only on high-conversion AI pages — pre-warming idle containers wastes resources if traffic never materialises.
            </div>
          </div>
        </div>

        {draft.enable_prewarm && (
          <div className="feature-config">
            <div className="feature-config-label">// CONFIG</div>
            <div className="feature-config-row">
              <span className="feature-config-field-label">Pre-warm lead time</span>
              <span className="feature-config-value">Configured per Knative service annotation</span>
            </div>
            <div className="feature-config-row">
              <span className="feature-config-field-label">Signal source</span>
              <span className="feature-config-value">Prometheus custom metric or webhook endpoint</span>
            </div>
            <div className="feature-config-hint">
              Advanced configuration via <code>finops.io/prewarm-lead-seconds</code> annotation on the target Knative service.
            </div>
          </div>
        )}
      </article>

      {/* ═══════════════════════════════════════════════════════
          Feature 2 — Metric Override
      ════════════════════════════════════════════════════════ */}
      <article className="feature-card feature-card--amber">
        <div className="feature-card-accent" />

        <div className="feature-card-header">
          <div className="feature-card-identity">
            <span className="feature-badge feature-badge--amber">SMART</span>
            <div>
              <div className="feature-name">Metric Override</div>
              <div className="feature-subtitle">
                Prevent false hibernation on anomalously quiet days
              </div>
            </div>
          </div>
          <div className="feature-toggle-area">
            <span className={`feature-status ${draft.enable_metric_override ? 'feature-status--on' : 'feature-status--off'}`}>
              {draft.enable_metric_override ? 'ENABLED' : 'DISABLED'}
            </span>
            <Toggle
              checked={draft.enable_metric_override}
              onChange={v => toggleFeature('enable_metric_override', v)}
            />
          </div>
        </div>

        <div className="feature-lead">
          Cross-checks the schedule against live Prometheus metrics before committing to a
          scale-down — so a genuine off-peak window doesn't become an accidental outage.
        </div>

        <div className="feature-body">
          <div className="feature-col">
            <div className="feature-col-heading">How it works</div>
            <p className="feature-col-text">
              At each scale-down candidate window, the controller queries <strong>current CPU usage</strong> and
              compares it against a <strong>rolling 7-day Prometheus baseline</strong> for the same
              time slot. If today's traffic is abnormally low compared to historical patterns —
              a bank holiday, a deployment freeze, a slow news day — the metrics confirm
              the cluster is genuinely idle. If the baseline says "this hour is normally busy,"
              scale-down is blocked even if the clock says off-hours.
            </p>
            <Pipeline steps={['Clock: off-hours?', 'Query current CPU', 'Compare 7d baseline', 'Confirm idle?', 'Scale decision']} />
          </div>

          <div className="feature-col">
            <div className="feature-col-heading">When to use</div>
            <ul className="feature-use-list">
              <li>Teams that occasionally work weekends or late evenings</li>
              <li>Clusters with <strong>irregular-but-real traffic</strong> patterns</li>
              <li>Environments affected by campaigns, batch jobs, or marketing spikes</li>
              <li>Any time you've had a false scale-down during an unexpected busy period</li>
            </ul>
            <div className="feature-note feature-note--amber">
              <span className="feature-note-label">Requires</span>
              Prometheus with at least 7 days of CPU metrics history. The baseline is computed from
              <code>rate(container_cpu_usage_seconds_total[5m])</code> averaged over the same weekday/hour slot.
            </div>
          </div>
        </div>

        {draft.enable_metric_override && (
          <div className="feature-config feature-config--amber">
            <div className="feature-config-label">// CONFIG</div>
            <div className="feature-config-row">
              <span className="feature-config-field-label">Baseline window</span>
              <span className="feature-config-value">7 days (fixed — enough to cover Mon–Sun patterns)</span>
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

      {/* ═══════════════════════════════════════════════════════
          Feature 3 — Prophet ML
      ════════════════════════════════════════════════════════ */}
      <article className="feature-card feature-card--green">
        <div className="feature-card-accent" />

        <div className="feature-card-header">
          <div className="feature-card-identity">
            <span className="feature-badge feature-badge--green">ML</span>
            <div>
              <div className="feature-name">Prophet ML Forecasting</div>
              <div className="feature-subtitle">
                Replace the fixed clock schedule with a learned time-series forecast
              </div>
            </div>
          </div>
          <div className="feature-toggle-area">
            <span className={`feature-status ${draft.enable_prophet ? 'feature-status--on' : 'feature-status--off'}`}>
              {draft.enable_prophet ? 'ENABLED' : 'DISABLED'}
            </span>
            <Toggle
              checked={draft.enable_prophet}
              onChange={v => toggleFeature('enable_prophet', v)}
            />
          </div>
        </div>

        <div className="feature-lead">
          The controller learns your cluster's actual usage patterns from Prometheus history —
          then forecasts 48 hours ahead to decide when to scale, rather than trusting a fixed
          Mon–Fri 9–5 clock window that may never have matched reality.
        </div>

        <div className="feature-body">
          <div className="feature-col">
            <div className="feature-col-heading">How it works</div>
            <p className="feature-col-text">
              Queries Prometheus for the last <strong>N weeks of CPU core usage</strong>,
              builds a pandas DataFrame with <code>ds</code> (timestamp) and <code>y</code> (cores) columns,
              fits a <strong>Facebook Prophet model</strong> with weekly + daily seasonality,
              then generates a 48-hour ahead forecast. The controller replaces its schedule gate with:
              <em>if forecast yhat &lt; idle threshold → cluster is idle → scale down</em>.
              The model retrains automatically on a configurable interval.
            </p>
            <Pipeline steps={['Prometheus history', 'pandas DataFrame', 'Prophet.fit()', '48h forecast (yhat)', 'Idle gate']} />

            <div className="feature-data-note">
              <div className="feature-data-row">
                <span>Seasonality</span>
                <span>weekly + daily</span>
              </div>
              <div className="feature-data-row">
                <span>Forecast horizon</span>
                <span>48 hours at 5-min resolution</span>
              </div>
              <div className="feature-data-row">
                <span>Fallback</span>
                <span>Schedule-based (if model not ready)</span>
              </div>
            </div>
          </div>

          <div className="feature-col">
            <div className="feature-col-heading">When to use</div>
            <ul className="feature-use-list">
              <li>Clusters with <strong>irregular patterns</strong> — sprint-end surges, monthly batch, seasonal peaks</li>
              <li>When your fixed schedule causes scale-downs too early or too late</li>
              <li>After you've seen the schedule miss scale-down windows due to unexpected traffic</li>
              <li>Multi-timezone teams where "business hours" is genuinely variable</li>
            </ul>
            <div className="feature-note feature-note--green">
              <span className="feature-note-label">Requires</span>
              Prometheus with <strong>≥ 4 weeks</strong> of CPU history.
              Install: <code>pip install prophet pandas</code>.
              If Prophet is not installed, the controller falls back to schedule-based decisions silently.
            </div>
          </div>
        </div>

        {/* Prophet config — always visible when enabled */}
        {draft.enable_prophet && (
          <div className="feature-config feature-config--green">
            <div className="feature-config-label">// CONFIG</div>
            <div className="feature-prophet-fields">
              <div className="feature-prophet-field">
                <label className="feature-config-field-label">
                  Training window
                </label>
                <div className="feature-prophet-input-row">
                  <input
                    className="feature-number-input"
                    type="number"
                    min="1"
                    max="52"
                    value={draft.prophet_training_weeks}
                    onChange={e => set('prophet_training_weeks', parseInt(e.target.value) || 4)}
                  />
                  <span className="feature-number-unit">weeks</span>
                </div>
                <div className="feature-config-hint">
                  Prometheus must have this much CPU history. More = better seasonality detection.
                </div>
              </div>

              <div className="feature-prophet-field">
                <label className="feature-config-field-label">
                  Idle threshold
                </label>
                <div className="feature-prophet-input-row">
                  <input
                    className="feature-number-input"
                    type="number"
                    min="0"
                    step="0.1"
                    value={draft.prophet_idle_threshold_cores}
                    onChange={e => set('prophet_idle_threshold_cores', parseFloat(e.target.value) || 0.5)}
                  />
                  <span className="feature-number-unit">cores (yhat)</span>
                </div>
                <div className="feature-config-hint">
                  Forecast below this → idle → scale down.
                </div>
              </div>

              <div className="feature-prophet-field">
                <label className="feature-config-field-label">
                  Retrain interval
                </label>
                <div className="feature-prophet-input-row">
                  <input
                    className="feature-number-input"
                    type="number"
                    min="1"
                    value={draft.prophet_retrain_hours}
                    onChange={e => set('prophet_retrain_hours', parseInt(e.target.value) || 6)}
                  />
                  <span className="feature-number-unit">hours</span>
                </div>
                <div className="feature-config-hint">
                  How often the model re-fits on fresh Prometheus data.
                </div>
              </div>
            </div>

            <button
              className="btn-primary"
              style={{ marginTop: 16, padding: '7px 20px', fontSize: 12 }}
              disabled={saving === 'prophet'}
              onClick={() => saveFeature('prophet', {
                prophet_training_weeks:       draft.prophet_training_weeks,
                prophet_idle_threshold_cores: draft.prophet_idle_threshold_cores,
                prophet_retrain_hours:        draft.prophet_retrain_hours,
              })}
            >
              {saving === 'prophet' ? 'Saving…' : 'Save Prophet config'}
            </button>
          </div>
        )}
      </article>

      {toast && (
        <div className={`toast toast-${toast.kind}`}>
          <span>{toast.kind === 'success' ? '✓' : '✕'}</span>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
