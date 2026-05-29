"""
FinOps Dashboard API — FastAPI application entry point.

All route handlers live in the ``routers/`` package.  This module is
responsible only for app creation, CORS, lifespan (K8s + tracker init),
router inclusion, and SPA static file serving.
"""

import asyncio
import logging
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import deps, pricing
from .k8s_client import K8sReader
from .savings_tracker import SavingsTracker

from .routers import health, config, connect, controller, data, features, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_STARTUP_DEMO = os.environ.get("DEMO_MODE", "false").lower() == "true"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise K8s reader and savings tracker on startup."""
    if _STARTUP_DEMO:
        from .demo_stub import DemoK8sReader
        deps._k8s = DemoK8sReader()
        logger.info("DEMO MODE active — using synthetic data (no K8s or Prometheus needed)")
    else:
        try:
            deps._k8s = K8sReader()
            logger.info("Kubernetes client initialised")
        except Exception as exc:
            logger.warning("K8s unavailable (no cluster?): %s", exc)

        try:
            pricing.get_hourly_rate()
        except Exception as exc:
            logger.warning("Pricing init failed: %s", exc)

        if deps._k8s:
            deps._tracker = SavingsTracker(deps._k8s, pricing.get_hourly_rate)
            asyncio.create_task(deps._tracker.start())

    yield

    if deps._tracker is not None:
        deps._tracker.stop()


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

# ── Include all routers ──────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(config.router)
app.include_router(connect.router)
app.include_router(controller.router)
app.include_router(data.router)
app.include_router(features.router)
app.include_router(stream.router)

# ── Serve React frontend (must be last) ──────────────────────────────────────

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
