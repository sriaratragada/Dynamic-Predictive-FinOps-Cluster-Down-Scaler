"""
Namespace-driven auto-labeller.

Any namespace annotated with  finops.io/scaledown-namespace=true  will have all
of its Deployments labelled  finops.io/scaledown-eligible=true  on the next
controller tick.  This lets cluster operators opt whole namespaces into FinOps
scale-down without touching individual Deployment manifests.

The labeller is idempotent — it skips Deployments that already carry the label.
"""
import logging

logger = logging.getLogger(__name__)

NAMESPACE_ANNOTATION = "finops.io/scaledown-namespace"
DEPLOYMENT_LABEL     = "finops.io/scaledown-eligible"


class AutoLabeller:
    def __init__(self, core_api, apps_api, dry_run: bool = False):
        self._core    = core_api
        self._apps    = apps_api
        self._dry_run = dry_run

    def label_eligible_namespaces(self) -> int:
        """
        Scan all namespaces for the opt-in annotation and label unlabelled Deployments.
        Returns the count of newly-labelled Deployments.
        """
        count = 0
        try:
            ns_list = self._core.list_namespace()
        except Exception as exc:
            logger.warning("AutoLabeller: could not list namespaces: %s", exc)
            return 0

        for ns_obj in ns_list.items:
            annotations = ns_obj.metadata.annotations or {}
            if annotations.get(NAMESPACE_ANNOTATION) != "true":
                continue
            ns_name = ns_obj.metadata.name
            count  += self._label_namespace(ns_name)

        return count

    def _label_namespace(self, namespace: str) -> int:
        count = 0
        try:
            deps = self._apps.list_namespaced_deployment(namespace)
        except Exception as exc:
            logger.warning(
                "AutoLabeller: could not list deployments in %s: %s", namespace, exc
            )
            return 0

        for dep in deps.items:
            labels = dep.metadata.labels or {}
            if labels.get(DEPLOYMENT_LABEL) == "true":
                continue
            dep_name = dep.metadata.name
            if self._dry_run:
                logger.info(
                    "[DRY-RUN] Would label %s/%s %s=true",
                    namespace, dep_name, DEPLOYMENT_LABEL,
                )
                count += 1
                continue
            try:
                self._apps.patch_namespaced_deployment(
                    dep_name, namespace,
                    {"metadata": {"labels": {DEPLOYMENT_LABEL: "true"}}},
                )
                logger.info(
                    "AutoLabeller: labelled %s/%s as %s=true",
                    namespace, dep_name, DEPLOYMENT_LABEL,
                )
                count += 1
            except Exception as exc:
                logger.warning(
                    "AutoLabeller: could not label %s/%s: %s", namespace, dep_name, exc
                )

        return count
