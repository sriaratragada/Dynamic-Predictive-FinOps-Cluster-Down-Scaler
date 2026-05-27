"""
Mutable runtime configuration for the dashboard backend.

Initialises from environment variables; individual fields can be hot-patched
at runtime via PATCH /api/config without restarting the process.
Pricing-related changes automatically invalidate the pricing cache.

Note
----
A subset of these settings (schedule, prophet, namespace filter, etc.)
mirrors ``controller/config.py`` by design — the dashboard backend is
intentionally self-contained and does not import the controller package
so each Docker image can ship without the other.  Keep defaults in
sync with ``.env.example``.
"""
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict


# ── Env-var coercion helpers ──────────────────────────────────────────────────

def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw is not None else default


# Defaults — keep in sync with .env.example and controller/config.py.
DEFAULT_NODE_HOURLY_COST = 0.192
DEFAULT_BUSINESS_DAYS    = "0,1,2,3,4"


@dataclass
class DashboardConfig:
    # ── Connection ────────────────────────────────────────────────────
    prometheus_url: str = "http://prometheus:9090"
    demo_mode: bool = False

    # ── Cloud & Pricing ───────────────────────────────────────────────
    cloud_provider: str = "manual"   # aws | gcp | manual
    instance_type: str = ""
    aws_region: str = ""
    node_hourly_cost: float = DEFAULT_NODE_HOURLY_COST

    # ── Schedule (controller settings — displayed for reference) ──────
    business_hours_start: str = "07:00"
    business_hours_end: str = "19:00"
    business_days: str = DEFAULT_BUSINESS_DAYS   # comma-separated 0=Mon…6=Sun
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
    prometheus_url               = _env_str("PROMETHEUS_URL",        "http://prometheus:9090"),
    demo_mode                    = _env_bool("DEMO_MODE",             False),
    cloud_provider               = _env_str("CLOUD_PROVIDER",         "manual"),
    instance_type                = _env_str("NODE_INSTANCE_TYPE",     ""),
    aws_region                   = _env_str("AWS_REGION",             ""),
    node_hourly_cost             = _env_float("NODE_HOURLY_COST",     DEFAULT_NODE_HOURLY_COST),
    business_hours_start         = _env_str("BUSINESS_HOURS_START",  "07:00"),
    business_hours_end           = _env_str("BUSINESS_HOURS_END",    "19:00"),
    business_days                = _env_str("BUSINESS_DAYS",          DEFAULT_BUSINESS_DAYS),
    timezone                     = _env_str("TIMEZONE",               "UTC"),
    prewarm_minutes              = _env_int("PREWARM_MINUTES",        15),
    enable_metric_override       = _env_bool("ENABLE_METRIC_OVERRIDE", False),
    enable_prophet               = _env_bool("ENABLE_PROPHET",         False),
    prophet_training_weeks       = _env_int("PROPHET_TRAINING_WEEKS",  4),
    prophet_idle_threshold_cores = _env_float("PROPHET_IDLE_THRESHOLD_CORES", 0.5),
    prophet_retrain_hours        = _env_int("PROPHET_RETRAIN_HOURS",   6),
    node_utilisation_threshold   = _env_float("NODE_UTILISATION_THRESHOLD", 0.10),
    namespace_filter             = _env_str("NAMESPACE_FILTER",        ""),
    min_replica_floor            = _env_int("MIN_REPLICA_FLOOR",       0),
    enable_prewarm               = _env_bool("ENABLE_PREWARM",         False),
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
