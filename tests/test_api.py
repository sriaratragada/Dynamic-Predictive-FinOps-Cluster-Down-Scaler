"""
Integration tests for the FastAPI dashboard backend.

These tests exercise the real route handlers against all six API endpoints
using an in-process ASGI transport — no network, no Kubernetes cluster, no
Prometheus required.  The demo K8s reader and Prometheus stubs are used for
all data, identical to what `docker compose up` serves.

Key setup choices
-----------------
- ``_k8s`` in the app module is patched to ``DemoK8sReader()`` so the startup
  lifespan event does not need to fire (httpx ASGITransport does not trigger
  ASGI lifespan by default).
- ``config_store._cfg.demo_mode = True`` activates the Prometheus demo stubs
  inside ``_prom_instant`` / ``_prom_range``.
- Config store state is restored after each test to prevent cross-test leakage.
- ``API_TOKEN`` auth is tested via ``monkeypatch.setenv``; because ``auth.py``
  reads the env var on every request, no module reload is required.
"""

import copy

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(monkeypatch):
    """
    Yield an AsyncClient wired to the FastAPI app in demo mode.
    Restores global state (config store + _k8s) after each test.
    """
    # Ensure no token auth blocks requests by default
    monkeypatch.delenv("API_TOKEN", raising=False)

    from dashboard.backend import app as _app_module, config_store, deps
    from dashboard.backend.demo_stub import DemoK8sReader

    # Save state
    original_k8s = deps._k8s
    original_tracker = deps._tracker
    original_cfg = copy.copy(config_store._cfg)

    # Inject demo dependencies
    deps._k8s = DemoK8sReader()
    deps._tracker = None
    config_store._cfg.demo_mode = True

    async with AsyncClient(
        transport=ASGITransport(app=_app_module.app),
        base_url="http://test",
    ) as c:
        yield c

    # Restore state
    deps._k8s = original_k8s
    deps._tracker = original_tracker
    config_store._cfg = original_cfg


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------

async def test_status_returns_valid_shape(client):
    r = await client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "scaled_down" in data
    assert isinstance(data["cordoned_nodes"], list)
    assert isinstance(data["deployments_scaled"], list)
    assert "cordoned_node_count" in data
    assert "deployment_count" in data


async def test_status_boolean_types(client):
    data = (await client.get("/api/status")).json()
    assert isinstance(data["scaled_down"], bool)


# ---------------------------------------------------------------------------
# GET /api/capacity
# ---------------------------------------------------------------------------

async def test_capacity_returns_valid_shape(client):
    r = await client.get("/api/capacity")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert isinstance(data["nodes"], list)
    assert "total_allocatable_cores" in data
    assert "cluster_utilisation_pct" in data


async def test_capacity_nodes_have_expected_fields(client):
    data = (await client.get("/api/capacity")).json()
    if data["nodes"]:
        node = data["nodes"][0]
        assert "name" in node
        assert "allocatable_cpu_cores" in node
        assert "utilisation_pct" in node
        assert "cordoned" in node


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

async def test_history_default_24h(client):
    r = await client.get("/api/history")
    assert r.status_code == 200
    data = r.json()
    assert data["hours"] == 24
    assert isinstance(data["cpu_used"], list)
    assert isinstance(data["cpu_capacity"], list)
    assert isinstance(data["scaledown_events"], list)
    assert isinstance(data["scaleup_events"], list)


async def test_history_custom_hours(client):
    r = await client.get("/api/history?hours=48")
    assert r.status_code == 200
    assert r.json()["hours"] == 48


async def test_history_cpu_used_has_datapoints(client):
    data = (await client.get("/api/history")).json()
    # Demo mode always generates time-series data
    assert len(data["cpu_used"]) > 0
    first = data["cpu_used"][0]
    assert "t" in first   # unix ms timestamp
    assert "v" in first   # float value


# ---------------------------------------------------------------------------
# GET /api/savings
# ---------------------------------------------------------------------------

async def test_savings_returns_valid_shape(client):
    r = await client.get("/api/savings")
    assert r.status_code == 200
    data = r.json()
    assert "total_saved_usd" in data
    assert "this_week_usd" in data
    assert "this_month_usd" in data
    assert "hourly_rate_per_node" in data
    assert "currently_cordoned_count" in data


async def test_savings_numeric_types(client):
    data = (await client.get("/api/savings")).json()
    assert isinstance(data["total_saved_usd"], float)
    assert isinstance(data["hourly_rate_per_node"], float)
    assert data["total_saved_usd"] >= 0


async def test_savings_demo_has_seeded_history(client):
    data = (await client.get("/api/savings")).json()
    # Demo mode seeds $847.52 base plus monthly events
    assert data["total_saved_usd"] > 0


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------

async def test_config_get_returns_all_fields(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    # Spot-check a field from each config section
    assert "demo_mode" in data              # Connection
    assert "cloud_provider" in data         # Cloud & Pricing
    assert "business_hours_start" in data   # Schedule
    assert "enable_prophet" in data         # Prediction
    assert "poll_interval_seconds" in data  # Dashboard UX
    assert "enable_prewarm" in data         # Pre-Warm Engine


async def test_config_get_demo_mode_is_true(client):
    # Fixture sets demo_mode=True
    assert (await client.get("/api/config")).json()["demo_mode"] is True


# ---------------------------------------------------------------------------
# PATCH /api/config  (no auth)
# ---------------------------------------------------------------------------

async def test_config_patch_updates_field(client):
    r = await client.patch("/api/config", json={"prewarm_minutes": 20})
    assert r.status_code == 200
    assert r.json()["prewarm_minutes"] == 20


async def test_config_patch_unknown_keys_ignored(client):
    r = await client.patch("/api/config", json={"nonexistent_key": "boom"})
    assert r.status_code == 200  # no error, unknown keys silently dropped


async def test_config_patch_multiple_fields(client):
    r = await client.patch(
        "/api/config",
        json={"business_hours_start": "08:00", "business_hours_end": "18:00"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["business_hours_start"] == "08:00"
    assert data["business_hours_end"] == "18:00"


# ---------------------------------------------------------------------------
# Auth — PATCH /api/config
# ---------------------------------------------------------------------------

async def test_patch_config_no_token_when_api_token_set(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-abc")
    r = await client.patch("/api/config", json={"prewarm_minutes": 5})
    assert r.status_code == 401


async def test_patch_config_valid_token_accepted(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-abc")
    r = await client.patch(
        "/api/config",
        json={"prewarm_minutes": 5},
        headers={"Authorization": "Bearer secret-abc"},
    )
    assert r.status_code == 200
    assert r.json()["prewarm_minutes"] == 5


async def test_patch_config_wrong_token_forbidden(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-abc")
    r = await client.patch(
        "/api/config",
        json={"prewarm_minutes": 5},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 403


async def test_patch_config_malformed_auth_header(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-abc")
    # Missing "Bearer " prefix
    r = await client.patch(
        "/api/config",
        json={"prewarm_minutes": 5},
        headers={"Authorization": "secret-abc"},
    )
    assert r.status_code == 401


async def test_patch_config_empty_api_token_allows_all(client, monkeypatch):
    """When API_TOKEN is empty string, auth is disabled — all requests pass."""
    monkeypatch.setenv("API_TOKEN", "")
    r = await client.patch("/api/config", json={"prewarm_minutes": 7})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/prewarm
# ---------------------------------------------------------------------------

async def test_prewarm_disabled_by_default(client):
    r = await client.post("/api/prewarm", json={"service_url": "http://model-api"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_prewarm_missing_service_url_returns_not_configured(client):
    await client.patch("/api/config", json={"enable_prewarm": True})
    r = await client.post("/api/prewarm", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "not_configured"
    assert data["action"] == "none"


async def test_prewarm_requires_token_when_api_token_set(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "tok")
    r = await client.post("/api/prewarm", json={"service_url": "http://model-api"})
    assert r.status_code == 401


async def test_prewarm_valid_token_accepted(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "tok")
    r = await client.post(
        "/api/prewarm",
        json={"service_url": "http://model-api"},
        headers={"Authorization": "Bearer tok"},
    )
    # Even with valid auth: prewarm disabled by default → {enabled: false}
    assert r.status_code == 200
    assert r.json()["enabled"] is False


# ---------------------------------------------------------------------------
# GET /api/events
# ---------------------------------------------------------------------------

async def test_events_returns_valid_shape(client):
    r = await client.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert isinstance(data["events"], list)


async def test_events_demo_has_historical_entries(client):
    data = (await client.get("/api/events")).json()
    # Demo mode seeds ~30 days of cordon events
    assert len(data["events"]) > 0


async def test_events_entries_have_expected_fields(client):
    data = (await client.get("/api/events")).json()
    if data["events"]:
        ev = data["events"][0]
        assert "node" in ev
        assert "start" in ev
        assert "end" in ev
        assert "hours" in ev
        assert "saved_usd" in ev


async def test_events_most_recent_first(client):
    data = (await client.get("/api/events")).json()
    events = data["events"]
    if len(events) >= 2:
        # Most recent event should have a later end time
        from datetime import datetime
        t0 = datetime.fromisoformat(events[0]["end"])
        t1 = datetime.fromisoformat(events[1]["end"])
        assert t0 >= t1
