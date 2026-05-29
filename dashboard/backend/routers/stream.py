"""SSE (Server-Sent Events) endpoint for real-time dashboard updates.

Replaces per-field polling with a single persistent connection that
pushes lightweight status, savings, and controller data every tick.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from .. import config_store, deps, pricing
from ..controller_runner import get_runner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


async def _build_status() -> dict:
    k8s = deps._k8s
    if not k8s:
        return {
            "scaled_down": False,
            "cordoned_nodes": [],
            "deployments_scaled": [],
            "cordoned_node_count": 0,
            "deployment_count": 0,
        }
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


async def _build_savings_summary() -> dict:
    cfg = config_store.get()
    if cfg.demo_mode:
        from ..demo_stub import _historical_events, _SEED_TOTAL_SAVED, _is_active
        now = datetime.now(tz=timezone.utc)
        events = _historical_events()
        month_ago = now.timestamp() - 30 * 86400
        month_usd = sum(
            e["saved_usd"] for e in events
            if e.get("end") and datetime.fromisoformat(e["end"]).timestamp() >= month_ago
        )
        cordoned = 0 if _is_active(now) else 2
        return {
            "total_saved_usd": round(_SEED_TOTAL_SAVED + month_usd, 2),
            "this_month_usd": round(month_usd, 2),
            "currently_cordoned_count": cordoned,
        }

    if deps._tracker:
        s = deps._tracker.get_summary()
        return {
            "total_saved_usd": s.get("total_saved_usd", 0.0),
            "this_month_usd": s.get("this_month_usd", 0.0),
            "currently_cordoned_count": s.get("currently_cordoned_count", 0),
        }
    return {"total_saved_usd": 0.0, "this_month_usd": 0.0, "currently_cordoned_count": 0}


@router.get("/stream")
async def api_stream(request: Request):
    """SSE endpoint — pushes status + savings + controller data each tick."""

    async def generate():
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = {
                    "status": await _build_status(),
                    "savings": await _build_savings_summary(),
                    "controller": get_runner().status().as_dict(),
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            except Exception:
                logger.debug("SSE tick error", exc_info=True)
                yield f"data: {json.dumps({'error': True})}\n\n"

            interval = max(5, config_store.get().poll_interval_seconds)
            await asyncio.sleep(interval)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
