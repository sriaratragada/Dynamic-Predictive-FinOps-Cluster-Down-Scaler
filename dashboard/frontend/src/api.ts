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
  // Dashboard UX
  poll_interval_seconds: number
  node_utilisation_threshold: number
  namespace_filter: string
  min_replica_floor: number
  // Pre-Warm Engine
  enable_prewarm: boolean
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
