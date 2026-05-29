"""Controller management routes — status, start/stop, wake/sleep, dry-run log."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_token
from ..controller_runner import get_runner, get_dry_run_log

router = APIRouter(prefix="/api")


@router.get("/controller")
async def api_controller_status():
    """Return the embedded controller's current status."""
    return get_runner().status().as_dict()


@router.post("/controller/stop")
async def api_controller_stop(_: None = Depends(require_token)):
    """Stop the embedded controller loop."""
    runner = get_runner()
    await asyncio.to_thread(runner.stop)
    return runner.status().as_dict()


@router.post("/controller/wake")
async def api_controller_wake(_: None = Depends(require_token)):
    """Immediately scale up the cluster regardless of schedule."""
    runner = get_runner()
    if not runner.status().connected:
        raise HTTPException(status_code=409, detail="No cluster connected")
    try:
        await asyncio.to_thread(runner.force_wake)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return runner.status().as_dict()


@router.post("/controller/sleep")
async def api_controller_sleep(_: None = Depends(require_token)):
    """Immediately scale down the cluster regardless of schedule."""
    runner = get_runner()
    if not runner.status().connected:
        raise HTTPException(status_code=409, detail="No cluster connected")
    try:
        await asyncio.to_thread(runner.force_sleep)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return runner.status().as_dict()


@router.get("/controller/dry-run-log")
async def api_dry_run_log():
    return {"entries": list(get_dry_run_log())[-50:]}
