"""
Demo-mode stubs for the controller.

When DEMO_MODE=true, these replace the real Kubernetes and Prometheus clients
so the controller can run fully locally with no cluster and no Prometheus instance.
All mutations are logged but never applied — state is persisted to /tmp instead.
"""
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

logger = logging.getLogger(__name__)

_STATE_FILE = Path("/tmp/finops-demo-state.json")

_DEMO_NODES = [
    {"name": "demo-node-1", "allocatable_cpu": 8.0},
    {"name": "demo-node-2", "allocatable_cpu": 8.0},
    {"name": "demo-node-3", "allocatable_cpu": 4.0},
]

_DEMO_DEPLOYMENTS = [
    {"namespace": "default", "name": "api-server", "replicas": 3},
    {"namespace": "default", "name": "worker", "replicas": 5},
]


# ------------------------------------------------------------------
# Synthetic data
# ------------------------------------------------------------------

def _synthetic_cpu_node(dt: datetime, node_idx: int) -> float:
    active = dt.weekday() < 5 and 7 <= dt.hour < 19
    base = 3.2 if active else 0.12
    rng = random.Random(int(dt.timestamp() // 300) * 10 + node_idx)
    return max(0.0, base + rng.gauss(0, 0.3))


def _synthetic_cpu_cluster(dt: datetime) -> float:
    return sum(_synthetic_cpu_node(dt, i) for i in range(len(_DEMO_NODES)))


# ------------------------------------------------------------------
# Helpers to build fake K8s SDK-like objects
# ------------------------------------------------------------------

def _make_node(name: str, allocatable_cpu: float, cordoned: bool = False):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels={}),
        status=SimpleNamespace(allocatable={"cpu": str(allocatable_cpu)}),
        spec=SimpleNamespace(unschedulable=cordoned),
    )


def _make_deployment(namespace: str, name: str, replicas: int):
    return SimpleNamespace(
        metadata=SimpleNamespace(namespace=namespace, name=name),
        spec=SimpleNamespace(replicas=replicas),
    )


# ------------------------------------------------------------------
# DemoPrometheusClient
# ------------------------------------------------------------------

class DemoPrometheusClient:
    """Returns synthetic CPU metrics without a real Prometheus."""

    def query(self, promql: str) -> list:
        now = datetime.now()
        return [{"metric": {}, "value": [now.timestamp(), str(round(_synthetic_cpu_cluster(now), 3))]}]

    def scalar(self, promql: str):
        return _synthetic_cpu_cluster(datetime.now())

    def per_node_cpu_usage(self) -> Dict[str, float]:
        now = datetime.now()
        return {n["name"]: _synthetic_cpu_node(now, i) for i, n in enumerate(_DEMO_NODES)}

    def cluster_cpu_baseline(self):
        return 6.0  # stable synthetic 7-day average

    def query_range(self, promql: str, start: float, end: float, step: int = 300) -> list:
        rng = random.Random(42)
        values = []
        t = start
        while t <= end:
            dt = datetime.fromtimestamp(t)
            active = dt.weekday() < 5 and 7 <= dt.hour < 19
            base = 9.5 if active else 0.4
            v = max(0.0, base + rng.gauss(0, 0.5))
            values.append([t, str(round(v, 3))])
            t += step
        return values


# ------------------------------------------------------------------
# DemoStateStore
# ------------------------------------------------------------------

class DemoStateStore:
    """File-backed state store that replaces the ConfigMap-based StateStore."""

    def __init__(self):
        self._data: dict = {"replicas": {}, "cordoned_nodes": []}
        if _STATE_FILE.exists():
            try:
                self._data = json.loads(_STATE_FILE.read_text())
            except Exception:
                pass

    def _save(self):
        try:
            _STATE_FILE.write_text(json.dumps(self._data))
        except Exception as exc:
            logger.warning("Demo state write failed: %s", exc)

    def save_replicas(self, namespace: str, name: str, replicas: int):
        self._data["replicas"][f"{namespace}/{name}"] = replicas
        self._save()

    def load_replicas(self) -> Dict[str, int]:
        return self._data["replicas"]

    def clear_replicas(self, namespace: str, name: str):
        self._data["replicas"].pop(f"{namespace}/{name}", None)
        self._save()

    def save_cordoned_nodes(self, nodes: List[str]):
        self._data["cordoned_nodes"] = nodes
        self._save()

    def load_cordoned_nodes(self) -> List[str]:
        return self._data["cordoned_nodes"]


# ------------------------------------------------------------------
# DemoCoreV1Api
# ------------------------------------------------------------------

class DemoCoreV1Api:
    """Duck-typed replacement for kubernetes.client.CoreV1Api."""

    def __init__(self):
        self._cordoned: Dict[str, bool] = {n["name"]: False for n in _DEMO_NODES}

    def list_node(self):
        nodes = [
            _make_node(n["name"], n["allocatable_cpu"], cordoned=self._cordoned.get(n["name"], False))
            for n in _DEMO_NODES
        ]
        return SimpleNamespace(items=nodes)

    def patch_node(self, name: str, body: dict):
        cordoned = body.get("spec", {}).get("unschedulable", False)
        self._cordoned[name] = cordoned
        logger.info("[DEMO] %s %s", "Cordoned" if cordoned else "Uncordoned", name)

    def list_pod_for_all_namespaces(self, field_selector: str = ""):
        return SimpleNamespace(items=[])  # no pods to drain in demo mode

    def create_namespaced_pod_eviction(self, name: str, namespace: str, eviction):
        logger.debug("[DEMO] Would evict pod %s/%s", namespace, name)

    # ConfigMap methods — not called when DemoStateStore is in use
    def read_namespaced_config_map(self, name: str, namespace: str):
        raise RuntimeError("Demo mode: ConfigMap access not supported — use DemoStateStore")

    def create_namespaced_config_map(self, namespace: str, body):
        pass

    def patch_namespaced_config_map(self, name: str, namespace: str, body):
        pass


# ------------------------------------------------------------------
# DemoAppsV1Api
# ------------------------------------------------------------------

class DemoAppsV1Api:
    """Duck-typed replacement for kubernetes.client.AppsV1Api."""

    def __init__(self):
        self._replicas: Dict[str, int] = {
            f"{d['namespace']}/{d['name']}": d["replicas"] for d in _DEMO_DEPLOYMENTS
        }

    def _all_deployments(self) -> list:
        return [
            _make_deployment(d["namespace"], d["name"],
                             self._replicas.get(f"{d['namespace']}/{d['name']}", d["replicas"]))
            for d in _DEMO_DEPLOYMENTS
        ]

    def list_namespaced_deployment(self, namespace: str, label_selector: str = ""):
        items = [dep for dep in self._all_deployments() if dep.metadata.namespace == namespace]
        return SimpleNamespace(items=items)

    def list_deployment_for_all_namespaces(self, label_selector: str = ""):
        return SimpleNamespace(items=self._all_deployments())

    def patch_namespaced_deployment_scale(self, name: str, namespace: str, scale):
        replicas = scale.spec.replicas
        self._replicas[f"{namespace}/{name}"] = replicas
        logger.info("[DEMO] Scaled %s/%s → %d replicas", namespace, name, replicas)
