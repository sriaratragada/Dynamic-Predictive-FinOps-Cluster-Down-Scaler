import asyncio
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Callable, Deque, Dict, List

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500
# Pricing rate refreshes — wall-clock based, not coupled to event throughput.
_PRICING_REFRESH_SECONDS = 30 * 60  # 30 min


class SavingsTracker:
    def __init__(self, k8s_reader, get_rate: Callable[[], float], poll_interval: int = 30):
        self._k8s = k8s_reader
        self._get_rate = get_rate
        self._poll_interval = poll_interval

        # {node_name: cordon_start_utc}
        self._active: Dict[str, datetime] = {}

        # Completed events — bounded ring buffer.
        self._events: Deque[Dict] = deque(maxlen=_MAX_EVENTS)
        self._total_saved: float = 0.0
        self._hourly_rate: float = 0.0
        self._last_rate_refresh: float = 0.0

        # Cooperative cancellation — the run loop checks this on each iteration.
        self._stop_event = asyncio.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the poll loop to exit on its next iteration."""
        self._stop_event.set()

    def list_events(self) -> List[Dict]:
        """Return a snapshot of completed events, oldest → newest."""
        return list(self._events)

    async def start(self):
        """Rehydrate from persisted savings log then run the poll loop."""
        self._rehydrate()
        self._refresh_rate(force=True)

        while not self._stop_event.is_set():
            try:
                await self._poll()
            except Exception as exc:
                logger.warning("Savings tracker poll error: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass  # normal poll cadence — keep going
        logger.info("Savings tracker stopped")

    def get_summary(self) -> Dict:
        now = datetime.now(tz=timezone.utc)
        week_ago  = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        this_week = sum(
            e["saved_usd"] for e in self._events
            if datetime.fromisoformat(e["end"]) >= week_ago
        )
        this_month = sum(
            e["saved_usd"] for e in self._events
            if datetime.fromisoformat(e["end"]) >= month_ago
        )

        # Running unrealised savings for currently cordoned nodes
        running = sum(
            (now - start).total_seconds() / 3600 * self._hourly_rate
            for start in self._active.values()
        )

        return {
            "total_saved_usd": round(self._total_saved + running, 2),
            "this_week_usd": round(this_week, 2),
            "this_month_usd": round(this_month, 2),
            "hourly_rate_per_node": round(self._hourly_rate, 6),
            "currently_cordoned_count": len(self._active),
            "active_cordon_running_cost": round(running, 4),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _rehydrate(self) -> None:
        try:
            saved = self._k8s.read_savings_log()
        except Exception as exc:
            logger.warning("Could not rehydrate savings log: %s", exc)
            return

        self._events.extend(saved.get("events", []))
        self._total_saved = saved.get("total_saved_usd", 0.0)
        # Restore in-flight active cordons so a pod restart does not
        # lose cordon start times and under-count savings.
        active_raw: dict = saved.get("active_cordons", {}) or {}
        self._active = {
            node: datetime.fromisoformat(ts)
            for node, ts in active_raw.items()
        }
        logger.info(
            "Savings rehydrated: $%.2f total, %d events, %d active cordon(s)",
            self._total_saved, len(self._events), len(self._active),
        )

    def _refresh_rate(self, force: bool = False) -> None:
        """Refresh hourly pricing on wall-clock cadence (or on demand)."""
        import time
        now = time.monotonic()
        if not force and (now - self._last_rate_refresh) < _PRICING_REFRESH_SECONDS:
            return
        try:
            self._hourly_rate = self._get_rate()
            self._last_rate_refresh = now
        except Exception as exc:
            logger.warning("Could not refresh pricing rate: %s", exc)

    async def _poll(self):
        self._refresh_rate()
        state = self._k8s.read_state()
        current: List[str] = state.get("cordoned_nodes", [])
        now = datetime.now(tz=timezone.utc)

        # Newly cordoned — persist start time immediately so a pod restart
        # can recover the correct duration even before the node uncordons.
        new_cordons = False
        for node in current:
            if node not in self._active:
                self._active[node] = now
                new_cordons = True
                logger.info("Cordon detected: %s at %s", node, now.isoformat())
        if new_cordons:
            self._persist()

        # Uncordoned → completed savings event
        for node in list(self._active):
            if node not in current:
                start = self._active.pop(node)
                hours = (now - start).total_seconds() / 3600
                saved = hours * self._hourly_rate
                event = {
                    "node": node,
                    "start": start.isoformat(),
                    "end": now.isoformat(),
                    "hours": round(hours, 4),
                    "rate_usd_hr": round(self._hourly_rate, 6),
                    "saved_usd": round(saved, 4),
                }
                self._events.append(event)
                self._total_saved += saved
                logger.info("Savings event: %s uncordoned %.2fh → $%.2f saved", node, hours, saved)
                self._persist()

    def _persist(self) -> None:
        try:
            self._k8s.write_savings_log({
                "events": list(self._events),
                "total_saved_usd": self._total_saved,
                "active_cordons": {n: dt.isoformat() for n, dt in self._active.items()},
            })
        except Exception as exc:
            logger.warning("Could not persist savings log: %s", exc)
