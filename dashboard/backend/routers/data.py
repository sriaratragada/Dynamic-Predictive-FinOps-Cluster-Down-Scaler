"""Data routes — status, capacity, history, savings, events, CSV export."""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import config_store, pricing, deps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/status")
async def api_status():
    k8s = deps._k8s
    if not k8s:
        return {"scaled_down": False, "cordoned_nodes": [], "deployments_scaled": [],
                "cordoned_node_count": 0, "deployment_count": 0}
    state = k8s.read_state()
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


@router.get("/capacity")
async def api_capacity():
    k8s = deps._k8s
    nodes = k8s.list_nodes() if k8s else []
    cordoned = k8s.read_state().get("cordoned_nodes", []) if k8s else []

    cpu_map: dict = {}
    try:
        results = await deps.prom_query(
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


@router.get("/history")
async def api_history(hours: int = 24):
    """Return CPU usage, capacity, and scale-event markers over the last *hours*."""
    out: dict[str, Any] = {"hours": hours}
    for key, promql, kind in _HISTORY_QUERIES:
        try:
            results = await deps.prom_query(promql, range_hours=hours)
        except Exception as exc:
            logger.warning("History query %s failed: %s", key, exc)
            out[key] = []
            continue
        values = results[0]["values"] if results else []
        if kind == "value":
            out[key] = [
                {"t": int(ts * 1000), "v": round(float(v), 3)} for ts, v in values
            ]
        else:
            out[key] = [int(ts * 1000) for ts, v in values if float(v) > 0]
    return out


@router.get("/events")
async def api_events():
    """Audit log of cordon/savings events (most recent first)."""
    cfg = config_store.get()
    if cfg.demo_mode:
        from ..demo_stub import _historical_events
        events = _historical_events()
        return {"events": list(reversed(events))}

    if deps._tracker is None:
        return {"events": []}

    return {"events": list(reversed(deps._tracker.list_events()))}


@router.get("/savings")
async def api_savings():
    cfg = config_store.get()

    if cfg.demo_mode:
        from ..demo_stub import _historical_events, _SEED_TOTAL_SAVED, _is_active
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
    if deps._tracker:
        summary = deps._tracker.get_summary()

    return {
        **summary,
        "cloud_provider": info["provider"],
        "instance_type": info["instance_type"],
        "region": info["region"],
    }


@router.get("/savings/export")
async def api_savings_export():
    """Export savings events as a CSV file for finance teams."""
    cfg = config_store.get()

    if cfg.demo_mode:
        from ..demo_stub import _historical_events
        events = _historical_events()
    elif deps._tracker:
        events = deps._tracker.list_events()
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
        headers={"Content-Disposition": f"attachment; filename=finops-savings-{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}.csv"},
    )
