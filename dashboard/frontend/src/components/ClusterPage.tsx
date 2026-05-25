import { useState } from 'react'
import type { ConfigData, ControllerStatus, EksCluster, GkeCluster } from '../api'
import {
  AWS_REGIONS,
  connectCluster, connectEks, connectGke,
  listEksClusters, listGkeClusters,
  saveConfig, stopController,
} from '../api'
import Toggle from './Toggle'

interface Props {
  config:             ConfigData
  controllerStatus:   ControllerStatus | null
  onConnected:        (s: ControllerStatus) => void
  onConfigChange:     (c: ConfigData) => void
  onControllerChange: (s: ControllerStatus) => void
}

type Provider = 'kubeconfig' | 'eks' | 'gke'
type Toast    = { msg: string; kind: 'success' | 'error' } | null

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function parseDays(str: string): Set<number> {
  return new Set(str.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)))
}

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

// ── Credentials sidebar ────────────────────────────────────────
function CredsSidebar({ onClose, initialProvider }: { onClose: () => void; initialProvider: Provider }) {
  const [tab, setTab] = useState<Provider>(initialProvider)

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer drawer--wide" role="dialog" aria-modal aria-label="Get Credentials">
        <div className="drawer-header">
          <span className="drawer-title">Get Credentials</span>
          <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="drawer-body">
          <div className="connect-tabs" style={{ marginBottom: 20 }}>
            {(['kubeconfig', 'eks', 'gke'] as Provider[]).map(p => (
              <button
                key={p}
                className={`connect-tab ${tab === p ? 'active' : ''}`}
                onClick={() => setTab(p)}
              >
                {p === 'kubeconfig' ? 'Kubeconfig' : p === 'eks' ? 'AWS EKS' : 'GCP GKE'}
              </button>
            ))}
          </div>

          {tab === 'kubeconfig' && (
            <>
              <div className="settings-section">
                <div className="settings-section-header">
                  <span className="settings-section-icon">// EXPORT</span>
                  Already have kubectl
                </div>
                <p className="connect-tab-desc">Export your kubeconfig file:</p>
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

              <div className="settings-section">
                <div className="settings-section-header">
                  <span className="settings-section-icon">// SA</span>
                  Create a dedicated service account
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">01 — Create service account</div>
                  <div className="cmd-block">
                    <code>kubectl create sa finops-scaler -n kube-system</code>
                    <CopyButton text="kubectl create sa finops-scaler -n kube-system" />
                  </div>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">02 — Grant cluster-admin</div>
                  <div className="cmd-block cmd-block--multi">
                    <code>{`kubectl create clusterrolebinding finops-scaler \\\n  --clusterrole=cluster-admin \\\n  --serviceaccount=kube-system:finops-scaler`}</code>
                    <CopyButton text="kubectl create clusterrolebinding finops-scaler --clusterrole=cluster-admin --serviceaccount=kube-system:finops-scaler" />
                  </div>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">03 — Generate long-lived token</div>
                  <div className="cmd-block">
                    <code>kubectl create token finops-scaler -n kube-system --duration=8760h</code>
                    <CopyButton text="kubectl create token finops-scaler -n kube-system --duration=8760h" />
                  </div>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">04 — Get server URL</div>
                  <div className="cmd-block">
                    <code>{`kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'`}</code>
                    <CopyButton text={`kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'`} />
                  </div>
                </div>
              </div>

              <div className="connect-deploy-note">
                <span className="connect-step-num">LABEL</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                    Tag deployments eligible for scale-down:
                  </div>
                  <div className="cmd-block">
                    <code>kubectl label deployment &lt;name&gt; finops.io/scaledown-eligible=true</code>
                    <CopyButton text="kubectl label deployment <name> finops.io/scaledown-eligible=true" />
                  </div>
                </div>
              </div>
            </>
          )}

          {tab === 'eks' && (
            <>
              <div className="settings-section">
                <div className="settings-section-header">
                  <span className="settings-section-icon">// IAM</span>
                  Create an IAM access key
                </div>
                <p className="connect-tab-desc">No kubeconfig file needed — IAM credentials are used directly.</p>
                <div className="cmd-step">
                  <div className="cmd-step-label">01 — Open IAM in the AWS Console</div>
                  <p className="connect-tab-desc">
                    <strong>IAM → Users</strong> → select or create a user →
                    <strong> Security credentials → Create access key</strong>.
                  </p>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">02 — Minimum required permissions</div>
                  <div className="cmd-block cmd-block--multi" style={{ fontSize: 11 }}>
                    <code>{`"Action": [\n  "eks:ListClusters",\n  "eks:DescribeCluster"\n],\n"Effect": "Allow",\n"Resource": "*"`}</code>
                    <CopyButton text={`{ "Action": ["eks:ListClusters", "eks:DescribeCluster"], "Effect": "Allow", "Resource": "*" }`} />
                  </div>
                  <p className="connect-tab-desc" style={{ marginTop: 8 }}>
                    Or attach the <strong>AmazonEKSClusterPolicy</strong> managed policy.
                  </p>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">03 — Ensure the IAM principal can access the cluster</div>
                  <div className="cmd-block cmd-block--multi">
                    <code>{`aws eks update-kubeconfig \\\n  --region <region> --name <cluster>`}</code>
                    <CopyButton text="aws eks update-kubeconfig --region <region> --name <cluster>" />
                  </div>
                  <p className="connect-tab-desc" style={{ marginTop: 8 }}>
                    Or add the IAM user to the cluster's <code>aws-auth</code> ConfigMap.
                  </p>
                </div>
              </div>

              <div className="connect-deploy-note">
                <span className="connect-step-num">LABEL</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                    Tag deployments eligible for scale-down:
                  </div>
                  <div className="cmd-block">
                    <code>kubectl label deployment &lt;name&gt; finops.io/scaledown-eligible=true</code>
                    <CopyButton text="kubectl label deployment <name> finops.io/scaledown-eligible=true" />
                  </div>
                </div>
              </div>
            </>
          )}

          {tab === 'gke' && (
            <>
              <div className="settings-section">
                <div className="settings-section-header">
                  <span className="settings-section-icon">// SA</span>
                  Create a service account JSON key
                </div>
                <p className="connect-tab-desc">No kubeconfig file needed — paste the JSON key directly into the form.</p>
                <div className="cmd-step">
                  <div className="cmd-step-label">01 — Create service account</div>
                  <div className="cmd-block cmd-block--multi">
                    <code>{`gcloud iam service-accounts create finops-scaler \\\n  --display-name="FinOps Scaler"`}</code>
                    <CopyButton text="gcloud iam service-accounts create finops-scaler --display-name=FinOps Scaler" />
                  </div>
                  <p className="connect-tab-desc" style={{ marginTop: 8 }}>
                    Or: <strong>Console → IAM &amp; Admin → Service Accounts → Create</strong>.
                  </p>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">02 — Grant Kubernetes Engine Viewer role</div>
                  <div className="cmd-block cmd-block--multi">
                    <code>{`gcloud projects add-iam-policy-binding PROJECT_ID \\\n  --member="serviceAccount:finops-scaler@PROJECT_ID.iam.gserviceaccount.com" \\\n  --role="roles/container.viewer"`}</code>
                    <CopyButton text='gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:finops-scaler@PROJECT_ID.iam.gserviceaccount.com" --role="roles/container.viewer"' />
                  </div>
                </div>
                <div className="cmd-step">
                  <div className="cmd-step-label">03 — Download JSON key</div>
                  <div className="cmd-block cmd-block--multi">
                    <code>{`gcloud iam service-accounts keys create key.json \\\n  --iam-account=finops-scaler@PROJECT_ID.iam.gserviceaccount.com`}</code>
                    <CopyButton text="gcloud iam service-accounts keys create key.json --iam-account=finops-scaler@PROJECT_ID.iam.gserviceaccount.com" />
                  </div>
                  <p className="connect-tab-desc" style={{ marginTop: 8 }}>
                    Paste the full contents of <code>key.json</code> into the form.
                  </p>
                </div>
              </div>

              <div className="connect-deploy-note">
                <span className="connect-step-num">LABEL</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                    Tag deployments eligible for scale-down:
                  </div>
                  <div className="cmd-block">
                    <code>kubectl label deployment &lt;name&gt; finops.io/scaledown-eligible=true</code>
                    <CopyButton text="kubectl label deployment <name> finops.io/scaledown-eligible=true" />
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}

// ── Main component ─────────────────────────────────────────────
export default function ClusterPage({
  config, controllerStatus, onConnected, onConfigChange, onControllerChange,
}: Props) {
  const [provider, setProvider] = useState<Provider>('kubeconfig')

  // Kubeconfig
  const [kubeconfig, setKubeconfig] = useState('')

  // AWS EKS
  const [awsRegion,    setAwsRegion]    = useState('us-east-1')
  const [awsKeyId,     setAwsKeyId]     = useState('')
  const [awsSecretKey, setAwsSecretKey] = useState('')
  const [eksClusters,  setEksClusters]  = useState<EksCluster[]>([])

  // GCP GKE
  const [gcpProject,  setGcpProject]  = useState('')
  const [gcpLocation, setGcpLocation] = useState('-')
  const [gcpJson,     setGcpJson]     = useState('')
  const [gkeClusters, setGkeClusters] = useState<GkeCluster[]>([])

  // Shared
  const [selectedCluster, setSelectedCluster] = useState('')
  const [listingClusters, setListingClusters] = useState(false)
  const [connecting,      setConnecting]      = useState(false)
  const [stopping,        setStopping]        = useState(false)
  const [error,           setError]           = useState<string | null>(null)
  const [toast,           setToast]           = useState<Toast>(null)
  const [credsOpen,       setCredsOpen]       = useState(false)

  // Schedule
  const [schedStart, setSchedStart] = useState(config.business_hours_start)
  const [schedEnd,   setSchedEnd]   = useState(config.business_hours_end)
  const [timezone,   setTimezone]   = useState(config.timezone || 'UTC')
  const [prewarm,    setPrewarm]    = useState(config.prewarm_minutes ?? 15)
  const [activeDays, setActiveDays] = useState<Set<number>>(() => parseDays(config.business_days))

  // Data source
  const [demoMode, setDemoMode] = useState(config.demo_mode)
  const [promUrl,  setPromUrl]  = useState(config.prometheus_url)

  // Controller config
  const [nsFilter,     setNsFilter]     = useState(config.namespace_filter || '')
  const [minFloor,     setMinFloor]     = useState(config.min_replica_floor ?? 0)
  const [pollInterval, setPollInterval] = useState(config.poll_interval_seconds ?? 30)

  const connected = controllerStatus?.connected ?? false

  function toggleDay(i: number) {
    setActiveDays(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  function switchProvider(p: Provider) {
    setProvider(p)
    setSelectedCluster('')
    setEksClusters([])
    setGkeClusters([])
    setError(null)
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

  async function handleSaveConfig() {
    try {
      const saved = await saveConfig({
        ...config,
        prometheus_url:       promUrl,
        business_hours_start: schedStart,
        business_hours_end:   schedEnd,
        timezone,
        prewarm_minutes:      prewarm,
        business_days:        [...activeDays].sort((a, b) => a - b).join(','),
        namespace_filter:     nsFilter,
        min_replica_floor:    minFloor,
        poll_interval_seconds: pollInterval,
      })
      onConfigChange(saved)
      showToast('Configuration saved', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Save failed', 'error')
    }
  }

  async function handleListEksClusters() {
    setListingClusters(true); setError(null)
    try {
      const clusters = await listEksClusters(awsRegion, awsKeyId, awsSecretKey)
      setEksClusters(clusters)
      if (clusters.length === 0) setError('No EKS clusters found in this region')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to list clusters')
    } finally { setListingClusters(false) }
  }

  async function handleListGkeClusters() {
    setListingClusters(true); setError(null)
    try {
      const clusters = await listGkeClusters(gcpProject, gcpLocation, gcpJson)
      setGkeClusters(clusters)
      if (clusters.length === 0) setError('No GKE clusters found in this project/location')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to list clusters')
    } finally { setListingClusters(false) }
  }

  async function handleConnect() {
    if (provider === 'kubeconfig' && !kubeconfig.trim()) return
    if (provider !== 'kubeconfig' && !selectedCluster) return
    setConnecting(true); setError(null)
    try {
      const saved = await saveConfig({
        ...config,
        demo_mode:            false,
        prometheus_url:       promUrl,
        business_hours_start: schedStart,
        business_hours_end:   schedEnd,
        timezone,
        prewarm_minutes:      prewarm,
        business_days:        [...activeDays].sort((a, b) => a - b).join(','),
        namespace_filter:     nsFilter,
        min_replica_floor:    minFloor,
        poll_interval_seconds: pollInterval,
      })
      onConfigChange(saved)

      let status: ControllerStatus
      if (provider === 'kubeconfig') {
        status = await connectCluster(kubeconfig.trim())
      } else if (provider === 'eks') {
        status = await connectEks(awsRegion, selectedCluster, awsKeyId, awsSecretKey)
      } else {
        const cluster = gkeClusters.find(c => c.name === selectedCluster)!
        status = await connectGke(gcpProject, cluster.location, selectedCluster, gcpJson)
      }
      onConnected(status)
      showToast('Connected — controller is running', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed — check credentials and reachability')
    } finally { setConnecting(false) }
  }

  async function handleStop() {
    setStopping(true)
    try {
      const status = await stopController()
      onControllerChange(status)
      showToast('Controller stopped', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Stop failed', 'error')
    } finally { setStopping(false) }
  }

  const connectDisabled =
    connecting ||
    (provider === 'kubeconfig' && !kubeconfig.trim()) ||
    (provider !== 'kubeconfig' && !selectedCluster)

  const connectLabel = connecting
    ? 'Validating credentials…'
    : connected
      ? 'Reconnect with new credentials →'
      : provider === 'kubeconfig'
        ? 'Connect →'
        : `Connect to ${selectedCluster || '…'} →`

  return (
    <div className="cluster-page">

      {/* ── Page header ── */}
      <div className="cluster-page-header">
        <div>
          <div className="cluster-page-tag">// CLUSTER</div>
          <h1 className="cluster-page-title">Cluster Connection</h1>
          <p className="cluster-page-desc">
            Connect this controller to your Kubernetes cluster. No in-cluster install required.
          </p>
        </div>

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

      {/* ── Hero: Connection method ── */}
      {!demoMode && (
        <section className="cluster-hero">
          <div className="cluster-hero-header">
            <div>
              <div className="cluster-hero-tag">// CONNECT</div>
              <div className="cluster-hero-title">Connection method</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="required-badge">REQUIRED</span>
              <button className="btn-ghost cluster-creds-btn" onClick={() => setCredsOpen(true)}>
                Get credentials ↗
              </button>
            </div>
          </div>

          {/* Large provider tabs */}
          <div className="cluster-provider-tabs">
            {([
              { id: 'kubeconfig', tag: '// YAML',  label: 'Kubeconfig',  desc: 'Paste your kubeconfig YAML' },
              { id: 'eks',        tag: '// AWS',   label: 'AWS EKS',     desc: 'IAM access key credentials' },
              { id: 'gke',        tag: '// GCP',   label: 'GCP GKE',     desc: 'Service account JSON key'   },
            ] as { id: Provider; tag: string; label: string; desc: string }[]).map(p => (
              <button
                key={p.id}
                type="button"
                className={`cluster-provider-tab ${provider === p.id ? 'active' : ''}`}
                onClick={() => switchProvider(p.id)}
              >
                <div className="cluster-provider-tab-tag">{p.tag}</div>
                <div className="cluster-provider-tab-name">{p.label}</div>
                <div className="cluster-provider-tab-desc">{p.desc}</div>
              </button>
            ))}
          </div>

          {/* Provider form */}
          <div className="cluster-provider-form">

            {provider === 'kubeconfig' && (
              <textarea
                className="connect-kubeconfig cluster-kubeconfig"
                value={kubeconfig}
                onChange={e => setKubeconfig(e.target.value)}
                placeholder={KUBECONFIG_PLACEHOLDER}
                spellCheck={false}
                autoComplete="off"
              />
            )}

            {provider === 'eks' && (
              <div className="cluster-form-grid">
                <div className="cluster-form-field">
                  <label className="cluster-form-label">Region</label>
                  <select
                    className="cluster-form-input"
                    value={awsRegion}
                    onChange={e => setAwsRegion(e.target.value)}
                  >
                    {AWS_REGIONS.map(r => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
                <div className="cluster-form-field">
                  <label className="cluster-form-label">Access Key ID</label>
                  <input
                    className="cluster-form-input"
                    value={awsKeyId}
                    onChange={e => setAwsKeyId(e.target.value)}
                    placeholder="AKIA…"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="cluster-form-field">
                  <label className="cluster-form-label">Secret Access Key</label>
                  <input
                    className="cluster-form-input"
                    type="password"
                    value={awsSecretKey}
                    onChange={e => setAwsSecretKey(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                <div className="cluster-form-field cluster-form-field--action">
                  <button
                    className="btn-ghost cluster-list-btn"
                    disabled={!awsKeyId || !awsSecretKey || listingClusters}
                    onClick={handleListEksClusters}
                  >
                    {listingClusters ? 'Listing…' : 'List clusters →'}
                  </button>
                </div>
                {eksClusters.length > 0 && (
                  <div className="cluster-form-field" style={{ gridColumn: '1 / -1' }}>
                    <label className="cluster-form-label">Select cluster</label>
                    <div className="cluster-cluster-pills">
                      {eksClusters.map(c => (
                        <button
                          key={c.name}
                          type="button"
                          className={`cluster-cluster-pill ${selectedCluster === c.name ? 'active' : ''}`}
                          onClick={() => setSelectedCluster(c.name)}
                          title={`${c.kubernetes_version} · ${c.status}`}
                        >
                          {c.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {provider === 'gke' && (
              <div className="cluster-form-grid">
                <div className="cluster-form-field">
                  <label className="cluster-form-label">Project ID</label>
                  <input
                    className="cluster-form-input"
                    value={gcpProject}
                    onChange={e => setGcpProject(e.target.value)}
                    placeholder="my-gcp-project"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="cluster-form-field">
                  <label className="cluster-form-label">
                    Location
                    <InfoTip>
                      Region or zone (e.g. <code>us-central1</code>).<br />
                      Use <code>-</code> to list across all locations.
                    </InfoTip>
                  </label>
                  <input
                    className="cluster-form-input"
                    value={gcpLocation}
                    onChange={e => setGcpLocation(e.target.value)}
                    placeholder="-"
                    spellCheck={false}
                  />
                </div>
                <div className="cluster-form-field" style={{ gridColumn: '1 / -1' }}>
                  <label className="cluster-form-label">
                    Service Account JSON
                    <InfoTip>
                      Full contents of your service account key JSON file.<br />
                      Requires <code>container.clusters.list</code> and <code>container.clusters.get</code>.
                    </InfoTip>
                  </label>
                  <textarea
                    className="connect-kubeconfig cluster-kubeconfig cluster-kubeconfig--short"
                    value={gcpJson}
                    onChange={e => setGcpJson(e.target.value)}
                    placeholder={'{ "type": "service_account", ... }'}
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="cluster-form-field cluster-form-field--action">
                  <button
                    className="btn-ghost cluster-list-btn"
                    disabled={!gcpProject || !gcpJson || listingClusters}
                    onClick={handleListGkeClusters}
                  >
                    {listingClusters ? 'Listing…' : 'List clusters →'}
                  </button>
                </div>
                {gkeClusters.length > 0 && (
                  <div className="cluster-form-field" style={{ gridColumn: '1 / -1' }}>
                    <label className="cluster-form-label">Select cluster</label>
                    <div className="cluster-cluster-pills">
                      {gkeClusters.map(c => (
                        <button
                          key={c.name}
                          type="button"
                          className={`cluster-cluster-pill ${selectedCluster === c.name ? 'active' : ''}`}
                          onClick={() => setSelectedCluster(c.name)}
                          title={`${c.location} · ${c.kubernetes_version}`}
                        >
                          {c.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {error && <div className="connect-error" style={{ marginTop: 12 }}>{error}</div>}

          <button
            className="btn-primary cluster-connect-cta"
            disabled={connectDisabled}
            onClick={handleConnect}
          >
            {connectLabel}
          </button>
        </section>
      )}

      {/* ── Demo mode active ── */}
      {demoMode && (
        <div className="cluster-demo-banner">
          <div className="cluster-demo-banner-icon">∿</div>
          <div>
            <div className="cluster-demo-banner-title">Synthetic data active</div>
            <div className="cluster-demo-banner-desc">
              All metrics, nodes, savings, and events are generated from a deterministic algorithm.
              Toggle Demo Mode off in the Data Source section below to connect a real cluster.
            </div>
          </div>
        </div>
      )}

      {/* ── Lower config grid ── */}
      <div className={`cluster-lower-grid ${demoMode ? 'cluster-lower-grid--demo' : ''}`}>

        {/* Scale schedule */}
        <div className="cluster-lower-section">
          <div className="cluster-lower-header">
            <span className="cluster-lower-tag">// SCHED</span>
            Scale schedule
            <span className="cluster-lower-note">saved on connect</span>
          </div>

          <div className="cluster-lower-field">
            <label className="cluster-lower-label">Active days</label>
            <div className="cluster-day-pills">
              {DAYS.map((label, i) => (
                <button
                  key={i}
                  type="button"
                  className={`cluster-day-pill ${activeDays.has(i) ? 'active' : ''}`}
                  onClick={() => toggleDay(i)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="cluster-lower-field">
            <label className="cluster-lower-label">Business hours</label>
            <div className="cluster-time-row">
              <input
                className="cluster-lower-input"
                type="time"
                value={schedStart}
                onChange={e => setSchedStart(e.target.value)}
              />
              <span className="cluster-time-sep">→</span>
              <input
                className="cluster-lower-input"
                type="time"
                value={schedEnd}
                onChange={e => setSchedEnd(e.target.value)}
              />
            </div>
          </div>

          <div className="cluster-lower-field">
            <label className="cluster-lower-label">
              Timezone
              <InfoTip>
                IANA timezone name.<br />
                Examples: <strong>America/New_York</strong>, <strong>Europe/London</strong>, <strong>Asia/Kolkata</strong>
              </InfoTip>
            </label>
            <input
              className="cluster-lower-input"
              value={timezone}
              onChange={e => setTimezone(e.target.value)}
              placeholder="UTC"
              spellCheck={false}
            />
          </div>

          <div className="cluster-lower-field">
            <label className="cluster-lower-label">Pre-warm (min)</label>
            <input
              className="cluster-lower-input cluster-lower-input--short"
              type="number"
              min="0"
              max="60"
              value={prewarm}
              onChange={e => setPrewarm(parseInt(e.target.value) || 0)}
            />
          </div>
        </div>

        {/* Data source */}
        <div className="cluster-lower-section">
          <div className="cluster-lower-header">
            <span className="cluster-lower-tag">// SOURCE</span>
            Data source
          </div>

          <div className="cluster-lower-field">
            <div className="cluster-lower-field-row">
              <div>
                <div className="cluster-lower-label">Demo Mode</div>
                <div className="cluster-lower-hint">Synthetic data — no K8s or Prometheus needed</div>
              </div>
              <Toggle checked={demoMode} onChange={handleDemoToggle} />
            </div>
          </div>

          {!demoMode && (
            <div className="cluster-lower-field">
              <label className="cluster-lower-label">
                Prometheus URL
                <InfoTip>
                  Base URL for your Prometheus instance.<br />
                  Example: <code>http://prometheus:9090</code>
                </InfoTip>
              </label>
              <input
                className="cluster-lower-input"
                type="url"
                value={promUrl}
                onChange={e => setPromUrl(e.target.value)}
                placeholder="http://prometheus:9090"
                spellCheck={false}
              />
            </div>
          )}
        </div>

        {/* Controller config */}
        {!demoMode && (
          <div className="cluster-lower-section">
            <div className="cluster-lower-header">
              <span className="cluster-lower-tag">// CTRL</span>
              Controller settings
            </div>

            <div className="cluster-lower-field">
              <label className="cluster-lower-label">
                Namespace filter
                <InfoTip>
                  Restrict scale-down to a single namespace.<br />
                  Leave blank to target all namespaces.
                </InfoTip>
              </label>
              <input
                className="cluster-lower-input"
                value={nsFilter}
                onChange={e => setNsFilter(e.target.value)}
                placeholder="all namespaces"
                spellCheck={false}
              />
            </div>

            <div className="cluster-lower-field">
              <label className="cluster-lower-label">
                Min replica floor
                <InfoTip>Scale-down target replica count. 0 scales deployments fully down.</InfoTip>
              </label>
              <input
                className="cluster-lower-input cluster-lower-input--short"
                type="number"
                min="0"
                max="10"
                value={minFloor}
                onChange={e => setMinFloor(parseInt(e.target.value) || 0)}
              />
            </div>

            <div className="cluster-lower-field">
              <label className="cluster-lower-label">Poll interval (sec)</label>
              <input
                className="cluster-lower-input cluster-lower-input--short"
                type="number"
                min="10"
                max="300"
                value={pollInterval}
                onChange={e => setPollInterval(parseInt(e.target.value) || 30)}
              />
            </div>

            <button
              className="btn-ghost"
              style={{ marginTop: 8, width: '100%', fontSize: 12 }}
              onClick={handleSaveConfig}
            >
              Save settings
            </button>
          </div>
        )}
      </div>

      {/* Credentials sidebar */}
      {credsOpen && (
        <CredsSidebar
          onClose={() => setCredsOpen(false)}
          initialProvider={provider}
        />
      )}

      {toast && (
        <div className={`toast toast-${toast.kind}`}>
          <span>{toast.kind === 'success' ? '✓' : '✕'}</span>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
