"""
Shared mutable state and helpers for route handlers.

Holds the K8s reader and savings tracker singletons that are set during
the FastAPI lifespan, plus the Prometheus query helper and shadow log
used across multiple routers.
"""

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from . import config_store

logger = logging.getLogger(__name__)

# ── Mutable singletons — set by app.py lifespan ──────────────────────────────

_k8s: Any = None
_tracker: Any = None

# ── Shadow log (capped) ──────────────────────────────────────────────────────

shadow_log: deque = deque(maxlen=200)

# ── Prometheus query helper ──────────────────────────────────────────────────


async def prom_query(
    query: str,
    range_hours: Optional[int] = None,
) -> list:
    """Unified Prometheus instant / range query with demo-mode support."""
    cfg = config_store.get()

    if range_hours is None:
        if cfg.demo_mode:
            from .demo_stub import demo_prom_instant
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
        from .demo_stub import demo_prom_range
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


# ── Request helpers ──────────────────────────────────────────────────────────


def require_fields(body: dict, *fields: str) -> dict:
    """Validate required JSON body fields; raises HTTPException(422)."""
    from fastapi import HTTPException

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
