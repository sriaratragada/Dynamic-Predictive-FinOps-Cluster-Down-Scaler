"""
Tests for controller.leader_election — Kubernetes Lease-based leader election.

Covers identity resolution, lease creation, lease renewal, expiry-based
stealing, and acquire_blocking() retry behaviour.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from controller.leader_election import LeaderElector


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _make_lease(holder: str = "pod-1", age_seconds: float = 0.0, duration: int = 30):
    """Return a SimpleNamespace mimicking a V1Lease response."""
    renew_time = _now() - timedelta(seconds=age_seconds)
    return SimpleNamespace(
        spec=SimpleNamespace(
            holder_identity=holder,
            renew_time=renew_time,
            lease_duration_seconds=duration,
        )
    )


@pytest.fixture
def coord_api():
    return MagicMock()


@pytest.fixture
def elector(coord_api):
    return LeaderElector(
        coord_api,
        namespace="kube-system",
        identity="pod-1",
        lease_duration_s=30,
        renew_every_s=10,
        retry_interval_s=0,  # no sleeping in tests
    )


# ── Identity resolution ───────────────────────────────────────────────────────

def test_identity_uses_explicit_value(elector):
    assert elector.identity == "pod-1"


def test_identity_falls_back_to_pod_name_env(monkeypatch):
    monkeypatch.setenv("POD_NAME", "my-pod-xyz")
    e = LeaderElector(MagicMock(), identity=None)
    assert e.identity == "my-pod-xyz"


def test_identity_falls_back_to_hostname_when_no_pod_name(monkeypatch):
    monkeypatch.delenv("POD_NAME", raising=False)
    with patch("controller.leader_election.socket.getfqdn", return_value="my-host"):
        e = LeaderElector(MagicMock(), identity=None)
    assert e.identity == "my-host"


# ── Lease does not exist → create ─────────────────────────────────────────────

def test_creates_lease_when_none_exists(elector, coord_api):
    coord_api.read_namespaced_lease.side_effect = Exception("404 Not Found")
    coord_api.create_namespaced_lease.return_value = None

    result = elector._try_acquire_or_renew()

    assert result is True
    coord_api.create_namespaced_lease.assert_called_once()


def test_create_conflict_returns_false(elector, coord_api):
    coord_api.read_namespaced_lease.side_effect = Exception("404 Not Found")
    coord_api.create_namespaced_lease.side_effect = Exception("409 Conflict")

    result = elector._try_acquire_or_renew()

    assert result is False


# ── Already the holder → renew ────────────────────────────────────────────────

def test_renews_own_lease_successfully(elector, coord_api):
    coord_api.read_namespaced_lease.return_value = _make_lease(holder="pod-1")
    coord_api.replace_namespaced_lease.return_value = None

    result = elector.renew()

    assert result is True
    coord_api.replace_namespaced_lease.assert_called_once()


def test_renew_patches_identity_on_lease_object(elector, coord_api):
    lease = _make_lease(holder="pod-1")
    coord_api.read_namespaced_lease.return_value = lease
    coord_api.replace_namespaced_lease.return_value = None

    elector.renew()

    # Verify the lease spec was mutated before replace was called
    assert lease.spec.holder_identity == "pod-1"
    assert lease.spec.lease_duration_seconds == 30


def test_renew_returns_false_when_replace_fails(elector, coord_api):
    coord_api.read_namespaced_lease.return_value = _make_lease(holder="pod-1")
    coord_api.replace_namespaced_lease.side_effect = Exception("conflict")

    assert elector.renew() is False


# ── Active foreign holder → wait ──────────────────────────────────────────────

def test_active_foreign_lease_returns_false(elector, coord_api):
    # Lease held by pod-2, renewed 5s ago (well within 30s duration)
    coord_api.read_namespaced_lease.return_value = _make_lease(
        holder="pod-2", age_seconds=5.0, duration=30
    )

    result = elector._try_acquire_or_renew()

    assert result is False
    coord_api.replace_namespaced_lease.assert_not_called()


# ── Expired foreign holder → steal ────────────────────────────────────────────

def test_steals_expired_lease(elector, coord_api):
    # Lease held by pod-2 but expired 60s ago
    coord_api.read_namespaced_lease.return_value = _make_lease(
        holder="pod-2", age_seconds=60.0, duration=30
    )
    coord_api.replace_namespaced_lease.return_value = None

    result = elector._try_acquire_or_renew()

    assert result is True


def test_stolen_lease_sets_new_holder(elector, coord_api):
    lease = _make_lease(holder="pod-2", age_seconds=60.0, duration=30)
    coord_api.read_namespaced_lease.return_value = lease
    coord_api.replace_namespaced_lease.return_value = None

    elector._try_acquire_or_renew()

    assert lease.spec.holder_identity == "pod-1"


def test_lease_with_none_renew_time_is_treated_as_expired(elector, coord_api):
    lease = SimpleNamespace(
        spec=SimpleNamespace(
            holder_identity="pod-2",
            renew_time=None,
            lease_duration_seconds=30,
        )
    )
    coord_api.read_namespaced_lease.return_value = lease
    coord_api.replace_namespaced_lease.return_value = None

    result = elector._try_acquire_or_renew()
    assert result is True


# ── acquire_blocking ──────────────────────────────────────────────────────────

def test_acquire_blocking_succeeds_on_first_try(elector, coord_api):
    coord_api.read_namespaced_lease.side_effect = Exception("404 Not Found")
    coord_api.create_namespaced_lease.return_value = None

    elector.acquire_blocking()  # should not block

    coord_api.create_namespaced_lease.assert_called_once()


def test_acquire_blocking_retries_until_lease_expires(coord_api):
    elector = LeaderElector(
        coord_api,
        namespace="kube-system",
        identity="pod-1",
        lease_duration_s=30,
        retry_interval_s=0,
    )
    # First 2 calls: active foreign lease; 3rd call: expired foreign lease
    responses = [
        _make_lease(holder="pod-2", age_seconds=1.0, duration=30),
        _make_lease(holder="pod-2", age_seconds=1.0, duration=30),
        _make_lease(holder="pod-2", age_seconds=60.0, duration=30),
    ]
    coord_api.read_namespaced_lease.side_effect = responses
    coord_api.replace_namespaced_lease.return_value = None

    with patch("controller.leader_election.time.sleep"):
        elector.acquire_blocking()

    assert coord_api.read_namespaced_lease.call_count == 3


# ── _current_holder ───────────────────────────────────────────────────────────

def test_current_holder_returns_identity_from_lease(elector, coord_api):
    coord_api.read_namespaced_lease.return_value = _make_lease(holder="pod-99")
    assert elector._current_holder() == "pod-99"


def test_current_holder_returns_unknown_on_error(elector, coord_api):
    coord_api.read_namespaced_lease.side_effect = Exception("error")
    assert elector._current_holder() == "unknown"


# ── API error handling (non-404) ──────────────────────────────────────────────

def test_unexpected_read_error_returns_false(elector, coord_api):
    coord_api.read_namespaced_lease.side_effect = RuntimeError("network timeout")
    result = elector._try_acquire_or_renew()
    assert result is False
    coord_api.create_namespaced_lease.assert_not_called()
