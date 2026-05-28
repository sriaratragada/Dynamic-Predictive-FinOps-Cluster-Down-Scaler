"""
Natural-language configuration parser.

Accepts a plain-English scaling policy description and returns
structured config fields that map to DashboardConfig.
"""
import json
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a Kubernetes FinOps configuration assistant. Parse the user's natural language scaling policy into a JSON config patch.

Available fields you can set:
- namespace_filter (string): Kubernetes namespace to target (empty = all namespaces)
- business_hours_start (string): Start of active hours in HH:MM format
- business_hours_end (string): End of active hours in HH:MM format
- business_days (string): Comma-separated day numbers (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun)
- timezone (string): IANA timezone like "America/New_York", "UTC", "Europe/London"
- prewarm_minutes (int): Minutes before active window to start warming up (default 15)
- min_replica_floor (int): Minimum replicas to keep during off-hours (0 = scale to zero)
- enable_metric_override (bool): Cross-check schedule against live Prometheus metrics
- enable_prophet (bool): Use ML forecasting instead of fixed schedule
- node_utilisation_threshold (float): 0.0-1.0, nodes below this CPU fraction are cordon-eligible

Respond with a JSON object containing exactly two keys:
- "config": an object with ONLY the fields that need to change (omit unchanged fields)
- "explanation": a brief human-readable summary of what you're changing and why

Examples:
User: "Scale down staging namespace from 8pm Friday to 7am Monday"
Response: {"config": {"namespace_filter": "staging", "business_hours_start": "07:00", "business_hours_end": "20:00", "business_days": "0,1,2,3,4"}, "explanation": "Targeting the staging namespace. Active hours set to Mon-Fri 7:00 AM to 8:00 PM, which means scale-down happens outside these hours including weekends."}

User: "Keep at least 1 replica of everything during off hours"
Response: {"config": {"min_replica_floor": 1}, "explanation": "Setting minimum replica floor to 1 so workloads are never fully scaled to zero during off-hours."}
"""


async def parse_natural_language(
    prompt: str,
    current_config: dict,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
) -> Tuple[Dict[str, Any], str]:
    """Parse natural language into a config patch.

    Returns (config_patch, explanation).
    Raises ValueError if parsing fails.
    """
    import httpx

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Current config: {json.dumps(current_config)}\n\nUser request: {prompt}"},
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        r.raise_for_status()

    content = r.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    config_patch = parsed.get("config", {})
    explanation = parsed.get("explanation", "Configuration updated.")

    from . import config_store
    known_fields = set(config_store.as_dict().keys())
    invalid = set(config_patch.keys()) - known_fields
    if invalid:
        raise ValueError(f"LLM produced unknown config fields: {invalid}")

    return config_patch, explanation


def compute_diff(current: dict, patch: dict) -> list:
    """Return a list of {field, old, new} change descriptions."""
    changes = []
    for key, new_val in patch.items():
        old_val = current.get(key)
        if old_val != new_val:
            changes.append({"field": key, "old": old_val, "new": new_val})
    return changes
