import asyncio
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import pricing
from .k8s_client import K8sReader
from .savings_tracker import SavingsTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="FinOps Dashboard API", docs_url="/api/docs", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)

_PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
_k8s: Optional[K8sReader] = None
_tracker: Optional[SavingsTracker] = None


@app.on_event("startup")
async def _startup():
    global _k8s, _tracker

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
# Prometheus helpers
# ------------------------------------------------------------------

async def _prom_instant(query: str) -> list:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{_PROMETHEUS}/api/v1/query", params={"query": query})
        r.raise_for_status()
        data = r.json()
        if data["status"] != "success":
            raise ValueError(data.get("error", "Prometheus error"))
        return data["data"]["result"]


async def _prom_range(query: str, hours: int) -> list:
    end = int(datetime.now(tz=timezone.utc).timestamp())
    start = end - hours * 3600
    step = max(300, (hours * 3600) // 200)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{_PROMETHEUS}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
        )
        r.raise_for_status()
        data = r.json()
        if data["status"] != "success":
            raise ValueError(data.get("error", "Prometheus range error"))
        return data["data"]["result"]


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
