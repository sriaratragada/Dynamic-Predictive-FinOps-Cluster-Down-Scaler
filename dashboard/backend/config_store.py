"""
Mutable runtime configuration for the dashboard backend.

Initialises from environment variables; individual fields can be hot-patched
at runtime via PATCH /api/config without restarting the process.
Pricing-related changes automatically invalidate the pricing cache.
"""
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict


def _bool(val: str) -> bool:
    return val.strip().lower() == "true"


@dataclass
class DashboardConfig:
    # ── Connection ────────────────────────────────────────────────────
    prometheus_url: str = "http://prometheus:9090"
    demo_mode: bool = False

    # ── Cloud & Pricing ───────────────────────────────────────────────
    cloud_provider: str = "manual"   # aws | gcp | manual
    instance_type: str = ""
    aws_region: str = ""
    node_hourly_cost: float = 0.192

    # ── Schedule (controller settings — displayed for reference) ──────
    business_hours_start: str = "07:00"
    business_hours_end: str = "19:00"
    business_days: str = "0,1,2,3,4"   # comma-separated 0=Mon…6=Sun
    timezone: str = "UTC"
    prewarm_minutes: int = 15

    # ── Prediction ────────────────────────────────────────────────────
    enable_metric_override: bool = False
    enable_prophet: bool = False
    prophet_training_weeks: int = 4
    prophet_idle_threshold_cores: float = 0.5
    prophet_retrain_hours: int = 6

    # ── Dashboard UX ──────────────────────────────────────────────────
    poll_interval_seconds: int = 30
    node_utilisation_threshold: float = 0.10
    namespace_filter: str = ""
    min_replica_floor: int = 0

    # ── Pre-Warm Engine (optional) ────────────────────────────────────
    # Proactively boots Knative AI containers on early user-intent signals
    # (login, hover, input focus) so the pod is warm before the user submits.
    # Enable only on high-conversion AI feature pages where cold-start delay
    # is directly user-facing.  Off by default.
    enable_prewarm: bool = False


_cfg = DashboardConfig(
    prometheus_url=os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
    demo_mode=_bool(os.environ.get("DEMO_MODE", "false")),
    cloud_provider=os.environ.get("CLOUD_PROVIDER", "manual"),
    instance_type=os.environ.get("NODE_INSTANCE_TYPE", ""),
    aws_region=os.environ.get("AWS_REGION", ""),
    node_hourly_cost=float(os.environ.get("NODE_HOURLY_COST", "0.192")),
    business_hours_start=os.environ.get("BUSINESS_HOURS_START", "07:00"),
    business_hours_end=os.environ.get("BUSINESS_HOURS_END", "19:00"),
    business_days=os.environ.get("BUSINESS_DAYS", "0,1,2,3,4"),
    timezone=os.environ.get("TIMEZONE", "UTC"),
    prewarm_minutes=int(os.environ.get("PREWARM_MINUTES", "15")),
    enable_metric_override=_bool(os.environ.get("ENABLE_METRIC_OVERRIDE", "false")),
    enable_prophet=_bool(os.environ.get("ENABLE_PROPHET", "false")),
    prophet_training_weeks=int(os.environ.get("PROPHET_TRAINING_WEEKS", "4")),
    prophet_idle_threshold_cores=float(os.environ.get("PROPHET_IDLE_THRESHOLD_CORES", "0.5")),
    prophet_retrain_hours=int(os.environ.get("PROPHET_RETRAIN_HOURS", "6")),
    node_utilisation_threshold=float(os.environ.get("NODE_UTILISATION_THRESHOLD", "0.10")),
    namespace_filter=os.environ.get("NAMESPACE_FILTER", ""),
    min_replica_floor=int(os.environ.get("MIN_REPLICA_FLOOR", "0")),
    enable_prewarm=_bool(os.environ.get("ENABLE_PREWARM", "false")),
)

_PRICING_KEYS = {"cloud_provider", "instance_type", "aws_region", "node_hourly_cost"}


def get() -> DashboardConfig:
    return _cfg


def patch(updates: Dict[str, Any]) -> DashboardConfig:
    """Apply a partial update dict to the live config. Unknown keys are ignored."""
    global _cfg
    changed_pricing = False
    for k, v in updates.items():
        if not hasattr(_cfg, k):
            continue
        # Coerce to the field's existing type
        current = getattr(_cfg, k)
        if isinstance(current, bool):
            v = bool(v)
        elif isinstance(current, int):
            v = int(v)
        elif isinstance(current, float):
            v = float(v)
        else:
            v = str(v)
        setattr(_cfg, k, v)
        if k in _PRICING_KEYS:
            changed_pricing = True

    if changed_pricing:
        try:
            from . import pricing
            pricing._cached_rate = None   # force re-fetch on next /api/savings
        except Exception:
            pass

    return _cfg


def as_dict() -> dict:
    return asdict(_cfg)
