import { useState } from 'react'
import type { ControllerStatus } from '../api'
import { connectCluster } from '../api'

interface Props {
  onConnected: (s: ControllerStatus) => void
}

export default function ConnectCard({ onConnected }: Props) {
  const [kubeconfig, setKubeconfig] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error,      setError]      = useState<string | null>(null)

  async function handleConnect() {
    if (!kubeconfig.trim()) return
    setConnecting(true)
    setError(null)
    try {
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

        {/* ── Left: info ── */}
        <div className="connect-card-info">
          <div className="connect-card-tag">CLUSTER SETUP</div>
          <h2 className="connect-card-title">Connect your cluster</h2>
          <p className="connect-card-desc">
            Paste your kubeconfig to start the embedded controller loop.
            No Helm chart or in-cluster install required — the controller
            runs inside this container and talks directly to your K8s API.
          </p>
          <div className="connect-checklist">
            <div className="connect-checklist-item">
              <span className="connect-step-num">01</span>
              <span>Paste <code>~/.kube/config</code> — credentials are used only for direct K8s API calls, never stored</span>
            </div>
            <div className="connect-checklist-item">
              <span className="connect-step-num">02</span>
              <span>Configure schedule in <strong>⚙ Settings → // SCHED</strong></span>
            </div>
            <div className="connect-checklist-item">
              <span className="connect-step-num">03</span>
              <span>Label target deployments: <code>finops.io/scaledown-eligible=true</code></span>
            </div>
          </div>
        </div>

        {/* ── Right: form ── */}
        <div className="connect-card-form">
          <label className="settings-label" style={{ display: 'block', marginBottom: 8 }}>
            kubeconfig YAML
          </label>
          <textarea
            className="connect-kubeconfig"
            value={kubeconfig}
            onChange={e => setKubeconfig(e.target.value)}
            placeholder={'apiVersion: v1\nkind: Config\nclusters:\n- cluster:\n    server: https://...\n  name: my-cluster\ncontexts:\n- context:\n    cluster: my-cluster\n    user: admin\n  name: my-context\ncurrent-context: my-context\nusers:\n- name: admin\n  user:\n    token: ...'}
            spellCheck={false}
            autoComplete="off"
          />
          {error && <div className="connect-error">{error}</div>}
          <button
            className="btn-primary"
            style={{ width: '100%', marginTop: 12 }}
            disabled={!kubeconfig.trim() || connecting}
            onClick={handleConnect}
          >
            {connecting ? 'Validating credentials…' : 'Validate & Connect'}
          </button>
          <p className="connect-footnote">
            No cluster? Enable demo mode in <strong>⚙ Settings → // CONN</strong>
          </p>
        </div>

      </div>
    </div>
  )
}
