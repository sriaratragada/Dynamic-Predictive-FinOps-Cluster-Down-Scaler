"""
Controller startup configuration.

Reads environment variables once at import time and freezes them into a
``Config`` dataclass.  All values have safe production-ready defaults so a
fresh ``python -m controller.main`` boots in demo-friendly mode without any
explicit env configuration.

Defaults are documented inline next to each field; the canonical operator-
facing reference is ``.env.example``.
"""
import os
from dataclasses import dataclass
from typing import List


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


def _env_days(name: str, default: str) -> List[int]:
    raw = os.environ.get(name, default)
    return [int(d.strip()) for d in raw.split(",") if d.strip()]


@dataclass
class Config:
    prometheus_url: str
    business_hours_start: str   # "HH:MM"
    business_hours_end: str     # "HH:MM"
    business_days: List[int]    # 0=Mon … 6=Sun
    prewarm_minutes: int
    loop_interval_seconds: int
    namespace_filter: str
    min_replica_floor: int
    node_utilisation_threshold: float
    state_configmap_name: str
    state_configmap_ns: str
    timezone: str
    enable_metric_override: bool
    dry_run: bool
    metrics_port: int
    # Prophet ML predictor (optional — requires: pip install -r requirements-prophet.txt)
    enable_prophet: bool
    prophet_training_weeks: int
    prophet_idle_threshold_cores: float
    prophet_retrain_hours: int
    # GPU-aware cordoning (optional — requires DCGM exporter in the cluster)
    # When enabled, nodes with nvidia.com/gpu allocatable use GPU utilisation
    # (via DCGM_FI_DEV_GPU_UTIL) instead of CPU as the cordon signal.
    enable_gpu_aware: bool
    gpu_idle_threshold: float   # fraction 0.0–1.0; below this → cordon
    # HPA suspend/resume — set minReplicas=0 on scale-down so HPAs don't fight
    # the controller; restores the original minReplicas value on scale-up.
    enable_hpa_suspend: bool
    # Auto-labeller — automatically labels deployments in namespaces annotated
    # with finops.io/scaledown-namespace=true as finops.io/scaledown-eligible=true.
    enable_auto_label: bool
    # Kubernetes Events — emit native K8s Events (kubectl get events) for every
    # scale-down / scale-up / cordon / uncordon transition.
    enable_k8s_events: bool
    # Webhook — POST a Slack-compatible JSON payload to this URL on every
    # scale-down and scale-up event.  Leave empty to disable.
    webhook_url: str
    # Human-readable cluster identifier included in webhook payloads.
    cluster_name: str
    # Leader election — only one controller replica executes the control loop;
    # others wait for the Lease to expire before competing.
    enable_leader_election: bool
    leader_lease_duration: int   # seconds; renew every ~1/3 of this value
    # Pre-flight — run startup validation checks before entering the control loop.
    enable_preflight: bool
    # State-loss acknowledgement — if the state ConfigMap is deleted manually
    # (or otherwise reset) while eligible Deployments are at 0 replicas, the
    # controller refuses to take any further scale action until an operator
    # acknowledges the lost state by setting this to true.  Prevents
    # workloads from being stranded at zero replicas indefinitely.
    acknowledge_state_loss: bool


def load_config() -> Config:
    return Config(
        prometheus_url             = _env_str("PROMETHEUS_URL",        "http://prometheus:9090"),
        business_hours_start       = _env_str("BUSINESS_HOURS_START",  "07:00"),
        business_hours_end         = _env_str("BUSINESS_HOURS_END",    "19:00"),
        business_days              = _env_days("BUSINESS_DAYS",        "0,1,2,3,4"),
        prewarm_minutes            = _env_int("PREWARM_MINUTES",        15),
        loop_interval_seconds      = _env_int("LOOP_INTERVAL_SECONDS",  60),
        namespace_filter           = _env_str("NAMESPACE_FILTER",       ""),
        min_replica_floor          = _env_int("MIN_REPLICA_FLOOR",      0),
        node_utilisation_threshold = _env_float("NODE_UTILISATION_THRESHOLD", 0.10),
        state_configmap_name       = _env_str("STATE_CONFIGMAP_NAME",  "finops-scaler-state"),
        state_configmap_ns         = _env_str("STATE_CONFIGMAP_NS",    "kube-system"),
        timezone                   = _env_str("TIMEZONE",               "UTC"),
        enable_metric_override     = _env_bool("ENABLE_METRIC_OVERRIDE", False),
        dry_run                    = _env_bool("DRY_RUN",                False),
        metrics_port               = _env_int("METRICS_PORT",            8080),
        enable_prophet             = _env_bool("ENABLE_PROPHET",         False),
        prophet_training_weeks     = _env_int("PROPHET_TRAINING_WEEKS",  4),
        prophet_idle_threshold_cores = _env_float("PROPHET_IDLE_THRESHOLD_CORES", 0.5),
        prophet_retrain_hours      = _env_int("PROPHET_RETRAIN_HOURS",   6),
        enable_gpu_aware           = _env_bool("ENABLE_GPU_AWARE",       False),
        gpu_idle_threshold         = _env_float("GPU_IDLE_THRESHOLD",    0.10),
        enable_hpa_suspend         = _env_bool("ENABLE_HPA_SUSPEND",     True),
        enable_auto_label          = _env_bool("ENABLE_AUTO_LABEL",      False),
        enable_k8s_events          = _env_bool("ENABLE_K8S_EVENTS",      True),
        webhook_url                = _env_str("WEBHOOK_URL",             ""),
        cluster_name               = _env_str("CLUSTER_NAME",            ""),
        enable_leader_election     = _env_bool("ENABLE_LEADER_ELECTION", True),
        leader_lease_duration      = _env_int("LEADER_LEASE_DURATION",   30),
        enable_preflight           = _env_bool("ENABLE_PREFLIGHT",       True),
        acknowledge_state_loss     = _env_bool("ACKNOWLEDGE_STATE_LOSS", False),
    )
