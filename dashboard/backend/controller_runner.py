"""
Embedded controller loop for web-service mode.

Activated via POST /api/connect — the user provides a kubeconfig string from
the browser; this module loads it, validates connectivity, and starts a
schedule-based scale-down/up loop as a background daemon thread.

Fully self-contained: no dependency on the controller/ package, so the
dashboard Docker image needs no changes to its build context.

Scale-down logic
  • Deployments labelled  finops.io/scaledown-eligible=true  are scaled to
    min_replica_floor (default 0).
  • All non-control-plane nodes are cordoned (marked unschedulable).  No drain
    is issued — existing pods continue running; the cluster simply stops
    accepting new scheduled work on those nodes.

Scale-up logic
  • Nodes are uncordoned.
  • Saved replica counts are restored on each eligible deployment.

Schedule awareness
  • Config is re-read from config_store on every tick, so changes made in the
    Settings panel take effect without a restart.
"""

import json
import logging
import os
import tempfile
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import yaml

from .schedule import is_outside_business_hours, resolve_override

logger = logging.getLogger(__name__)

_STATE_FILE  = os.path.join(tempfile.gettempdir(), "finops-web-state.json")
_LABEL_SEL   = "finops.io/scaledown-eligible=true"
_CP_LABELS   = {"node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"}

# EKS STS tokens expire after 15 minutes; refresh 2 minutes early
_EKS_TOKEN_REFRESH_INTERVAL = 13 * 60  # seconds


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_cpu(cpu_str: str) -> float:
    if str(cpu_str).endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


def _load_state() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"replicas": {}, "cordoned_nodes": []}


def _save_state(state: dict) -> None:
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as exc:
        logger.warning("State save failed: %s", exc)


_dry_run_log: deque = deque(maxlen=500)


def get_dry_run_log() -> deque:
    """Return the capped dry-run log for the API."""
    return _dry_run_log

# ── Runner ────────────────────────────────────────────────────────────────────

@dataclass
class RunnerStatus:
    running: bool
    connected: bool
    cluster_host: str
    last_tick: Optional[str]   # ISO-8601
    last_action: str
    error: Optional[str]

    def as_dict(self) -> dict:
        return asdict(self)


class ControllerRunner:
    """Background thread that runs the schedule-based scale loop."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event  = threading.Event()
        self._lock        = threading.Lock()

        self._running      = False
        self._connected    = False
        self._cluster_host = ""
        self._last_tick: Optional[datetime] = None
        self._last_action  = "not_started"
        self._error: Optional[str] = None

        # kubernetes client handles — set by connect()
        self._core_v1 = None
        self._apps_v1 = None
        self._kubeconfig_path: Optional[str] = None

        # cloud provider credentials — set by set_cloud_creds() after connect()
        self._connection_type: str = "kubeconfig"  # "kubeconfig" | "eks" | "gke"
        self._cloud_creds: dict = {}

        # EKS token refresh thread
        self._refresher_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────

    def connect(self, kubeconfig_str: str):
        """
        Parse and load the kubeconfig string, then validate by listing nodes.
        Returns (core_v1, apps_v1) for the dashboard's K8sReader.
        Raises on invalid kubeconfig or unreachable cluster.
        """
        from kubernetes import client as kc
        from kubernetes import config as kcfg

        # Write to temp file (most cross-version-compatible approach)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="finops-kube-"
        )
        try:
            tmp.write(kubeconfig_str)
            tmp_path = tmp.name
        finally:
            tmp.close()

        kcfg.load_kube_config(config_file=tmp_path)
        core_v1 = kc.CoreV1Api()
        apps_v1 = kc.AppsV1Api()

        # Validate: round-trip to the API server
        node_list  = core_v1.list_node(limit=5)
        node_count = len(node_list.items)

        # Parse cluster server URL for status display
        server = "unknown"
        try:
            parsed   = yaml.safe_load(kubeconfig_str)
            clusters = parsed.get("clusters", [])
            if clusters:
                server = clusters[0]["cluster"].get("server", "unknown")
        except Exception:
            pass

        with self._lock:
            # Clean up old temp file if any
            if self._kubeconfig_path:
                try:
                    os.unlink(self._kubeconfig_path)
                except Exception:
                    pass
            self._kubeconfig_path = tmp_path
            self._core_v1    = core_v1
            self._apps_v1    = apps_v1
            self._cluster_host = server
            self._connected  = True
            self._error      = None

        logger.info("Connected to cluster: %s (%d node(s) visible)", server, node_count)
        return core_v1, apps_v1

    def start(self, interval_seconds: int = 60):
        """
        Start the control loop in a background daemon thread.
        Config is re-read from config_store on every tick.
        Also starts the EKS token refresh thread when connected via EKS.
        """
        self.stop()
        self._stop_event.clear()
        self._running     = True
        self._last_action = "starting"
        self._thread      = threading.Thread(
            target=self._loop,
            args=(interval_seconds,),
            daemon=True,
            name="finops-controller",
        )
        self._thread.start()

        # Start token refresh only after stop_event is cleared
        if self._connection_type == "eks" and self._cloud_creds:
            self._start_token_refresher()

        logger.info("Controller loop started (interval=%ds)", interval_seconds)

    def stop(self):
        """Signal the loop to stop and wait for the thread to finish."""
        self._stop_event.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8)
        if self._refresher_thread and self._refresher_thread.is_alive():
            self._refresher_thread.join(timeout=5)
        self._last_action = "stopped"
        logger.info("Controller loop stopped")

    def set_cloud_creds(self, connection_type: str, creds: dict) -> None:
        """Store cloud provider credentials for use by the token refresh thread (Session 3)."""
        with self._lock:
            self._connection_type = connection_type
            self._cloud_creds = creds

    def disconnect(self):
        """Stop loop and clear the cluster connection."""
        self.stop()
        with self._lock:
            self._connected    = False
            self._cluster_host = ""
            self._core_v1      = None
            self._apps_v1      = None

    def status(self) -> RunnerStatus:
        is_alive = bool(self._thread and self._thread.is_alive())
        return RunnerStatus(
            running      = self._running and is_alive,
            connected    = self._connected,
            cluster_host = self._cluster_host,
            last_tick    = self._last_tick.isoformat() if self._last_tick else None,
            last_action  = self._last_action,
            error        = self._error,
        )

    # ── Emergency scale controls ────────────────────────────────────

    def force_wake(self):
        """Force immediate scale-up regardless of schedule."""
        state = _load_state()
        if not state.get("replicas"):
            logger.info("force_wake: cluster is already active")
            with self._lock:
                self._last_action = "force_wake (already active)"
            return
        self._scale_up(state)
        with self._lock:
            self._last_action = "force_wake"
        logger.info("Force wake completed")

    def force_sleep(self):
        """Force immediate scale-down regardless of schedule."""
        from . import config_store
        state = _load_state()
        if state.get("replicas"):
            logger.info("force_sleep: cluster is already hibernating")
            with self._lock:
                self._last_action = "force_sleep (already hibernating)"
            return
        self._scale_down(config_store.as_dict())
        with self._lock:
            self._last_action = "force_sleep"
        logger.info("Force sleep completed")

    # ── EKS token refresh ─────────────────────────────────────────

    def _start_token_refresher(self) -> None:
        self._refresher_thread = threading.Thread(
            target=self._token_refresh_loop,
            daemon=True,
            name="finops-eks-token-refresher",
        )
        self._refresher_thread.start()
        logger.info(
            "EKS token refresh thread started (interval=%ds)", _EKS_TOKEN_REFRESH_INTERVAL
        )

    def _token_refresh_loop(self) -> None:
        """
        Refresh the EKS STS bearer token every 13 minutes while connected.

        EKS tokens expire after 15 minutes.  We patch the token directly on
        the ApiClient.configuration held by the already-connected CoreV1Api /
        AppsV1Api objects so the running control loop picks it up transparently.
        """
        from .cloud_providers import get_eks_token  # local import — only for EKS

        # Stop immediately if the event is already set (e.g., called during stop/restart)
        while not self._stop_event.wait(timeout=_EKS_TOKEN_REFRESH_INTERVAL):
            with self._lock:
                if self._connection_type != "eks" or not self._cloud_creds:
                    break
                creds   = dict(self._cloud_creds)
                core_v1 = self._core_v1
                apps_v1 = self._apps_v1

            try:
                new_token = get_eks_token(
                    creds["cluster_name"],
                    creds["region"],
                    creds["access_key_id"],
                    creds["secret_access_key"],
                )
                # Patch the token in-place on both API clients
                for api in (core_v1, apps_v1):
                    if api is not None:
                        api.api_client.configuration.api_key["authorization"] = new_token
                logger.info("EKS token refreshed for cluster %s", creds["cluster_name"])
            except Exception as exc:
                logger.warning("EKS token refresh failed (will retry next interval): %s", exc)

    # ── Internal loop ─────────────────────────────────────────────

    def _loop(self, interval_s: int):
        from . import config_store  # live reference — picks up setting changes

        while not self._stop_event.is_set():
            try:
                self._tick(config_store.as_dict())
                with self._lock:
                    self._last_tick = datetime.now(tz=timezone.utc)
                    self._error     = None
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
                logger.exception("Controller tick error")

            self._stop_event.wait(timeout=interval_s)

    def _tick(self, cfg: dict):
        now = datetime.now(tz=timezone.utc)

        # Check manual override via shared schedule module
        override = resolve_override(cfg, now)
        if override != cfg.get("override_mode", ""):
            from . import config_store
            config_store.patch({"override_mode": "", "override_until": ""})

        state = _load_state()
        down = bool(state.get("replicas"))

        if override == "awake":
            if down:
                self._scale_up(state)
            else:
                with self._lock:
                    self._last_action = "override_awake"
            return
        elif override == "sleep":
            if not down:
                self._scale_down(cfg)
            else:
                with self._lock:
                    self._last_action = "override_sleep"
            return

        # Normal schedule — delegated to shared schedule module
        low = is_outside_business_hours(cfg, now)
        if low and not down:
            self._scale_down(cfg)
        elif not low and down:
            self._scale_up(state)
        else:
            with self._lock:
                self._last_action = "no_action"
            logger.debug("tick: no action (low=%s, already_down=%s)", low, down)

    # ── Scale operations ──────────────────────────────────────────

    def _scale_down(self, cfg: dict):
        core     = self._core_v1
        apps     = self._apps_v1
        ns_f     = cfg.get("namespace_filter", "")
        floor    = int(cfg.get("min_replica_floor", 0))
        dry_run  = bool(cfg.get("dry_run", False))

        exclude_raw = cfg.get("exclude_deployments", "")
        excludes = set(e.strip() for e in exclude_raw.split(",") if e.strip())

        logger.info("Idle window — scaling down eligible deployments")

        if ns_f:
            deps = apps.list_namespaced_deployment(ns_f, label_selector=_LABEL_SEL).items
        else:
            deps = apps.list_deployment_for_all_namespaces(label_selector=_LABEL_SEL).items

        saved = {}
        for dep in deps:
            ns, name = dep.metadata.namespace, dep.metadata.name
            current  = dep.spec.replicas or 0
            key = f"{ns}/{name}"
            if key in excludes or name in excludes:
                logger.info("  safelist skip: %s", key)
                continue
            if current <= floor:
                continue
            if not dry_run:
                apps.patch_namespaced_deployment_scale(name, ns, {"spec": {"replicas": floor}})
            saved[key] = current
            logger.info("  %sscaled %s/%s  %d → %d", "(dry-run) " if dry_run else "", ns, name, current, floor)

        # Cordon non-control-plane nodes
        cordoned = []
        for node in core.list_node().items:
            labels = node.metadata.labels or {}
            if _CP_LABELS & set(labels):
                continue
            n_name = node.metadata.name
            if not node.spec.unschedulable:
                if not dry_run:
                    core.patch_node(n_name, {"spec": {"unschedulable": True}})
                cordoned.append(n_name)
                logger.info("  %scordoned node: %s", "(dry-run) " if dry_run else "", n_name)

        if dry_run:
            now = datetime.now(tz=timezone.utc)
            _dry_run_log.append({
                "timestamp": now.isoformat(),
                "action": "would_scale_down",
                "deployments": list(saved.keys()),
                "nodes": cordoned,
            })
            with self._lock:
                self._last_action = f"dry_run_scale_down ({len(saved)} deps, {len(cordoned)} nodes)"
        else:
            _save_state({"replicas": saved, "cordoned_nodes": cordoned})
            with self._lock:
                self._last_action = f"scaled_down ({len(saved)} deps, {len(cordoned)} nodes)"
        logger.info("Scale-down complete — %d dep(s), %d node(s)%s", len(saved), len(cordoned), " [DRY RUN]" if dry_run else "")

    def _scale_up(self, state: dict):
        from . import config_store as _cs
        dry_run = bool(_cs.get().dry_run)
        core = self._core_v1
        apps = self._apps_v1

        logger.info("Active window — restoring cluster")

        for n_name in state.get("cordoned_nodes", []):
            try:
                if not dry_run:
                    core.patch_node(n_name, {"spec": {"unschedulable": False}})
                logger.info("  %suncordoned: %s", "(dry-run) " if dry_run else "", n_name)
            except Exception as exc:
                logger.warning("  uncordon %s failed: %s", n_name, exc)

        for key, replicas in state.get("replicas", {}).items():
            ns, name = key.split("/", 1)
            try:
                if not dry_run:
                    apps.patch_namespaced_deployment_scale(
                        name, ns, {"spec": {"replicas": replicas}}
                    )
                logger.info("  %srestored %s/%s → %d", "(dry-run) " if dry_run else "", ns, name, replicas)
            except Exception as exc:
                logger.warning("  restore %s failed: %s", key, exc)

        if dry_run:
            now = datetime.now(tz=timezone.utc)
            _dry_run_log.append({
                "timestamp": now.isoformat(),
                "action": "would_scale_up",
                "deployments": list(state.get("replicas", {}).keys()),
                "nodes": state.get("cordoned_nodes", []),
            })
            with self._lock:
                self._last_action = "dry_run_scale_up"
        else:
            _save_state({"replicas": {}, "cordoned_nodes": []})
            with self._lock:
                self._last_action = "scaled_up"
        logger.info("Scale-up complete%s", " [DRY RUN]" if dry_run else "")


# ── Module-level singleton ────────────────────────────────────────────────────

_runner = ControllerRunner()


def get_runner() -> ControllerRunner:
    return _runner
