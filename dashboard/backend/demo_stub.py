"""
Demo-mode stubs for the dashboard backend.

When DEMO_MODE=true these replace the real K8sReader and Prometheus HTTP calls
so the dashboard works without a Kubernetes cluster or Prometheus instance.
All data is generated synthetically from the current wall clock.
"""
import random
from datetime import datetime, timedelta, timezone
from typing import List

_DEMO_NODES = [
    {"name": "demo-node-1", "allocatable_cpu": 8.0},
    {"name": "demo-node-2", "allocatable_cpu": 8.0},
    {"name": "demo-node-3", "allocatable_cpu": 4.0},
]

_DEMO_DEPLOYMENTS = [
    {"namespace": "default", "name": "api-server"},
    {"namespace": "default", "name": "worker"},
]

_SEED_TOTAL_SAVED = 847.52


# ------------------------------------------------------------------
# Shared synthetic helpers
# ------------------------------------------------------------------

def _is_active(dt: datetime) -> bool:
    return dt.weekday() < 5 and 7 <= dt.hour < 19


def _cluster_cpu(dt: datetime) -> float:
    rng = random.Random(int(dt.timestamp() // 300))
    base = 9.5 if _is_active(dt) else 0.4
    return max(0.0, base + rng.gauss(0, 0.4))


def _node_cpu(dt: datetime, idx: int) -> float:
    allocatable = _DEMO_NODES[idx]["allocatable_cpu"]
    rng = random.Random(int(dt.timestamp() // 300) * 10 + idx)
    base = 3.2 if _is_active(dt) else 0.12
    return max(0.0, min(allocatable, base + rng.gauss(0, 0.3)))


# ------------------------------------------------------------------
# DemoK8sReader
# ------------------------------------------------------------------

class DemoK8sReader:
    """Simulates k8s_client.K8sReader for demo mode."""

    def read_state(self) -> dict:
        now = datetime.now()
        idle = not _is_active(now)
        return {
            "replicas": {"default/api-server": 3, "default/worker": 5} if idle else {},
            "cordoned_nodes": ["demo-node-2", "demo-node-3"] if idle else [],
        }

    def list_nodes(self) -> list:
        return [
            {"name": n["name"], "allocatable_cpu": n["allocatable_cpu"], "is_control_plane": False}
            for n in _DEMO_NODES
        ]

    def list_eligible_deployments(self) -> list:
        now = datetime.now()
        idle = not _is_active(now)
        return [
            {
                "namespace": d["namespace"],
                "name": d["name"],
                "current_replicas": 0 if idle else (3 if d["name"] == "api-server" else 5),
            }
            for d in _DEMO_DEPLOYMENTS
        ]

    def read_savings_log(self) -> dict:
        return {"events": _historical_events(), "total_saved_usd": _SEED_TOTAL_SAVED}

    def write_savings_log(self, log: dict):
        pass  # no-op in demo mode


# ------------------------------------------------------------------
# Historical savings events (pre-seeded demo data)
# ------------------------------------------------------------------

def _historical_events() -> List[dict]:
    """Generate the last 30 days of synthetic scale-down events."""
    events = []
    now = datetime.now(tz=timezone.utc)
    # Seed about 20 past cordon events (one per weekday evening → morning)
    for days_ago in range(1, 30):
        dt = now - timedelta(days=days_ago)
        if dt.weekday() >= 5:  # weekend — skip
            continue
        start_iso = dt.replace(hour=19, minute=0, second=0, microsecond=0).isoformat()
        end_iso = (dt + timedelta(hours=12)).replace(hour=7, minute=0, second=0, microsecond=0).isoformat()
        hours = 12.0
        rate = 0.192
        events.append({
            "node": "demo-node-2",
            "start": start_iso,
            "end": end_iso,
            "hours": hours,
            "rate_usd_hr": rate,
            "saved_usd": round(hours * rate, 4),
        })
        events.append({
            "node": "demo-node-3",
            "start": start_iso,
            "end": end_iso,
            "hours": hours,
            "rate_usd_hr": rate,
            "saved_usd": round(hours * rate, 4),
        })
    return events


# ------------------------------------------------------------------
# Demo Prometheus: instant queries  (/api/v1/query format)
# ------------------------------------------------------------------

def demo_prom_instant(promql: str) -> list:
    """Return a synthetic result list matching Prometheus /api/v1/query format."""
    now = datetime.now()
    ts = now.timestamp()

    if "by (node)" in promql:
        return [
            {"metric": {"node": n["name"]}, "value": [ts, str(round(_node_cpu(now, i), 4))]}
            for i, n in enumerate(_DEMO_NODES)
        ]

    total = _cluster_cpu(now)
    return [{"metric": {}, "value": [ts, str(round(total, 3))]}]


# ------------------------------------------------------------------
# Demo Prometheus: range queries  (/api/v1/query_range format)
# ------------------------------------------------------------------

def demo_prom_range(promql: str, start: float, end: float, step: int) -> list:
    """Return a synthetic result list matching Prometheus /api/v1/query_range format."""
    if "kube_node_status_allocatable" in promql:
        total_alloc = sum(n["allocatable_cpu"] for n in _DEMO_NODES)
        values = [[t, str(total_alloc)] for t in range(int(start), int(end) + step, step)]
        return [{"metric": {}, "values": values}]

    if "finops_scaledown_events_total" in promql:
        return [{"metric": {}, "values": _event_values(start, end, step, hour=19)}]

    if "finops_scaleup_events_total" in promql:
        return [{"metric": {}, "values": _event_values(start, end, step, hour=7)}]

    # Default: synthetic CPU time series
    rng = random.Random(int(start))
    values = []
    t = start
    while t <= end:
        dt = datetime.fromtimestamp(t)
        base = 9.5 if _is_active(dt) else 0.4
        v = max(0.0, base + rng.gauss(0, 0.5))
        values.append([t, str(round(v, 3))])
        t += step
    return [{"metric": {}, "values": values}]


def _event_values(start: float, end: float, step: int, hour: int) -> list:
    """Return [[ts, "1.0"]] at the target hour on weekdays, else [[ts, "0.0"]]."""
    values = []
    t = start
    while t <= end:
        dt = datetime.fromtimestamp(t)
        is_event = dt.weekday() < 5 and dt.hour == hour and dt.minute < (step // 60)
        values.append([t, "1.0" if is_event else "0.0"])
        t += step
    return values
