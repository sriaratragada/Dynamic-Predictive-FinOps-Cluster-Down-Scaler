import logging
from typing import List

from kubernetes import client

logger = logging.getLogger(__name__)

ELIGIBLE_LABEL = "finops.io/scaledown-eligible=true"


class DeploymentScaler:
    def __init__(
        self,
        apps_api: client.AppsV1Api,
        namespace_filter: str = "",
        min_floor: int = 0,
        dry_run: bool = False,
    ):
        self._api = apps_api
        self._ns_filter = namespace_filter
        self._floor = min_floor
        self._dry_run = dry_run

    def find_eligible(self) -> List[client.V1Deployment]:
        """Return all Deployments opted in via the finops scaledown label."""
        if self._ns_filter:
            result = self._api.list_namespaced_deployment(
                self._ns_filter, label_selector=ELIGIBLE_LABEL
            )
        else:
            result = self._api.list_deployment_for_all_namespaces(
                label_selector=ELIGIBLE_LABEL
            )
        return result.items

    def scale_down(self, deployment: client.V1Deployment) -> int:
        """Scale a deployment to the configured floor. Returns the original replica count."""
        ns = deployment.metadata.namespace
        name = deployment.metadata.name
        current = deployment.spec.replicas if deployment.spec.replicas is not None else 1

        if current == self._floor:
            logger.debug("%s/%s already at floor (%d)", ns, name, self._floor)
            return current

        self._set_replicas(ns, name, self._floor)
        logger.info("Scaled down %s/%s: %d → %d", ns, name, current, self._floor)
        return current

    def scale_up(self, deployment: client.V1Deployment, replicas: int):
        """Restore a deployment to the given replica count."""
        ns = deployment.metadata.namespace
        name = deployment.metadata.name
        self._set_replicas(ns, name, replicas)
        logger.info("Scaled up %s/%s → %d", ns, name, replicas)

    def _set_replicas(self, namespace: str, name: str, replicas: int):
        if self._dry_run:
            logger.info("[DRY-RUN] Would set %s/%s replicas → %d", namespace, name, replicas)
            return
        self._api.patch_namespaced_deployment_scale(
            name,
            namespace,
            client.V1Scale(spec=client.V1ScaleSpec(replicas=replicas)),
        )
