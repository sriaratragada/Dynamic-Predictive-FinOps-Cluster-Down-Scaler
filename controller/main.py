import logging
import os
import time
from datetime import datetime

from kubernetes import client, config as k8s_config
from kubernetes.config import ConfigException

from . import telemetry
from .auto_labeller import AutoLabeller
from .config import load_config
from .metrics import PrometheusClient
from .node_manager import NodeManager
from .predictor import ActivityPredictor
from .scaler import DeploymentScaler
from .state_store import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

_DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"


def _load_k8s():
    try:
        k8s_config.load_incluster_config()
        logger.info("Kubernetes: using in-cluster config")
    except ConfigException:
        k8s_config.load_kube_config()
        logger.info("Kubernetes: using local kubeconfig")


def run():
    cfg = load_config()

    if _DEMO_MODE:
        logger.warning(
            "*** DEMO MODE — synthetic data only, no Kubernetes cluster or Prometheus required ***"
        )
        from .demo_stub import (  # noqa: PLC0415
            DemoAppsV1Api, DemoAutoscalingV2Api, DemoCoreV1Api,
            DemoPrometheusClient, DemoStateStore,
        )
        core_api        = DemoCoreV1Api()
        apps_api        = DemoAppsV1Api()
        autoscaling_api = DemoAutoscalingV2Api()
        prometheus      = DemoPrometheusClient()
        state_store     = DemoStateStore()
    else:
        _load_k8s()
        core_api        = client.CoreV1Api()
        apps_api        = client.AppsV1Api()
        autoscaling_api = client.AutoscalingV2Api() if cfg.enable_hpa_suspend else None
        prometheus      = PrometheusClient(cfg.prometheus_url)
        state_store     = StateStore(
            cfg.state_configmap_name, cfg.state_configmap_ns, core_api, dry_run=cfg.dry_run
        )

    if cfg.dry_run:
        logger.warning("*** DRY-RUN MODE ENABLED — no Kubernetes resources will be modified ***")

    telemetry.start_metrics_server(cfg.metrics_port)

    predictor = ActivityPredictor(cfg, prometheus)
    scaler = DeploymentScaler(
        apps_api, cfg.namespace_filter, cfg.min_replica_floor,
        dry_run=cfg.dry_run,
        autoscaling_api=autoscaling_api if cfg.enable_hpa_suspend else None,
    )
    node_mgr = NodeManager(
        core_api, prometheus, state_store,
        dry_run=cfg.dry_run,
        enable_gpu_aware=cfg.enable_gpu_aware,
        gpu_idle_threshold=cfg.gpu_idle_threshold,
    )
    auto_labeller = AutoLabeller(core_api, apps_api, dry_run=cfg.dry_run) \
        if cfg.enable_auto_label else None

    already_scaled_down = bool(state_store.load_replicas())
    logger.info(
        "Controller started (loop=%ds, tz=%s, dry_run=%s, demo=%s, prophet=%s, "
        "gpu_aware=%s, hpa_suspend=%s, auto_label=%s, recovered=%s)",
        cfg.loop_interval_seconds,
        cfg.timezone,
        cfg.dry_run,
        _DEMO_MODE,
        cfg.enable_prophet,
        cfg.enable_gpu_aware,
        cfg.enable_hpa_suspend,
        cfg.enable_auto_label,
        already_scaled_down,
    )

    while True:
        try:
            _tick(cfg, predictor, scaler, node_mgr, state_store, auto_labeller)
        except Exception:
            telemetry.controller_errors.inc()
            logger.exception("Unhandled error in control loop — will retry next tick")
        time.sleep(cfg.loop_interval_seconds)


def _tick(cfg, predictor, scaler, node_mgr, state_store, auto_labeller=None):
    now = datetime.now()

    # Auto-label opt-in namespaces before evaluating eligibility
    if auto_labeller is not None:
        try:
            labelled = auto_labeller.label_eligible_namespaces()
            if labelled:
                logger.info("AutoLabeller: labelled %d deployment(s) this tick", labelled)
        except Exception:
            logger.exception("AutoLabeller error — continuing without it")

    low = predictor.is_low_activity(now)
    mins_to_active = predictor.minutes_until_next_active_window(now)

    in_prewarm = mins_to_active is not None and mins_to_active <= cfg.prewarm_minutes

    currently_scaled_down = bool(state_store.load_replicas())

    if low and not in_prewarm and not currently_scaled_down:
        _scale_down_cluster(cfg, scaler, node_mgr, state_store)

    elif (not low or in_prewarm) and currently_scaled_down:
        reason = f"pre-warm ({mins_to_active} min to active)" if in_prewarm else "active window"
        logger.info("Restoring cluster — reason: %s", reason)
        _scale_up_cluster(scaler, node_mgr, state_store)

    else:
        logger.debug(
            "No action (low=%s, prewarm=%s, scaled_down=%s, mins_to_active=%s)",
            low, in_prewarm, currently_scaled_down, mins_to_active,
        )


def _scale_down_cluster(cfg, scaler, node_mgr, state_store):
    logger.info("Entering low-activity window — scaling down eligible deployments")

    eligible = scaler.find_eligible()
    if not eligible:
        logger.info("No eligible deployments found (label finops.io/scaledown-eligible=true)")

    for dep in eligible:
        ns   = dep.metadata.namespace
        name = dep.metadata.name

        # Suspend HPA first so it doesn't counteract the scale-down
        hpa = scaler.find_hpa(dep)
        if hpa is not None:
            original_min = scaler.suspend_hpa(hpa)
            state_store.save_hpa_min_replicas(ns, name, original_min)

        original = scaler.scale_down(dep)
        state_store.save_replicas(ns, name, original)
        telemetry.deployments_scaled.labels(namespace=ns).inc()

    underutil = node_mgr.get_underutilised_nodes(cfg.node_utilisation_threshold)
    for node_name in underutil:
        node_mgr.cordon(node_name)
        node_mgr.drain(node_name)

    telemetry.scaledown_events.inc()
    telemetry.nodes_cordoned.set(len(underutil))
    telemetry.replicas_saved.set(sum(state_store.load_replicas().values()))

    logger.info(
        "Scale-down complete: %d deployment(s) scaled, %d node(s) cordoned/drained",
        len(eligible), len(underutil),
    )


def _scale_up_cluster(scaler, node_mgr, state_store):
    node_mgr.uncordon_all()

    saved     = state_store.load_replicas()
    saved_hpa = state_store.load_hpa_min_replicas()
    eligible  = scaler.find_eligible()

    for dep in eligible:
        ns   = dep.metadata.namespace
        name = dep.metadata.name
        key  = f"{ns}/{name}"

        target = saved.get(key, 1)
        scaler.scale_up(dep, target)
        state_store.clear_replicas(ns, name)

        # Restore HPA after deployments are back up
        if key in saved_hpa:
            hpa = scaler.find_hpa(dep)
            if hpa is not None:
                scaler.resume_hpa(hpa, saved_hpa[key])
            state_store.clear_hpa_min_replicas(ns, name)

    telemetry.scaleup_events.inc()
    telemetry.nodes_cordoned.set(0)
    telemetry.replicas_saved.set(0)

    logger.info("Scale-up complete: %d deployment(s) restored", len(eligible))


if __name__ == "__main__":
    run()
