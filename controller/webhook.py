"""
Webhook notifier — HTTP POST on scale-down / scale-up events.

Payload format is Slack-compatible (``text`` + ``attachments``) and also
includes machine-readable fields so it works with any HTTP receiver:

.. code-block:: json

    {
        "text": ":zzz: *FinOps scale-down* — my-cluster ...",
        "event": "scale_down",
        "cluster": "my-cluster",
        "timestamp": "2025-10-01T02:00:00+00:00",
        "deployments": ["default/api-server", "default/worker"],
        "nodes": ["node-2", "node-3"],
        "savings_rate_usd_hr": 0.384
    }

All network errors are swallowed — a broken webhook endpoint must never
prevent scale-down from completing.
"""

import logging
from datetime import datetime, timezone
from typing import List

import requests

logger = logging.getLogger(__name__)

_DEFAULT_CLUSTER = "finops-cluster"


class WebhookNotifier:
    """
    Fire-and-forget HTTP POST notifier.

    Parameters
    ----------
    url:
        The endpoint to POST to (e.g. a Slack Incoming Webhook URL).
    timeout:
        HTTP request timeout in seconds (default: 5).
    cluster_name:
        Human-readable cluster identifier included in every payload.
        Defaults to ``"finops-cluster"`` when empty.
    """

    def __init__(self, url: str, timeout: int = 5, cluster_name: str = ""):
        self._url = url
        self._timeout = timeout
        self._cluster = cluster_name or _DEFAULT_CLUSTER

    def notify_scale_down(
        self,
        deployments: List[str],
        nodes: List[str],
        savings_rate_usd_hr: float,
    ) -> None:
        n_dep = len(deployments)
        n_node = len(nodes)
        text = (
            f":zzz: *FinOps scale-down* — {self._cluster}\n"
            f"Scaled {n_dep} deployment(s) to zero, cordoned {n_node} node(s).\n"
            f"Saving *${savings_rate_usd_hr:.2f}/hr* during off-hours."
        )
        payload = self._build(
            "scale_down",
            deployments,
            nodes,
            text=text,
            savings_rate_usd_hr=savings_rate_usd_hr,
        )
        self._post(payload)

    def notify_scale_up(
        self,
        deployments: List[str],
        nodes: List[str],
        savings_usd: float,
    ) -> None:
        n_dep = len(deployments)
        n_node = len(nodes)
        text = (
            f":sunrise: *FinOps scale-up* — {self._cluster}\n"
            f"Restored {n_dep} deployment(s), uncordoned {n_node} node(s).\n"
            f"Saved *${savings_usd:.2f}* this cycle."
        )
        payload = self._build(
            "scale_up",
            deployments,
            nodes,
            text=text,
            savings_usd=savings_usd,
        )
        self._post(payload)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build(
        self,
        event_type: str,
        deployments: List[str],
        nodes: List[str],
        text: str = "",
        **extra,
    ) -> dict:
        return {
            "text": text,
            "event": event_type,
            "cluster": self._cluster,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "deployments": deployments,
            "nodes": nodes,
            **extra,
        }

    def _post(self, payload: dict) -> None:
        try:
            resp = requests.post(
                self._url, json=payload, timeout=self._timeout
            )
            resp.raise_for_status()
            logger.info(
                "Webhook delivered (%d): %s", resp.status_code, self._url
            )
        except Exception as exc:
            logger.warning("Webhook delivery failed (non-fatal): %s", exc)
