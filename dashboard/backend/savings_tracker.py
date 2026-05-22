import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SavingsTracker:
    def __init__(self, k8s_reader, get_rate: Callable[[], float], poll_interval: int = 30):
        self._k8s = k8s_reader
        self._get_rate = get_rate
        self._poll_interval = poll_interval

        # {node_name: cordon_start_utc}
        self._active: Dict[str, datetime] = {}

        # Completed events list (max 500 kept in memory)
        self._events: List[Dict] = []
        self._total_saved: float = 0.0
        self._hourly_rate: float = 0.0

    async def start(self):
        """Rehydrate from persisted savings log then run the poll loop."""
        try:
            saved = self._k8s.read_savings_log()
            self._events = saved["events"]
            self._total_saved = saved["total_saved_usd"]
            # Restore in-flight active cordons so a pod restart does not
            # lose cordon start times and under-count savings.
            active_raw: dict = saved.get("active_cordons", {})
            self._active = {
                node: datetime.fromisoformat(ts)
                for node, ts in active_raw.items()
            }
            logger.info(
                "Savings rehydrated: $%.2f total, %d events, %d active cordon(s)",
                self._total_saved, len(self._events), len(self._active),
            )
        except Exception as exc:
            logger.warning("Could not rehydrate savings log: %s", exc)

        try:
            self._hourly_rate = self._get_rate()
        except Exception as exc:
            logger.warning("Could not fetch initial pricing rate: %s", exc)

        while True:
            try:
                await self._poll()
            except Exception as exc:
                logger.warning("Savings tracker poll error: %s", exc)
            await asyncio.sleep(self._poll_interval)

    async def _poll(self):
        state = self._k8s.read_state()
        current: List[str] = state.get("cordoned_nodes", [])
        now = datetime.now(tz=timezone.utc)

        # Refresh pricing every ~50 minutes (100 polls × 30 s)
        if len(self._events) % 100 == 99:
            try:
                self._hourly_rate = self._get_rate()
            except Exception:
                pass

        # Newly cordoned — persist start time immediately so a pod restart
        # can recover the correct duration even before the node uncordons.
        new_cordons = False
        for node in current:
            if node not in self._active:
                self._active[node] = now
                new_cordons = True
                logger.info("Cordon detected: %s at %s", node, now.isoformat())
        if new_cordons:
            try:
                self._k8s.write_savings_log({
                    "events": self._events,
                    "total_saved_usd": self._total_saved,
                    "active_cordons": {n: dt.isoformat() for n, dt in self._active.items()},
                })
            except Exception as exc:
                logger.warning("Could not persist active cordons: %s", exc)

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
                self._events = self._events[-500:]  # keep last 500
                self._total_saved += saved
                logger.info("Savings event: %s uncordoned %.2fh → $%.2f saved", node, hours, saved)
                try:
                    self._k8s.write_savings_log({
                        "events": self._events,
                        "total_saved_usd": self._total_saved,
                        "active_cordons": {n: dt.isoformat() for n, dt in self._active.items()},
                    })
                except Exception as exc:
                    logger.warning("Could not persist savings: %s", exc)

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
