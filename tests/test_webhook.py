"""
Tests for controller.webhook — fire-and-forget HTTP notifier.

Covers payload shape, correct HTTP verb, Slack-compatible fields,
error-swallowing, and default cluster-name behaviour.
"""

from unittest.mock import MagicMock, patch

import pytest

from controller.webhook import WebhookNotifier, _DEFAULT_CLUSTER


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_resp(status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    return resp


# ── notify_scale_down ─────────────────────────────────────────────────────────

def test_scale_down_posts_to_url():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        notifier = WebhookNotifier("http://hooks.example.com/webhook")
        notifier.notify_scale_down(["default/api"], ["node-1"], 0.384)
    mock_post.assert_called_once()
    url_arg = mock_post.call_args[0][0]
    assert url_arg == "http://hooks.example.com/webhook"


def test_scale_down_payload_event_type():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_down([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert payload["event"] == "scale_down"


def test_scale_down_payload_includes_deployments_and_nodes():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_down(
            ["ns/api", "ns/worker"], ["node-1", "node-2"], 0.5
        )
    payload = mock_post.call_args[1]["json"]
    assert payload["deployments"] == ["ns/api", "ns/worker"]
    assert payload["nodes"] == ["node-1", "node-2"]


def test_scale_down_payload_includes_savings_rate():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_down([], [], 1.23)
    payload = mock_post.call_args[1]["json"]
    assert payload["savings_rate_usd_hr"] == pytest.approx(1.23)


def test_scale_down_text_mentions_cluster():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w", cluster_name="prod-eks").notify_scale_down([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert "prod-eks" in payload["text"]


# ── notify_scale_up ───────────────────────────────────────────────────────────

def test_scale_up_posts_to_url():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_up(["default/api"], ["node-1"], 4.56)
    mock_post.assert_called_once()


def test_scale_up_payload_event_type():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_up([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert payload["event"] == "scale_up"


def test_scale_up_payload_includes_savings_usd():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_up([], [], 9.87)
    payload = mock_post.call_args[1]["json"]
    assert payload["savings_usd"] == pytest.approx(9.87)


def test_scale_up_text_mentions_cluster():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w", cluster_name="staging").notify_scale_up([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert "staging" in payload["text"]


# ── Default cluster name ──────────────────────────────────────────────────────

def test_empty_cluster_name_defaults_to_constant():
    notifier = WebhookNotifier("http://h/w", cluster_name="")
    assert notifier._cluster == _DEFAULT_CLUSTER


def test_explicit_cluster_name_is_used():
    notifier = WebhookNotifier("http://h/w", cluster_name="my-cluster")
    assert notifier._cluster == "my-cluster"


# ── Payload contains standard fields ─────────────────────────────────────────

def test_payload_contains_timestamp():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w").notify_scale_down([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert "timestamp" in payload
    assert "T" in payload["timestamp"]  # ISO 8601


def test_payload_contains_cluster():
    with patch("controller.webhook.requests.post", return_value=_mock_resp()) as mock_post:
        WebhookNotifier("http://h/w", cluster_name="demo").notify_scale_up([], [], 0.0)
    payload = mock_post.call_args[1]["json"]
    assert payload["cluster"] == "demo"


# ── Error handling ────────────────────────────────────────────────────────────

def test_network_error_is_swallowed():
    with patch("controller.webhook.requests.post", side_effect=ConnectionError("refused")):
        # Must not raise
        WebhookNotifier("http://h/w").notify_scale_down([], [], 0.0)


def test_http_error_is_swallowed():
    import requests as _req
    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad_resp.raise_for_status.side_effect = _req.HTTPError("500 Server Error")
    with patch("controller.webhook.requests.post", return_value=bad_resp):
        # Must not raise
        WebhookNotifier("http://h/w").notify_scale_up([], [], 0.0)


def test_timeout_is_swallowed():
    import requests as _req
    with patch("controller.webhook.requests.post", side_effect=_req.Timeout("timeout")):
        WebhookNotifier("http://h/w").notify_scale_down([], [], 0.0)
