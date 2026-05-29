"""
Shared schedule evaluation — single source of truth for idle detection.

Both the embedded ControllerRunner (web-service mode) and the full
in-cluster controller delegate to these functions for schedule-based
decisions.  New schedule logic only needs to change here.
"""

import zoneinfo
from datetime import datetime, timezone


def is_outside_business_hours(cfg: dict, now: datetime | None = None) -> bool:
    """Return True when the schedule says the cluster should be idle."""
    if now is None:
        now = datetime.now(tz=timezone.utc)

    tz = zoneinfo.ZoneInfo(cfg.get("timezone", "UTC"))
    local = now.astimezone(tz)

    days = [int(d) for d in cfg.get("business_days", "0,1,2,3,4").split(",") if d.strip()]
    if local.weekday() not in days:
        return True

    sh, sm = _hm(cfg.get("business_hours_start", "07:00"))
    eh, em = _hm(cfg.get("business_hours_end", "19:00"))
    prewarm = int(cfg.get("prewarm_minutes", 15))
    cur_m = local.hour * 60 + local.minute
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    return cur_m < (start_m - prewarm) or cur_m >= end_m


def resolve_override(cfg: dict, now: datetime | None = None) -> str:
    """Evaluate manual override state.

    Returns ``'awake'``, ``'sleep'``, or ``''`` (no active override).
    An expired override returns ``''``.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    override_mode = cfg.get("override_mode", "")
    if not override_mode:
        return ""

    override_until = cfg.get("override_until", "")
    if not override_until:
        return override_mode

    try:
        expiry = datetime.fromisoformat(override_until)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if now >= expiry:
            return ""
    except (ValueError, TypeError):
        return ""

    return override_mode


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)
