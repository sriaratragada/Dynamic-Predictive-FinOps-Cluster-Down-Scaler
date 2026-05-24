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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_STATE_FILE  = os.path.join(tempfile.gettempdir(), "finops-web-state.json")
_LABEL_SEL   = "finops.io/scaledown-eligible=true"
_CP_LABELS   = {"node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_cpu(cpu_str: str) -> float:
    if str(cpu_str).endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


def _is_low_activity(cfg: dict, now: datetime) -> bool:
    """Return True when the schedule says the cluster should be idle."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo(cfg.get("timezone", "UTC"))
    local = now.astimezone(tz)

    days = [int(d) for d in cfg.get("business_days", "0,1,2,3,4").split(",") if d.strip()]
    if local.weekday() not in days:
        return True

    def _hm(s: str) -> tuple[int, int]:
        h, m = s.split(":")
        return int(h), int(m)

    sh, sm = _hm(cfg.get("business_hours_start", "07:00"))
    eh, em = _hm(cfg.get("business_hours_end", "19:00"))
    prewarm  = int(cfg.get("prewarm_minutes", 15))
    cur_m    = local.hour * 60 + local.minute
    start_m  = sh * 60 + sm
    end_m    = eh * 60 + em
    return cur_m < (start_m - prewarm) or cur_m >= end_m


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
        logger.info("Controller loop started (interval=%ds)", interval_seconds)

    def stop(self):
        """Signal the loop to stop and wait for the thread to finish."""
        self._stop_event.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8)
        self._last_action = "stopped"
        logger.info("Controller loop stopped")

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
        now  = datetime.now(tz=timezone.utc)
        low  = _is_low_activity(cfg, now)
        state = _load_state()
        down  = bool(state.get("replicas"))

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

        logger.info("Idle window — scaling down eligible deployments")

        if ns_f:
            deps = apps.list_namespaced_deployment(ns_f, label_selector=_LABEL_SEL).items
        else:
            deps = apps.list_deployment_for_all_namespaces(label_selector=_LABEL_SEL).items

        saved = {}
        for dep in deps:
            ns, name = dep.metadata.namespace, dep.metadata.name
            current  = dep.spec.replicas or 0
            if current <= floor:
                continue
            apps.patch_namespaced_deployment_scale(name, ns, {"spec": {"replicas": floor}})
            saved[f"{ns}/{name}"] = current
            logger.info("  scaled %s/%s  %d → %d", ns, name, current, floor)

        # Cordon non-control-plane nodes
        cordoned = []
        for node in core.list_node().items:
            labels = node.metadata.labels or {}
            if _CP_LABELS & set(labels):
                continue
            n_name = node.metadata.name
            if not node.spec.unschedulable:
                core.patch_node(n_name, {"spec": {"unschedulable": True}})
                cordoned.append(n_name)
                logger.info("  cordoned node: %s", n_name)

        _save_state({"replicas": saved, "cordoned_nodes": cordoned})
        with self._lock:
            self._last_action = f"scaled_down ({len(saved)} deps, {len(cordoned)} nodes)"
        logger.info("Scale-down complete — %d dep(s), %d node(s)", len(saved), len(cordoned))

    def _scale_up(self, state: dict):
        core = self._core_v1
        apps = self._apps_v1

        logger.info("Active window — restoring cluster")

        for n_name in state.get("cordoned_nodes", []):
            try:
                core.patch_node(n_name, {"spec": {"unschedulable": False}})
                logger.info("  uncordoned: %s", n_name)
            except Exception as exc:
                logger.warning("  uncordon %s failed: %s", n_name, exc)

        for key, replicas in state.get("replicas", {}).items():
            ns, name = key.split("/", 1)
            try:
                apps.patch_namespaced_deployment_scale(
                    name, ns, {"spec": {"replicas": replicas}}
                )
                logger.info("  restored %s/%s → %d", ns, name, replicas)
            except Exception as exc:
                logger.warning("  restore %s failed: %s", key, exc)

        _save_state({"replicas": {}, "cordoned_nodes": []})
        with self._lock:
            self._last_action = "scaled_up"
        logger.info("Scale-up complete")


# ── Module-level singleton ────────────────────────────────────────────────────

_runner = ControllerRunner()


def get_runner() -> ControllerRunner:
    return _runner
