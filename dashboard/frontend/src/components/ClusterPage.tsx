import { useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { connectCluster, saveConfig, stopController } from '../api'
import Toggle from './Toggle'

interface Props {
  config:              ConfigData
  controllerStatus:    ControllerStatus | null
  onConnected:         (s: ControllerStatus) => void
  onConfigChange:      (c: ConfigData) => void
  onControllerChange:  (s: ControllerStatus) => void
}

type Tab   = 'paste' | 'generate'
type Toast = { msg: string; kind: 'success' | 'error' } | null

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try { await navigator.clipboard.writeText(text) } catch { /* ignore */ }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button className="cmd-copy-btn" onClick={copy}>
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

function InfoTip({ children }: { children: React.ReactNode }) {
  return (
    <span className="info-tip-wrap">
      <span className="info-tip-icon">ⓘ</span>
      <div className="info-tip-content">{children}</div>
    </span>
  )
}

function parseDays(str: string): Set<number> {
  return new Set(str.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)))
}

const KUBECONFIG_PLACEHOLDER = `apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://your-api-server:6443
  name: my-cluster
contexts:
- context:
    cluster: my-cluster
    user: finops-scaler
  name: my-context
current-context: my-context
users:
- name: finops-scaler
  user:
    token: eyJhbGci...`

export default function ClusterPage({
  config, controllerStatus, onConnected, onConfigChange, onControllerChange,
}: Props) {
  const [tab,        setTab]        = useState<Tab>('paste')
  const [kubeconfig, setKubeconfig] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [stopping,   setStopping]   = useState(false)
  const [error,      setError]      = useState<string | null>(null)
  const [toast,      setToast]      = useState<Toast>(null)

  // Local draft of connection-related config
  const [demoMode,   setDemoMode]   = useState(config.demo_mode)
  const [promUrl,    setPromUrl]    = useState(config.prometheus_url)
  const [schedStart, setSchedStart] = useState(config.business_hours_start)
  const [schedEnd,   setSchedEnd]   = useState(config.business_hours_end)
  const [timezone,   setTimezone]   = useState(config.timezone || 'UTC')
  const [activeDays, setActiveDays] = useState<Set<number>>(() => parseDays(config.business_days))

  const connected = controllerStatus?.connected ?? false

  function toggleDay(i: number) {
    setActiveDays(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  function showToast(msg: string, kind: 'success' | 'error') {
    setToast({ msg, kind })
    setTimeout(() => setToast(null), 3000)
  }

  async function handleDemoToggle(enabled: boolean) {
    setDemoMode(enabled)
    try {
      const saved = await saveConfig({ ...config, demo_mode: enabled })
      onConfigChange(saved)
      showToast(enabled ? 'Demo mode enabled' : 'Demo mode disabled', 'success')
    } catch {
      showToast('Failed to save', 'error')
      setDemoMode(!enabled)
    }
  }

  async function handleConnect() {
    if (!kubeconfig.trim()) return
    setConnecting(true)
    setError(null)
    try {
      const updated: ConfigData = {
        ...config,
        demo_mode:            false,
        prometheus_url:       promUrl,
        business_hours_start: schedStart,
        business_hours_end:   schedEnd,
        timezone,
        business_days: [...activeDays].sort((a, b) => a - b).join(','),
      }
      const saved = await saveConfig(updated)
      onConfigChange(saved)
      const status = await connectCluster(kubeconfig.trim())
      onConnected(status)
      showToast('Connected — controller is running', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed — check credentials and reachability')
    } finally {
      setConnecting(false)
    }
  }

  async function handleStop() {
    setStopping(true)
    try {
      const status = await stopController()
      onControllerChange(status)
      showToast('Controller stopped', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Stop failed', 'error')
    } finally {
      setStopping(false)
    }
  }

  return (
    <div className="cluster-page">

      {/* ── Page header ── */}
      <div className="cluster-page-header">
        <div>
          <div className="cluster-page-tag">// CLUSTER</div>
          <h1 className="cluster-page-title">Cluster Connection</h1>
          <p className="cluster-page-desc">
            Connect this controller to your Kubernetes cluster. The controller runs
            embedded in this container — no in-cluster install required.
          </p>
        </div>

        {/* Connection status */}
        {connected && controllerStatus && (
          <div className="cluster-status-card">
            <div className="cluster-status-row">
              <span className={`cluster-status-dot cluster-status-dot--${controllerStatus.running ? 'running' : 'stopped'}`} />
              <div>
                <div className="cluster-status-label">
                  {controllerStatus.running ? 'Controller running' : 'Controller stopped'}
                </div>
                <div className="cluster-status-host">{controllerStatus.cluster_host}</div>
              </div>
              <button
                className="btn-ghost"
                style={{ marginLeft: 'auto', padding: '5px 14px', fontSize: 11 }}
                disabled={stopping}
                onClick={handleStop}
              >
                {stopping ? '…' : 'Stop'}
              </button>
            </div>
            {controllerStatus.last_action && (
              <div className="cluster-status-action">
                Last action · <span>{controllerStatus.last_action}</span>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="cluster-page-body">

        {/* ── Left: instructions ── */}
        <div className="cluster-page-left">

          {/* Data source */}
          <section className="cluster-section">
            <div className="cluster-section-header">
              <span className="cluster-section-tag">// SOURCE</span>
              Data source
            </div>

            <div className="cluster-field">
              <div className="cluster-field-row">
                <div>
                  <div className="cluster-field-label">Demo Mode</div>
                  <div className="cluster-field-hint">Synthetic data — no K8s or Prometheus needed</div>
                </div>
                <Toggle checked={demoMode} onChange={handleDemoToggle} />
              </div>
            </div>

            {!demoMode && (
              <div className="cluster-field" style={{ marginTop: 14 }}>
                <label className="cluster-field-label">
                  Prometheus URL
                  <InfoTip>
                    The base URL for your Prometheus instance.<br />
                    Used for metric queries and baseline detection.<br />
                    Example: <code>http://prometheus:9090</code>
                  </InfoTip>
                </label>
                <input
                  className="cluster-input"
                  type="url"
                  value={promUrl}
                  onChange={e => setPromUrl(e.target.value)}
                  placeholder="http://prometheus:9090"
                  spellCheck={false}
                />
              </div>
            )}
          </section>

          {/* Get credentials */}
          {!demoMode && (
            <section className="cluster-section">
              <div className="cluster-section-header">
                <span className="cluster-section-tag">// CREDS</span>
                Get credentials
              </div>

              <div className="connect-tabs">
                <button
                  className={`connect-tab ${tab === 'paste' ? 'active' : ''}`}
                  onClick={() => setTab('paste')}
                >
                  Already have kubectl
                </button>
                <button
                  className={`connect-tab ${tab === 'generate' ? 'active' : ''}`}
                  onClick={() => setTab('generate')}
                >
                  Need credentials
                </button>
              </div>

              {tab === 'paste' && (
                <div className="connect-tab-content" style={{ marginTop: 12 }}>
                  <p className="connect-tab-desc">Export your current kubeconfig:</p>
                  <div className="cmd-block">
                    <code>cat ~/.kube/config</code>
                    <CopyButton text="cat ~/.kube/config" />
                  </div>
                  <p className="connect-tab-desc" style={{ marginTop: 10 }}>Or just the active context:</p>
                  <div className="cmd-block">
                    <code>kubectl config view --raw --minify -o yaml</code>
                    <CopyButton text="kubectl config view --raw --minify -o yaml" />
                  </div>
                </div>
              )}

              {tab === 'generate' && (
                <div className="connect-tab-content" style={{ marginTop: 12 }}>
                  <div className="cmd-step">
                    <div className="cmd-step-label">01 — Create service account</div>
                    <div className="cmd-block">
                      <code>kubectl create sa finops-scaler -n kube-system</code>
                      <CopyButton text="kubectl create sa finops-scaler -n kube-system" />
                    </div>
                  </div>
                  <div className="cmd-step">
                    <div className="cmd-step-label">
                      02 — Grant permissions
                      <InfoTip>
                        <code>cluster-admin</code> gives full read/write access.<br />
                        Minimal RBAC: see <code>manifests/rbac.yaml</code>.
                      </InfoTip>
                    </div>
                    <div className="cmd-block cmd-block--multi">
                      <code>{`kubectl create clusterrolebinding finops-scaler \\\n  --clusterrole=cluster-admin \\\n  --serviceaccount=kube-system:finops-scaler`}</code>
                      <CopyButton text="kubectl create clusterrolebinding finops-scaler --clusterrole=cluster-admin --serviceaccount=kube-system:finops-scaler" />
                    </div>
                  </div>
                  <div className="cmd-step">
                    <div className="cmd-step-label">03 — Generate token (1-year expiry)</div>
                    <div className="cmd-block">
                      <code>kubectl create token finops-scaler -n kube-system --duration=8760h</code>
                      <CopyButton text="kubectl create token finops-scaler -n kube-system --duration=8760h" />
                    </div>
                  </div>
                  <div className="cmd-step">
                    <div className="cmd-step-label">
                      04 — Get server URL
                      <InfoTip>
                        The <code>server:</code> field in your kubeconfig.<br />
                        Looks like <code>https://&lt;host&gt;:6443</code>.
                      </InfoTip>
                    </div>
                    <div className="cmd-block">
                      <code>{`kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'`}</code>
                      <CopyButton text={`kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'`} />
                    </div>
                  </div>
                </div>
              )}

              {/* Label deployments */}
              <div className="connect-deploy-note" style={{ marginTop: 16 }}>
                <span className="connect-step-num">LABEL</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                    Tag deployments that should scale down during off-hours:
                  </div>
                  <div className="cmd-block">
                    <code>kubectl label deployment &lt;name&gt; finops.io/scaledown-eligible=true</code>
                    <CopyButton text="kubectl label deployment <name> finops.io/scaledown-eligible=true" />
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>

        {/* ── Right: schedule + connect ── */}
        {!demoMode && (
          <div className="cluster-page-right">

            {/* Schedule */}
            <section className="cluster-section">
              <div className="cluster-section-header">
                <span className="cluster-section-tag">// SCHED</span>
                Scale schedule
                <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 'auto', fontFamily: "'JetBrains Mono', monospace" }}>
                  saved on connect
                </span>
              </div>

              <div className="cluster-field">
                <label className="cluster-field-label">Active days</label>
                <div className="connect-day-pills">
                  {DAYS.map((label, i) => (
                    <button
                      key={i}
                      type="button"
                      className={`connect-day-pill ${activeDays.has(i) ? 'active' : ''}`}
                      onClick={() => toggleDay(i)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="cluster-field">
                <label className="cluster-field-label">Business hours</label>
                <div className="dash-time-row">
                  <input
                    className="dash-time-input"
                    type="time"
                    value={schedStart}
                    onChange={e => setSchedStart(e.target.value)}
                  />
                  <span className="dash-time-sep">→</span>
                  <input
                    className="dash-time-input"
                    type="time"
                    value={schedEnd}
                    onChange={e => setSchedEnd(e.target.value)}
                  />
                </div>
              </div>

              <div className="cluster-field">
                <label className="cluster-field-label">
                  Timezone
                  <InfoTip>
                    IANA timezone name. Examples:<br />
                    <strong>America/New_York</strong><br />
                    <strong>Europe/London</strong><br />
                    <strong>Asia/Kolkata</strong>
                  </InfoTip>
                </label>
                <input
                  className="cluster-input"
                  value={timezone}
                  onChange={e => setTimezone(e.target.value)}
                  placeholder="UTC"
                  spellCheck={false}
                />
              </div>
            </section>

            {/* kubeconfig */}
            <section className="cluster-section">
              <div className="cluster-section-header">
                <span className="cluster-section-tag">// YAML</span>
                kubeconfig
                <span className="required-badge" style={{ marginLeft: 'auto' }}>REQUIRED</span>
              </div>

              <textarea
                className="connect-kubeconfig"
                style={{ minHeight: 200 }}
                value={kubeconfig}
                onChange={e => setKubeconfig(e.target.value)}
                placeholder={KUBECONFIG_PLACEHOLDER}
                spellCheck={false}
                autoComplete="off"
              />

              {error && <div className="connect-error" style={{ marginTop: 10 }}>{error}</div>}

              <button
                className="btn-primary"
                style={{ width: '100%', marginTop: 14 }}
                disabled={!kubeconfig.trim() || connecting}
                onClick={handleConnect}
              >
                {connecting
                  ? 'Validating credentials…'
                  : connected
                    ? 'Reconnect with new credentials →'
                    : 'Save Schedule & Connect →'}
              </button>
            </section>

          </div>
        )}

        {/* Demo mode active state */}
        {demoMode && (
          <div className="cluster-demo-active">
            <div className="cluster-demo-icon">∿</div>
            <div className="cluster-demo-label">Synthetic data active</div>
            <div className="cluster-demo-desc">
              All metrics, nodes, savings, and events are generated from a deterministic
              algorithm seeded by wall-clock time. No Kubernetes cluster or Prometheus
              instance is required. Toggle Demo Mode off above to connect a real cluster.
            </div>
            <div className="cluster-demo-nodes">
              <div className="cluster-demo-node">
                <span className="cluster-demo-node-name">demo-node-1</span>
                <span className="cluster-demo-node-role">control-plane · always ready</span>
              </div>
              <div className="cluster-demo-node cluster-demo-node--cordoned">
                <span className="cluster-demo-node-name">demo-node-2</span>
                <span className="cluster-demo-node-role">worker · cordoned outside hours</span>
              </div>
              <div className="cluster-demo-node cluster-demo-node--cordoned">
                <span className="cluster-demo-node-name">demo-node-3</span>
                <span className="cluster-demo-node-role">worker · cordoned outside hours</span>
              </div>
            </div>
          </div>
        )}

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
