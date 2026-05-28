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

Thrashing protection
--------------------
Without limits, a stream of low-confidence signals (e.g. a user repeatedly
hovering the AI button without submitting) could ping the service every time
Knative's grace period expires, producing a wasteful spin-up / tear-down
cycle.  Three layers guard against this:

  1. ``min_confidence``      — drop signals below this confidence outright.
  2. signal debounce         — collapse identical (url, signal) within N s.
  3. ``attempt_cooldown``    — refuse new pings to a URL for N s after any
                                attempt (success OR failure), preventing both
                                rapid-retry storms and warm-cache thrash.
  4. sliding-window rate cap — hard ceiling on attempts per URL per window.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional

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

    def __init__(
        self,
        warm_ttl_seconds: int = 180,
        attempt_cooldown_seconds: int = 30,
        signal_debounce_seconds: float = 2.0,
        min_confidence: float = 0.0,
        rate_limit_max_attempts: int = 5,
        rate_limit_window_seconds: int = 300,
        history_maxlen: int = 50,
    ):
        """
        Args:
            warm_ttl_seconds: How long to treat a service as warm after a
                successful ping.  Set this conservatively below Knative's
                ``scale-to-zero-grace-period`` (default 30s–300s depending
                on your config).  180 s is a safe default for most setups.

            attempt_cooldown_seconds: Minimum interval between *attempts*
                to the same URL — applied whether the previous ping
                succeeded or failed.  Prevents immediate retry storms after
                a failure and tames hover-spam thrashing once the warm
                cache expires.  Set to 0 to disable.

            signal_debounce_seconds: Window during which repeated identical
                (service_url, signal_type) signals are collapsed to one.
                Cheap defence against fast-firing UI events (mouse
                wiggling across a hover target, repeated focus/blur, etc.).
                Set to 0 to disable.

            min_confidence: Signals with confidence strictly below this
                value are dropped outright.  Operators who don't trust
                hover-only triggers can set this to e.g. 0.7 to require
                stronger intent before paying compute cost.

            rate_limit_max_attempts: Maximum number of pre-warm pings to
                the same URL within ``rate_limit_window_seconds``.  Hard
                ceiling against pathological cases (auto-clickers, broken
                clients).  Set to 0 to disable.

            rate_limit_window_seconds: Length of the sliding window for
                the rate limit above.
        """
        self._warm_ttl = warm_ttl_seconds
        self._attempt_cooldown = attempt_cooldown_seconds
        self._signal_debounce = signal_debounce_seconds
        self._min_confidence = min_confidence
        self._rate_max = rate_limit_max_attempts
        self._rate_window = rate_limit_window_seconds

        self._warm_until: dict[str, float] = {}        # service_url → monotonic expiry
        self._inflight: set[str] = set()               # service_urls with a ping in flight
        self._attempt_after: dict[str, float] = {}     # service_url → earliest next attempt
        self._last_signal_at: dict[tuple[str, str], float] = {}  # (url, signal) → ts
        self._attempt_history: dict[str, Deque[float]] = {}      # service_url → ping timestamps
        self._history: deque = deque(maxlen=history_maxlen)

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
        now = time.monotonic()

        # 1) Confidence floor — operator can disable low-trust signals wholesale
        if confidence < self._min_confidence:
            logger.debug(
                "Pre-warm skip — signal=%s confidence=%.2f below floor=%.2f",
                signal_type, confidence, self._min_confidence,
            )
            result = {
                "status": "rejected",
                "action": "none",
                "signal": signal_type,
                "reason": "below_min_confidence",
                "confidence": confidence,
            }
            self._record_history(signal_type, service_url, result["status"])
            return result

        # 2) Signal debounce — collapse identical fast-firing UI events
        if self._signal_debounce > 0:
            key = (service_url, signal_type)
            last = self._last_signal_at.get(key, 0.0)
            if now - last < self._signal_debounce:
                logger.debug(
                    "Pre-warm skip — debounced %s/%s (%.2fs since last)",
                    service_url, signal_type, now - last,
                )
                result = {
                    "status": "debounced",
                    "action": "none",
                    "signal": signal_type,
                }
                self._record_history(signal_type, service_url, result["status"])
                return result
            self._last_signal_at[key] = now

        # 3) Warm cache hit — Knative already booted, nothing to do
        if self.is_warm(service_url):
            logger.debug("Pre-warm skip — %s is already warm", service_url)
            result = {"status": "warm", "action": "none", "signal": signal_type}
            self._record_history(signal_type, service_url, result["status"])
            return result

        # 4) In-flight dedup — a ping is already on the wire
        if service_url in self._inflight:
            logger.debug("Pre-warm skip — %s ping already in flight", service_url)
            result = {"status": "warming", "action": "none", "signal": signal_type}
            self._record_history(signal_type, service_url, result["status"])
            return result

        # 5) Attempt cooldown — refuse rapid re-pings after success OR failure.
        ready_at = self._attempt_after.get(service_url, 0.0)
        if ready_at > now:
            logger.debug(
                "Pre-warm skip — %s in cooldown for %.1fs more",
                service_url, ready_at - now,
            )
            result = {
                "status": "cooldown",
                "action": "none",
                "signal": signal_type,
                "retry_after_s": round(ready_at - now, 1),
            }
            self._record_history(signal_type, service_url, result["status"])
            return result

        # 6) Sliding-window rate limit — hard ceiling on attempts per URL
        if self._rate_max > 0 and self._over_rate_limit(service_url, now):
            logger.warning(
                "Pre-warm rate-limited — %s hit %d attempts in %ds; dropping signal=%s",
                service_url, self._rate_max, self._rate_window, signal_type,
            )
            result = {
                "status": "rate_limited",
                "action": "none",
                "signal": signal_type,
                "max_attempts": self._rate_max,
                "window_s": self._rate_window,
            }
            self._record_history(signal_type, service_url, result["status"])
            return result

        # All guards passed — fire the pre-warm
        self._record_attempt(service_url, now)
        logger.info(
            "Pre-warm triggered — service=%s signal=%s confidence=%.2f user=%s",
            service_url, signal_type, confidence, user_id or "anonymous",
        )
        asyncio.create_task(self._ping(service_url))
        result = {
            "status": "cold",
            "action": "prewarm_triggered",
            "signal": signal_type,
            "confidence": confidence,
        }
        self._record_history(signal_type, service_url, result["status"])
        return result

    def get_history(self) -> list:
        """Return the signal history list (most recent last)."""
        return list(self._history)

    def _record_history(self, signal: str, service_url: str, result: str) -> None:
        """Append a signal event to the history deque."""
        self._history.append({
            "signal": signal,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "service_url": service_url,
            "result": result,
        })

    # ── Internal ──────────────────────────────────────────────────────────────

    def _over_rate_limit(self, service_url: str, now: float) -> bool:
        """Return True if attempts in the trailing window exceed the cap."""
        history = self._attempt_history.get(service_url)
        if not history:
            return False
        cutoff = now - self._rate_window
        # Discard expired entries from the left
        while history and history[0] < cutoff:
            history.popleft()
        return len(history) >= self._rate_max

    def _record_attempt(self, service_url: str, now: float) -> None:
        """Stamp the attempt cooldown and append to the rate-limit window."""
        if self._attempt_cooldown > 0:
            self._attempt_after[service_url] = now + self._attempt_cooldown
        if self._rate_max > 0:
            hist = self._attempt_history.setdefault(service_url, deque())
            hist.append(now)
            # Keep deque trimmed so it doesn't grow unbounded
            cutoff = now - self._rate_window
            while hist and hist[0] < cutoff:
                hist.popleft()

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
