import asyncio
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config_store, pricing
from .auth import require_token
from .controller_runner import get_runner as _get_runner
from .k8s_client import K8sReader
from .prewarm import get_controller as _get_prewarm
from .savings_tracker import SavingsTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# Demo mode for K8s-reader initialisation is fixed at startup from env var.
# Prometheus demo mode is dynamic — reads from config_store on every request.
_STARTUP_DEMO = os.environ.get("DEMO_MODE", "false").lower() == "true"

_k8s: Optional[K8sReader] = None
_tracker: Optional[SavingsTracker] = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """FastAPI lifespan — initialise K8s reader and savings tracker on startup."""
    global _k8s, _tracker

    if _STARTUP_DEMO:
        from .demo_stub import DemoK8sReader  # noqa: PLC0415
        _k8s = DemoK8sReader()
        logger.info("DEMO MODE active — using synthetic data (no K8s or Prometheus needed)")
    else:
        try:
            _k8s = K8sReader()
            logger.info("Kubernetes client initialised")
        except Exception as exc:
            logger.warning("K8s unavailable (no cluster?): %s", exc)

        try:
            pricing.get_hourly_rate()
        except Exception as exc:
            logger.warning("Pricing init failed: %s", exc)

        if _k8s:
            _tracker = SavingsTracker(_k8s, pricing.get_hourly_rate)
            asyncio.create_task(_tracker.start())

    yield  # application runs here

    # Shutdown — stop the savings tracker cleanly
    if _tracker is not None:
        _tracker.stop()


app = FastAPI(
    title="FinOps Dashboard API",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["GET", "PATCH", "POST"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Prometheus helpers — read prometheus_url + demo_mode from config_store
# ------------------------------------------------------------------

async def _prom_query(
    query: str,
    range_hours: Optional[int] = None,
) -> list:
    """Single helper for both instant and range queries.

    When ``range_hours`` is None this hits ``/api/v1/query``; otherwise it
    hits ``/api/v1/query_range`` with a step derived to give ~200 samples.
    Honours demo mode and reads prometheus_url live from config_store.
    """
    cfg = config_store.get()

    if range_hours is None:
        if cfg.demo_mode:
            from .demo_stub import demo_prom_instant  # noqa: PLC0415
            return demo_prom_instant(query)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{cfg.prometheus_url}/api/v1/query", params={"query": query}
            )
            r.raise_for_status()
            data = r.json()
            if data["status"] != "success":
                raise ValueError(data.get("error", "Prometheus error"))
            return data["data"]["result"]

    end = int(datetime.now(tz=timezone.utc).timestamp())
    start = end - range_hours * 3600
    step = max(300, (range_hours * 3600) // 200)
    if cfg.demo_mode:
        from .demo_stub import demo_prom_range  # noqa: PLC0415
        return demo_prom_range(query, start, end, step)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{cfg.prometheus_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
        )
        r.raise_for_status()
        data = r.json()
        if data["status"] != "success":
            raise ValueError(data.get("error", "Prometheus range error"))
        return data["data"]["result"]


# Thin BC-friendly wrappers — tests / external code might import these names.
async def _prom_instant(query: str) -> list:
    return await _prom_query(query)


async def _prom_range(query: str, hours: int) -> list:
    return await _prom_query(query, range_hours=hours)


# ------------------------------------------------------------------
# Configuration routes
# ------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return config_store.as_dict()


@app.patch("/api/config")
async def patch_config(request: Request, _: None = Depends(require_token)):
    updates = await request.json()
    config_store.patch(updates)
    logger.info("Config updated: %s", list(updates.keys()))
    return config_store.as_dict()


# ------------------------------------------------------------------
# Pre-warm route
# ------------------------------------------------------------------

@app.post("/api/prewarm")
async def api_prewarm(request: Request, _: None = Depends(require_token)):
    """
    Receive an early-intent signal from a frontend client and proactively
    boot the target Knative AI container before the user submits a prompt.

    Body (JSON):
        service_url  str   Full URL of the Knative service to pre-warm
                           e.g. "http://model-api.default.svc.cluster.local"
        signal       str   Intent signal type: login | page_load | hover | input_focus
        user_id      str   (optional) Opaque user identifier for log correlation

    Returns:
        status  "warm" | "warming" | "cold" | "rejected" | "debounced" | "cooldown" | "rate_limited"
        action  "none" | "prewarm_triggered"

    Disabled (returns {enabled: false}) when config.enable_prewarm is false.
    """
    cfg = config_store.get()
    if not cfg.enable_prewarm:
        return {"enabled": False, "action": "none"}

    body = await request.json()
    service_url: str = (body.get("service_url") or "").strip()
    if not service_url:
        raise HTTPException(status_code=422, detail="service_url is required")

    signal = str(body.get("signal", "unknown"))
    user_id = body.get("user_id")

    controller = _get_prewarm()
    return await controller.handle_signal(service_url, signal, user_id)


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def api_status():
    if not _k8s:
        return {"scaled_down": False, "cordoned_nodes": [], "deployments_scaled": [],
                "cordoned_node_count": 0, "deployment_count": 0}
    state = _k8s.read_state()
    replicas = state.get("replicas", {})
    cordoned = state.get("cordoned_nodes", [])
    return {
        "scaled_down": bool(replicas),
        "cordoned_nodes": cordoned,
        "deployments_scaled": [
            {"key": k, "original_replicas": v} for k, v in replicas.items()
        ],
        "cordoned_node_count": len(cordoned),
        "deployment_count": len(replicas),
    }


@app.get("/api/capacity")
async def api_capacity():
    nodes = _k8s.list_nodes() if _k8s else []
    cordoned = _k8s.read_state().get("cordoned_nodes", []) if _k8s else []

    cpu_map: dict = {}
    try:
        results = await _prom_query(
            'sum by (node) (rate(container_cpu_usage_seconds_total{container!=""}[5m]))'
        )
        cpu_map = {r["metric"].get("node", ""): float(r["value"][1]) for r in results}
    except Exception as exc:
        logger.warning("Node CPU query failed: %s", exc)

    node_rows = []
    total_alloc = total_used = 0.0
    for n in nodes:
        if n["is_control_plane"]:
            continue
        alloc = n["allocatable_cpu"]
        used = cpu_map.get(n["name"], 0.0)
        total_alloc += alloc
        total_used += used
        node_rows.append({
            "name": n["name"],
            "allocatable_cpu_cores": round(alloc, 2),
            "used_cpu_cores": round(used, 4),
            "utilisation_pct": round(used / alloc * 100, 1) if alloc > 0 else 0.0,
            "cordoned": n["name"] in cordoned,
        })

    return {
        "nodes": node_rows,
        "total_allocatable_cores": round(total_alloc, 2),
        "total_used_cores": round(total_used, 4),
        "cluster_utilisation_pct": round(total_used / total_alloc * 100, 1) if total_alloc > 0 else 0.0,
    }


_HISTORY_QUERIES = (
    ("cpu_used",
     'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))',
     "value"),
    ("cpu_capacity",
     'sum(kube_node_status_allocatable{resource="cpu"})',
     "value"),
    ("scaledown_events",
     "increase(finops_scaledown_events_total[5m])",
     "marker"),
    ("scaleup_events",
     "increase(finops_scaleup_events_total[5m])",
     "marker"),
)


@app.get("/api/history")
async def api_history(hours: int = 24):
    """Return CPU usage, capacity, and scale-event markers over the last *hours*."""
    out: dict[str, Any] = {"hours": hours}
    for key, promql, kind in _HISTORY_QUERIES:
        try:
            results = await _prom_query(promql, range_hours=hours)
        except Exception as exc:
            logger.warning("History query %s failed: %s", key, exc)
            out[key] = []
            continue
        values = results[0]["values"] if results else []
        if kind == "value":
            out[key] = [
                {"t": int(ts * 1000), "v": round(float(v), 3)} for ts, v in values
            ]
        else:  # marker
            out[key] = [int(ts * 1000) for ts, v in values if float(v) > 0]
    return out


@app.get("/api/events")
async def api_events():
    """
    Return the audit log — a list of completed cordon/savings events in reverse
    chronological order (most recent first).  Each event has:
        node       str   Kubernetes node name
        start      str   ISO-8601 UTC cordon start time
        end        str   ISO-8601 UTC cordon end time
        hours      float Duration in fractional hours
        saved_usd  float Dollars saved during this cordon window
    """
    cfg = config_store.get()
    if cfg.demo_mode:
        from .demo_stub import _historical_events  # noqa: PLC0415
        events = _historical_events()
        return {"events": list(reversed(events))}

    if _tracker is None:
        return {"events": []}

    # Most recent first
    return {"events": list(reversed(_tracker.list_events()))}


@app.get("/api/savings")
async def api_savings():
    cfg = config_store.get()

    if cfg.demo_mode:
        from .demo_stub import _historical_events, _SEED_TOTAL_SAVED, _is_active  # noqa: PLC0415
        now = datetime.now(tz=timezone.utc)
        events = _historical_events()
        week_ago = now.timestamp() - 7 * 86400
        month_ago = now.timestamp() - 30 * 86400
        week_usd = sum(
            e["saved_usd"] for e in events
            if e.get("end") and datetime.fromisoformat(e["end"]).timestamp() >= week_ago
        )
        month_usd = sum(
            e["saved_usd"] for e in events
            if e.get("end") and datetime.fromisoformat(e["end"]).timestamp() >= month_ago
        )
        cordoned = 0 if _is_active(now) else 2
        running_cost = cordoned * cfg.node_hourly_cost * 0.5
        return {
            "total_saved_usd": round(_SEED_TOTAL_SAVED + month_usd, 2),
            "this_week_usd": round(week_usd, 2),
            "this_month_usd": round(month_usd, 2),
            "hourly_rate_per_node": cfg.node_hourly_cost,
            "currently_cordoned_count": cordoned,
            "active_cordon_running_cost": round(running_cost, 4),
            "cloud_provider": cfg.cloud_provider,
            "instance_type": cfg.instance_type or "m5.xlarge",
            "region": cfg.aws_region or "demo",
        }

    info = pricing.get_provider_info()
    rate = pricing.get_hourly_rate()

    summary = {
        "total_saved_usd": 0.0,
        "this_week_usd": 0.0,
        "this_month_usd": 0.0,
        "hourly_rate_per_node": rate,
        "currently_cordoned_count": 0,
        "active_cordon_running_cost": 0.0,
    }
    if _tracker:
        summary = _tracker.get_summary()

    return {
        **summary,
        "cloud_provider": info["provider"],
        "instance_type": info["instance_type"],
        "region": info["region"],
    }


# ------------------------------------------------------------------
# Web-service: cluster connect / controller management
# ------------------------------------------------------------------

async def _activate_cluster(core_v1, apps_v1) -> None:
    """Shared post-connect setup used by every connect endpoint.

    Re-points the dashboard's K8s reader at the new cluster, restarts the
    savings tracker cleanly (stopping the old one to avoid a thread leak),
    switches the dashboard out of demo mode, and starts the embedded loop.
    """
    global _k8s, _tracker

    _k8s = K8sReader(core_v1=core_v1, apps_v1=apps_v1)

    if _tracker is not None:
        _tracker.stop()  # cooperative cancellation — old task exits cleanly
    _tracker = SavingsTracker(_k8s, pricing.get_hourly_rate)
    asyncio.create_task(_tracker.start())

    config_store.patch({"demo_mode": False})

    runner = _get_runner()
    await asyncio.to_thread(runner.start, 60)


def _require_fields(body: dict, *fields: str) -> dict:
    """Strip & validate required JSON body fields. Raises HTTPException(422) if missing."""
    out: dict[str, str] = {}
    missing: list[str] = []
    for f in fields:
        v = (body.get(f) or "").strip() if isinstance(body.get(f), str) else body.get(f)
        if not v:
            missing.append(f)
        else:
            out[f] = v
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"required fields: {', '.join(missing)}",
        )
    return out


@app.post("/api/connect")
async def api_connect(request: Request, _: None = Depends(require_token)):
    """
    Accept a kubeconfig YAML string, validate it by listing nodes, then
    start the embedded controller loop.

    Body (JSON):
        kubeconfig  str  Full kubeconfig YAML (same as ~/.kube/config)
    """
    body = await request.json()
    fields = _require_fields(body, "kubeconfig")

    runner = _get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, fields["kubeconfig"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    await _activate_cluster(core_v1, apps_v1)
    logger.info("Web-service mode: controller started, K8sReader re-initialised")
    return runner.status().as_dict()


@app.post("/api/aws/clusters")
async def api_aws_clusters(request: Request, _: None = Depends(require_token)):
    """List EKS clusters in the given region using explicit AWS credentials."""
    from . import cloud_providers  # noqa: PLC0415

    body = await request.json()
    f = _require_fields(body, "region", "access_key_id", "secret_access_key")

    try:
        clusters = await asyncio.to_thread(
            cloud_providers.list_eks_clusters,
            f["region"], f["access_key_id"], f["secret_access_key"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"AWS error: {exc}") from exc

    return {"clusters": clusters}


@app.post("/api/gcp/clusters")
async def api_gcp_clusters(request: Request, _: None = Depends(require_token)):
    """List GKE clusters using a GCP service account JSON string."""
    from . import cloud_providers  # noqa: PLC0415

    body = await request.json()
    f = _require_fields(body, "project_id", "service_account_json")
    location = (body.get("location") or "-").strip() or "-"

    try:
        clusters = await asyncio.to_thread(
            cloud_providers.list_gke_clusters,
            f["project_id"], location, f["service_account_json"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GCP error: {exc}") from exc

    return {"clusters": clusters}


@app.post("/api/connect/eks")
async def api_connect_eks(request: Request, _: None = Depends(require_token)):
    """Connect to an EKS cluster using explicit AWS credentials, then start the embedded controller loop."""
    from . import cloud_providers  # noqa: PLC0415

    body = await request.json()
    f = _require_fields(body, "region", "cluster_name", "access_key_id", "secret_access_key")

    try:
        kubeconfig_str = await asyncio.to_thread(
            cloud_providers.kubeconfig_from_eks,
            f["cluster_name"], f["region"], f["access_key_id"], f["secret_access_key"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"EKS kubeconfig error: {exc}") from exc

    runner = _get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, kubeconfig_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    # Store credentials for STS token auto-refresh
    runner.set_cloud_creds("eks", {
        "region": f["region"],
        "cluster_name": f["cluster_name"],
        "access_key_id": f["access_key_id"],
        "secret_access_key": f["secret_access_key"],
    })

    await _activate_cluster(core_v1, apps_v1)
    logger.info("EKS cluster connected: %s (%s)", f["cluster_name"], f["region"])
    return runner.status().as_dict()


@app.post("/api/connect/gke")
async def api_connect_gke(request: Request, _: None = Depends(require_token)):
    """Connect to a GKE cluster using a GCP service account JSON string, then start the embedded controller loop."""
    from . import cloud_providers  # noqa: PLC0415

    body = await request.json()
    f = _require_fields(body, "project_id", "location", "cluster_name", "service_account_json")

    try:
        kubeconfig_str = await asyncio.to_thread(
            cloud_providers.kubeconfig_from_gke,
            f["project_id"], f["location"], f["cluster_name"], f["service_account_json"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GKE kubeconfig error: {exc}") from exc

    runner = _get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, kubeconfig_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    runner.set_cloud_creds("gke", {
        "project_id": f["project_id"],
        "location": f["location"],
        "cluster_name": f["cluster_name"],
        "service_account_json": f["service_account_json"],
    })

    await _activate_cluster(core_v1, apps_v1)
    logger.info("GKE cluster connected: %s (%s/%s)", f["cluster_name"], f["project_id"], f["location"])
    return runner.status().as_dict()


@app.get("/api/controller")
async def api_controller_status():
    """Return the embedded controller's current status."""
    return _get_runner().status().as_dict()


@app.post("/api/controller/stop")
async def api_controller_stop(_: None = Depends(require_token)):
    """Stop the embedded controller loop (does not disconnect from the cluster)."""
    runner = _get_runner()
    await asyncio.to_thread(runner.stop)
    return runner.status().as_dict()


# ------------------------------------------------------------------
# Serve React frontend (must be last)
# ------------------------------------------------------------------

_STATIC = pathlib.Path(__file__).parent.parent / "frontend" / "dist"

if _STATIC.is_dir():
    _assets = _STATIC / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}")
    async def _spa(full_path: str):
        return FileResponse(str(_STATIC / "index.html"))
else:
    @app.get("/")
    async def _no_frontend():
        return {"message": "Frontend not built. Run: cd dashboard/frontend && npm run build"}
