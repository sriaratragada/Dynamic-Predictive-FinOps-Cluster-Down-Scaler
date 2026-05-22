import logging
import time as _time
from typing import Dict, List, TYPE_CHECKING

from kubernetes import client
from kubernetes.client.rest import ApiException

from .metrics import PrometheusClient

if TYPE_CHECKING:
    from .state_store import StateStore

logger = logging.getLogger(__name__)

_EVICTION_GRACE_SECONDS = 30
_DRAIN_POLL_INTERVAL = 5
_DRAIN_TIMEOUT = 300

_CONTROL_PLANE_LABELS = {
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",
}


class NodeManager:
    def __init__(
        self,
        core_api: client.CoreV1Api,
        prometheus: PrometheusClient,
        state_store: "StateStore",
        dry_run: bool = False,
    ):
        self._core = core_api
        self._prom = prometheus
        self._state = state_store
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_underutilised_nodes(self, threshold: float) -> List[str]:
        """Return worker node names whose CPU usage ratio is below *threshold*."""
        try:
            cpu_map: Dict[str, float] = self._prom.per_node_cpu_usage()
        except Exception as exc:
            logger.warning("Cannot fetch node CPU metrics from Prometheus: %s", exc)
            return []

        underutil = []
        for node in self._core.list_node().items:
            name = node.metadata.name
            labels = node.metadata.labels or {}

            if any(lbl in labels for lbl in _CONTROL_PLANE_LABELS):
                continue  # never touch control-plane nodes

            allocatable_cpu = _parse_cpu(
                (node.status.allocatable or {}).get("cpu", "1")
            )
            used_cpu = cpu_map.get(name, 0.0)
            ratio = used_cpu / allocatable_cpu if allocatable_cpu > 0 else 0.0

            if ratio < threshold:
                logger.info(
                    "Node %s is underutilised: %.1f%% CPU (threshold %.0f%%)",
                    name, ratio * 100, threshold * 100,
                )
                underutil.append(name)

        return underutil

    # ------------------------------------------------------------------
    # Cordon / uncordon
    # ------------------------------------------------------------------

    def cordon(self, node_name: str):
        if self._dry_run:
            logger.info("[DRY-RUN] Would cordon node %s", node_name)
        else:
            self._core.patch_node(node_name, {"spec": {"unschedulable": True}})
            logger.info("Cordoned node %s", node_name)
        cordoned = self._state.load_cordoned_nodes()
        if node_name not in cordoned:
            cordoned.append(node_name)
            self._state.save_cordoned_nodes(cordoned)

    def uncordon(self, node_name: str):
        if self._dry_run:
            logger.info("[DRY-RUN] Would uncordon node %s", node_name)
            return
        self._core.patch_node(node_name, {"spec": {"unschedulable": False}})
        logger.info("Uncordoned node %s", node_name)

    def uncordon_all(self):
        for node_name in self._state.load_cordoned_nodes():
            try:
                self.uncordon(node_name)
            except Exception as exc:
                logger.warning("Could not uncordon %s: %s", node_name, exc)
        self._state.save_cordoned_nodes([])

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    def drain(self, node_name: str):
        if self._dry_run:
            logger.info("[DRY-RUN] Would drain node %s", node_name)
            return
        logger.info("Draining node %s", node_name)
        pods = self._core.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        ).items

        for pod in pods:
            if _is_daemonset_pod(pod) or _is_mirror_pod(pod):
                continue
            self._evict(pod)

        self._wait_for_drain(node_name)

    def _evict(self, pod: client.V1Pod):
        ns = pod.metadata.namespace
        name = pod.metadata.name
        eviction = client.V1Eviction(
            metadata=client.V1ObjectMeta(name=name, namespace=ns),
            delete_options=client.V1DeleteOptions(
                grace_period_seconds=_EVICTION_GRACE_SECONDS
            ),
        )
        try:
            self._core.create_namespaced_pod_eviction(name, ns, eviction)
            logger.debug("Evicted pod %s/%s", ns, name)
        except ApiException as exc:
            if exc.status == 429:
                logger.warning(
                    "PDB prevented eviction of %s/%s — skipping this pod", ns, name
                )
            elif exc.status == 404:
                pass  # already terminated
            else:
                raise

    def _wait_for_drain(self, node_name: str):
        deadline = _time.monotonic() + _DRAIN_TIMEOUT
        while _time.monotonic() < deadline:
            remaining = [
                p
                for p in self._core.list_pod_for_all_namespaces(
                    field_selector=f"spec.nodeName={node_name}"
                ).items
                if not _is_daemonset_pod(p) and not _is_mirror_pod(p)
            ]
            if not remaining:
                logger.info("Node %s drained successfully", node_name)
                return
            _time.sleep(_DRAIN_POLL_INTERVAL)
        logger.warning(
            "Drain of node %s timed out after %ds; %d pod(s) still present",
            node_name, _DRAIN_TIMEOUT, len(remaining),
        )


# ------------------------------------------------------------------
# Pod classification helpers
# ------------------------------------------------------------------

def _is_daemonset_pod(pod: client.V1Pod) -> bool:
    return any(
        ref.kind == "DaemonSet"
        for ref in (pod.metadata.owner_references or [])
    )


def _is_mirror_pod(pod: client.V1Pod) -> bool:
    return "kubernetes.io/config.mirror" in (pod.metadata.annotations or {})


def _parse_cpu(cpu_str: str) -> float:
    """Convert a Kubernetes CPU string ('500m', '2') to float cores."""
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    return float(cpu_str)
