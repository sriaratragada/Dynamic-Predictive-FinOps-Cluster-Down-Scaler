import logging
from datetime import datetime, time, timedelta
from typing import Optional

import pytz

from .config import Config
from .metrics import PrometheusClient

logger = logging.getLogger(__name__)


class ActivityPredictor:
    def __init__(self, cfg: Config, prometheus: PrometheusClient):
        self._cfg = cfg
        self._prom = prometheus
        self._tz = pytz.timezone(cfg.timezone)

        if cfg.enable_prophet:
            from .prophet_predictor import ProphetPredictor
            self._prophet: Optional[object] = ProphetPredictor(prometheus, cfg)
            logger.info("Prophet predictor enabled (training on first tick)")
        else:
            self._prophet = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_low_activity(self, reference: Optional[datetime] = None) -> bool:
        """Return True when the cluster should be considered idle.

        When Prophet is enabled and trained, its forecast takes precedence.
        Falls back to the schedule + metric-override path if Prophet is
        unavailable or training fails.
        """
        now = self._localise(reference)

        if self._prophet is not None and self._prophet.ensure_trained(now):
            idle = self._prophet.is_predicted_idle(now)
            logger.debug("Prophet predicts cluster %s at %s", "IDLE" if idle else "ACTIVE", now)
            return idle

        in_window = self._in_active_schedule(now)
        if in_window and self._cfg.enable_metric_override:
            in_window = self._metrics_confirm_active()
        return not in_window

    def minutes_until_next_active_window(self, reference: Optional[datetime] = None) -> Optional[int]:
        """Return minutes until the next scheduled active window begins.

        Returns None if already in an active window.
        Uses Prophet's forecast when available; otherwise walks the schedule calendar.
        """
        if not self.is_low_activity(reference):
            return None

        now = self._localise(reference)

        if self._prophet is not None and self._prophet.ensure_trained(now):
            mins = self._prophet.minutes_until_predicted_active(now)
            if mins is not None:
                return mins
            # fall through if Prophet has no prediction available

        start = self._parse_hhmm(self._cfg.business_hours_start)

        # Build next candidate start datetime
        candidate = now.replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)

        for _ in range(7):
            if candidate.weekday() in self._cfg.business_days:
                delta = candidate - now
                return max(0, int(delta.total_seconds() / 60))
            candidate += timedelta(days=1)

        return None  # degenerate: no business days configured

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _localise(self, reference: Optional[datetime]) -> datetime:
        if reference is not None:
            if reference.tzinfo is None:
                return self._tz.localize(reference)
            return reference.astimezone(self._tz)
        return datetime.now(tz=self._tz)

    def _in_active_schedule(self, now: datetime) -> bool:
        if now.weekday() not in self._cfg.business_days:
            return False
        start = self._parse_hhmm(self._cfg.business_hours_start)
        end = self._parse_hhmm(self._cfg.business_hours_end)
        current = now.time().replace(second=0, microsecond=0)
        return start <= current < end

    def _metrics_confirm_active(self) -> bool:
        """Return False (treat as idle) when live usage is <10 % of the 7-day baseline."""
        try:
            baseline = self._prom.cluster_cpu_baseline()
            if not baseline:
                return True
            current = self._prom.scalar(
                'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))'
            )
            if current is None:
                return True
            ratio = current / baseline
            if ratio < 0.10:
                logger.info(
                    "Metric override: live CPU is %.1f%% of 7-day baseline — treating as idle",
                    ratio * 100,
                )
                return False
        except Exception as exc:
            logger.warning("Metric override check failed, defaulting to schedule: %s", exc)
        return True

    @staticmethod
    def _parse_hhmm(hhmm: str) -> time:
        h, m = hhmm.split(":")
        return time(int(h), int(m))
