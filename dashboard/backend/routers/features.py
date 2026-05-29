"""Feature routes — prewarm, shadow log, HPA predictions, policies, spot status."""

import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config_store, deps
from ..auth import require_token
from ..prewarm import get_controller as _get_prewarm

# ── Public prewarm signal rate limiter ───────────────────────────────────────
# Tracks request timestamps per IP; allows 10 signals per 10s window.

_SIGNAL_WINDOW = 10.0        # seconds
_SIGNAL_MAX    = 10          # max requests per window per IP
_signal_hits: dict = defaultdict(list)


def _check_signal_rate(request: Request) -> None:
    if not request.client:
        return  # test transport / trusted proxy — skip rate check
    ip = request.client.host
    now = time.monotonic()
    _signal_hits[ip] = [t for t in _signal_hits[ip] if now - t < _SIGNAL_WINDOW]
    if len(_signal_hits[ip]) >= _SIGNAL_MAX:
        raise HTTPException(status_code=429, detail="Too many pre-warm signals from this client")
    _signal_hits[ip].append(now)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ── Pre-warm ──────────────────────────────────────────────────────────────────


@router.post("/prewarm")
async def api_prewarm(request: Request, _: None = Depends(require_token)):
    """Handle early-intent signal to pre-warm a Knative AI container."""
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


@router.post("/prewarm/signal")
async def api_prewarm_signal_public(request: Request):
    """Public endpoint for embedded pre-warm signals (no auth required, rate-limited)."""
    _check_signal_rate(request)
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


@router.get("/prewarm/snippet")
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


@router.get("/prewarm/history")
async def api_prewarm_history():
    """Return the last 50 pre-warm signal events."""
    controller = _get_prewarm()
    return {"history": controller.get_history()}


# ── Shadow log ────────────────────────────────────────────────────────────────


def _generate_demo_shadow_log() -> list:
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


@router.post("/prophet/shadow-log")
async def api_post_shadow_log(request: Request, _: None = Depends(require_token)):
    """Receive shadow log entries from the controller."""
    body = await request.json()
    entries = body if isinstance(body, list) else [body]
    for entry in entries:
        deps.shadow_log.append(entry)
    return {"accepted": len(entries)}


@router.get("/prophet/shadow-log")
async def api_get_shadow_log():
    """Return Prophet shadow log entries. In demo mode, returns synthetic data."""
    cfg = config_store.get()
    if cfg.demo_mode and not deps.shadow_log:
        return {"entries": _generate_demo_shadow_log()}
    return {"entries": list(deps.shadow_log)[-200:]}


# ── HPA predictions ───────────────────────────────────────────────────────────


@router.get("/hpa/predictions")
async def api_hpa_predictions():
    cfg = config_store.get()

    if cfg.demo_mode:
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


# ── CRD Policies ─────────────────────────────────────────────────────────────


@router.get("/policies")
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
        from kubernetes import client as k8s_client, config as k8s_config
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


# ── Spot Migration ────────────────────────────────────────────────────────────


@router.get("/spot/status")
async def api_spot_status():
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
        from kubernetes import client as k8s_client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        core = k8s_client.CoreV1Api()
        apps = k8s_client.AppsV1Api()

        from controller.spot_migrator import SpotMigrator
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
