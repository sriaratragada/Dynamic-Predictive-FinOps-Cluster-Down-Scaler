from unittest.mock import MagicMock, patch

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from controller.node_manager import NodeManager


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _node(name: str, labels: dict = None, allocatable_cpu: str = "4") -> client.V1Node:
    node = MagicMock(spec=client.V1Node)
    node.metadata.name = name
    node.metadata.labels = labels or {}
    node.status.allocatable = {"cpu": allocatable_cpu}
    return node


def _pod(name: str, namespace: str = "default", owner_kind: str = None, annotations: dict = None):
    pod = MagicMock(spec=client.V1Pod)
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.annotations = annotations or {}
    if owner_kind:
        ref = MagicMock()
        ref.kind = owner_kind
        pod.metadata.owner_references = [ref]
    else:
        pod.metadata.owner_references = []
    return pod


@pytest.fixture
def node_mgr(mock_core_api, mock_prometheus, mock_state_store):
    return NodeManager(mock_core_api, mock_prometheus, mock_state_store)


# ------------------------------------------------------------------
# get_underutilised_nodes
# ------------------------------------------------------------------

def test_skips_control_plane_nodes(node_mgr, mock_core_api, mock_prometheus):
    cp = _node("master-1", labels={"node-role.kubernetes.io/control-plane": ""})
    worker = _node("worker-1")
    mock_core_api.list_node.return_value.items = [cp, worker]
    # worker-1: 0.1 cores / 4 cores = 2.5% < 10%
    mock_prometheus.per_node_cpu_usage.return_value = {"master-1": 3.8, "worker-1": 0.1}
    result = node_mgr.get_underutilised_nodes(threshold=0.10)
    assert "master-1" not in result
    assert "worker-1" in result


def test_skips_master_label_nodes(node_mgr, mock_core_api, mock_prometheus):
    master = _node("old-master", labels={"node-role.kubernetes.io/master": ""})
    mock_core_api.list_node.return_value.items = [master]
    mock_prometheus.per_node_cpu_usage.return_value = {}
    result = node_mgr.get_underutilised_nodes(threshold=0.10)
    assert result == []


def test_returns_empty_list_when_prometheus_fails(node_mgr, mock_prometheus):
    mock_prometheus.per_node_cpu_usage.side_effect = Exception("timeout")
    result = node_mgr.get_underutilised_nodes(threshold=0.10)
    assert result == []


def test_node_above_threshold_excluded(node_mgr, mock_core_api, mock_prometheus):
    worker = _node("worker-1")
    mock_core_api.list_node.return_value.items = [worker]
    # 2.0 / 4.0 = 50% > 10% threshold
    mock_prometheus.per_node_cpu_usage.return_value = {"worker-1": 2.0}
    result = node_mgr.get_underutilised_nodes(threshold=0.10)
    assert result == []


# ------------------------------------------------------------------
# drain — pod filtering
# ------------------------------------------------------------------

def test_drain_skips_daemonset_pods(node_mgr, mock_core_api):
    ds_pod = _pod("ds-pod", owner_kind="DaemonSet")
    app_pod = _pod("app-pod", owner_kind="ReplicaSet")
    mock_core_api.list_pod_for_all_namespaces.return_value.items = [ds_pod, app_pod]
    with patch.object(node_mgr, "_evict") as mock_evict, \
         patch.object(node_mgr, "_wait_for_drain"):
        node_mgr.drain("worker-1")
        mock_evict.assert_called_once_with(app_pod)


def test_drain_skips_mirror_pods(node_mgr, mock_core_api):
    mirror = _pod("mirror", annotations={"kubernetes.io/config.mirror": "sha256abc"})
    mock_core_api.list_pod_for_all_namespaces.return_value.items = [mirror]
    with patch.object(node_mgr, "_evict") as mock_evict, \
         patch.object(node_mgr, "_wait_for_drain"):
        node_mgr.drain("worker-1")
        mock_evict.assert_not_called()


def test_drain_dry_run_does_not_evict(mock_core_api, mock_prometheus, mock_state_store):
    mgr = NodeManager(mock_core_api, mock_prometheus, mock_state_store, dry_run=True)
    with patch.object(mgr, "_evict") as mock_evict:
        mgr.drain("worker-1")
        mock_evict.assert_not_called()
        mock_core_api.list_pod_for_all_namespaces.assert_not_called()


# ------------------------------------------------------------------
# _evict — error handling
# ------------------------------------------------------------------

def test_evict_handles_pdb_429_gracefully(node_mgr, mock_core_api):
    pod = _pod("blocked-pod")
    mock_core_api.create_namespaced_pod_eviction.side_effect = ApiException(status=429)
    node_mgr._evict(pod)  # must not raise


def test_evict_handles_404_silently(node_mgr, mock_core_api):
    pod = _pod("gone-pod")
    mock_core_api.create_namespaced_pod_eviction.side_effect = ApiException(status=404)
    node_mgr._evict(pod)  # must not raise


def test_evict_raises_on_unexpected_error(node_mgr, mock_core_api):
    pod = _pod("bad-pod")
    mock_core_api.create_namespaced_pod_eviction.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        node_mgr._evict(pod)


# ------------------------------------------------------------------
# cordon / uncordon
# ------------------------------------------------------------------

def test_cordon_patches_node_and_updates_state(node_mgr, mock_core_api, mock_state_store):
    mock_state_store.load_cordoned_nodes.return_value = []
    node_mgr.cordon("worker-1")
    mock_core_api.patch_node.assert_called_once_with(
        "worker-1", {"spec": {"unschedulable": True}}
    )
    mock_state_store.save_cordoned_nodes.assert_called_once_with(["worker-1"])


def test_cordon_does_not_duplicate_node_in_state(node_mgr, mock_core_api, mock_state_store):
    mock_state_store.load_cordoned_nodes.return_value = ["worker-1"]
    node_mgr.cordon("worker-1")
    mock_state_store.save_cordoned_nodes.assert_not_called()


def test_uncordon_all_patches_and_clears_state(node_mgr, mock_core_api, mock_state_store):
    mock_state_store.load_cordoned_nodes.return_value = ["worker-1", "worker-2"]
    node_mgr.uncordon_all()
    assert mock_core_api.patch_node.call_count == 2
    mock_state_store.save_cordoned_nodes.assert_called_once_with([])


def test_cordon_dry_run_does_not_patch_node(mock_core_api, mock_prometheus, mock_state_store):
    mgr = NodeManager(mock_core_api, mock_prometheus, mock_state_store, dry_run=True)
    mock_state_store.load_cordoned_nodes.return_value = []
    mgr.cordon("worker-1")
    mock_core_api.patch_node.assert_not_called()


# ------------------------------------------------------------------
# GPU-aware cordoning
# ------------------------------------------------------------------

def _gpu_node(name: str, gpu_count: int = 4, allocatable_cpu: str = "32") -> client.V1Node:
    """Create a mock node with nvidia.com/gpu in its allocatable resources."""
    node = MagicMock(spec=client.V1Node)
    node.metadata.name = name
    node.metadata.labels = {}
    node.status.allocatable = {"cpu": allocatable_cpu, "nvidia.com/gpu": str(gpu_count)}
    return node


def test_gpu_node_below_threshold_is_cordoned(mock_core_api, mock_prometheus, mock_state_store):
    """GPU node whose GPU utilisation is below the threshold is flagged."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=True, gpu_idle_threshold=0.10,
    )
    node = _gpu_node("gpu-node-1")
    mock_core_api.list_node.return_value.items = [node]
    mock_prometheus.per_node_cpu_usage.return_value = {"gpu-node-1": 28.0}  # high CPU (irrelevant)
    mock_prometheus.per_node_gpu_usage.return_value = {"gpu-node-1": 0.04}  # 4% GPU < 10%
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert "gpu-node-1" in result


def test_gpu_node_above_threshold_not_cordoned(mock_core_api, mock_prometheus, mock_state_store):
    """GPU node whose GPU utilisation exceeds the threshold is left alone."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=True, gpu_idle_threshold=0.10,
    )
    node = _gpu_node("gpu-node-1")
    mock_core_api.list_node.return_value.items = [node]
    mock_prometheus.per_node_cpu_usage.return_value = {}
    mock_prometheus.per_node_gpu_usage.return_value = {"gpu-node-1": 0.82}  # 82% GPU > 10%
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert result == []


def test_gpu_aware_disabled_uses_cpu_for_gpu_node(mock_core_api, mock_prometheus, mock_state_store):
    """When enable_gpu_aware=False, GPU nodes are evaluated by CPU like any other node."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=False,
    )
    node = _gpu_node("gpu-node-1")
    mock_core_api.list_node.return_value.items = [node]
    mock_prometheus.per_node_cpu_usage.return_value = {"gpu-node-1": 0.5}  # 0.5 / 32 ≈ 1.6% < 10%
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert "gpu-node-1" in result


def test_gpu_node_without_dcgm_data_is_skipped(mock_core_api, mock_prometheus, mock_state_store):
    """GPU node with no DCGM entry in the result is skipped (not cordoned)."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=True, gpu_idle_threshold=0.10,
    )
    node = _gpu_node("gpu-node-1")
    mock_core_api.list_node.return_value.items = [node]
    mock_prometheus.per_node_cpu_usage.return_value = {}
    mock_prometheus.per_node_gpu_usage.return_value = {}  # DCGM returned no data for this node
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert result == []


def test_dcgm_failure_skips_gpu_nodes_keeps_cpu_nodes(
    mock_core_api, mock_prometheus, mock_state_store
):
    """When the DCGM query throws, GPU nodes are skipped; CPU nodes still evaluated."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=True, gpu_idle_threshold=0.10,
    )
    gpu_node = _gpu_node("gpu-node-1")
    cpu_node = _node("cpu-node-1")
    mock_core_api.list_node.return_value.items = [gpu_node, cpu_node]
    mock_prometheus.per_node_cpu_usage.return_value = {
        "gpu-node-1": 0.05,   # low CPU (irrelevant — DCGM will fail)
        "cpu-node-1": 0.05,   # 0.05 / 4 = 1.25% < 10%
    }
    mock_prometheus.per_node_gpu_usage.side_effect = Exception("dcgm-exporter unavailable")
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert "gpu-node-1" not in result   # skipped — no DCGM data
    assert "cpu-node-1" in result        # CPU node evaluated normally


def test_mixed_cluster_each_node_uses_correct_metric(
    mock_core_api, mock_prometheus, mock_state_store
):
    """Mixed cluster: GPU nodes use GPU util, CPU nodes use CPU util independently."""
    mgr = NodeManager(
        mock_core_api, mock_prometheus, mock_state_store,
        enable_gpu_aware=True, gpu_idle_threshold=0.10,
    )
    gpu_idle = _gpu_node("gpu-idle")
    gpu_busy = _gpu_node("gpu-busy")
    cpu_idle = _node("cpu-idle")
    cpu_busy = _node("cpu-busy")
    mock_core_api.list_node.return_value.items = [gpu_idle, gpu_busy, cpu_idle, cpu_busy]
    mock_prometheus.per_node_cpu_usage.return_value = {
        "gpu-idle": 30.0,   # high CPU (irrelevant for GPU node)
        "gpu-busy": 28.0,
        "cpu-idle": 0.1,    # 0.1 / 4 = 2.5% < 10%
        "cpu-busy": 3.8,    # 3.8 / 4 = 95% > 10%
    }
    mock_prometheus.per_node_gpu_usage.return_value = {
        "gpu-idle": 0.03,   # 3% GPU < 10% → cordon
        "gpu-busy": 0.91,   # 91% GPU > 10% → keep
    }
    result = mgr.get_underutilised_nodes(threshold=0.10)
    assert "gpu-idle" in result
    assert "gpu-busy" not in result
    assert "cpu-idle" in result
    assert "cpu-busy" not in result
