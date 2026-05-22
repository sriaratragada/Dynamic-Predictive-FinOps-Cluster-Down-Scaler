import asyncio
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config_store, pricing
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

app = FastAPI(title="FinOps Dashboard API", docs_url="/api/docs", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "PATCH", "POST"],
    allow_headers=["*"],
)

_k8s: Optional[K8sReader] = None
_tracker: Optional[SavingsTracker] = None


@app.on_event("startup")
async def _startup():
    global _k8s, _tracker

    if _STARTUP_DEMO:
        from .demo_stub import DemoK8sReader  # noqa: PLC0415
        _k8s = DemoK8sReader()
        logger.info("DEMO MODE active — using synthetic data (no K8s or Prometheus needed)")
        return

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


# ------------------------------------------------------------------
# Prometheus helpers  (read prometheus_url + demo_mode from config_store)
# ------------------------------------------------------------------

async def _prom_instant(query: str) -> list:
    cfg = config_store.get()
    if cfg.demo_mode:
        from .demo_stub import demo_prom_instant  # noqa: PLC0415
        return demo_prom_instant(query)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{cfg.prometheus_url}/api/v1/query", params={"query": query})
        r.raise_for_status()
        data = r.json()
        if data["status"] != "success":
            raise ValueError(data.get("error", "Prometheus error"))
        return data["data"]["result"]


async def _prom_range(query: str, hours: int) -> list:
    cfg = config_store.get()
    end = int(datetime.now(tz=timezone.utc).timestamp())
    start = end - hours * 3600
    step = max(300, (hours * 3600) // 200)
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


# ------------------------------------------------------------------
# Configuration routes
# ------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return config_store.as_dict()


@app.patch("/api/config")
async def patch_config(request: Request):
    updates = await request.json()
    updated = config_store.patch(updates)
    logger.info("Config updated: %s", list(updates.keys()))
    return config_store.as_dict()


# ------------------------------------------------------------------
# Pre-warm route
# ------------------------------------------------------------------

@app.post("/api/prewarm")
async def api_prewarm(request: Request):
    """
    Receive an early-intent signal from a frontend client and proactively
    boot the target Knative AI container before the user submits a prompt.

    Body (JSON):
        service_url  str   Full URL of the Knative service to pre-warm
                           e.g. "http://model-api.default.svc.cluster.local"
        signal       str   Intent signal type: login | page_load | hover | input_focus
        user_id      str   (optional) Opaque user identifier for log correlation

    Returns:
        status  "warm" | "warming" | "cold"
        action  "none" | "prewarm_triggered"

    Disabled (returns {enabled: false}) when config.enable_prewarm is false.
    """
    cfg = config_store.get()
    if not cfg.enable_prewarm:
        return {"enabled": False, "action": "none"}

    body = await request.json()
    service_url: str = (body.get("service_url") or "").strip()
    if not service_url:
        from fastapi import HTTPException  # noqa: PLC0415
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
        results = await _prom_instant(
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


@app.get("/api/history")
async def api_history(hours: int = 24):
    cpu_used: list = []
    cpu_cap: list = []
    sd_events: list = []
    su_events: list = []

    try:
        results = await _prom_range(
            'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))', hours
        )
        if results:
            cpu_used = [{"t": int(ts * 1000), "v": round(float(v), 3)}
                        for ts, v in results[0]["values"]]
    except Exception as exc:
        logger.warning("History CPU query failed: %s", exc)

    try:
        results = await _prom_range(
            'sum(kube_node_status_allocatable{resource="cpu"})', hours
        )
        if results:
            cpu_cap = [{"t": int(ts * 1000), "v": round(float(v), 2)}
                       for ts, v in results[0]["values"]]
    except Exception as exc:
        logger.warning("History capacity query failed: %s", exc)

    try:
        results = await _prom_range("increase(finops_scaledown_events_total[5m])", hours)
        if results:
            sd_events = [int(ts * 1000) for ts, v in results[0]["values"] if float(v) > 0]
    except Exception as exc:
        logger.warning("Scale-down event query failed: %s", exc)

    try:
        results = await _prom_range("increase(finops_scaleup_events_total[5m])", hours)
        if results:
            su_events = [int(ts * 1000) for ts, v in results[0]["values"] if float(v) > 0]
    except Exception as exc:
        logger.warning("Scale-up event query failed: %s", exc)

    return {
        "cpu_used": cpu_used,
        "cpu_capacity": cpu_cap,
        "scaledown_events": sd_events,
        "scaleup_events": su_events,
        "hours": hours,
    }


@app.get("/api/savings")
async def api_savings():
    cfg = config_store.get()

    if cfg.demo_mode:
        from .demo_stub import _historical_events, _SEED_TOTAL_SAVED  # noqa: PLC0415
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
        from .demo_stub import _is_active  # noqa: PLC0415
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
