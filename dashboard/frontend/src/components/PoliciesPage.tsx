import { useEffect, useState } from 'react'
import type { DownscalePolicy } from '../api'
import { fetchPolicies } from '../api'

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function dayLabel(csv: string): string {
  return csv
    .split(',')
    .map(d => DAY_NAMES[parseInt(d.trim())] ?? d.trim())
    .join(', ')
}

function PolicyCard({ policy }: { policy: DownscalePolicy }) {
  return (
    <article className="policy-card">
      <div className="policy-card-header">
        <div className="policy-card-identity">
          <span className={`policy-badge ${policy.enabled ? 'policy-badge--on' : 'policy-badge--off'}`}>
            {policy.enabled ? 'ACTIVE' : 'DISABLED'}
          </span>
          <div>
            <div className="policy-name">{policy.name}</div>
            <div className="policy-ns">{policy.namespace}</div>
          </div>
        </div>
      </div>

      <div className="policy-body">
        <div className="policy-row">
          <span className="policy-label">Schedule</span>
          <span className="policy-value">
            {policy.schedule.businessHoursStart} – {policy.schedule.businessHoursEnd}
          </span>
        </div>
        <div className="policy-row">
          <span className="policy-label">Days</span>
          <span className="policy-value">{dayLabel(policy.schedule.businessDays)}</span>
        </div>
        <div className="policy-row">
          <span className="policy-label">Timezone</span>
          <span className="policy-value">{policy.schedule.timezone}</span>
        </div>
        {policy.targetNamespaces.length > 0 && (
          <div className="policy-row">
            <span className="policy-label">Namespaces</span>
            <span className="policy-value">
              {policy.targetNamespaces.map(ns => (
                <span key={ns} className="policy-ns-chip">{ns}</span>
              ))}
            </span>
          </div>
        )}
        {policy.excludeDeployments.length > 0 && (
          <div className="policy-row">
            <span className="policy-label">Excluded</span>
            <span className="policy-value">
              {policy.excludeDeployments.map(d => (
                <span key={d} className="policy-exclude-chip">{d}</span>
              ))}
            </span>
          </div>
        )}
        <div className="policy-row">
          <span className="policy-label">Min floor</span>
          <span className="policy-value">{policy.minReplicaFloor} replica(s)</span>
        </div>
        <div className="policy-row">
          <span className="policy-label">Pre-warm</span>
          <span className="policy-value">{policy.prewarmMinutes} min</span>
        </div>
      </div>
    </article>
  )
}

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<DownscalePolicy[]>([])
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    fetchPolicies()
      .then(d => setPolicies(d.policies))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="policies-page">
      <div className="policies-page-intro">
        <div className="policies-page-tag">// CRD</div>
        <h1 className="policies-page-title">DownscalePolicy Resources</h1>
        <p className="policies-page-desc">
          Kubernetes-native policy objects that define per-namespace or per-label
          scale-down schedules. Apply them with <code>kubectl apply -f</code> — the
          CRD watcher picks them up automatically.
        </p>
      </div>

      {loading ? (
        <div className="policies-loading">Loading policies…</div>
      ) : policies.length === 0 ? (
        <div className="policies-empty">
          <div className="policies-empty-icon">{'{ }'}</div>
          <div className="policies-empty-title">No DownscalePolicy resources found</div>
          <p className="policies-empty-desc">
            Create a CRD to define a scoping policy. Here's an example:
          </p>
          <pre className="policies-example">{`apiVersion: finops.io/v1alpha1
kind: DownscalePolicy
metadata:
  name: off-hours-staging
  namespace: staging
spec:
  enabled: true
  schedule:
    businessHoursStart: "08:00"
    businessHoursEnd: "18:00"
    businessDays: "0,1,2,3,4"
    timezone: America/New_York
  targetNamespaces:
    - staging
    - qa
  excludeDeployments:
    - monitoring-agent
  minReplicaFloor: 1
  prewarmMinutes: 10`}</pre>
          <p className="policies-empty-hint">
            Apply the CRD first: <code>kubectl apply -f manifests/crd-downscalepolicy.yaml</code>
          </p>
        </div>
      ) : (
        <div className="policies-grid">
          {policies.map(p => (
            <PolicyCard key={`${p.namespace}/${p.name}`} policy={p} />
          ))}
        </div>
      )}
    </div>
  )
}
