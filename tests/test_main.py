from unittest.mock import MagicMock, patch

from controller import main as main_module


def _run_tick(cfg, mock_state_store, low: bool, mins_to_active, scaled_down_replicas: dict):
    predictor = MagicMock()
    predictor.is_low_activity.return_value = low
    predictor.minutes_until_next_active_window.return_value = mins_to_active
    mock_state_store.load_replicas.return_value = scaled_down_replicas

    scaler = MagicMock()
    scaler.find_eligible.return_value = []  # no stranded workloads by default
    node_mgr = MagicMock()

    with patch.object(main_module, "_scale_down_cluster") as mock_down, \
         patch.object(main_module, "_scale_up_cluster") as mock_up:
        main_module._tick(cfg, predictor, scaler, node_mgr, mock_state_store)
        return mock_down, mock_up


def _eligible_dep(namespace: str, name: str, replicas: int):
    """Build a minimal V1Deployment-shaped mock for stranded-detection tests."""
    dep = MagicMock()
    dep.metadata.namespace = namespace
    dep.metadata.name = name
    dep.spec.replicas = replicas
    return dep


# ------------------------------------------------------------------
# Control-loop transition logic
# ------------------------------------------------------------------

def test_tick_enters_idle_window_and_scales_down(cfg, mock_state_store):
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=True, mins_to_active=300, scaled_down_replicas={}
    )
    mock_down.assert_called_once()
    mock_up.assert_not_called()


def test_tick_already_idle_no_action(cfg, mock_state_store):
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=True, mins_to_active=300, scaled_down_replicas={"default/worker": 3}
    )
    mock_down.assert_not_called()
    mock_up.assert_not_called()


def test_tick_active_window_restores_cluster(cfg, mock_state_store):
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=False, mins_to_active=None, scaled_down_replicas={"default/worker": 3}
    )
    mock_up.assert_called_once()
    mock_down.assert_not_called()


def test_tick_already_active_no_action(cfg, mock_state_store):
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=False, mins_to_active=None, scaled_down_replicas={}
    )
    mock_down.assert_not_called()
    mock_up.assert_not_called()


def test_tick_prewarm_triggers_scale_up(cfg, mock_state_store):
    # 10 minutes until active window, prewarm_minutes=15 → should pre-warm
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=True, mins_to_active=10, scaled_down_replicas={"default/worker": 3}
    )
    mock_up.assert_called_once()
    mock_down.assert_not_called()


def test_tick_prewarm_does_not_trigger_if_not_scaled_down(cfg, mock_state_store):
    # Pre-warm window but nothing was scaled down → no action
    mock_down, mock_up = _run_tick(
        cfg, mock_state_store,
        low=True, mins_to_active=10, scaled_down_replicas={}
    )
    mock_down.assert_not_called()
    mock_up.assert_not_called()


# ------------------------------------------------------------------
# State-loss guard — stranded workload detection
# ------------------------------------------------------------------

def test_detect_stranded_returns_zero_replica_deps_not_in_state():
    state_store = MagicMock()
    state_store.load_replicas.return_value = {}  # state wiped
    scaler = MagicMock()
    scaler.find_eligible.return_value = [
        _eligible_dep("default", "api", 0),     # stranded
        _eligible_dep("staging", "worker", 3),  # healthy — non-zero
        _eligible_dep("prod", "billing", 0),    # stranded
    ]
    stranded = main_module._detect_stranded_workloads(scaler, state_store)
    assert sorted(stranded) == ["default/api", "prod/billing"]


def test_detect_stranded_ignores_deps_present_in_state():
    state_store = MagicMock()
    state_store.load_replicas.return_value = {"default/api": 3}
    scaler = MagicMock()
    scaler.find_eligible.return_value = [_eligible_dep("default", "api", 0)]
    assert main_module._detect_stranded_workloads(scaler, state_store) == []


def test_detect_stranded_returns_empty_on_list_failure():
    state_store = MagicMock()
    state_store.load_replicas.return_value = {}
    scaler = MagicMock()
    scaler.find_eligible.side_effect = RuntimeError("api down")
    # Must not raise — failure is logged and we return empty list
    assert main_module._detect_stranded_workloads(scaler, state_store) == []


def test_tick_refuses_to_act_when_state_lost_without_ack(cfg, mock_state_store):
    """State-loss + ack=False → skip tick entirely, even when scale-down would normally fire."""
    cfg.acknowledge_state_loss = False
    mock_state_store.load_replicas.return_value = {}

    predictor = MagicMock()
    predictor.is_low_activity.return_value = True
    predictor.minutes_until_next_active_window.return_value = 300

    scaler = MagicMock()
    scaler.find_eligible.return_value = [_eligible_dep("default", "api", 0)]

    with patch.object(main_module, "_scale_down_cluster") as mock_down, \
         patch.object(main_module, "_scale_up_cluster") as mock_up:
        main_module._tick(cfg, predictor, scaler, MagicMock(), mock_state_store)

    mock_down.assert_not_called()
    mock_up.assert_not_called()
    mock_state_store.save_replicas.assert_not_called()  # state not modified


def test_tick_reseeds_state_when_state_lost_with_ack(cfg, mock_state_store):
    """State-loss + ack=True → re-seed state with default replicas=1 per stranded dep."""
    cfg.acknowledge_state_loss = True
    mock_state_store.load_replicas.return_value = {}

    predictor = MagicMock()
    predictor.is_low_activity.return_value = False  # active window
    predictor.minutes_until_next_active_window.return_value = None

    scaler = MagicMock()
    scaler.find_eligible.return_value = [
        _eligible_dep("default", "api", 0),
        _eligible_dep("prod", "billing", 0),
    ]

    with patch.object(main_module, "_scale_down_cluster"), \
         patch.object(main_module, "_scale_up_cluster"):
        main_module._tick(cfg, predictor, scaler, MagicMock(), mock_state_store)

    # Both stranded deployments re-seeded with replicas=1
    save_calls = mock_state_store.save_replicas.call_args_list
    saved = {(c.args[0], c.args[1]): c.args[2] for c in save_calls}
    assert saved == {("default", "api"): 1, ("prod", "billing"): 1}
