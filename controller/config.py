import os
from dataclasses import dataclass
from typing import List


def _parse_days(val: str) -> List[int]:
    return [int(d.strip()) for d in val.split(",") if d.strip()]


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


def load_config() -> Config:
    return Config(
        prometheus_url=os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
        business_hours_start=os.environ.get("BUSINESS_HOURS_START", "07:00"),
        business_hours_end=os.environ.get("BUSINESS_HOURS_END", "19:00"),
        business_days=_parse_days(os.environ.get("BUSINESS_DAYS", "0,1,2,3,4")),
        prewarm_minutes=int(os.environ.get("PREWARM_MINUTES", "15")),
        loop_interval_seconds=int(os.environ.get("LOOP_INTERVAL_SECONDS", "60")),
        namespace_filter=os.environ.get("NAMESPACE_FILTER", ""),
        min_replica_floor=int(os.environ.get("MIN_REPLICA_FLOOR", "0")),
        node_utilisation_threshold=float(os.environ.get("NODE_UTILISATION_THRESHOLD", "0.10")),
        state_configmap_name=os.environ.get("STATE_CONFIGMAP_NAME", "finops-scaler-state"),
        state_configmap_ns=os.environ.get("STATE_CONFIGMAP_NS", "kube-system"),
        timezone=os.environ.get("TIMEZONE", "UTC"),
        enable_metric_override=os.environ.get("ENABLE_METRIC_OVERRIDE", "false").lower() == "true",
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
        metrics_port=int(os.environ.get("METRICS_PORT", "8080")),
        enable_prophet=os.environ.get("ENABLE_PROPHET", "false").lower() == "true",
        prophet_training_weeks=int(os.environ.get("PROPHET_TRAINING_WEEKS", "4")),
        prophet_idle_threshold_cores=float(os.environ.get("PROPHET_IDLE_THRESHOLD_CORES", "0.5")),
        prophet_retrain_hours=int(os.environ.get("PROPHET_RETRAIN_HOURS", "6")),
        enable_gpu_aware=os.environ.get("ENABLE_GPU_AWARE", "false").lower() == "true",
        gpu_idle_threshold=float(os.environ.get("GPU_IDLE_THRESHOLD", "0.10")),
        enable_hpa_suspend=os.environ.get("ENABLE_HPA_SUSPEND", "true").lower() == "true",
        enable_auto_label=os.environ.get("ENABLE_AUTO_LABEL", "false").lower() == "true",
        enable_k8s_events=os.environ.get("ENABLE_K8S_EVENTS", "true").lower() == "true",
        webhook_url=os.environ.get("WEBHOOK_URL", ""),
        cluster_name=os.environ.get("CLUSTER_NAME", ""),
        enable_leader_election=os.environ.get("ENABLE_LEADER_ELECTION", "true").lower() == "true",
        leader_lease_duration=int(os.environ.get("LEADER_LEASE_DURATION", "30")),
        enable_preflight=os.environ.get("ENABLE_PREFLIGHT", "true").lower() == "true",
    )
