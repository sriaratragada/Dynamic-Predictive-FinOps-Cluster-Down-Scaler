from unittest.mock import MagicMock, patch

from controller import main as main_module


def _run_tick(cfg, mock_state_store, low: bool, mins_to_active, scaled_down_replicas: dict):
    predictor = MagicMock()
    predictor.is_low_activity.return_value = low
    predictor.minutes_until_next_active_window.return_value = mins_to_active
    mock_state_store.load_replicas.return_value = scaled_down_replicas

    scaler = MagicMock()
    node_mgr = MagicMock()

    with patch.object(main_module, "_scale_down_cluster") as mock_down, \
         patch.object(main_module, "_scale_up_cluster") as mock_up:
        main_module._tick(cfg, predictor, scaler, node_mgr, mock_state_store)
        return mock_down, mock_up


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
