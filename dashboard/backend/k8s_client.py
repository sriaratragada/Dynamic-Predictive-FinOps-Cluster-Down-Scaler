import json
import logging
import os
from typing import Dict, List

from kubernetes import client, config as k8s_config
from kubernetes.config import ConfigException
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


def _load():
    try:
        k8s_config.load_incluster_config()
    except ConfigException:
        k8s_config.load_kube_config()


def _parse_cpu(cpu_str: str) -> float:
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


class K8sReader:
    def __init__(self):
        _load()
        self._core = client.CoreV1Api()
        self._apps = client.AppsV1Api()
        self._state_name = os.environ.get("STATE_CONFIGMAP_NAME", "finops-scaler-state")
        self._state_ns = os.environ.get("STATE_CONFIGMAP_NS", "kube-system")
        self._savings_name = os.environ.get("SAVINGS_CONFIGMAP_NAME", "finops-savings-state")

    # ------------------------------------------------------------------
    # Controller state (read-only)
    # ------------------------------------------------------------------

    def read_state(self) -> Dict:
        try:
            cm = self._core.read_namespaced_config_map(self._state_name, self._state_ns)
            raw = cm.data or {}
            return {
                "replicas": json.loads(raw.get("replicas", "{}")),
                "cordoned_nodes": json.loads(raw.get("cordoned_nodes", "[]")),
            }
        except ApiException as exc:
            if exc.status == 404:
                return {"replicas": {}, "cordoned_nodes": []}
            raise

    # ------------------------------------------------------------------
    # Savings log (read + write by dashboard)
    # ------------------------------------------------------------------

    def read_savings_log(self) -> Dict:
        try:
            cm = self._core.read_namespaced_config_map(self._savings_name, self._state_ns)
            raw = cm.data or {}
            return {
                "events": json.loads(raw.get("events", "[]")),
                "total_saved_usd": float(raw.get("total_saved_usd", "0")),
            }
        except ApiException as exc:
            if exc.status == 404:
                return {"events": [], "total_saved_usd": 0.0}
            raise

    def write_savings_log(self, log: Dict):
        data = {
            "events": json.dumps(log["events"]),
            "total_saved_usd": str(round(log["total_saved_usd"], 6)),
        }
        cm_obj = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=self._savings_name, namespace=self._state_ns),
            data=data,
        )
        try:
            self._core.read_namespaced_config_map(self._savings_name, self._state_ns)
            self._core.patch_namespaced_config_map(self._savings_name, self._state_ns, cm_obj)
        except ApiException as exc:
            if exc.status == 404:
                self._core.create_namespaced_config_map(self._state_ns, cm_obj)
            else:
                raise

    # ------------------------------------------------------------------
    # Cluster topology
    # ------------------------------------------------------------------

    def list_nodes(self) -> List[Dict]:
        nodes = []
        _CP = {"node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"}
        for node in self._core.list_node().items:
            labels = node.metadata.labels or {}
            nodes.append({
                "name": node.metadata.name,
                "allocatable_cpu": _parse_cpu(
                    (node.status.allocatable or {}).get("cpu", "1")
                ),
                "is_control_plane": bool(_CP & set(labels)),
            })
        return nodes

    def list_eligible_deployments(self) -> List[Dict]:
        result = self._apps.list_deployment_for_all_namespaces(
            label_selector="finops.io/scaledown-eligible=true"
        )
        return [
            {
                "namespace": d.metadata.namespace,
                "name": d.metadata.name,
                "current_replicas": d.spec.replicas or 0,
            }
            for d in result.items
        ]
