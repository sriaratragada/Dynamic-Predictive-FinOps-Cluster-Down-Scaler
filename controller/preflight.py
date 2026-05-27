"""
Pre-flight configuration validator.

Runs once at controller startup (before the control loop) and prints a
structured table of PASS / WARN / FAIL / SKIP check results.  A FAIL
result is surfaced in the log but does NOT abort the controller — callers
decide whether to exit on failure.
"""

import logging
from dataclasses import dataclass
from typing import List

from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

_ICONS = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭ "}


@dataclass
class CheckResult:
    name: str
    status: str   # PASS | WARN | FAIL | SKIP
    message: str


class PreflightChecker:
    """
    Runs a battery of startup checks and returns a list of CheckResult objects.

    Usage::

        checker = PreflightChecker()
        results = checker.run(cfg, core_api, apps_api, prom, autoscaling_api)
        failed = log_preflight_results(results)
        if failed:
            logger.error("Pre-flight FAILED — %d check(s) require attention", failed)
    """

    def run(
        self,
        cfg,
        core_api,
        apps_api,
        prom,
        autoscaling_api=None,
    ) -> List[CheckResult]:
        results: List[CheckResult] = []
        results.append(self._check_schedule(cfg))
        results.extend(self._check_k8s(cfg, core_api, apps_api))
        results.append(self._check_prometheus(cfg, prom))
        results.append(self._check_prophet(cfg))
        results.append(self._check_hpa_rbac(cfg, autoscaling_api))
        results.append(self._check_state_cm(cfg, core_api))
        return results

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_schedule(self, cfg) -> CheckResult:
        try:
            sh, sm = (int(x) for x in cfg.business_hours_start.split(":"))
            eh, em = (int(x) for x in cfg.business_hours_end.split(":"))
        except Exception as exc:
            return CheckResult("Schedule", "FAIL", f"cannot parse hours: {exc}")

        start_mins = sh * 60 + sm
        end_mins = eh * 60 + em
        if start_mins >= end_mins:
            return CheckResult(
                "Schedule", "FAIL",
                f"{cfg.business_hours_start} is not before {cfg.business_hours_end}",
            )
        if not cfg.business_days:
            return CheckResult("Schedule", "FAIL", "BUSINESS_DAYS is empty")

        days_str = ",".join(str(d) for d in sorted(cfg.business_days))
        return CheckResult(
            "Schedule", "PASS",
            f"{cfg.business_hours_start}–{cfg.business_hours_end}  "
            f"days={days_str}  tz={cfg.timezone}",
        )

    def _check_prometheus(self, cfg, prom) -> CheckResult:
        try:
            result = prom.scalar("vector(1)")
            if result is not None:
                return CheckResult("Prometheus", "PASS", cfg.prometheus_url)
            return CheckResult(
                "Prometheus", "WARN",
                f"empty response from {cfg.prometheus_url}",
            )
        except Exception as exc:
            return CheckResult(
                "Prometheus", "FAIL",
                f"{cfg.prometheus_url} — {exc}",
            )

    def _check_k8s(self, cfg, core_api, apps_api) -> List[CheckResult]:
        results: List[CheckResult] = []

        # Node visibility
        try:
            nl = core_api.list_node()
            count = len(nl.items)
            results.append(CheckResult("K8s nodes", "PASS", f"{count} node(s) visible"))
        except Exception as exc:
            results.append(CheckResult("K8s nodes", "FAIL", str(exc)))

        # Eligible deployments
        try:
            ns = cfg.namespace_filter or None
            if ns:
                dl = apps_api.list_namespaced_deployment(
                    ns, label_selector="finops.io/scaledown-eligible=true"
                )
            else:
                dl = apps_api.list_deployment_for_all_namespaces(
                    label_selector="finops.io/scaledown-eligible=true"
                )
            count = len(dl.items)
            if count == 0:
                results.append(CheckResult(
                    "Eligible deployments", "WARN",
                    "0 deployments with finops.io/scaledown-eligible=true — "
                    "nothing will be scaled down",
                ))
            else:
                results.append(CheckResult(
                    "Eligible deployments", "PASS",
                    f"{count} deployment(s) labelled for scale-down",
                ))
        except Exception as exc:
            results.append(CheckResult("Eligible deployments", "FAIL", str(exc)))

        return results

    def _check_prophet(self, cfg) -> CheckResult:
        if not cfg.enable_prophet:
            return CheckResult("Prophet ML", "SKIP", "ENABLE_PROPHET=false")
        try:
            import prophet  # noqa: F401
            return CheckResult(
                "Prophet ML", "PASS",
                f"installed  (training_weeks={cfg.prophet_training_weeks})",
            )
        except ImportError:
            return CheckResult(
                "Prophet ML", "FAIL",
                "ENABLE_PROPHET=true but prophet package not installed — "
                "run: pip install -r requirements-prophet.txt",
            )

    def _check_hpa_rbac(self, cfg, autoscaling_api) -> CheckResult:
        if not cfg.enable_hpa_suspend:
            return CheckResult("HPA RBAC", "SKIP", "ENABLE_HPA_SUSPEND=false")
        if autoscaling_api is None:
            return CheckResult("HPA RBAC", "SKIP", "autoscaling API not provided")
        try:
            autoscaling_api.list_namespaced_horizontal_pod_autoscaler("kube-system")
            return CheckResult("HPA RBAC", "PASS", "autoscaling GET verb verified")
        except ApiException as exc:
            if exc.status == 403:
                return CheckResult(
                    "HPA RBAC", "FAIL",
                    "missing autoscaling GET verb — add to ClusterRole: "
                    "apiGroups=[autoscaling] resources=[horizontalpodautoscalers]",
                )
            return CheckResult("HPA RBAC", "WARN", f"inconclusive: {exc}")
        except Exception as exc:
            # Fallback for duck-typed stubs / mocks that don't raise ApiException.
            msg = str(exc)
            if "403" in msg or "Forbidden" in msg:
                return CheckResult(
                    "HPA RBAC", "FAIL",
                    "missing autoscaling GET verb — add to ClusterRole: "
                    "apiGroups=[autoscaling] resources=[horizontalpodautoscalers]",
                )
            return CheckResult("HPA RBAC", "WARN", f"inconclusive: {exc}")

    def _check_state_cm(self, cfg, core_api) -> CheckResult:
        try:
            core_api.read_namespaced_config_map(
                cfg.state_configmap_name, cfg.state_configmap_ns
            )
            return CheckResult(
                "State ConfigMap", "PASS",
                f"{cfg.state_configmap_ns}/{cfg.state_configmap_name} exists",
            )
        except ApiException as exc:
            if exc.status == 404:
                return CheckResult(
                    "State ConfigMap", "WARN",
                    f"{cfg.state_configmap_ns}/{cfg.state_configmap_name} not found — "
                    "will be created on first scale-down",
                )
            return CheckResult("State ConfigMap", "FAIL", str(exc))
        except Exception as exc:
            # Fallback for duck-typed stubs / mocks that don't raise ApiException.
            msg = str(exc)
            if "404" in msg or "Not Found" in msg:
                return CheckResult(
                    "State ConfigMap", "WARN",
                    f"{cfg.state_configmap_ns}/{cfg.state_configmap_name} not found — "
                    "will be created on first scale-down",
                )
            return CheckResult("State ConfigMap", "FAIL", msg)


def log_preflight_results(results: List[CheckResult]) -> int:
    """
    Pretty-print all check results to the controller log.

    Returns the number of FAIL results (0 = all good).
    """
    border = "─" * 62
    logger.info(border)
    logger.info("Pre-flight checks")
    logger.info(border)
    failed = 0
    warned = 0
    for r in results:
        icon = _ICONS.get(r.status, "? ")
        logger.info("  %s %-26s %s", icon, r.name, r.message)
        if r.status == "FAIL":
            failed += 1
        elif r.status == "WARN":
            warned += 1
    logger.info(border)
    passed = sum(1 for r in results if r.status == "PASS")
    skipped = sum(1 for r in results if r.status == "SKIP")
    logger.info(
        "Pre-flight: %d passed  %d warned  %d failed  %d skipped",
        passed, warned, failed, skipped,
    )
    logger.info(border)
    return failed
