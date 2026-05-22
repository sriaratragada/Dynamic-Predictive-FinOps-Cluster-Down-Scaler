import logging
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


class PrometheusClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def query(self, promql: str) -> list:
        resp = requests.get(
            f"{self._base}/api/v1/query",
            params={"query": promql},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            raise RuntimeError(f"Prometheus query failed: {data.get('error')}")
        return data["data"]["result"]

    def scalar(self, promql: str) -> Optional[float]:
        results = self.query(promql)
        if not results:
            return None
        return float(results[0]["value"][1])

    def per_node_cpu_usage(self) -> Dict[str, float]:
        """Returns {node_name: cpu_cores_used} computed from a 5-minute rate."""
        results = self.query(
            'sum by (node) (rate(container_cpu_usage_seconds_total{container!=""}[5m]))'
        )
        return {
            r["metric"].get("node", "unknown"): float(r["value"][1])
            for r in results
        }

    def cluster_cpu_baseline(self) -> Optional[float]:
        """7-day rolling average of total cluster CPU usage rate in cores."""
        return self.scalar(
            'avg_over_time('
            '  sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))'
            '[7d:5m])'
        )
