"""
Smart Pre-Warm Engine
=====================
Listens for early-intent signals from frontend clients (login, page load,
hover, input focus) and proactively sends a lightweight HTTP request to a
Knative-hosted AI model service before the user submits a prompt.

Because Knative scales up in response to inbound HTTP traffic, the pre-warm
request causes the activator to boot the pod and load model weights. By the
time the user submits, the container is already warm — eliminating the
cold-start penalty entirely.

Intended for high-conversion scenarios:
  - Dedicated AI chat / inference pages
  - Authenticated flows where login precedes the first prompt
  - Demo pages where hovering the AI button is a strong purchase-intent signal

Do NOT enable globally — only wire signals on pages where AI usage is
the primary purpose and cold-start delay would be directly felt by the user.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Signal confidence ─────────────────────────────────────────────────────────
# Informational only — all signals trigger a pre-warm if the service is cold.
# The confidence value is logged so you can tune which events to hook in your
# frontend based on observed false-positive rates.

SIGNAL_CONFIDENCE: dict[str, float] = {
    "login":        0.95,   # user just authenticated → almost certain to use AI
    "input_focus":  0.90,   # user focused the prompt box → typing imminently
    "page_load":    0.65,   # user navigated to an AI feature page
    "hover":        0.50,   # user hovering the AI call-to-action (≥ 500 ms dwell)
}


class PrewarmController:
    """
    Maintains a warm-state cache per Knative service URL and fires async
    HTTP pings to cold services when an intent signal arrives.

    Thread-safety: single asyncio event loop; no locking required.
    """

    def __init__(self, warm_ttl_seconds: int = 180):
        """
        Args:
            warm_ttl_seconds: How long to treat a service as warm after a
                              successful ping.  Set this conservatively below
                              Knative's ``scale-to-zero-grace-period`` (default
                              30s–300s depending on your config).  180 s is a
                              safe default for most setups.
        """
        self._warm_ttl = warm_ttl_seconds
        self._warm_until: dict[str, float] = {}  # service_url → monotonic expiry
        self._inflight: set[str] = set()          # service_urls with a ping in flight

    # ── Public API ────────────────────────────────────────────────────────────

    def is_warm(self, service_url: str) -> bool:
        """Return True if we believe the service is currently warm."""
        return self._warm_until.get(service_url, 0.0) > time.monotonic()

    async def handle_signal(
        self,
        service_url: str,
        signal_type: str = "unknown",
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Process an intent signal and trigger a pre-warm if appropriate.

        Returns a dict describing the action taken — safe to return directly
        as a JSON response so callers can log outcomes.
        """
        confidence = SIGNAL_CONFIDENCE.get(signal_type, 0.0)

        if self.is_warm(service_url):
            logger.debug("Pre-warm skip — %s is already warm", service_url)
            return {"status": "warm", "action": "none", "signal": signal_type}

        if service_url in self._inflight:
            logger.debug("Pre-warm skip — %s ping already in flight", service_url)
            return {"status": "warming", "action": "none", "signal": signal_type}

        logger.info(
            "Pre-warm triggered — service=%s signal=%s confidence=%.2f user=%s",
            service_url, signal_type, confidence, user_id or "anonymous",
        )
        asyncio.create_task(self._ping(service_url))
        return {
            "status": "cold",
            "action": "prewarm_triggered",
            "signal": signal_type,
            "confidence": confidence,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _ping(self, service_url: str) -> None:
        """
        Send a lightweight GET to the Knative service.

        The ``X-Prewarm: true`` header lets the model service detect that this
        is a warm-up request and skip actual inference, returning 200 immediately.
        If the model service doesn't handle this header, the request still warms
        the pod — it just runs a real inference as a side-effect.

        Timeout is generous (60 s) to cover the full cold-start duration.
        """
        self._inflight.add(service_url)
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(
                    service_url,
                    headers={"X-Prewarm": "true", "User-Agent": "finops-prewarm/1.0"},
                )
            elapsed = time.monotonic() - t0
            self._warm_until[service_url] = time.monotonic() + self._warm_ttl
            logger.info(
                "Pre-warm complete — %s  status=%d  elapsed=%.1fs  warm_for=%ds",
                service_url, r.status_code, elapsed, self._warm_ttl,
            )
        except httpx.TimeoutException:
            logger.warning("Pre-warm timed out for %s (60 s)", service_url)
        except Exception as exc:
            logger.warning("Pre-warm failed for %s: %s", service_url, exc)
        finally:
            self._inflight.discard(service_url)


# ── Module-level singleton ────────────────────────────────────────────────────
# Shared across all requests in the same process; the warm cache persists for
# the lifetime of the dashboard backend pod.

_controller = PrewarmController()


def get_controller() -> PrewarmController:
    return _controller
