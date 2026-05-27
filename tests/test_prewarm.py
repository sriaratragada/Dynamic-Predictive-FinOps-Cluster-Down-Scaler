"""
Tests for dashboard.backend.prewarm — Smart Pre-Warm Engine.

Covers:
  - is_warm() cache logic (hit, miss, expiry)
  - handle_signal() dispatch (warm / warming / cold branches)
  - signal confidence values
  - _ping() success and failure paths
  - multi-service isolation
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from dashboard.backend.prewarm import PrewarmController, SIGNAL_CONFIDENCE


# ── is_warm() ──────────────────────────────────────────────────────────────────

def test_is_warm_false_by_default():
    ctrl = PrewarmController()
    assert ctrl.is_warm("http://model-api") is False


def test_is_warm_true_when_cache_entry_exists():
    ctrl = PrewarmController()
    ctrl._warm_until["http://model-api"] = time.monotonic() + 1000
    assert ctrl.is_warm("http://model-api") is True


def test_is_warm_false_after_ttl_expires():
    ctrl = PrewarmController(warm_ttl_seconds=1)
    ctrl._warm_until["http://model-api"] = time.monotonic() - 1  # already past
    assert ctrl.is_warm("http://model-api") is False


# ── handle_signal() — warm branch ─────────────────────────────────────────────

async def test_warm_service_returns_warm_no_action():
    ctrl = PrewarmController()
    ctrl._warm_until["http://svc"] = time.monotonic() + 500
    result = await ctrl.handle_signal("http://svc", "login")
    assert result["status"] == "warm"
    assert result["action"] == "none"
    assert result["signal"] == "login"


# ── handle_signal() — in-flight dedup branch ─────────────────────────────────

async def test_inflight_service_returns_warming():
    ctrl = PrewarmController()
    ctrl._inflight.add("http://svc")
    result = await ctrl.handle_signal("http://svc", "hover")
    assert result["status"] == "warming"
    assert result["action"] == "none"


# ── handle_signal() — cold branch ────────────────────────────────────────────

def _discard_coro(coro):
    """Close the coroutine immediately so Python doesn't warn about it being unawaited."""
    coro.close()


async def test_cold_service_fires_prewarm_and_returns_cold():
    ctrl = PrewarmController()
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        result = await ctrl.handle_signal("http://svc", "login")
    assert result["status"] == "cold"
    assert result["action"] == "prewarm_triggered"
    assert result["signal"] == "login"
    assert result["confidence"] == SIGNAL_CONFIDENCE["login"]
    mock_task.assert_called_once()


async def test_cold_service_input_focus_confidence():
    ctrl = PrewarmController()
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro):
        result = await ctrl.handle_signal("http://svc", "input_focus")
    assert result["confidence"] == SIGNAL_CONFIDENCE["input_focus"]


async def test_cold_service_page_load_confidence():
    ctrl = PrewarmController()
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro):
        result = await ctrl.handle_signal("http://svc", "page_load")
    assert result["confidence"] == SIGNAL_CONFIDENCE["page_load"]


async def test_cold_service_hover_confidence():
    ctrl = PrewarmController()
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro):
        result = await ctrl.handle_signal("http://svc", "hover")
    assert result["confidence"] == SIGNAL_CONFIDENCE["hover"]


async def test_unknown_signal_type_returns_zero_confidence():
    ctrl = PrewarmController()
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro):
        result = await ctrl.handle_signal("http://svc", "MADE_UP_SIGNAL")
    assert result["confidence"] == 0.0
    assert result["status"] == "cold"


# ── _ping() — success path ────────────────────────────────────────────────────

async def test_ping_success_marks_service_warm():
    ctrl = PrewarmController(warm_ttl_seconds=180)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("dashboard.backend.prewarm.httpx.AsyncClient", return_value=mock_client):
        await ctrl._ping("http://svc")

    assert ctrl.is_warm("http://svc") is True
    assert "http://svc" not in ctrl._inflight


async def test_ping_success_sends_prewarm_header():
    ctrl = PrewarmController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("dashboard.backend.prewarm.httpx.AsyncClient", return_value=mock_client):
        await ctrl._ping("http://svc")

    _, kwargs = mock_client.get.call_args
    assert kwargs.get("headers", {}).get("X-Prewarm") == "true"


# ── _ping() — failure paths ───────────────────────────────────────────────────

async def test_ping_timeout_does_not_mark_warm():
    ctrl = PrewarmController()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("dashboard.backend.prewarm.httpx.AsyncClient", return_value=mock_client):
        await ctrl._ping("http://svc")

    assert ctrl.is_warm("http://svc") is False
    assert "http://svc" not in ctrl._inflight  # inflight cleared in finally


async def test_ping_connection_error_does_not_mark_warm():
    ctrl = PrewarmController()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch("dashboard.backend.prewarm.httpx.AsyncClient", return_value=mock_client):
        await ctrl._ping("http://svc")

    assert ctrl.is_warm("http://svc") is False
    assert "http://svc" not in ctrl._inflight


# ── Multi-service isolation ───────────────────────────────────────────────────

def test_two_services_do_not_share_warm_state():
    ctrl = PrewarmController()
    ctrl._warm_until["http://svc-a"] = time.monotonic() + 1000
    assert ctrl.is_warm("http://svc-a") is True
    assert ctrl.is_warm("http://svc-b") is False


async def test_inflight_for_one_url_does_not_block_another():
    ctrl = PrewarmController()
    ctrl._inflight.add("http://svc-a")
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        result = await ctrl.handle_signal("http://svc-b", "login")
    assert result["status"] == "cold"
    mock_task.assert_called_once()


# ── Thrash protection — attempt cooldown ──────────────────────────────────────

async def test_attempt_cooldown_blocks_immediate_retry_after_attempt():
    """A second signal arriving inside the cooldown window must not fire a ping."""
    ctrl = PrewarmController(signal_debounce_seconds=0, attempt_cooldown_seconds=30)
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        first = await ctrl.handle_signal("http://svc", "login")
        second = await ctrl.handle_signal("http://svc", "login")

    assert first["status"] == "cold"
    assert first["action"] == "prewarm_triggered"
    assert second["status"] == "cooldown"
    assert second["action"] == "none"
    assert "retry_after_s" in second
    mock_task.assert_called_once()


async def test_attempt_cooldown_expires_after_window():
    ctrl = PrewarmController(signal_debounce_seconds=0, attempt_cooldown_seconds=30)
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        await ctrl.handle_signal("http://svc", "login")
        # Manually expire cooldown — easier than mocking time.monotonic everywhere
        ctrl._attempt_after["http://svc"] = time.monotonic() - 1
        result = await ctrl.handle_signal("http://svc", "login")

    assert result["status"] == "cold"
    assert mock_task.call_count == 2


async def test_attempt_cooldown_disabled_when_zero():
    ctrl = PrewarmController(
        signal_debounce_seconds=0, attempt_cooldown_seconds=0, rate_limit_max_attempts=0
    )
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        await ctrl.handle_signal("http://svc", "login")
        result = await ctrl.handle_signal("http://svc", "login")
    # Without cooldown, second signal still hits inflight guard — but inflight
    # only blocks while a ping is mid-flight.  In tests asyncio.create_task is
    # discarded, so _ping never adds to _inflight.  Therefore the second signal
    # should fire a fresh ping.
    assert result["action"] == "prewarm_triggered"
    assert mock_task.call_count == 2


# ── Thrash protection — signal debounce ───────────────────────────────────────

async def test_signal_debounce_collapses_rapid_identical_signals():
    """Repeated hover events within the debounce window must collapse to one."""
    ctrl = PrewarmController(signal_debounce_seconds=2.0, attempt_cooldown_seconds=0)
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        first = await ctrl.handle_signal("http://svc", "hover")
        second = await ctrl.handle_signal("http://svc", "hover")

    assert first["action"] == "prewarm_triggered"
    assert second["status"] == "debounced"
    mock_task.assert_called_once()


async def test_signal_debounce_does_not_block_different_signal_type():
    """Different signal types for the same URL are tracked independently."""
    ctrl = PrewarmController(
        signal_debounce_seconds=2.0,
        attempt_cooldown_seconds=0,
        rate_limit_max_attempts=0,
    )
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        first = await ctrl.handle_signal("http://svc", "hover")
        second = await ctrl.handle_signal("http://svc", "login")
    assert first["action"] == "prewarm_triggered"
    # second is not debounced (different signal_type) — it gets through
    assert second["status"] != "debounced"
    assert second["action"] == "prewarm_triggered"
    assert mock_task.call_count == 2


# ── Thrash protection — min confidence floor ──────────────────────────────────

async def test_min_confidence_drops_low_signals():
    ctrl = PrewarmController(min_confidence=0.7)
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        result = await ctrl.handle_signal("http://svc", "hover")  # confidence 0.50
    assert result["status"] == "rejected"
    assert result["reason"] == "below_min_confidence"
    mock_task.assert_not_called()


async def test_min_confidence_allows_high_signals():
    ctrl = PrewarmController(min_confidence=0.7)
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        result = await ctrl.handle_signal("http://svc", "login")  # confidence 0.95
    assert result["action"] == "prewarm_triggered"
    mock_task.assert_called_once()


# ── Thrash protection — sliding-window rate limit ─────────────────────────────

async def test_rate_limit_caps_attempts_per_window():
    """After max attempts, further signals in the window are rate-limited."""
    ctrl = PrewarmController(
        signal_debounce_seconds=0,
        attempt_cooldown_seconds=0,
        rate_limit_max_attempts=3,
        rate_limit_window_seconds=300,
    )
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        r1 = await ctrl.handle_signal("http://svc", "login")
        r2 = await ctrl.handle_signal("http://svc", "login")
        r3 = await ctrl.handle_signal("http://svc", "login")
        r4 = await ctrl.handle_signal("http://svc", "login")

    assert r1["action"] == "prewarm_triggered"
    assert r2["action"] == "prewarm_triggered"
    assert r3["action"] == "prewarm_triggered"
    assert r4["status"] == "rate_limited"
    assert r4["max_attempts"] == 3
    assert mock_task.call_count == 3


async def test_rate_limit_disabled_when_zero():
    ctrl = PrewarmController(
        signal_debounce_seconds=0,
        attempt_cooldown_seconds=0,
        rate_limit_max_attempts=0,
    )
    with patch("dashboard.backend.prewarm.asyncio.create_task", side_effect=_discard_coro) as mock_task:
        for _ in range(10):
            await ctrl.handle_signal("http://svc", "login")
    assert mock_task.call_count == 10
