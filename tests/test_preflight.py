"""
Tests for controller.preflight — startup configuration validator.

Each check (schedule, Prometheus, K8s nodes, eligible deployments, Prophet,
HPA RBAC, state ConfigMap) is exercised for PASS, WARN, FAIL, and SKIP
outcomes.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from controller.preflight import CheckResult, PreflightChecker, log_preflight_results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_cfg(**overrides):
    defaults = dict(
        prometheus_url="http://prometheus:9090",
        business_hours_start="07:00",
        business_hours_end="19:00",
        business_days=[0, 1, 2, 3, 4],
        timezone="UTC",
        namespace_filter="",
        enable_prophet=False,
        prophet_training_weeks=4,
        enable_hpa_suspend=True,
        state_configmap_name="finops-scaler-state",
        state_configmap_ns="kube-system",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _checker():
    return PreflightChecker()


def _items(count):
    return SimpleNamespace(items=[SimpleNamespace() for _ in range(count)])


# ── Schedule check ────────────────────────────────────────────────────────────

def test_schedule_passes_with_valid_hours():
    r = _checker()._check_schedule(_make_cfg())
    assert r.status == "PASS"
    assert "07:00" in r.message


def test_schedule_fails_when_start_not_before_end():
    r = _checker()._check_schedule(_make_cfg(
        business_hours_start="19:00", business_hours_end="07:00"
    ))
    assert r.status == "FAIL"
    assert "not before" in r.message


def test_schedule_fails_when_hours_equal():
    r = _checker()._check_schedule(_make_cfg(
        business_hours_start="08:00", business_hours_end="08:00"
    ))
    assert r.status == "FAIL"


def test_schedule_fails_when_business_days_empty():
    r = _checker()._check_schedule(_make_cfg(business_days=[]))
    assert r.status == "FAIL"
    assert "BUSINESS_DAYS" in r.message


def test_schedule_fails_on_malformed_time():
    r = _checker()._check_schedule(_make_cfg(business_hours_start="NOT_A_TIME"))
    assert r.status == "FAIL"


# ── Prometheus check ──────────────────────────────────────────────────────────

def test_prometheus_passes_when_scalar_returns_value():
    prom = MagicMock()
    prom.scalar.return_value = 1.0
    r = _checker()._check_prometheus(_make_cfg(), prom)
    assert r.status == "PASS"
    assert "prometheus:9090" in r.message


def test_prometheus_warns_when_scalar_returns_none():
    prom = MagicMock()
    prom.scalar.return_value = None
    r = _checker()._check_prometheus(_make_cfg(), prom)
    assert r.status == "WARN"


def test_prometheus_fails_on_connection_error():
    prom = MagicMock()
    prom.scalar.side_effect = ConnectionError("refused")
    r = _checker()._check_prometheus(_make_cfg(), prom)
    assert r.status == "FAIL"
    assert "refused" in r.message


# ── K8s checks ────────────────────────────────────────────────────────────────

def test_k8s_nodes_passes_when_nodes_visible():
    core = MagicMock()
    core.list_node.return_value = _items(3)
    apps = MagicMock()
    apps.list_deployment_for_all_namespaces.return_value = _items(2)
    results = _checker()._check_k8s(_make_cfg(), core, apps)
    node_r = next(r for r in results if r.name == "K8s nodes")
    assert node_r.status == "PASS"
    assert "3" in node_r.message


def test_k8s_nodes_fails_on_api_error():
    core = MagicMock()
    core.list_node.side_effect = RuntimeError("forbidden")
    apps = MagicMock()
    apps.list_deployment_for_all_namespaces.return_value = _items(0)
    results = _checker()._check_k8s(_make_cfg(), core, apps)
    node_r = next(r for r in results if r.name == "K8s nodes")
    assert node_r.status == "FAIL"


def test_eligible_deployments_warns_when_zero():
    core = MagicMock()
    core.list_node.return_value = _items(3)
    apps = MagicMock()
    apps.list_deployment_for_all_namespaces.return_value = _items(0)
    results = _checker()._check_k8s(_make_cfg(), core, apps)
    dep_r = next(r for r in results if r.name == "Eligible deployments")
    assert dep_r.status == "WARN"
    assert "0" in dep_r.message


def test_eligible_deployments_passes_with_matches():
    core = MagicMock()
    core.list_node.return_value = _items(2)
    apps = MagicMock()
    apps.list_deployment_for_all_namespaces.return_value = _items(4)
    results = _checker()._check_k8s(_make_cfg(), core, apps)
    dep_r = next(r for r in results if r.name == "Eligible deployments")
    assert dep_r.status == "PASS"
    assert "4" in dep_r.message


def test_eligible_deployments_uses_namespace_filter():
    core = MagicMock()
    core.list_node.return_value = _items(1)
    apps = MagicMock()
    apps.list_namespaced_deployment.return_value = _items(1)
    results = _checker()._check_k8s(_make_cfg(namespace_filter="staging"), core, apps)
    apps.list_namespaced_deployment.assert_called_once_with(
        "staging", label_selector="finops.io/scaledown-eligible=true"
    )
    dep_r = next(r for r in results if r.name == "Eligible deployments")
    assert dep_r.status == "PASS"


# ── Prophet check ─────────────────────────────────────────────────────────────

def test_prophet_skipped_when_disabled():
    r = _checker()._check_prophet(_make_cfg(enable_prophet=False))
    assert r.status == "SKIP"


def test_prophet_passes_when_package_installed():
    with patch.dict("sys.modules", {"prophet": MagicMock()}):
        r = _checker()._check_prophet(_make_cfg(enable_prophet=True))
    assert r.status == "PASS"


def test_prophet_fails_when_package_missing():
    with patch("builtins.__import__", side_effect=ImportError("No module named 'prophet'")):
        r = _checker()._check_prophet(_make_cfg(enable_prophet=True))
    assert r.status == "FAIL"
    assert "requirements-prophet.txt" in r.message


# ── HPA RBAC check ────────────────────────────────────────────────────────────

def test_hpa_rbac_skipped_when_hpa_suspend_disabled():
    r = _checker()._check_hpa_rbac(_make_cfg(enable_hpa_suspend=False), autoscaling_api=None)
    assert r.status == "SKIP"


def test_hpa_rbac_skipped_when_no_autoscaling_api():
    r = _checker()._check_hpa_rbac(_make_cfg(enable_hpa_suspend=True), autoscaling_api=None)
    assert r.status == "SKIP"


def test_hpa_rbac_passes_when_list_succeeds():
    hpa_api = MagicMock()
    hpa_api.list_namespaced_horizontal_pod_autoscaler.return_value = _items(0)
    r = _checker()._check_hpa_rbac(_make_cfg(enable_hpa_suspend=True), autoscaling_api=hpa_api)
    assert r.status == "PASS"


def test_hpa_rbac_fails_when_forbidden():
    hpa_api = MagicMock()
    hpa_api.list_namespaced_horizontal_pod_autoscaler.side_effect = RuntimeError("403 Forbidden")
    r = _checker()._check_hpa_rbac(_make_cfg(enable_hpa_suspend=True), autoscaling_api=hpa_api)
    assert r.status == "FAIL"
    assert "ClusterRole" in r.message


def test_hpa_rbac_warns_on_inconclusive_error():
    hpa_api = MagicMock()
    hpa_api.list_namespaced_horizontal_pod_autoscaler.side_effect = RuntimeError("timeout")
    r = _checker()._check_hpa_rbac(_make_cfg(enable_hpa_suspend=True), autoscaling_api=hpa_api)
    assert r.status == "WARN"


# ── State ConfigMap check ─────────────────────────────────────────────────────

def test_state_cm_passes_when_found():
    core = MagicMock()
    core.read_namespaced_config_map.return_value = SimpleNamespace(data={})
    r = _checker()._check_state_cm(_make_cfg(), core)
    assert r.status == "PASS"
    assert "kube-system" in r.message


def test_state_cm_warns_when_not_found():
    core = MagicMock()
    core.read_namespaced_config_map.side_effect = RuntimeError("404 Not Found")
    r = _checker()._check_state_cm(_make_cfg(), core)
    assert r.status == "WARN"
    assert "created on first" in r.message


def test_state_cm_fails_on_unexpected_error():
    core = MagicMock()
    core.read_namespaced_config_map.side_effect = RuntimeError("forbidden")
    r = _checker()._check_state_cm(_make_cfg(), core)
    assert r.status == "FAIL"


# ── log_preflight_results ─────────────────────────────────────────────────────

def test_log_preflight_results_returns_fail_count():
    results = [
        CheckResult("A", "PASS", "ok"),
        CheckResult("B", "WARN", "watch out"),
        CheckResult("C", "FAIL", "broken"),
        CheckResult("D", "SKIP", "not needed"),
    ]
    count = log_preflight_results(results)
    assert count == 1


def test_log_preflight_results_returns_zero_when_all_pass():
    results = [
        CheckResult("A", "PASS", "ok"),
        CheckResult("B", "PASS", "also ok"),
    ]
    assert log_preflight_results(results) == 0
