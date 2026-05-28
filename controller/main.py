import logging
import os
import time
from datetime import datetime

from kubernetes import client, config as k8s_config
from kubernetes.config import ConfigException

from . import telemetry
from .auto_labeller import AutoLabeller
from .config import load_config
from .k8s_events import K8sEventEmitter
from .metrics import PrometheusClient
from .node_manager import NodeManager
from .predictor import ActivityPredictor
from .scaler import DeploymentScaler
from .state_store import StateStore
from .webhook import WebhookNotifier

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
            DemoAppsV1Api, DemoAutoscalingV2Api, DemoCoordinationV1Api,
            DemoCoreV1Api, DemoPrometheusClient, DemoStateStore,
        )
        core_api          = DemoCoreV1Api()
        apps_api          = DemoAppsV1Api()
        autoscaling_api   = DemoAutoscalingV2Api()
        coordination_api  = DemoCoordinationV1Api()
        prometheus        = DemoPrometheusClient()
        state_store       = DemoStateStore()
    else:
        _load_k8s()
        core_api         = client.CoreV1Api()
        apps_api         = client.AppsV1Api()
        autoscaling_api  = client.AutoscalingV2Api() if cfg.enable_hpa_suspend else None
        coordination_api = client.CoordinationV1Api() if cfg.enable_leader_election else None
        prometheus       = PrometheusClient(cfg.prometheus_url)
        state_store      = StateStore(
            cfg.state_configmap_name, cfg.state_configmap_ns, core_api, dry_run=cfg.dry_run
        )

    if cfg.dry_run:
        logger.warning("*** DRY-RUN MODE ENABLED — no Kubernetes resources will be modified ***")

    # ── Pre-flight checks ────────────────────────────────────────────────────
    if cfg.enable_preflight and not _DEMO_MODE:
        from .preflight import PreflightChecker, log_preflight_results  # noqa: PLC0415
        checker = PreflightChecker()
        results = checker.run(cfg, core_api, apps_api, prometheus, autoscaling_api)
        failed = log_preflight_results(results)
        if failed:
            logger.error(
                "Pre-flight: %d check(s) failed — review the output above and "
                "fix before running in production",
                failed,
            )

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

    # Optional: CRD-based DownscalePolicy watcher
    crd_watcher = None
    if not _DEMO_MODE:
        try:
            from .crd_watcher import CRDWatcher  # noqa: PLC0415
            custom_api = client.CustomObjectsApi()
            crd_watcher = CRDWatcher(custom_api)
            crd_watcher.start()
        except Exception:
            logger.info("CRD watcher not started (DownscalePolicy CRD may not be installed)")

    # Optional: Spot Instance Migrator
    spot_migrator = None
    if cfg.enable_spot_migration and not _DEMO_MODE:
        try:
            from .spot_migrator import SpotMigrator  # noqa: PLC0415
            spot_migrator = SpotMigrator(
                core_api, apps_api,
                eligible_label=cfg.spot_eligible_label,
                max_price_pct=cfg.spot_max_price_pct,
                dry_run=cfg.dry_run,
            )
            logger.info("Spot migrator initialised (label=%s, max_pct=%d)",
                        cfg.spot_eligible_label, cfg.spot_max_price_pct)
        except Exception:
            logger.info("Spot migrator not started")

    # Optional: native K8s Events
    event_emitter = (
        K8sEventEmitter(core_api, namespace=cfg.state_configmap_ns)
        if cfg.enable_k8s_events else None
    )

    # Optional: webhook notifications
    notifier = (
        WebhookNotifier(cfg.webhook_url, cluster_name=cfg.cluster_name)
        if cfg.webhook_url else None
    )

    # Optional: leader election (HA mode)
    elector = None
    if cfg.enable_leader_election and coordination_api is not None:
        from .leader_election import LeaderElector  # noqa: PLC0415
        elector = LeaderElector(
            coordination_api,
            namespace=cfg.state_configmap_ns,
            lease_duration_s=cfg.leader_lease_duration,
            renew_every_s=max(5, cfg.leader_lease_duration // 3),
        )
        elector.acquire_blocking()

    already_scaled_down = bool(state_store.load_replicas())
    logger.info(
        "Controller started (loop=%ds, tz=%s, dry_run=%s, demo=%s, prophet=%s, "
        "gpu_aware=%s, hpa_suspend=%s, auto_label=%s, k8s_events=%s, "
        "webhook=%s, leader_election=%s, recovered=%s)",
        cfg.loop_interval_seconds,
        cfg.timezone,
        cfg.dry_run,
        _DEMO_MODE,
        cfg.enable_prophet,
        cfg.enable_gpu_aware,
        cfg.enable_hpa_suspend,
        cfg.enable_auto_label,
        cfg.enable_k8s_events,
        bool(cfg.webhook_url),
        cfg.enable_leader_election,
        already_scaled_down,
    )

    while True:
        try:
            _tick(
                cfg, predictor, scaler, node_mgr, state_store,
                auto_labeller=auto_labeller,
                event_emitter=event_emitter,
                notifier=notifier,
                elector=elector,
                crd_watcher=crd_watcher,
                spot_migrator=spot_migrator,
            )
        except Exception:
            telemetry.controller_errors.inc()
            logger.exception("Unhandled error in control loop — will retry next tick")
        time.sleep(cfg.loop_interval_seconds)


def _detect_stranded_workloads(scaler, state_store):
    """
    Find Deployments labelled ``finops.io/scaledown-eligible=true`` that are
    currently at 0 replicas but have NO entry in the state store.

    This indicates the state ConfigMap was deleted, manually edited, or
    otherwise lost while the cluster was in a scaled-down state — without
    intervention the controller would never restore them because
    ``currently_scaled_down`` would evaluate False.

    Returns a list of ``"<namespace>/<name>"`` strings (empty when healthy).
    """
    try:
        eligible = scaler.find_eligible()
    except Exception:
        logger.exception("Stranded-workload check: could not list deployments")
        return []

    saved = state_store.load_replicas()
    stranded = []
    for dep in eligible:
        replicas = dep.spec.replicas if dep.spec.replicas is not None else 0
        if replicas != 0:
            continue
        key = f"{dep.metadata.namespace}/{dep.metadata.name}"
        if key not in saved:
            stranded.append(key)
    return stranded


def _tick(
    cfg,
    predictor,
    scaler,
    node_mgr,
    state_store,
    auto_labeller=None,
    event_emitter=None,
    notifier=None,
    elector=None,
    crd_watcher=None,
    spot_migrator=None,
):
    # Renew leader lease before doing any work; step down if we lost it
    if elector is not None and not elector.renew():
        logger.warning("Lost leader lease — skipping tick and re-acquiring")
        elector.acquire_blocking()
        return

    # Detect a lost state ConfigMap.  If eligible Deployments are at 0
    # replicas with no record in state, refuse to take further scale action
    # until an operator acknowledges (or the workloads are manually restored).
    stranded = _detect_stranded_workloads(scaler, state_store)
    if stranded:
        if cfg.acknowledge_state_loss:
            # Repopulate state with a default replica count (1) for each
            # stranded workload.  This re-enters the normal control flow:
            # the next active-window tick will see `currently_scaled_down=True`
            # and call `_scale_up_cluster`, which restores each Deployment to
            # the saved value before clearing state.
            logger.warning(
                "State-loss acknowledged: re-seeding state for %d stranded "
                "deployment(s) with default replicas=1 — they will be restored "
                "at the next active window: %s",
                len(stranded), ", ".join(stranded[:10]),
            )
            for key in stranded:
                ns, name = key.split("/", 1)
                state_store.save_replicas(ns, name, 1)
        else:
            logger.error(
                "STATE LOST: %d eligible deployment(s) are at 0 replicas with no "
                "state record — the state ConfigMap may have been deleted or "
                "edited manually.  Refusing to scale further to avoid stranding "
                "workloads.  Resolve by either (a) manually scaling them back up "
                "with `kubectl scale`, or (b) setting ACKNOWLEDGE_STATE_LOSS=true "
                "to let the controller restore them at the next active window. "
                "Affected: %s",
                len(stranded), ", ".join(stranded[:10]),
            )
            telemetry.controller_errors.inc()
            return

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
        _scale_down_cluster(cfg, scaler, node_mgr, state_store,
                            event_emitter=event_emitter, notifier=notifier)

    elif (not low or in_prewarm) and currently_scaled_down:
        reason = f"pre-warm ({mins_to_active} min to active)" if in_prewarm else "active window"
        logger.info("Restoring cluster — reason: %s", reason)
        _scale_up_cluster(scaler, node_mgr, state_store,
                          event_emitter=event_emitter, notifier=notifier)

    else:
        logger.debug(
            "No action (low=%s, prewarm=%s, scaled_down=%s, mins_to_active=%s)",
            low, in_prewarm, currently_scaled_down, mins_to_active,
        )

    # ── HPA synergy — predictive spike preparation ─────────────────
    if cfg.enable_hpa_synergy and not low and scaler._hpa_api is not None:
        spike = predictor.predict_traffic_spike(cfg.hpa_spike_lookahead_minutes)
        if spike:
            logger.info(
                "HPA synergy: traffic spike predicted in %d min (%.2f -> %.2f cores)",
                spike["minutes_away"], spike["current_cpu"], spike["predicted_peak_cpu"],
            )
            eligible = scaler.find_eligible()
            for dep in eligible:
                hpa = scaler.find_hpa(dep)
                if hpa is not None:
                    predicted_replicas = max(1, int(spike["predicted_peak_cpu"] / 0.5))
                    original_max = scaler.prepare_hpa_for_spike(
                        hpa, predicted_replicas, cfg.hpa_spike_headroom_pct
                    )
                    ns = dep.metadata.namespace
                    name = dep.metadata.name
                    state_store.save_hpa_min_replicas(ns, f"_max_{name}", original_max)

    # ── Spot migration evaluation ──────────────────────────────────
    if hasattr(cfg, 'enable_spot_migration') and cfg.enable_spot_migration and spot_migrator is not None:
        try:
            candidates = spot_migrator.discover_spot_candidates()
            if candidates:
                logger.info("Spot migrator: found %d eligible workloads", len(candidates))
        except Exception:
            logger.debug("Spot migration evaluation failed", exc_info=True)


def _scale_down_cluster(cfg, scaler, node_mgr, state_store,
                         event_emitter=None, notifier=None):
    logger.info("Entering low-activity window — scaling down eligible deployments")

    eligible = scaler.find_eligible()
    if not eligible:
        logger.info("No eligible deployments found (label finops.io/scaledown-eligible=true)")

    scaled_dep_names = []
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
        scaled_dep_names.append(f"{ns}/{name}")

        if event_emitter is not None:
            try:
                event_emitter.deployment_scaled_down(ns, name, original)
            except Exception:
                logger.debug("K8s Event emit failed", exc_info=True)

    underutil = node_mgr.get_underutilised_nodes(cfg.node_utilisation_threshold)
    for node_name in underutil:
        node_mgr.cordon(node_name)
        node_mgr.drain(node_name)
        if event_emitter is not None:
            try:
                event_emitter.node_cordoned(node_name)
            except Exception:
                logger.debug("K8s Event emit failed", exc_info=True)

    telemetry.scaledown_events.inc()
    telemetry.nodes_cordoned.set(len(underutil))
    telemetry.replicas_saved.set(sum(state_store.load_replicas().values()))

    if notifier is not None:
        try:
            notifier.notify_scale_down(scaled_dep_names, underutil, savings_rate_usd_hr=0.0)
        except Exception:
            logger.debug("Webhook notify_scale_down failed", exc_info=True)

    logger.info(
        "Scale-down complete: %d deployment(s) scaled, %d node(s) cordoned/drained",
        len(eligible), len(underutil),
    )


def _scale_up_cluster(scaler, node_mgr, state_store,
                       event_emitter=None, notifier=None):
    cordoned_nodes = state_store.load_cordoned_nodes()
    node_mgr.uncordon_all()

    for node_name in cordoned_nodes:
        if event_emitter is not None:
            try:
                event_emitter.node_uncordoned(node_name)
            except Exception:
                logger.debug("K8s Event emit failed", exc_info=True)

    saved     = state_store.load_replicas()
    saved_hpa = state_store.load_hpa_min_replicas()
    eligible  = scaler.find_eligible()

    restored_dep_names = []
    for dep in eligible:
        ns   = dep.metadata.namespace
        name = dep.metadata.name
        key  = f"{ns}/{name}"

        target = saved.get(key, 1)
        scaler.scale_up(dep, target)
        state_store.clear_replicas(ns, name)
        restored_dep_names.append(f"{ns}/{name}")

        if event_emitter is not None:
            try:
                event_emitter.deployment_scaled_up(ns, name, target)
            except Exception:
                logger.debug("K8s Event emit failed", exc_info=True)

        # Restore HPA after deployments are back up
        if key in saved_hpa:
            hpa = scaler.find_hpa(dep)
            if hpa is not None:
                scaler.resume_hpa(hpa, saved_hpa[key])
            state_store.clear_hpa_min_replicas(ns, name)

    telemetry.scaleup_events.inc()
    telemetry.nodes_cordoned.set(0)
    telemetry.replicas_saved.set(0)

    if notifier is not None:
        try:
            notifier.notify_scale_up(restored_dep_names, cordoned_nodes, savings_usd=0.0)
        except Exception:
            logger.debug("Webhook notify_scale_up failed", exc_info=True)

    logger.info("Scale-up complete: %d deployment(s) restored", len(eligible))


if __name__ == "__main__":
    run()
