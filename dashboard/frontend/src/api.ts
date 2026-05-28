export interface StatusData {
  scaled_down: boolean
  cordoned_nodes: string[]
  deployments_scaled: Array<{ key: string; original_replicas: number }>
  cordoned_node_count: number
  deployment_count: number
}

export interface NodeCapacity {
  name: string
  allocatable_cpu_cores: number
  used_cpu_cores: number
  utilisation_pct: number
  cordoned: boolean
}

export interface CapacityData {
  nodes: NodeCapacity[]
  total_allocatable_cores: number
  total_used_cores: number
  cluster_utilisation_pct: number
}

export interface DataPoint {
  t: number  // unix ms
  v: number
}

export interface HistoryData {
  cpu_used: DataPoint[]
  cpu_capacity: DataPoint[]
  scaledown_events: number[]
  scaleup_events: number[]
  hours: number
}

export interface SavingsData {
  total_saved_usd: number
  this_week_usd: number
  this_month_usd: number
  hourly_rate_per_node: number
  currently_cordoned_count: number
  active_cordon_running_cost: number
  cloud_provider: string
  instance_type: string
  region: string
}

export interface ConfigData {
  // Connection
  prometheus_url: string
  demo_mode: boolean
  // Cloud & Pricing
  cloud_provider: string
  instance_type: string
  aws_region: string
  node_hourly_cost: number
  // Schedule
  business_hours_start: string
  business_hours_end: string
  business_days: string
  timezone: string
  prewarm_minutes: number
  // Prediction
  enable_metric_override: boolean
  enable_prophet: boolean
  prophet_training_weeks: number
  prophet_idle_threshold_cores: number
  prophet_retrain_hours: number
  prophet_shadow_mode: boolean
  // Dashboard UX
  poll_interval_seconds: number
  node_utilisation_threshold: number
  namespace_filter: string
  min_replica_floor: number
  // Pre-Warm Engine
  enable_prewarm: boolean
  prewarm_service_url: string
  // LLM / Natural Language
  openai_api_key_set: boolean
  openai_base_url: string
  // HPA Synergy
  enable_hpa_synergy: boolean
  hpa_spike_headroom_pct: number
  hpa_spike_lookahead_minutes: number
  // Spot Instance Migration
  enable_spot_migration: boolean
  spot_max_price_pct: number
  spot_eligible_label: string
}

export interface ControllerStatus {
  running: boolean
  connected: boolean
  cluster_host: string
  last_tick: string | null   // ISO-8601 or null
  last_action: string
  error: string | null
}

export interface ScaleEvent {
  node: string
  start: string    // ISO-8601 UTC
  end: string      // ISO-8601 UTC
  hours: number
  rate_usd_hr: number
  saved_usd: number
}

export interface EventsData {
  events: ScaleEvent[]
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const fetchStatus   = ()            => get<StatusData>('/api/status')
export const fetchCapacity = ()            => get<CapacityData>('/api/capacity')
export const fetchHistory  = (hours = 24) => get<HistoryData>(`/api/history?hours=${hours}`)
export const fetchSavings  = ()            => get<SavingsData>('/api/savings')
export const fetchConfig   = ()            => get<ConfigData>('/api/config')
export const fetchEvents   = ()            => get<EventsData>('/api/events')

export const fetchControllerStatus = () => get<ControllerStatus>('/api/controller')

export async function connectCluster(kubeconfig: string): Promise<ControllerStatus> {
  const r = await fetch('/api/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kubeconfig }),
  })
  if (!r.ok) {
    const payload = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(payload.detail || r.statusText)
  }
  return r.json()
}

export async function stopController(): Promise<ControllerStatus> {
  const r = await fetch('/api/controller/stop', { method: 'POST' })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function saveConfig(updates: Partial<ConfigData>): Promise<ConfigData> {
  const r = await fetch('/api/config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

// ── Cloud provider types ──────────────────────────────────────────────────────

export const AWS_REGIONS = [
  { value: 'us-east-1',      label: 'US East (N. Virginia)' },
  { value: 'us-east-2',      label: 'US East (Ohio)' },
  { value: 'us-west-1',      label: 'US West (N. California)' },
  { value: 'us-west-2',      label: 'US West (Oregon)' },
  { value: 'eu-west-1',      label: 'EU (Ireland)' },
  { value: 'eu-central-1',   label: 'EU (Frankfurt)' },
  { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
  { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
  { value: 'ap-south-1',     label: 'Asia Pacific (Mumbai)' },
]

export interface EksCluster {
  name: string
  endpoint: string
  status: string
  kubernetes_version: string
}

export interface GkeCluster {
  name: string
  endpoint: string
  status: string
  kubernetes_version: string
  location: string
}

// ── Cloud provider API calls ──────────────────────────────────────────────────

async function _post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const payload = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(payload.detail || r.statusText)
  }
  return r.json()
}

export const listEksClusters = (
  region: string, accessKeyId: string, secretAccessKey: string,
): Promise<EksCluster[]> =>
  _post<{ clusters: EksCluster[] }>('/api/aws/clusters', {
    region, access_key_id: accessKeyId, secret_access_key: secretAccessKey,
  }).then(d => d.clusters)

export const listGkeClusters = (
  projectId: string, location: string, serviceAccountJson: string,
): Promise<GkeCluster[]> =>
  _post<{ clusters: GkeCluster[] }>('/api/gcp/clusters', {
    project_id: projectId, location, service_account_json: serviceAccountJson,
  }).then(d => d.clusters)

export const connectEks = (
  region: string, clusterName: string, accessKeyId: string, secretAccessKey: string,
): Promise<ControllerStatus> =>
  _post('/api/connect/eks', {
    region, cluster_name: clusterName,
    access_key_id: accessKeyId, secret_access_key: secretAccessKey,
  })

export const connectGke = (
  projectId: string, location: string, clusterName: string, serviceAccountJson: string,
): Promise<ControllerStatus> =>
  _post('/api/connect/gke', {
    project_id: projectId, location,
    cluster_name: clusterName, service_account_json: serviceAccountJson,
  })

// ── Natural Language Config API ──────────────────────────────────────────────

export interface NLConfigResult {
  config: Partial<ConfigData>
  explanation: string
  diff: Array<{ field: string; old: unknown; new: unknown }>
}

export const parseNaturalLanguageConfig = (prompt: string) =>
  _post<NLConfigResult>('/api/config/natural-language', { prompt })

export const applyNaturalLanguageConfig = (config: Partial<ConfigData>) =>
  _post<ConfigData>('/api/config/natural-language/apply', { config })

// ── HPA Predictions API ─────────────────────────────────────────────────────

export interface HpaPrediction {
  enabled: boolean
  spike_predicted: boolean
  prediction: {
    expected_at: string
    current_cpu: number
    predicted_peak_cpu: number
    minutes_away: number
  } | null
  headroom_pct: number
  lookahead_minutes: number
}

export const fetchHpaPredictions = () => get<HpaPrediction>('/api/hpa/predictions')

// ── Pre-Warm API ──────────────────────────────────────────────────────────────

export interface PrewarmSignalResult {
  status: string
  action: string
  signal: string
  confidence?: number
  reason?: string
}

export interface PrewarmHistoryEntry {
  signal: string
  timestamp: string
  service_url: string
  result: string
}

export const sendPrewarmSignal = (signal: string, serviceUrl = 'default') =>
  _post<PrewarmSignalResult>('/api/prewarm', {
    service_url: serviceUrl,
    signal,
    user_id: 'anonymous',
  })

export const fetchPrewarmHistory = () =>
  get<{ history: PrewarmHistoryEntry[] }>('/api/prewarm/history')

export interface PrewarmSnippet {
  snippet: string
  service_url: string
}
export const fetchPrewarmSnippet = () => get<PrewarmSnippet>('/api/prewarm/snippet')

// ── Shadow Mode API ───────────────────────────────────────────────────────────

export interface ShadowLogEntry {
  timestamp: string
  prophet_says_idle: boolean
  schedule_says_idle: boolean
  agreement: boolean
  predicted_yhat: number
}

export const fetchShadowLog = () =>
  get<{ entries: ShadowLogEntry[] }>('/api/prophet/shadow-log')

// ── Policies API ──────────────────────────────────────────────────────────────

export interface DownscalePolicy {
  name: string
  namespace: string
  enabled: boolean
  schedule: {
    businessHoursStart: string
    businessHoursEnd: string
    businessDays: string
    timezone: string
  }
  targetNamespaces: string[]
  excludeDeployments: string[]
  minReplicaFloor: number
  prewarmMinutes: number
}

export const fetchPolicies = () =>
  get<{ policies: DownscalePolicy[] }>('/api/policies')

// ── Spot Migration API ────────────────────────────────────────────────────────

export interface SpotStatus {
  on_demand_nodes: number
  spot_nodes: number
  spot_eligible_workloads: number
  estimated_hourly_savings: number
  recent_interruptions: number
  migrations_today: number
  max_spot_price_pct: number
}

export const fetchSpotStatus = () =>
  get<SpotStatus>('/api/spot/status')
