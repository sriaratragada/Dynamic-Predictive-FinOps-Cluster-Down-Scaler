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

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const fetchStatus   = ()            => get<StatusData>('/api/status')
export const fetchCapacity = ()            => get<CapacityData>('/api/capacity')
export const fetchHistory  = (hours = 24) => get<HistoryData>(`/api/history?hours=${hours}`)
export const fetchSavings  = ()            => get<SavingsData>('/api/savings')
