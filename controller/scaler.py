import logging
from typing import List, Optional

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
        autoscaling_api=None,
    ):
        self._api = apps_api
        self._ns_filter = namespace_filter
        self._floor = min_floor
        self._dry_run = dry_run
        self._hpa_api = autoscaling_api  # client.AutoscalingV2Api or None

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
        """Scale a deployment to the configured floor. Returns the original replica count.

        Note: returns the *actual* current value — including the floor itself —
        so callers can record it in the state store and restore exactly that
        value on scale-up.  Without this, a deployment paused at 0 would be
        silently revived to 1 replica at the next active window.
        """
        ns = deployment.metadata.namespace
        name = deployment.metadata.name
        current = deployment.spec.replicas if deployment.spec.replicas is not None else 1

        if current == self._floor:
            logger.debug("%s/%s already at floor (%d) — recording for restore", ns, name, self._floor)
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

    # ------------------------------------------------------------------
    # HPA suspend / resume
    # ------------------------------------------------------------------

    def find_hpa(self, deployment: client.V1Deployment) -> Optional[object]:
        """Return the autoscaling/v2 HPA that targets this deployment, or None."""
        if self._hpa_api is None:
            return None
        ns = deployment.metadata.namespace
        name = deployment.metadata.name
        try:
            hpas = self._hpa_api.list_namespaced_horizontal_pod_autoscaler(ns)
            for hpa in hpas.items:
                ref = hpa.spec.scale_target_ref
                if ref.kind == "Deployment" and ref.name == name:
                    return hpa
        except Exception as exc:
            logger.warning("Could not list HPAs in %s: %s", ns, exc)
        return None

    def suspend_hpa(self, hpa) -> int:
        """
        Patch HPA minReplicas → 0 so it does not fight the scale-down.
        Returns the original minReplicas value for later restoration.
        """
        ns   = hpa.metadata.namespace
        name = hpa.metadata.name
        original_min = hpa.spec.min_replicas if hpa.spec.min_replicas is not None else 1
        if self._dry_run:
            logger.info(
                "[DRY-RUN] Would suspend HPA %s/%s (minReplicas %d → 0)",
                ns, name, original_min,
            )
            return original_min
        self._hpa_api.patch_namespaced_horizontal_pod_autoscaler(
            name, ns, {"spec": {"minReplicas": 0}}
        )
        logger.info("Suspended HPA %s/%s: minReplicas %d → 0", ns, name, original_min)
        return original_min

    def resume_hpa(self, hpa, original_min: int):
        """Restore HPA minReplicas to its pre-suspend value."""
        ns   = hpa.metadata.namespace
        name = hpa.metadata.name
        if self._dry_run:
            logger.info(
                "[DRY-RUN] Would resume HPA %s/%s (minReplicas → %d)",
                ns, name, original_min,
            )
            return
        self._hpa_api.patch_namespaced_horizontal_pod_autoscaler(
            name, ns, {"spec": {"minReplicas": original_min}}
        )
        logger.info("Resumed HPA %s/%s: minReplicas → %d", ns, name, original_min)

    # ------------------------------------------------------------------
    # HPA spike preparation
    # ------------------------------------------------------------------

    def prepare_hpa_for_spike(self, hpa, predicted_max_replicas: int, headroom_pct: int = 30):
        """Raise HPA maxReplicas ahead of a predicted traffic spike."""
        ns = hpa.metadata.namespace
        name = hpa.metadata.name
        current_max = hpa.spec.max_replicas
        new_max = int(predicted_max_replicas * (1 + headroom_pct / 100))
        if new_max <= current_max:
            logger.debug("HPA %s/%s maxReplicas %d already >= needed %d", ns, name, current_max, new_max)
            return current_max
        if self._dry_run:
            logger.info("[DRY-RUN] Would raise HPA %s/%s maxReplicas %d -> %d", ns, name, current_max, new_max)
            return current_max
        self._hpa_api.patch_namespaced_horizontal_pod_autoscaler(
            name, ns, {"spec": {"maxReplicas": new_max}}
        )
        logger.info("HPA spike prep: %s/%s maxReplicas %d -> %d (headroom %d%%)", ns, name, current_max, new_max, headroom_pct)
        return current_max

    def restore_hpa_max(self, hpa, original_max: int):
        """Restore HPA maxReplicas after a spike window passes."""
        ns = hpa.metadata.namespace
        name = hpa.metadata.name
        if self._dry_run:
            logger.info("[DRY-RUN] Would restore HPA %s/%s maxReplicas -> %d", ns, name, original_max)
            return
        self._hpa_api.patch_namespaced_horizontal_pod_autoscaler(
            name, ns, {"spec": {"maxReplicas": original_max}}
        )
        logger.info("HPA spike restored: %s/%s maxReplicas -> %d", ns, name, original_max)
