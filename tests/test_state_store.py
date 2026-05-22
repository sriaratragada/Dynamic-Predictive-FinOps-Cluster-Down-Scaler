import json
from unittest.mock import MagicMock

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from controller.state_store import StateStore


def _configmap(replicas: dict = None, cordoned: list = None) -> client.V1ConfigMap:
    cm = MagicMock(spec=client.V1ConfigMap)
    cm.data = {
        "replicas": json.dumps(replicas or {}),
        "cordoned_nodes": json.dumps(cordoned or []),
    }
    return cm


@pytest.fixture
def store(mock_core_api):
    return StateStore("finops-scaler-state", "kube-system", mock_core_api)


# ------------------------------------------------------------------
# _ensure — ConfigMap creation
# ------------------------------------------------------------------

def test_ensure_creates_configmap_when_not_found(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
    mock_core_api.create_namespaced_config_map.return_value = _configmap()
    store._ensure()
    mock_core_api.create_namespaced_config_map.assert_called_once()


def test_ensure_reraises_non_404_errors(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.side_effect = ApiException(status=403)
    with pytest.raises(ApiException):
        store._ensure()


# ------------------------------------------------------------------
# replica state
# ------------------------------------------------------------------

def test_save_replicas_writes_correct_entry(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.return_value = _configmap()
    store.save_replicas("default", "worker", 3)
    patch_cm = mock_core_api.patch_namespaced_config_map.call_args[0][2]
    saved = json.loads(patch_cm.data["replicas"])
    assert saved["default/worker"] == 3


def test_load_replicas_returns_stored_values(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.return_value = _configmap(
        replicas={"default/worker": 3, "staging/api": 2}
    )
    result = store.load_replicas()
    assert result == {"default/worker": 3, "staging/api": 2}


def test_clear_replicas_removes_only_target(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.return_value = _configmap(
        replicas={"default/worker": 3, "staging/api": 5}
    )
    store.clear_replicas("default", "worker")
    patch_cm = mock_core_api.patch_namespaced_config_map.call_args[0][2]
    remaining = json.loads(patch_cm.data["replicas"])
    assert "default/worker" not in remaining
    assert remaining["staging/api"] == 5


# ------------------------------------------------------------------
# cordoned-node state
# ------------------------------------------------------------------

def test_save_and_load_cordoned_nodes(store, mock_core_api):
    mock_core_api.read_namespaced_config_map.return_value = _configmap()
    store.save_cordoned_nodes(["worker-1", "worker-2"])
    patch_cm = mock_core_api.patch_namespaced_config_map.call_args[0][2]
    result = json.loads(patch_cm.data["cordoned_nodes"])
    assert result == ["worker-1", "worker-2"]


# ------------------------------------------------------------------
# dry-run
# ------------------------------------------------------------------

def test_dry_run_skips_patch(mock_core_api):
    store = StateStore("finops-scaler-state", "kube-system", mock_core_api, dry_run=True)
    mock_core_api.read_namespaced_config_map.return_value = _configmap()
    store.save_replicas("default", "worker", 3)
    mock_core_api.patch_namespaced_config_map.assert_not_called()
