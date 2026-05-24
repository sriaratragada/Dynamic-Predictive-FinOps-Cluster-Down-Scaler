import { useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'
import { connectCluster, saveConfig } from '../api'

interface Props {
  config: ConfigData
  onConnected: (s: ControllerStatus) => void
  onConfigChange?: (c: ConfigData) => void
}

type Tab = 'paste' | 'generate'

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

export default function ConnectCard({ config, onConnected, onConfigChange }: Props) {
  const [tab, setTab] = useState<Tab>('paste')
  const [kubeconfig, setKubeconfig] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Inline schedule state — seeded from config
  const [schedStart, setSchedStart] = useState(config.business_hours_start)
  const [schedEnd,   setSchedEnd]   = useState(config.business_hours_end)
  const [timezone,   setTimezone]   = useState(config.timezone || 'UTC')
  const [activeDays, setActiveDays] = useState<Set<number>>(() => parseDays(config.business_days))

  function toggleDay(i: number) {
    setActiveDays(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  async function handleConnect() {
    if (!kubeconfig.trim()) return
    setConnecting(true)
    setError(null)
    try {
      // Save schedule + disable demo mode first
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

      // Then connect
      const status = await connectCluster(kubeconfig.trim())
      onConnected(status)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed — check credentials and cluster reachability')
    } finally {
      setConnecting(false)
    }
  }

  return (
    <div className="connect-card" data-reveal="1">
      <div className="connect-card-beam" />
      <div className="connect-card-body">

        {/* ── Left: instructions ── */}
        <div className="connect-card-info">
          <div className="connect-card-tag">CLUSTER SETUP</div>
          <h2 className="connect-card-title">Connect your cluster</h2>
          <p className="connect-card-desc">
            The controller runs inside this container — no Helm chart needed.
            Paste credentials and it connects directly to your K8s API server.
          </p>

          {/* Tabs */}
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
            <div className="connect-tab-content">
              <p className="connect-tab-desc">Export your current kubeconfig, then paste it →</p>
              <div className="cmd-block">
                <code>cat ~/.kube/config</code>
                <CopyButton text="cat ~/.kube/config" />
              </div>
              <p className="connect-tab-desc" style={{ marginTop: 10 }}>
                Or just the active context:
              </p>
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
                    For a minimal role, see the RBAC manifest in <code>manifests/rbac.yaml</code>.
                  </InfoTip>
                </div>
                <div className="cmd-block cmd-block--multi">
                  <code>{`kubectl create clusterrolebinding finops-scaler \\\n  --clusterrole=cluster-admin \\\n  --serviceaccount=kube-system:finops-scaler`}</code>
                  <CopyButton text={`kubectl create clusterrolebinding finops-scaler --clusterrole=cluster-admin --serviceaccount=kube-system:finops-scaler`} />
                </div>
              </div>
              <div className="cmd-step">
                <div className="cmd-step-label">03 — Generate a token (1-year expiry)</div>
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
          <div className="connect-deploy-note">
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

        {/* ── Right: schedule + kubeconfig ── */}
        <div className="connect-card-form">

          {/* Quick Schedule */}
          <div className="connect-schedule-block">
            <div className="connect-field-header" style={{ marginBottom: 10 }}>
              <span className="connect-field-label">Schedule</span>
              <span className="connect-hint">Active window — scale-up and scale-down times</span>
            </div>

            <div className="connect-schedule-row">
              <div className="connect-schedule-field">
                <label className="connect-sched-label">
                  Scale-up before
                  <InfoTip>
                    Cluster warms up at this time on active days.<br />
                    24-hour format in your chosen timezone.
                  </InfoTip>
                </label>
                <input
                  className="connect-sched-input"
                  type="time"
                  value={schedStart}
                  onChange={e => setSchedStart(e.target.value)}
                />
              </div>
              <div className="connect-sched-sep">→</div>
              <div className="connect-schedule-field">
                <label className="connect-sched-label">Scale-down after</label>
                <input
                  className="connect-sched-input"
                  type="time"
                  value={schedEnd}
                  onChange={e => setSchedEnd(e.target.value)}
                />
              </div>
            </div>

            <div style={{ marginTop: 10 }}>
              <label className="connect-sched-label">
                Timezone
                <InfoTip>
                  IANA timezone name. Examples:<br />
                  <strong>America/New_York</strong><br />
                  <strong>Europe/London</strong><br />
                  <strong>Asia/Kolkata</strong><br />
                  <strong>Asia/Tokyo</strong><br />
                  Full list: wikipedia.org/wiki/List_of_tz_database_time_zones
                </InfoTip>
              </label>
              <input
                className="connect-sched-input-full"
                value={timezone}
                onChange={e => setTimezone(e.target.value)}
                placeholder="UTC"
                spellCheck={false}
              />
            </div>

            <div style={{ marginTop: 10 }}>
              <label className="connect-sched-label">Active days</label>
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
          </div>

          {/* Kubeconfig paste */}
          <div style={{ marginTop: 16 }}>
            <div className="connect-field-header" style={{ marginBottom: 6 }}>
              <span className="connect-field-label">
                kubeconfig YAML
                <InfoTip>
                  Your kubeconfig contains:<br />
                  • <strong>server</strong> — K8s API endpoint URL<br />
                  • <strong>token</strong> or cert — auth credentials<br /><br />
                  Found at <code>~/.kube/config</code> or use the<br />
                  "Need credentials" tab to generate one.
                </InfoTip>
              </span>
              <span className="required-badge">REQUIRED</span>
            </div>
            <textarea
              className="connect-kubeconfig"
              value={kubeconfig}
              onChange={e => setKubeconfig(e.target.value)}
              placeholder={KUBECONFIG_PLACEHOLDER}
              spellCheck={false}
              autoComplete="off"
            />
          </div>

          {error && <div className="connect-error">{error}</div>}

          <button
            className="btn-primary"
            style={{ width: '100%', marginTop: 12 }}
            disabled={!kubeconfig.trim() || connecting}
            onClick={handleConnect}
          >
            {connecting ? 'Validating credentials…' : 'Save Schedule & Connect →'}
          </button>

          <p className="connect-footnote">
            No cluster? Enable <strong>Demo Mode</strong> in <strong>⚙ Settings → // CONN</strong>
          </p>
        </div>

      </div>
    </div>
  )
}
