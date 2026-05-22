import json
import logging
from typing import Dict, List

from kubernetes import client
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

_KEY_REPLICAS = "replicas"
_KEY_CORDONED = "cordoned_nodes"


class StateStore:
    """Persists scaler state in a Kubernetes ConfigMap so it survives pod restarts."""

    def __init__(self, name: str, namespace: str, core_api: client.CoreV1Api):
        self._name = name
        self._namespace = namespace
        self._api = core_api

    # ------------------------------------------------------------------
    # Replica state
    # ------------------------------------------------------------------

    def save_replicas(self, namespace: str, name: str, replicas: int):
        data = self._load()
        data[_KEY_REPLICAS][f"{namespace}/{name}"] = replicas
        self._patch(data)
        logger.debug("Saved replica state %s/%s = %d", namespace, name, replicas)

    def load_replicas(self) -> Dict[str, int]:
        return self._load()[_KEY_REPLICAS]

    def clear_replicas(self, namespace: str, name: str):
        data = self._load()
        data[_KEY_REPLICAS].pop(f"{namespace}/{name}", None)
        self._patch(data)

    # ------------------------------------------------------------------
    # Cordoned-node state
    # ------------------------------------------------------------------

    def save_cordoned_nodes(self, nodes: List[str]):
        data = self._load()
        data[_KEY_CORDONED] = nodes
        self._patch(data)

    def load_cordoned_nodes(self) -> List[str]:
        return self._load()[_KEY_CORDONED]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure(self) -> client.V1ConfigMap:
        try:
            return self._api.read_namespaced_config_map(self._name, self._namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
        cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=self._name, namespace=self._namespace),
            data={_KEY_REPLICAS: "{}", _KEY_CORDONED: "[]"},
        )
        return self._api.create_namespaced_config_map(self._namespace, cm)

    def _load(self) -> dict:
        cm = self._ensure()
        raw = cm.data or {}
        return {
            _KEY_REPLICAS: json.loads(raw.get(_KEY_REPLICAS, "{}")),
            _KEY_CORDONED: json.loads(raw.get(_KEY_CORDONED, "[]")),
        }

    def _patch(self, data: dict):
        self._api.patch_namespaced_config_map(
            self._name,
            self._namespace,
            client.V1ConfigMap(
                data={
                    _KEY_REPLICAS: json.dumps(data[_KEY_REPLICAS]),
                    _KEY_CORDONED: json.dumps(data[_KEY_CORDONED]),
                }
            ),
        )
