"""
Bearer-token authentication for mutating dashboard API routes.

Configuration
-------------
Set the ``API_TOKEN`` environment variable to a secret string.
Leave it empty (the default) to run without authentication — suitable for
local dev and demo mode where the dashboard is not publicly reachable.

Protected routes
----------------
  PATCH /api/config    — changes live configuration
  POST  /api/prewarm   — triggers Knative pre-warm (external network call)

Read-only routes (GET /api/*) remain open so dashboards and status monitors
can poll without credentials.

Usage
-----
The token is read from the environment on *every request*, not at import time.
This lets integration tests and ``monkeypatch.setenv`` work without reloading
the module.
"""

import os
import logging

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


async def require_token(authorization: str = Header(default="")) -> None:
    """
    FastAPI dependency — raises 401/403 if API_TOKEN is configured and the
    request does not supply a matching ``Authorization: Bearer <token>`` header.

    When ``API_TOKEN`` is empty or unset, the check is skipped entirely.
    """
    token = os.environ.get("API_TOKEN", "").strip()
    if not token:
        return  # auth disabled — no token configured

    if not authorization.startswith("Bearer "):
        logger.warning("Rejected mutating request — no Bearer token supplied")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if authorization[7:] != token:
        logger.warning("Rejected mutating request — invalid token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )
