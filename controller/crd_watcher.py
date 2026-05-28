"""
CRD Watcher for DownscalePolicy custom resources.

Watches for DownscalePolicy CRDs and maintains an in-memory registry
of active policies. Each policy defines a schedule and targeting rules
that can override the global config for specific namespaces/deployments.
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from kubernetes import client, watch

logger = logging.getLogger(__name__)

CRD_GROUP = "finops.io"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "downscalepolicies"


@dataclass
class DownscalePolicy:
    name: str
    namespace: str
    enabled: bool = True
    business_hours_start: str = "07:00"
    business_hours_end: str = "19:00"
    business_days: str = "0,1,2,3,4"
    timezone: str = "UTC"
    target_namespaces: List[str] = field(default_factory=list)
    target_labels: Dict[str, str] = field(default_factory=dict)
    exclude_deployments: List[str] = field(default_factory=list)
    min_replica_floor: int = 0
    prewarm_minutes: int = 15

    @classmethod
    def from_crd(cls, obj: dict) -> "DownscalePolicy":
        meta = obj.get("metadata", {})
        spec = obj.get("spec", {})
        schedule = spec.get("schedule", {})
        return cls(
            name=meta.get("name", ""),
            namespace=meta.get("namespace", ""),
            enabled=spec.get("enabled", True),
            business_hours_start=schedule.get("businessHoursStart", "07:00"),
            business_hours_end=schedule.get("businessHoursEnd", "19:00"),
            business_days=schedule.get("businessDays", "0,1,2,3,4"),
            timezone=schedule.get("timezone", "UTC"),
            target_namespaces=spec.get("targetNamespaces", []),
            target_labels=spec.get("targetLabels", {}),
            exclude_deployments=spec.get("excludeDeployments", []),
            min_replica_floor=spec.get("minReplicaFloor", 0),
            prewarm_minutes=spec.get("prewarmMinutes", 15),
        )

    def matches_deployment(self, namespace: str, name: str, labels: dict) -> bool:
        if not self.enabled:
            return False
        if self.target_namespaces and namespace not in self.target_namespaces:
            return False
        if name in self.exclude_deployments:
            return False
        if self.target_labels:
            for k, v in self.target_labels.items():
                if labels.get(k) != v:
                    return False
        return True

    def get_business_days(self) -> List[int]:
        return [int(d.strip()) for d in self.business_days.split(",") if d.strip()]


class CRDWatcher:
    """Watches DownscalePolicy CRDs and maintains a registry."""

    def __init__(self, custom_api: client.CustomObjectsApi = None):
        self._api = custom_api
        self._policies: Dict[str, DownscalePolicy] = {}
        self._lock = threading.Lock()
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if self._api is None:
            logger.info("CRD watcher: no CustomObjectsApi provided, skipping")
            return
        self._initial_list()
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("CRD watcher started — monitoring DownscalePolicy resources")

    def stop(self):
        self._stop_event.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=5)

    def _initial_list(self):
        try:
            result = self._api.list_cluster_custom_object(
                CRD_GROUP, CRD_VERSION, CRD_PLURAL
            )
            with self._lock:
                self._policies.clear()
                for item in result.get("items", []):
                    policy = DownscalePolicy.from_crd(item)
                    key = f"{policy.namespace}/{policy.name}"
                    self._policies[key] = policy
            logger.info("CRD watcher: loaded %d existing policies", len(self._policies))
        except Exception as exc:
            logger.warning("CRD watcher: initial list failed (CRD may not be installed): %s", exc)

    def _watch_loop(self):
        w = watch.Watch()
        while not self._stop_event.is_set():
            try:
                for event in w.stream(
                    self._api.list_cluster_custom_object,
                    CRD_GROUP, CRD_VERSION, CRD_PLURAL,
                    timeout_seconds=300,
                ):
                    if self._stop_event.is_set():
                        break
                    self._handle_event(event)
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning("CRD watcher: stream error, will retry: %s", exc)
                    import time as _time
                    _time.sleep(5)

    def _handle_event(self, event: dict):
        event_type = event.get("type", "")
        obj = event.get("object", {})
        policy = DownscalePolicy.from_crd(obj)
        key = f"{policy.namespace}/{policy.name}"

        with self._lock:
            if event_type in ("ADDED", "MODIFIED"):
                self._policies[key] = policy
                logger.info("CRD watcher: %s policy %s", event_type.lower(), key)
            elif event_type == "DELETED":
                self._policies.pop(key, None)
                logger.info("CRD watcher: deleted policy %s", key)

    def get_policies(self) -> List[DownscalePolicy]:
        with self._lock:
            return list(self._policies.values())

    def get_policy_for_deployment(
        self, namespace: str, name: str, labels: dict = None
    ) -> Optional[DownscalePolicy]:
        labels = labels or {}
        with self._lock:
            for policy in self._policies.values():
                if policy.matches_deployment(namespace, name, labels):
                    return policy
        return None

    def as_dicts(self) -> list:
        with self._lock:
            return [
                {
                    "name": p.name,
                    "namespace": p.namespace,
                    "enabled": p.enabled,
                    "schedule": {
                        "businessHoursStart": p.business_hours_start,
                        "businessHoursEnd": p.business_hours_end,
                        "businessDays": p.business_days,
                        "timezone": p.timezone,
                    },
                    "targetNamespaces": p.target_namespaces,
                    "excludeDeployments": p.exclude_deployments,
                    "minReplicaFloor": p.min_replica_floor,
                    "prewarmMinutes": p.prewarm_minutes,
                }
                for p in self._policies.values()
            ]
