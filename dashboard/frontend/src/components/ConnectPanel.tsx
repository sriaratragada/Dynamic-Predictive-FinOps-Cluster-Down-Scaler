import { useEffect, useState } from 'react'
import type { ConfigData, ControllerStatus, EksCluster, GkeCluster } from '../api'
import {
  AWS_REGIONS,
  connectCluster, connectEks, connectGke,
  listEksClusters, listGkeClusters,
  saveConfig, stopController,
} from '../api'

interface Props {
  config:              ConfigData
  controllerStatus?:   ControllerStatus | null
  onClose:             () => void
  onConnected:         (s: ControllerStatus) => void
  onConfigChange?:     (c: ConfigData) => void
  onControllerChange?: (s: ControllerStatus) => void
}

type Provider = 'kubeconfig' | 'eks' | 'gke'
type Toast    = { msg: string; kind: 'success' | 'error' } | null

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

export default function ConnectPanel({
  config, controllerStatus, onClose, onConnected, onConfigChange, onControllerChange,
}: Props) {
  const [provider, setProvider] = useState<Provider>('kubeconfig')

  // Kubeconfig paste
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

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

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

  async function handleListEksClusters() {
    setListingClusters(true)
    setError(null)
    try {
      const clusters = await listEksClusters(awsRegion, awsKeyId, awsSecretKey)
      setEksClusters(clusters)
      if (clusters.length === 0) setError('No EKS clusters found in this region')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to list clusters')
    } finally {
      setListingClusters(false)
    }
  }

  async function handleListGkeClusters() {
    setListingClusters(true)
    setError(null)
    try {
      const clusters = await listGkeClusters(gcpProject, gcpLocation, gcpJson)
      setGkeClusters(clusters)
      if (clusters.length === 0) setError('No GKE clusters found in this project/location')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to list clusters')
    } finally {
      setListingClusters(false)
    }
  }

  async function handleConnect() {
    if (provider === 'kubeconfig' && !kubeconfig.trim()) return
    if (provider !== 'kubeconfig' && !selectedCluster) return
    setConnecting(true)
    setError(null)
    try {
      const saved = await saveConfig({ ...config, demo_mode: false })
      onConfigChange?.(saved)

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

  const connectDisabled =
    connecting ||
    (provider === 'kubeconfig' && !kubeconfig.trim()) ||
    (provider !== 'kubeconfig' && !selectedCluster)

  const connectLabel = connecting
    ? 'Validating…'
    : connected
      ? (provider === 'kubeconfig' ? 'Reconnect →' : `Reconnect to ${selectedCluster || '…'} →`)
      : (provider === 'kubeconfig' ? 'Connect →' : `Connect to ${selectedCluster || '…'} →`)

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

          {/* Connected state */}
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
                To connect a different cluster, choose a provider below and click Connect again.
              </div>
            </div>
          )}

          {/* Provider + cluster form */}
          <div className="settings-section">
            <div className="settings-section-header">
              <span className="settings-section-icon">// CLUSTER</span>
              Connection method
              <span className="required-badge" style={{ marginLeft: 'auto' }}>REQUIRED</span>
            </div>

            {/* Provider pills */}
            <div className="settings-field">
              <div className="day-pills">
                {(['kubeconfig', 'eks', 'gke'] as Provider[]).map(p => (
                  <button
                    key={p}
                    type="button"
                    className={`day-pill ${provider === p ? 'active' : ''}`}
                    onClick={() => switchProvider(p)}
                  >
                    {p === 'kubeconfig' ? 'Kubeconfig' : p === 'eks' ? 'AWS EKS' : 'GCP GKE'}
                  </button>
                ))}
              </div>
            </div>

            {/* Kubeconfig textarea */}
            {provider === 'kubeconfig' && (
              <textarea
                className="connect-kubeconfig"
                style={{ minHeight: 160 }}
                value={kubeconfig}
                onChange={e => setKubeconfig(e.target.value)}
                placeholder={KUBECONFIG_PLACEHOLDER}
                spellCheck={false}
                autoComplete="off"
              />
            )}

            {/* AWS EKS */}
            {provider === 'eks' && (
              <>
                <div className="settings-field">
                  <label className="settings-label">Region</label>
                  <select
                    className="settings-input"
                    value={awsRegion}
                    onChange={e => setAwsRegion(e.target.value)}
                  >
                    {AWS_REGIONS.map(r => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
                <div className="settings-field">
                  <label className="settings-label">Access Key ID</label>
                  <input
                    className="settings-input"
                    value={awsKeyId}
                    onChange={e => setAwsKeyId(e.target.value)}
                    placeholder="AKIA…"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="settings-field">
                  <label className="settings-label">Secret Access Key</label>
                  <input
                    className="settings-input"
                    type="password"
                    value={awsSecretKey}
                    onChange={e => setAwsSecretKey(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                <button
                  className="btn-ghost"
                  style={{ width: '100%', marginBottom: 4 }}
                  disabled={!awsKeyId || !awsSecretKey || listingClusters}
                  onClick={handleListEksClusters}
                >
                  {listingClusters ? 'Listing clusters…' : 'List clusters →'}
                </button>
                {eksClusters.length > 0 && (
                  <div className="settings-field">
                    <label className="settings-label">Select cluster</label>
                    <div className="day-pills" style={{ flexWrap: 'wrap' }}>
                      {eksClusters.map(c => (
                        <button
                          key={c.name}
                          type="button"
                          className={`day-pill ${selectedCluster === c.name ? 'active' : ''}`}
                          onClick={() => setSelectedCluster(c.name)}
                          title={`${c.kubernetes_version} · ${c.status}`}
                        >
                          {c.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* GCP GKE */}
            {provider === 'gke' && (
              <>
                <div className="settings-field">
                  <label className="settings-label">Project ID</label>
                  <input
                    className="settings-input"
                    value={gcpProject}
                    onChange={e => setGcpProject(e.target.value)}
                    placeholder="my-gcp-project"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="settings-field">
                  <label className="settings-label">
                    Location
                    <InfoTip>
                      Region or zone (e.g. <code>us-central1</code>).<br />
                      Use <code>-</code> to list across all locations.
                    </InfoTip>
                  </label>
                  <input
                    className="settings-input"
                    value={gcpLocation}
                    onChange={e => setGcpLocation(e.target.value)}
                    placeholder="-"
                    spellCheck={false}
                  />
                </div>
                <div className="settings-field">
                  <label className="settings-label">
                    Service Account JSON
                    <InfoTip>
                      Paste the full contents of your service account key JSON file.<br />
                      Requires <code>container.clusters.list</code> and <code>container.clusters.get</code>.
                    </InfoTip>
                  </label>
                  <textarea
                    className="connect-kubeconfig"
                    style={{ minHeight: 100 }}
                    value={gcpJson}
                    onChange={e => setGcpJson(e.target.value)}
                    placeholder={'{ "type": "service_account", ... }'}
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <button
                  className="btn-ghost"
                  style={{ width: '100%', marginBottom: 4 }}
                  disabled={!gcpProject || !gcpJson || listingClusters}
                  onClick={handleListGkeClusters}
                >
                  {listingClusters ? 'Listing clusters…' : 'List clusters →'}
                </button>
                {gkeClusters.length > 0 && (
                  <div className="settings-field">
                    <label className="settings-label">Select cluster</label>
                    <div className="day-pills" style={{ flexWrap: 'wrap' }}>
                      {gkeClusters.map(c => (
                        <button
                          key={c.name}
                          type="button"
                          className={`day-pill ${selectedCluster === c.name ? 'active' : ''}`}
                          onClick={() => setSelectedCluster(c.name)}
                          title={`${c.location} · ${c.kubernetes_version}`}
                        >
                          {c.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {error && <div className="connect-error" style={{ marginTop: 10 }}>{error}</div>}
          </div>

        </div>{/* /drawer-body */}

        {/* ── Footer ── */}
        <div className="drawer-footer">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={connectDisabled}
            onClick={handleConnect}
          >
            {connectLabel}
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
