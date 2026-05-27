import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .metrics import PrometheusClient

logger = logging.getLogger(__name__)

_CPU_QUERY = 'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))'


class ProphetPredictor:
    """Trains a Prophet time-series model on historical Prometheus CPU data
    and predicts cluster idle/active periods from the resulting forecast.

    Prophet is an optional dependency — if not installed, ensure_trained() returns
    False and the caller falls back to the schedule-based predictor.
    """

    def __init__(self, prom_client: "PrometheusClient", cfg: "Config"):
        self._prom = prom_client
        self._cfg = cfg
        self._model = None
        self._forecast_df = None      # pandas DataFrame with columns [ds, yhat]
        self._last_trained: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_trained(self, now: datetime) -> bool:
        """Return True if a trained model is ready (retraining if stale)."""
        if self._last_trained is not None and self._model is not None:
            hours_since = (now - self._last_trained).total_seconds() / 3600
            if hours_since < self._cfg.prophet_retrain_hours:
                return True
        return self._train(now)

    def is_predicted_idle(self, now: datetime) -> bool:
        """True if the forecast yhat at `now` is below the idle threshold."""
        row = self._nearest_forecast(now)
        if row is None:
            return False
        return float(row["yhat"]) < self._cfg.prophet_idle_threshold_cores

    def minutes_until_predicted_active(self, now: datetime) -> Optional[int]:
        """Minutes until the forecast first crosses above the idle threshold."""
        if self._forecast_df is None:
            return None
        now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
        future = self._forecast_df[self._forecast_df["ds"] >= now_naive]
        active = future[future["yhat"] >= self._cfg.prophet_idle_threshold_cores]
        if active.empty:
            return None
        delta = (active.iloc[0]["ds"] - now_naive).total_seconds() / 60
        return max(0, int(delta))

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train(self, now: datetime) -> bool:
        try:
            from prophet import Prophet
            import pandas as pd
        except ImportError:
            logger.warning(
                "prophet package not installed — falling back to schedule predictor. "
                "Install with: pip install -r requirements-prophet.txt"
            )
            return False

        try:
            end_ts = now.timestamp()
            start_ts = end_ts - self._cfg.prophet_training_weeks * 7 * 24 * 3600
            step = 300  # 5-minute resolution

            values = self._prom.query_range(_CPU_QUERY, start_ts, end_ts, step)
            if len(values) < 24:
                logger.warning(
                    "Prophet: only %d data points retrieved (need ≥ 24); skipping fit",
                    len(values),
                )
                return False

            df = pd.DataFrame(values, columns=["ds", "y"])
            df["ds"] = pd.to_datetime(df["ds"].astype(float), unit="s")
            df["y"] = df["y"].astype(float).clip(lower=0)
            df = df.dropna()

            m = Prophet(
                weekly_seasonality=True,
                daily_seasonality=True,
                changepoint_prior_scale=0.05,
                uncertainty_samples=0,  # faster — we only need yhat
            )
            m.fit(df)

            # Forecast 48 hours ahead at 5-minute resolution
            future = m.make_future_dataframe(
                periods=48 * 12,
                freq="5min",
                include_history=False,
            )
            forecast = m.predict(future)[["ds", "yhat"]]
            forecast["yhat"] = forecast["yhat"].clip(lower=0)

            self._model = m
            self._forecast_df = forecast
            self._last_trained = now
            logger.info(
                "Prophet model trained on %d data points covering %d weeks; "
                "forecast cached for %d hours",
                len(df),
                self._cfg.prophet_training_weeks,
                self._cfg.prophet_retrain_hours,
            )
            return True

        except Exception as exc:
            logger.warning("Prophet training failed — falling back to schedule: %s", exc)
            self._model = None
            self._forecast_df = None
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nearest_forecast(self, now: datetime):
        if self._forecast_df is None:
            return None
        now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
        idx = (self._forecast_df["ds"] - now_naive).abs().idxmin()
        return self._forecast_df.loc[idx]
