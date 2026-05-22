from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes import client

from controller.scaler import DeploymentScaler


def _deployment(namespace: str, name: str, replicas: int) -> client.V1Deployment:
    dep = MagicMock(spec=client.V1Deployment)
    dep.metadata.namespace = namespace
    dep.metadata.name = name
    dep.spec.replicas = replicas
    return dep


def _hpa(namespace: str, name: str, target_name: str, min_replicas: int = 2):
    """Build a minimal fake HPA object."""
    return SimpleNamespace(
        metadata=SimpleNamespace(namespace=namespace, name=name),
        spec=SimpleNamespace(
            min_replicas=min_replicas,
            scale_target_ref=SimpleNamespace(kind="Deployment", name=target_name),
        ),
    )


@pytest.fixture
def mock_autoscaling_api():
    return MagicMock()


@pytest.fixture
def scaler(mock_apps_api):
    return DeploymentScaler(mock_apps_api, namespace_filter="", min_floor=0)


@pytest.fixture
def scaler_with_hpa(mock_apps_api, mock_autoscaling_api):
    return DeploymentScaler(
        mock_apps_api, namespace_filter="", min_floor=0, autoscaling_api=mock_autoscaling_api
    )


# ------------------------------------------------------------------
# find_eligible
# ------------------------------------------------------------------

def test_find_eligible_queries_all_namespaces_when_no_filter(scaler, mock_apps_api):
    mock_apps_api.list_deployment_for_all_namespaces.return_value.items = []
    scaler.find_eligible()
    mock_apps_api.list_deployment_for_all_namespaces.assert_called_once()
    mock_apps_api.list_namespaced_deployment.assert_not_called()


def test_find_eligible_queries_single_namespace_when_filter_set(mock_apps_api):
    s = DeploymentScaler(mock_apps_api, namespace_filter="staging")
    mock_apps_api.list_namespaced_deployment.return_value.items = []
    s.find_eligible()
    mock_apps_api.list_namespaced_deployment.assert_called_once()
    mock_apps_api.list_deployment_for_all_namespaces.assert_not_called()


# ------------------------------------------------------------------
# scale_down
# ------------------------------------------------------------------

def test_scale_down_returns_original_replica_count(scaler, mock_apps_api):
    dep = _deployment("default", "worker", 3)
    result = scaler.scale_down(dep)
    assert result == 3


def test_scale_down_patches_to_floor(scaler, mock_apps_api):
    dep = _deployment("default", "worker", 3)
    scaler.scale_down(dep)
    mock_apps_api.patch_namespaced_deployment_scale.assert_called_once()
    scale_obj = mock_apps_api.patch_namespaced_deployment_scale.call_args[0][2]
    assert scale_obj.spec.replicas == 0  # default floor


def test_scale_down_skips_patch_when_already_at_floor(scaler, mock_apps_api):
    dep = _deployment("default", "worker", 0)
    scaler.scale_down(dep)
    mock_apps_api.patch_namespaced_deployment_scale.assert_not_called()


# ------------------------------------------------------------------
# scale_up
# ------------------------------------------------------------------

def test_scale_up_patches_correct_replica_count(scaler, mock_apps_api):
    dep = _deployment("default", "worker", 0)
    scaler.scale_up(dep, 5)
    scale_obj = mock_apps_api.patch_namespaced_deployment_scale.call_args[0][2]
    assert scale_obj.spec.replicas == 5


# ------------------------------------------------------------------
# dry-run
# ------------------------------------------------------------------

def test_scale_down_dry_run_logs_but_does_not_patch(mock_apps_api):
    s = DeploymentScaler(mock_apps_api, dry_run=True)
    dep = _deployment("default", "worker", 3)
    original = s.scale_down(dep)
    assert original == 3
    mock_apps_api.patch_namespaced_deployment_scale.assert_not_called()


def test_scale_up_dry_run_does_not_patch(mock_apps_api):
    s = DeploymentScaler(mock_apps_api, dry_run=True)
    dep = _deployment("default", "worker", 0)
    s.scale_up(dep, 3)
    mock_apps_api.patch_namespaced_deployment_scale.assert_not_called()


# ------------------------------------------------------------------
# HPA suspend / resume
# ------------------------------------------------------------------

def test_find_hpa_returns_none_when_no_autoscaling_api(scaler):
    dep = _deployment("default", "worker", 3)
    assert scaler.find_hpa(dep) is None


def test_find_hpa_returns_matching_hpa(scaler_with_hpa, mock_autoscaling_api):
    dep = _deployment("default", "worker", 3)
    h   = _hpa("default", "worker-hpa", target_name="worker", min_replicas=2)
    mock_autoscaling_api.list_namespaced_horizontal_pod_autoscaler.return_value = \
        SimpleNamespace(items=[h])
    result = scaler_with_hpa.find_hpa(dep)
    assert result is h


def test_find_hpa_returns_none_when_no_matching_target(scaler_with_hpa, mock_autoscaling_api):
    dep = _deployment("default", "worker", 3)
    h   = _hpa("default", "other-hpa", target_name="other-service", min_replicas=1)
    mock_autoscaling_api.list_namespaced_horizontal_pod_autoscaler.return_value = \
        SimpleNamespace(items=[h])
    result = scaler_with_hpa.find_hpa(dep)
    assert result is None


def test_suspend_hpa_patches_min_replicas_to_zero(scaler_with_hpa, mock_autoscaling_api):
    h = _hpa("default", "worker-hpa", target_name="worker", min_replicas=3)
    original = scaler_with_hpa.suspend_hpa(h)
    assert original == 3
    mock_autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.assert_called_once_with(
        "worker-hpa", "default", {"spec": {"minReplicas": 0}}
    )


def test_resume_hpa_restores_original_min(scaler_with_hpa, mock_autoscaling_api):
    h = _hpa("default", "worker-hpa", target_name="worker", min_replicas=0)
    scaler_with_hpa.resume_hpa(h, 3)
    mock_autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.assert_called_once_with(
        "worker-hpa", "default", {"spec": {"minReplicas": 3}}
    )


def test_suspend_hpa_dry_run_does_not_patch(mock_apps_api, mock_autoscaling_api):
    s = DeploymentScaler(mock_apps_api, dry_run=True, autoscaling_api=mock_autoscaling_api)
    h = _hpa("default", "worker-hpa", target_name="worker", min_replicas=2)
    original = s.suspend_hpa(h)
    assert original == 2
    mock_autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.assert_not_called()


def test_resume_hpa_dry_run_does_not_patch(mock_apps_api, mock_autoscaling_api):
    s = DeploymentScaler(mock_apps_api, dry_run=True, autoscaling_api=mock_autoscaling_api)
    h = _hpa("default", "worker-hpa", target_name="worker", min_replicas=0)
    s.resume_hpa(h, 3)
    mock_autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.assert_not_called()
