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

    def per_node_gpu_usage(self) -> Dict[str, float]:
        """
        Returns {node_name: gpu_utilisation_fraction (0.0–1.0)} from DCGM exporter.

        Requires nvidia/dcgm-exporter deployed in the cluster and scraping by
        Prometheus.  DCGM_FI_DEV_GPU_UTIL is a 0–100 gauge (percent); we average
        across all GPUs on each node and normalise to 0.0–1.0.

        Label precedence: ``kubernetes_node`` (dcgm-exporter default) then ``node``.
        """
        results = self.query(
            "avg by (kubernetes_node) (DCGM_FI_DEV_GPU_UTIL / 100)"
        )
        return {
            r["metric"].get("kubernetes_node", r["metric"].get("node", "unknown")): float(r["value"][1])
            for r in results
        }

    def query_range(self, promql: str, start: float, end: float, step: int = 300) -> list:
        """Range query returning [[timestamp, value_str], ...] for use with Prophet."""
        resp = requests.get(
            f"{self._base}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            raise RuntimeError(f"Prometheus range query failed: {data.get('error')}")
        results = data["data"]["result"]
        return results[0]["values"] if results else []
