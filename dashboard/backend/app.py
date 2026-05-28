import asyncio
import csv
import io
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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
    if not service_url or service_url == "default":
        service_url = cfg.prewarm_service_url.strip()
    if not service_url:
        return {
            "enabled": True,
            "action": "none",
            "status": "not_configured",
            "message": "Set a Knative service URL in Features > Pre-Warm to activate.",
        }

    signal = str(body.get("signal", "unknown"))
    user_id = body.get("user_id")

    controller = _get_prewarm()
    return await controller.handle_signal(service_url, signal, user_id)


@app.post("/api/prewarm/signal")
async def api_prewarm_signal_public(request: Request):
    """Public endpoint for embedded pre-warm signals (no auth required)."""
    cfg = config_store.get()
    if not cfg.enable_prewarm:
        return {"enabled": False, "action": "none"}
    body = await request.json()
    service_url = (body.get("service_url") or cfg.prewarm_service_url or "").strip()
    if not service_url:
        return {"enabled": True, "action": "none", "status": "not_configured"}
    signal = str(body.get("signal", "unknown"))
    user_id = body.get("user_id")
    controller = _get_prewarm()
    return await controller.handle_signal(service_url, signal, user_id)


@app.get("/api/prewarm/snippet")
async def api_prewarm_snippet():
    """Return a ready-to-paste JS snippet for embedding pre-warm signals."""
    cfg = config_store.get()
    dashboard_url = "http://localhost:8090"
    snippet = f"""<script>
(function() {{
  var DASHBOARD = '{dashboard_url}';
  var SERVICE  = '{cfg.prewarm_service_url}';
  var last = 0;
  function fire(signal) {{
    if (Date.now() - last < 500) return;
    last = Date.now();
    navigator.sendBeacon(DASHBOARD + '/api/prewarm/signal', JSON.stringify({{
      service_url: SERVICE, signal: signal, user_id: 'web'
    }}));
  }}
  document.addEventListener('mouseover', function(e) {{
    if (e.target.closest('button,a,input,[role=button]')) fire('hover');
  }}, {{passive:true}});
  document.addEventListener('focusin', function(e) {{
    if (e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') fire('input_focus');
  }}, {{passive:true}});
}})();
</script>""".strip()
    return {"snippet": snippet, "service_url": cfg.prewarm_service_url}


@app.get("/api/prewarm/history")
async def api_prewarm_history():
    """Return the last 50 pre-warm signal events with timestamps and outcomes."""
    controller = _get_prewarm()
    return {"history": controller.get_history()}


# ------------------------------------------------------------------
# Prophet Shadow Log
# ------------------------------------------------------------------

_shadow_log: list = []


def _generate_demo_shadow_log() -> list:
    """Generate 20 synthetic shadow log entries for demo mode."""
    import random
    entries = []
    base = datetime.now(tz=timezone.utc) - timedelta(hours=10)
    for i in range(20):
        ts = base + timedelta(minutes=i * 30)
        yhat = round(random.uniform(0.1, 1.8), 3)
        prophet_idle = yhat < 0.5
        schedule_idle = i % 3 != 0
        entries.append({
            "timestamp": ts.isoformat(),
            "prophet_says_idle": prophet_idle,
            "schedule_says_idle": schedule_idle,
            "agreement": prophet_idle == schedule_idle,
            "predicted_yhat": yhat,
        })
    return entries


@app.post("/api/prophet/shadow-log")
async def api_post_shadow_log(request: Request, _: None = Depends(require_token)):
    """Receive shadow log entries from the controller."""
    body = await request.json()
    entries = body if isinstance(body, list) else [body]
    for entry in entries:
        _shadow_log.append(entry)
    if len(_shadow_log) > 200:
        del _shadow_log[:-200]
    return {"accepted": len(entries)}


@app.get("/api/prophet/shadow-log")
async def api_get_shadow_log():
    """Return Prophet shadow log entries. In demo mode, returns synthetic data."""
    cfg = config_store.get()
    if cfg.demo_mode and not _shadow_log:
        return {"entries": _generate_demo_shadow_log()}
    return {"entries": _shadow_log[-200:]}


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


@app.get("/api/savings/export")
async def api_savings_export():
    """Export savings events as a CSV file for finance teams."""
    cfg = config_store.get()

    if cfg.demo_mode:
        from .demo_stub import _historical_events
        events = _historical_events()
    elif _tracker:
        events = _tracker.list_events()
    else:
        events = []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Node", "Start (UTC)", "End (UTC)", "Duration (hours)", "Rate ($/hr)", "Saved ($)"])
    for e in events:
        writer.writerow([
            e.get("node", ""),
            e.get("start", ""),
            e.get("end", ""),
            round(e.get("hours", 0), 2),
            round(e.get("rate_usd_hr", 0), 4),
            round(e.get("saved_usd", 0), 4),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=finops-savings-{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}.csv"}
    )


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


@app.post("/api/controller/wake")
async def api_controller_wake(_: None = Depends(require_token)):
    """Immediately scale up the cluster regardless of schedule."""
    runner = _get_runner()
    status = runner.status()
    if not status.connected:
        raise HTTPException(status_code=409, detail="No cluster connected")
    try:
        await asyncio.to_thread(runner.force_wake)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return runner.status().as_dict()


@app.post("/api/controller/sleep")
async def api_controller_sleep(_: None = Depends(require_token)):
    """Immediately scale down the cluster regardless of schedule."""
    runner = _get_runner()
    status = runner.status()
    if not status.connected:
        raise HTTPException(status_code=409, detail="No cluster connected")
    try:
        await asyncio.to_thread(runner.force_sleep)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return runner.status().as_dict()


@app.get("/api/controller/dry-run-log")
async def api_dry_run_log():
    from .controller_runner import _dry_run_log
    return {"entries": _dry_run_log[-50:]}


# ------------------------------------------------------------------
# Natural-language configuration
# ------------------------------------------------------------------

@app.post("/api/config/natural-language")
async def api_nl_config_preview(request: Request, _: None = Depends(require_token)):
    """Parse a natural-language scaling policy into a config patch preview."""
    cfg = config_store.get()
    if not cfg.openai_api_key:
        raise HTTPException(
            status_code=422,
            detail="Set your OpenAI API key in Settings before using natural-language configuration.",
        )

    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt is required")

    from .nl_config import parse_natural_language, compute_diff  # noqa: PLC0415

    current = config_store.as_dict()
    try:
        patch, explanation = await parse_natural_language(
            prompt, current, cfg.openai_api_key, cfg.openai_base_url,
        )
    except Exception as exc:
        logger.warning("NL config parse failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM parsing failed: {exc}") from exc

    diff = compute_diff(current, patch)
    return {"config": patch, "explanation": explanation, "diff": diff}


@app.post("/api/config/natural-language/apply")
async def api_nl_config_apply(request: Request, _: None = Depends(require_token)):
    """Apply a previously previewed NL config patch."""
    body = await request.json()
    patch = body.get("config")
    if not patch or not isinstance(patch, dict):
        raise HTTPException(status_code=422, detail="config object is required")

    config_store.patch(patch)
    logger.info("NL config applied: %s", list(patch.keys()))
    return config_store.as_dict()


# ------------------------------------------------------------------
# HPA predictions
# ------------------------------------------------------------------

@app.get("/api/hpa/predictions")
async def api_hpa_predictions():
    """Return HPA spike predictions from Prophet forecasting."""
    cfg = config_store.get()

    if cfg.demo_mode:
        import random
        from datetime import timedelta
        now = datetime.now(tz=timezone.utc)
        has_spike = random.random() > 0.4
        if has_spike:
            mins_away = random.randint(5, 30)
            current_cpu = round(random.uniform(0.3, 0.8), 3)
            peak_cpu = round(current_cpu * random.uniform(1.8, 3.5), 3)
            return {
                "enabled": cfg.enable_hpa_synergy,
                "spike_predicted": True,
                "prediction": {
                    "expected_at": (now + timedelta(minutes=mins_away)).isoformat(),
                    "current_cpu": current_cpu,
                    "predicted_peak_cpu": peak_cpu,
                    "minutes_away": mins_away,
                },
                "headroom_pct": cfg.hpa_spike_headroom_pct,
                "lookahead_minutes": cfg.hpa_spike_lookahead_minutes,
            }
        return {
            "enabled": cfg.enable_hpa_synergy,
            "spike_predicted": False,
            "prediction": None,
            "headroom_pct": cfg.hpa_spike_headroom_pct,
            "lookahead_minutes": cfg.hpa_spike_lookahead_minutes,
        }

    return {
        "enabled": cfg.enable_hpa_synergy,
        "spike_predicted": False,
        "prediction": None,
        "headroom_pct": cfg.hpa_spike_headroom_pct,
        "lookahead_minutes": cfg.hpa_spike_lookahead_minutes,
    }


# ------------------------------------------------------------------
# CRD Policies
# ------------------------------------------------------------------

@app.get("/api/policies")
async def api_policies():
    """Return DownscalePolicy CRDs. In demo mode returns synthetic examples."""
    cfg = config_store.get()
    if cfg.demo_mode:
        return {"policies": [
            {
                "name": "off-hours-staging",
                "namespace": "staging",
                "enabled": True,
                "schedule": {
                    "businessHoursStart": "08:00",
                    "businessHoursEnd": "18:00",
                    "businessDays": "0,1,2,3,4",
                    "timezone": "America/New_York",
                },
                "targetNamespaces": ["staging", "qa"],
                "excludeDeployments": ["monitoring-agent"],
                "minReplicaFloor": 1,
                "prewarmMinutes": 10,
            },
            {
                "name": "weekend-shutdown",
                "namespace": "default",
                "enabled": True,
                "schedule": {
                    "businessHoursStart": "09:00",
                    "businessHoursEnd": "17:00",
                    "businessDays": "0,1,2,3,4",
                    "timezone": "UTC",
                },
                "targetNamespaces": ["default"],
                "excludeDeployments": [],
                "minReplicaFloor": 0,
                "prewarmMinutes": 15,
            },
        ]}

    try:
        from kubernetes import client as k8s_client, config as k8s_config  # noqa: PLC0415
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        custom_api = k8s_client.CustomObjectsApi()
        result = custom_api.list_cluster_custom_object(
            "finops.io", "v1alpha1", "downscalepolicies"
        )
        policies = []
        for item in result.get("items", []):
            meta = item.get("metadata", {})
            spec = item.get("spec", {})
            schedule = spec.get("schedule", {})
            policies.append({
                "name": meta.get("name", ""),
                "namespace": meta.get("namespace", ""),
                "enabled": spec.get("enabled", True),
                "schedule": {
                    "businessHoursStart": schedule.get("businessHoursStart", "07:00"),
                    "businessHoursEnd": schedule.get("businessHoursEnd", "19:00"),
                    "businessDays": schedule.get("businessDays", "0,1,2,3,4"),
                    "timezone": schedule.get("timezone", "UTC"),
                },
                "targetNamespaces": spec.get("targetNamespaces", []),
                "excludeDeployments": spec.get("excludeDeployments", []),
                "minReplicaFloor": spec.get("minReplicaFloor", 0),
                "prewarmMinutes": spec.get("prewarmMinutes", 15),
            })
        return {"policies": policies}
    except Exception as exc:
        logger.warning("CRD policy list failed (CRD may not be installed): %s", exc)
        return {"policies": []}


# ------------------------------------------------------------------
# Spot Migration Status
# ------------------------------------------------------------------

@app.get("/api/spot/status")
async def api_spot_status():
    """Return spot migration status. In demo mode returns synthetic data."""
    cfg = config_store.get()
    if cfg.demo_mode:
        return {
            "on_demand_nodes": 4,
            "spot_nodes": 1,
            "spot_eligible_workloads": 3,
            "estimated_hourly_savings": 0.0576,
            "recent_interruptions": 0,
            "migrations_today": 1,
            "max_spot_price_pct": cfg.spot_max_price_pct,
        }

    try:
        from kubernetes import client as k8s_client, config as k8s_config  # noqa: PLC0415
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        core = k8s_client.CoreV1Api()
        apps = k8s_client.AppsV1Api()

        from controller.spot_migrator import SpotMigrator  # noqa: PLC0415
        migrator = SpotMigrator(
            core, apps,
            eligible_label=cfg.spot_eligible_label,
            max_price_pct=cfg.spot_max_price_pct,
        )
        return migrator.get_status(on_demand_rate=cfg.node_hourly_cost)
    except Exception as exc:
        logger.warning("Spot status query failed: %s", exc)
        return {
            "on_demand_nodes": 0,
            "spot_nodes": 0,
            "spot_eligible_workloads": 0,
            "estimated_hourly_savings": 0.0,
            "recent_interruptions": 0,
            "migrations_today": 0,
            "max_spot_price_pct": cfg.spot_max_price_pct,
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
