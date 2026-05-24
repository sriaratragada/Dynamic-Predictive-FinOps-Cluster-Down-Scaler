import { useEffect, useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { connectCluster, saveConfig, stopController } from '../api'

interface Props {
  config:             ConfigData
  controllerStatus?:  ControllerStatus | null
  onClose:            () => void
  onConnected:        (s: ControllerStatus) => void
  onConfigChange?:    (c: ConfigData) => void
  onControllerChange?:(s: ControllerStatus) => void
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
    <button className="cmd-copy-btn" onClick={copy} title="Copy to clipboard">
      {copied ? '✓' : 'Copy'}
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

function parseDays(str: string): Set<number> {
  return new Set(str.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)))
}

export default function ConnectPanel({
  config, controllerStatus, onClose, onConnected, onConfigChange, onControllerChange,
}: Props) {
  const [tab,        setTab]        = useState<Tab>('paste')
  const [kubeconfig, setKubeconfig] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [stopping,   setStopping]   = useState(false)
  const [error,      setError]      = useState<string | null>(null)
  const [toast,      setToast]      = useState<Toast>(null)

  // Inline schedule — seeded from config
  const [schedStart, setSchedStart] = useState(config.business_hours_start)
  const [schedEnd,   setSchedEnd]   = useState(config.business_hours_end)
  const [timezone,   setTimezone]   = useState(config.timezone || 'UTC')
  const [activeDays, setActiveDays] = useState<Set<number>>(() => parseDays(config.business_days))

  // Keyboard close
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

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

  async function handleConnect() {
    if (!kubeconfig.trim()) return
    setConnecting(true)
    setError(null)
    try {
      const updatedConfig: ConfigData = {
        ...config,
        business_hours_start: schedStart,
        business_hours_end:   schedEnd,
        timezone,
        business_days: [...activeDays].sort((a, b) => a - b).join(','),
        demo_mode: false,
      }
      const saved = await saveConfig(updatedConfig)
      onConfigChange?.(saved)
      const status = await connectCluster(kubeconfig.trim())
      onConnected(status)
      showToast('Connected to cluster', 'success')
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
      onControllerChange?.(status)
      showToast('Controller loop stopped', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Stop failed', 'error')
    } finally {
      setStopping(false)
    }
  }

  const connected = controllerStatus?.connected ?? false

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />

      <div className="drawer drawer--wide" role="dialog" aria-modal aria-label="Connect Cluster">

        {/* ── Header ── */}
        <div className="drawer-header">
          <span className="drawer-title">Connect Cluster</span>
          <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {/* ── Body ── */}
        <div className="drawer-body">

          {/* ── Connected state ── */}
          {connected && controllerStatus && (
            <div className="connect-panel-status">
              <div className="connect-panel-status-row">
                <span className={`connect-panel-dot connect-panel-dot--${controllerStatus.running ? 'running' : 'stopped'}`} />
                <div>
                  <div className="connect-panel-status-title">
                    {controllerStatus.running ? 'Controller running' : 'Controller stopped'}
                  </div>
                  <div className="connect-panel-status-host">{controllerStatus.cluster_host}</div>
                </div>
                <button
                  className="btn-ghost"
                  style={{ marginLeft: 'auto', padding: '5px 14px', fontSize: 11 }}
                  disabled={stopping}
                  onClick={handleStop}
                >
                  {stopping ? '…' : 'Stop controller'}
                </button>
              </div>
              {controllerStatus.last_action && (
                <div className="connect-panel-last-action">
                  Last action: <span>{controllerStatus.last_action}</span>
                </div>
              )}
              <div className="connect-panel-reconnect-hint">
                To connect a different cluster, paste new credentials below and click Connect again.
              </div>
            </div>
          )}

          {/* ── Instruction tabs ── */}
          <div className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// CREDS</span>
              Get credentials
            </div>

            <div className="connect-tabs" style={{ marginBottom: 14 }}>
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
              <div className="connect-tab-content">
                <p className="connect-tab-desc">Export your kubeconfig and paste it below:</p>
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
              <div className="connect-tab-content">
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
                      For a minimal role, see <code>manifests/rbac.yaml</code>.
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
                    04 — Get cluster server URL
                    <InfoTip>
                      This is the <code>server:</code> field in your kubeconfig.<br />
                      Looks like <code>https://&lt;ip-or-hostname&gt;:6443</code>.
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
            <div className="connect-deploy-note" style={{ marginTop: 4 }}>
              <span className="connect-step-num">LABEL</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                  Tag deployments that should scale down:
                </div>
                <div className="cmd-block">
                  <code>kubectl label deployment &lt;name&gt; finops.io/scaledown-eligible=true</code>
                  <CopyButton text="kubectl label deployment <name> finops.io/scaledown-eligible=true" />
                </div>
              </div>
            </div>
          </div>

          {/* ── Quick schedule ── */}
          <div className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// SCHED</span>
              Scale schedule
              <span className="settings-controller-note">saved on connect</span>
            </div>

            <div className="settings-field">
              <label className="settings-label">Active days</label>
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
              <label className="settings-label">Business hours</label>
              <div className="settings-input-row">
                <input
                  className="settings-input"
                  type="time"
                  value={schedStart}
                  onChange={e => setSchedStart(e.target.value)}
                />
                <span className="settings-time-sep">to</span>
                <input
                  className="settings-input"
                  type="time"
                  value={schedEnd}
                  onChange={e => setSchedEnd(e.target.value)}
                />
              </div>
            </div>

            <div className="settings-field">
              <label className="settings-label">
                Timezone
                <InfoTip>
                  IANA timezone name. Examples:<br />
                  <strong>America/New_York</strong><br />
                  <strong>Europe/London</strong><br />
                  <strong>Asia/Kolkata</strong>
                </InfoTip>
              </label>
              <input
                className="settings-input"
                value={timezone}
                onChange={e => setTimezone(e.target.value)}
                placeholder="UTC"
                spellCheck={false}
              />
            </div>
          </div>

          {/* ── kubeconfig paste ── */}
          <div className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// YAML</span>
              kubeconfig
              <span className="required-badge" style={{ marginLeft: 'auto' }}>REQUIRED</span>
            </div>

            <textarea
              className="connect-kubeconfig"
              style={{ minHeight: 160 }}
              value={kubeconfig}
              onChange={e => setKubeconfig(e.target.value)}
              placeholder={KUBECONFIG_PLACEHOLDER}
              spellCheck={false}
              autoComplete="off"
            />
            {error && <div className="connect-error" style={{ marginTop: 10 }}>{error}</div>}
          </div>

        </div>{/* /drawer-body */}

        {/* ── Footer ── */}
        <div className="drawer-footer">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!kubeconfig.trim() || connecting}
            onClick={handleConnect}
          >
            {connecting ? 'Validating…' : connected ? 'Reconnect →' : 'Save Schedule & Connect →'}
          </button>
        </div>
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
