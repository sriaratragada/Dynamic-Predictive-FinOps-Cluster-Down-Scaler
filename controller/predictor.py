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
        self._shadow_log: list = []

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

        When Prophet is enabled and trained, its forecast takes precedence
        (unless shadow mode is active — in which case Prophet's recommendation
        is logged but the schedule-based answer is returned instead).

        Falls back to the schedule + metric-override path if Prophet is
        unavailable or training fails.
        """
        now = self._localise(reference)

        if self._prophet is not None and self._prophet.ensure_trained(now):
            prophet_idle = self._prophet.is_predicted_idle(now)

            if self._cfg.prophet_shadow_mode:
                schedule_idle = not self._in_active_schedule(now)
                yhat = getattr(self._prophet, 'last_yhat', 0.0)
                entry = {
                    "timestamp": now.isoformat(),
                    "prophet_says_idle": prophet_idle,
                    "schedule_says_idle": schedule_idle,
                    "agreement": prophet_idle == schedule_idle,
                    "predicted_yhat": round(float(yhat), 4),
                }
                self._shadow_log.append(entry)
                if len(self._shadow_log) > 200:
                    self._shadow_log = self._shadow_log[-200:]
                logger.debug(
                    "Shadow mode: prophet=%s schedule=%s agreement=%s yhat=%.3f",
                    "IDLE" if prophet_idle else "ACTIVE",
                    "IDLE" if schedule_idle else "ACTIVE",
                    entry["agreement"],
                    float(yhat),
                )
                return schedule_idle

            logger.debug("Prophet predicts cluster %s at %s", "IDLE" if prophet_idle else "ACTIVE", now)
            return prophet_idle

        in_window = self._in_active_schedule(now)
        if in_window and self._cfg.enable_metric_override:
            in_window = self._metrics_confirm_active()
        return not in_window

    def get_shadow_log(self) -> list:
        """Return the Prophet shadow mode log (max 200 entries)."""
        return list(self._shadow_log)

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

    def predict_traffic_spike(self, horizon_minutes: int = 15) -> Optional[dict]:
        """Predict if a traffic spike is coming within the horizon.

        Returns a dict with spike info if predicted, None otherwise.
        Only works when Prophet is enabled and trained.
        """
        if self._prophet is None:
            return None
        now = self._localise(None)
        if not self._prophet.ensure_trained(now):
            return None

        if self._prophet._forecast_df is None:
            return None

        import pandas as pd  # noqa: E402

        now_naive = now.replace(tzinfo=None)
        horizon_end = now_naive + pd.Timedelta(minutes=horizon_minutes)
        window = self._prophet._forecast_df[
            (self._prophet._forecast_df["ds"] >= now_naive)
            & (self._prophet._forecast_df["ds"] <= horizon_end)
        ]
        if window.empty:
            return None

        peak_yhat = float(window["yhat"].max())
        current_yhat_row = self._prophet._nearest_forecast(now)
        current_yhat = float(current_yhat_row["yhat"]) if current_yhat_row is not None else 0

        if peak_yhat > current_yhat * 1.5 and peak_yhat > self._cfg.prophet_idle_threshold_cores * 2:
            peak_time = window.loc[window["yhat"].idxmax(), "ds"]
            return {
                "expected_at": peak_time.isoformat(),
                "current_cpu": round(current_yhat, 3),
                "predicted_peak_cpu": round(peak_yhat, 3),
                "minutes_away": int((peak_time - now_naive).total_seconds() / 60),
            }
        return None

    @staticmethod
    def _parse_hhmm(hhmm: str) -> time:
        h, m = hhmm.split(":")
        return time(int(h), int(m))
