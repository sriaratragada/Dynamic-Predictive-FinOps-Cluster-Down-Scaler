"""Tests for the namespace-driven auto-labeller."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from controller.auto_labeller import AutoLabeller, NAMESPACE_ANNOTATION, DEPLOYMENT_LABEL


def _namespace(name: str, annotated: bool = False):
    annotations = {NAMESPACE_ANNOTATION: "true"} if annotated else {}
    return SimpleNamespace(metadata=SimpleNamespace(name=name, annotations=annotations))


def _deployment(namespace: str, name: str, already_labelled: bool = False):
    labels = {DEPLOYMENT_LABEL: "true"} if already_labelled else {}
    return SimpleNamespace(metadata=SimpleNamespace(namespace=namespace, name=name, labels=labels))


@pytest.fixture
def core_api():
    return MagicMock()


@pytest.fixture
def apps_api():
    return MagicMock()


@pytest.fixture
def labeller(core_api, apps_api):
    return AutoLabeller(core_api, apps_api)


# ------------------------------------------------------------------
# Namespace discovery
# ------------------------------------------------------------------

def test_no_annotated_namespaces_labels_nothing(labeller, core_api, apps_api):
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[_namespace("default"), _namespace("kube-system")]
    )
    count = labeller.label_eligible_namespaces()
    assert count == 0
    apps_api.patch_namespaced_deployment.assert_not_called()


def test_annotated_namespace_labels_unlabelled_deployments(labeller, core_api, apps_api):
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[_namespace("staging", annotated=True)]
    )
    apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
        items=[
            _deployment("staging", "api-server"),
            _deployment("staging", "worker"),
        ]
    )
    count = labeller.label_eligible_namespaces()
    assert count == 2
    assert apps_api.patch_namespaced_deployment.call_count == 2


def test_already_labelled_deployments_are_skipped(labeller, core_api, apps_api):
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[_namespace("staging", annotated=True)]
    )
    apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
        items=[
            _deployment("staging", "api-server", already_labelled=True),
            _deployment("staging", "worker"),
        ]
    )
    count = labeller.label_eligible_namespaces()
    assert count == 1
    assert apps_api.patch_namespaced_deployment.call_count == 1


def test_unannotated_namespace_deployments_not_touched(labeller, core_api, apps_api):
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[
            _namespace("prod", annotated=False),
            _namespace("staging", annotated=True),
        ]
    )
    apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
        items=[_deployment("staging", "worker")]
    )
    labeller.label_eligible_namespaces()
    # Only called once (for "staging"), not twice
    apps_api.list_namespaced_deployment.assert_called_once_with("staging")


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------

def test_list_namespace_failure_returns_zero(labeller, core_api):
    core_api.list_namespace.side_effect = RuntimeError("k8s down")
    count = labeller.label_eligible_namespaces()
    assert count == 0


def test_patch_failure_is_logged_and_skipped(labeller, core_api, apps_api):
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[_namespace("staging", annotated=True)]
    )
    apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
        items=[_deployment("staging", "api-server")]
    )
    apps_api.patch_namespaced_deployment.side_effect = RuntimeError("patch failed")
    count = labeller.label_eligible_namespaces()
    assert count == 0  # patch raised, so nothing counted


# ------------------------------------------------------------------
# Dry-run
# ------------------------------------------------------------------

def test_dry_run_does_not_patch(core_api, apps_api):
    labeller = AutoLabeller(core_api, apps_api, dry_run=True)
    core_api.list_namespace.return_value = SimpleNamespace(
        items=[_namespace("staging", annotated=True)]
    )
    apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
        items=[_deployment("staging", "worker")]
    )
    count = labeller.label_eligible_namespaces()
    assert count == 1  # dry-run still counts
    apps_api.patch_namespaced_deployment.assert_not_called()
