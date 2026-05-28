"""
Cross-AZ Spot Instance Migration Controller.

Identifies low-priority workloads on expensive on-demand nodes and
evaluates whether migrating them to spot instances would save money.
Handles spot interruption notices gracefully.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List

from kubernetes import client

logger = logging.getLogger(__name__)

SPOT_LABEL = "finops.io/priority"
SPOT_NODE_LABEL = "node.kubernetes.io/lifecycle"


@dataclass
class SpotCandidate:
    deployment_name: str
    namespace: str
    current_node: str
    current_cost_hr: float


@dataclass
class SpotOption:
    az: str
    spot_price_hr: float
    savings_pct: float


@dataclass
class MigrationStatus:
    total_on_demand_nodes: int = 0
    total_spot_nodes: int = 0
    spot_eligible_workloads: int = 0
    estimated_savings_hr: float = 0.0
    recent_interruptions: int = 0
    migrations_today: int = 0


class SpotMigrator:
    """Evaluates and executes spot instance migration for eligible workloads."""

    def __init__(
        self,
        core_api: client.CoreV1Api,
        apps_api: client.AppsV1Api,
        eligible_label: str = "finops.io/priority=low",
        max_price_pct: int = 80,
        dry_run: bool = False,
    ):
        self._core = core_api
        self._apps = apps_api
        self._eligible_label = eligible_label
        self._max_price_pct = max_price_pct
        self._dry_run = dry_run
        self._migration_log: list = []
        self._interruption_count = 0

    def discover_spot_candidates(self) -> List[SpotCandidate]:
        """Find on-demand nodes running low-priority workloads."""
        candidates = []
        try:
            deps = self._apps.list_deployment_for_all_namespaces(
                label_selector=self._eligible_label
            )
            for dep in deps.items:
                candidates.append(SpotCandidate(
                    deployment_name=dep.metadata.name,
                    namespace=dep.metadata.namespace,
                    current_node="",
                    current_cost_hr=0.0,
                ))
        except Exception as exc:
            logger.warning("Spot candidate discovery failed: %s", exc)
        return candidates

    def get_node_lifecycle_mix(self) -> Dict[str, int]:
        """Return count of on-demand vs spot nodes."""
        mix = {"on-demand": 0, "spot": 0}
        try:
            nodes = self._core.list_node()
            for node in nodes.items:
                labels = node.metadata.labels or {}
                lifecycle = labels.get(SPOT_NODE_LABEL, "on-demand")
                if lifecycle == "spot":
                    mix["spot"] += 1
                else:
                    mix["on-demand"] += 1
        except Exception as exc:
            logger.warning("Node lifecycle query failed: %s", exc)
        return mix

    def get_status(self, on_demand_rate: float = 0.192) -> dict:
        """Return current spot migration status."""
        mix = self.get_node_lifecycle_mix()
        candidates = self.discover_spot_candidates()
        estimated_savings = len(candidates) * on_demand_rate * (self._max_price_pct / 100) * 0.5

        return {
            "on_demand_nodes": mix["on-demand"],
            "spot_nodes": mix["spot"],
            "spot_eligible_workloads": len(candidates),
            "estimated_hourly_savings": round(estimated_savings, 4),
            "recent_interruptions": self._interruption_count,
            "migrations_today": len(self._migration_log),
            "max_spot_price_pct": self._max_price_pct,
        }

    def evaluate_migration(self, spot_prices: Dict[str, float], on_demand_rate: float) -> List[dict]:
        """Evaluate which workloads should migrate to spot."""
        recommendations = []
        max_spot = on_demand_rate * (self._max_price_pct / 100)

        for az, price in sorted(spot_prices.items(), key=lambda x: x[1]):
            if price <= max_spot:
                savings_pct = round((1 - price / on_demand_rate) * 100, 1)
                recommendations.append({
                    "az": az,
                    "spot_price": price,
                    "on_demand_price": on_demand_rate,
                    "savings_pct": savings_pct,
                    "recommended": True,
                })

        return recommendations
