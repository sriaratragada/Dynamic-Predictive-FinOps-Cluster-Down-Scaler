"""Configuration routes — GET/PATCH config + natural-language parsing."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config_store
from ..auth import require_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# ── Rate limiter for NL config (LLM-backed) ──────────────────────────────────

_nl_last_call: float = 0
_NL_MIN_INTERVAL = 5.0  # seconds


@router.get("/config")
async def get_config():
    return config_store.as_dict()


@router.patch("/config")
async def patch_config(request: Request, _: None = Depends(require_token)):
    updates = await request.json()
    config_store.patch(updates)
    logger.info("Config updated: %s", list(updates.keys()))
    return config_store.as_dict()


@router.post("/config/natural-language")
async def nl_config_preview(request: Request, _: None = Depends(require_token)):
    """Parse a natural-language scaling policy into a config patch preview."""
    global _nl_last_call

    cfg = config_store.get()
    if not cfg.openai_api_key:
        raise HTTPException(
            status_code=422,
            detail="Set your OpenAI API key in Settings before using natural-language configuration.",
        )

    now = time.monotonic()
    if now - _nl_last_call < _NL_MIN_INTERVAL:
        wait = int(_NL_MIN_INTERVAL - (now - _nl_last_call)) + 1
        raise HTTPException(status_code=429, detail=f"Rate limited — try again in {wait}s")
    _nl_last_call = now

    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt is required")

    from ..nl_config import compute_diff, parse_natural_language

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


@router.post("/config/natural-language/apply")
async def nl_config_apply(request: Request, _: None = Depends(require_token)):
    """Apply a previously previewed NL config patch."""
    body = await request.json()
    patch = body.get("config")
    if not patch or not isinstance(patch, dict):
        raise HTTPException(status_code=422, detail="config object is required")

    config_store.patch(patch)
    logger.info("NL config applied: %s", list(patch.keys()))
    return config_store.as_dict()
