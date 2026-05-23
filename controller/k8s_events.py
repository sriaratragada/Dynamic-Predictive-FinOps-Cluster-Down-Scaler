"""
Kubernetes Event emitter for the FinOps controller.

Emits native K8s Events visible via ``kubectl get events -n kube-system``
for every scale-down, scale-up, cordon, and uncordon transition.

All errors are non-fatal — a failed emit is logged at DEBUG level only so
a broken RBAC configuration never interrupts the control loop.
"""

import logging
import socket
from datetime import datetime, timezone

from kubernetes.client import CoreV1Event, V1EventSource, V1ObjectMeta, V1ObjectReference

logger = logging.getLogger(__name__)

_COMPONENT = "finops-scaler"


class K8sEventEmitter:
    """
    Thin wrapper around ``CoreV1Api.create_namespaced_event``.

    Parameters
    ----------
    core_api:
        A ``kubernetes.client.CoreV1Api`` instance (or compatible duck-type).
    namespace:
        Namespace into which events are written (default: ``kube-system``).
    """

    def __init__(self, core_api, namespace: str = "kube-system"):
        self._api = core_api
        self._ns = namespace
        self._host = socket.getfqdn()

    # ── Public helpers ────────────────────────────────────────────────────────

    def deployment_scaled_down(
        self, namespace: str, name: str, from_replicas: int
    ) -> None:
        self._emit(
            involved_object=V1ObjectReference(
                api_version="apps/v1",
                kind="Deployment",
                namespace=namespace,
                name=name,
            ),
            reason="ScaledDown",
            message=(
                f"FinOps controller scaled {namespace}/{name} "
                f"from {from_replicas} → 0 (off-hours)"
            ),
        )

    def deployment_scaled_up(
        self, namespace: str, name: str, to_replicas: int
    ) -> None:
        self._emit(
            involved_object=V1ObjectReference(
                api_version="apps/v1",
                kind="Deployment",
                namespace=namespace,
                name=name,
            ),
            reason="ScaledUp",
            message=(
                f"FinOps controller restored {namespace}/{name} "
                f"to {to_replicas} replica(s)"
            ),
        )

    def node_cordoned(self, node_name: str) -> None:
        self._emit(
            involved_object=V1ObjectReference(
                api_version="v1",
                kind="Node",
                name=node_name,
            ),
            reason="NodeCordoned",
            message=(
                f"FinOps controller cordoned {node_name} "
                "(underutilised during off-hours)"
            ),
        )

    def node_uncordoned(self, node_name: str) -> None:
        self._emit(
            involved_object=V1ObjectReference(
                api_version="v1",
                kind="Node",
                name=node_name,
            ),
            reason="NodeUncordoned",
            message=(
                f"FinOps controller uncordoned {node_name} "
                "(pre-warm / active window)"
            ),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(
        self,
        involved_object: V1ObjectReference,
        reason: str,
        message: str,
        event_type: str = "Normal",
    ) -> None:
        now = datetime.now(timezone.utc)
        event = CoreV1Event(
            metadata=V1ObjectMeta(
                generate_name=f"{_COMPONENT}-",
                namespace=self._ns,
            ),
            involved_object=involved_object,
            reason=reason,
            message=message,
            type=event_type,
            source=V1EventSource(
                component=_COMPONENT,
                host=self._host,
            ),
            first_timestamp=now,
            last_timestamp=now,
            count=1,
            action=reason,
            reporting_component=_COMPONENT,
            reporting_instance=self._host,
        )
        try:
            self._api.create_namespaced_event(namespace=self._ns, body=event)
            logger.debug(
                "K8s Event emitted: %s %s/%s",
                reason,
                involved_object.kind,
                involved_object.name,
            )
        except Exception as exc:
            logger.debug("K8s Event emit failed (non-fatal): %s", exc)
