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
import json
import logging
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import Any, Dict

_log = logging.getLogger(__name__)
_CONFIG_FILE = os.environ.get(
    "FINOPS_CONFIG_FILE",
    os.path.join(tempfile.gettempdir(), "finops-dashboard-config.json"),
)


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
    prophet_shadow_mode: bool = False

    # ── Dashboard UX ──────────────────────────────────────────────────
    poll_interval_seconds: int = 30
    node_utilisation_threshold: float = 0.10
    namespace_filter: str = ""
    min_replica_floor: int = 0

    # ── LLM / Natural Language ────────────────────────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # ── HPA Synergy ────────────────────────────────────────────────
    enable_hpa_synergy: bool = False
    hpa_spike_headroom_pct: int = 30
    hpa_spike_lookahead_minutes: int = 15

    # ── Pre-Warm Engine (optional) ────────────────────────────────────
    # Proactively boots Knative AI containers on early user-intent signals
    # (login, hover, input focus) so the pod is warm before the user submits.
    # Enable only on high-conversion AI feature pages where cold-start delay
    # is directly user-facing.  Off by default.
    enable_prewarm: bool = False
    prewarm_service_url: str = ""

    # ── Manual Override ────────────────────────────────────────────
    override_mode: str = ""  # "" = no override, "awake" = keep awake, "sleep" = force sleep
    override_until: str = ""  # ISO-8601 datetime when override expires, empty = indefinite

    # ── App Safelist ───────────────────────────────────────────────
    exclude_deployments: str = ""  # comma-separated "ns/name" patterns to never scale down

    # ── Dry Run ────────────────────────────────────────────────────
    dry_run: bool = False  # log what would happen without actually scaling

    # ── Notifications ──────────────────────────────────────────────
    webhook_url: str = ""  # Slack-compatible webhook URL for scale event notifications

    # ── Spot Instance Migration ───────────────────────────────────
    enable_spot_migration: bool = False
    spot_max_price_pct: int = 80
    spot_eligible_label: str = "finops.io/priority=low"


def _load_persisted() -> dict:
    """Load previously persisted config patches from disk."""
    try:
        with open(_CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _persist(cfg_obj: "DashboardConfig") -> None:
    """Write config to disk so it survives restarts.  Never persists secrets."""
    try:
        d = asdict(cfg_obj)
        d.pop("openai_api_key", None)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception as exc:
        _log.warning("Config persist failed: %s", exc)


# Build config: env vars first, then overlay any persisted patches.
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
    prophet_shadow_mode          = _env_bool("PROPHET_SHADOW_MODE",    False),
    node_utilisation_threshold   = _env_float("NODE_UTILISATION_THRESHOLD", 0.10),
    namespace_filter             = _env_str("NAMESPACE_FILTER",        ""),
    min_replica_floor            = _env_int("MIN_REPLICA_FLOOR",       0),
    openai_api_key               = _env_str("OPENAI_API_KEY",           ""),
    openai_base_url              = _env_str("OPENAI_BASE_URL",          "https://api.openai.com/v1"),
    enable_hpa_synergy           = _env_bool("ENABLE_HPA_SYNERGY",      False),
    hpa_spike_headroom_pct       = _env_int("HPA_SPIKE_HEADROOM_PCT",   30),
    hpa_spike_lookahead_minutes  = _env_int("HPA_SPIKE_LOOKAHEAD_MINUTES", 15),
    enable_prewarm               = _env_bool("ENABLE_PREWARM",         False),
    prewarm_service_url          = _env_str("PREWARM_SERVICE_URL",     ""),
    override_mode                = _env_str("OVERRIDE_MODE",             ""),
    override_until               = _env_str("OVERRIDE_UNTIL",            ""),
    exclude_deployments          = _env_str("EXCLUDE_DEPLOYMENTS",       ""),
    dry_run                      = _env_bool("DRY_RUN",                  False),
    webhook_url                  = _env_str("WEBHOOK_URL",               ""),
    enable_spot_migration        = _env_bool("ENABLE_SPOT_MIGRATION",  False),
    spot_max_price_pct           = _env_int("SPOT_MAX_PRICE_PCT",      80),
    spot_eligible_label          = _env_str("SPOT_ELIGIBLE_LABEL",     "finops.io/priority=low"),
)

# Overlay any previously persisted patches (env vars take precedence on first boot,
# but runtime PATCH changes survive restarts via this file).
_persisted = _load_persisted()
if _persisted:
    _log.info("Restoring %d persisted config field(s) from %s", len(_persisted), _CONFIG_FILE)
    for k, v in _persisted.items():
        if hasattr(_cfg, k) and k != "openai_api_key":
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

    _persist(_cfg)
    return _cfg


def as_dict() -> dict:
    d = asdict(_cfg)
    d["openai_api_key_set"] = bool(d.pop("openai_api_key", ""))
    return d
