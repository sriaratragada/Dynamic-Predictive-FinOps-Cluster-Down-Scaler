from unittest.mock import MagicMock

import pytest
from kubernetes import client

from controller.config import Config
from controller.metrics import PrometheusClient
from controller.state_store import StateStore


@pytest.fixture
def cfg():
    return Config(
        prometheus_url="http://prometheus:9090",
        business_hours_start="07:00",
        business_hours_end="19:00",
        business_days=[0, 1, 2, 3, 4],
        prewarm_minutes=15,
        loop_interval_seconds=60,
        namespace_filter="",
        min_replica_floor=0,
        node_utilisation_threshold=0.10,
        state_configmap_name="finops-scaler-state",
        state_configmap_ns="kube-system",
        timezone="UTC",
        enable_metric_override=False,
        dry_run=False,
        metrics_port=8080,
        enable_prophet=False,
        prophet_training_weeks=4,
        prophet_idle_threshold_cores=0.5,
        prophet_retrain_hours=6,
        enable_gpu_aware=False,
        gpu_idle_threshold=0.10,
    )


@pytest.fixture
def mock_prometheus():
    return MagicMock(spec=PrometheusClient)


@pytest.fixture
def mock_core_api():
    return MagicMock(spec=client.CoreV1Api)


@pytest.fixture
def mock_apps_api():
    return MagicMock(spec=client.AppsV1Api)


@pytest.fixture
def mock_state_store():
    store = MagicMock(spec=StateStore)
    store.load_replicas.return_value = {}
    store.load_cordoned_nodes.return_value = []
    return store
