"""
Leader election using Kubernetes ``coordination.k8s.io/v1`` Lease objects.

Allows multiple controller replicas to run safely in an HA configuration —
only the holder of the Lease will execute the control loop body.  Non-leader
pods block in ``acquire_blocking()`` and retry on a short interval.

Lease semantics
---------------
* ``lease_duration_s``   – how long a Lease is valid after its last renewal.
* ``renew_every_s``      – how often the leader renews (must be < ``lease_duration_s``).
* ``retry_interval_s``   – how often a follower polls to check for expiry.

Usage::

    elector = LeaderElector(coordination_api, namespace="kube-system")
    elector.acquire_blocking()          # blocks until we hold the lease

    # inside the control loop:
    if not elector.renew():
        logger.warning("Lost leadership — re-acquiring")
        elector.acquire_blocking()
    # … do work …
"""

import logging
import os
import socket
import time
from datetime import datetime, timezone
from typing import Optional

from kubernetes.client import V1Lease, V1LeaseSpec, V1ObjectMeta

logger = logging.getLogger(__name__)

LEASE_NAME = "finops-scaler-leader"


class LeaderElector:
    """
    Kubernetes Lease-based leader election.

    Parameters
    ----------
    coordination_api:
        A ``kubernetes.client.CoordinationV1Api`` instance (or compatible
        duck-type with ``read_namespaced_lease``, ``create_namespaced_lease``,
        ``replace_namespaced_lease``).
    namespace:
        Namespace where the Lease object lives (default: ``kube-system``).
    identity:
        Unique identifier for this instance.  Defaults to the ``POD_NAME``
        environment variable, then falls back to the FQDN hostname.
    lease_duration_s:
        Seconds after which an un-renewed lease is considered expired.
    renew_every_s:
        How often the leader should call ``renew()`` (informational only —
        the caller is responsible for the cadence).
    retry_interval_s:
        Seconds a follower sleeps between acquisition attempts.
    """

    def __init__(
        self,
        coordination_api,
        namespace: str = "kube-system",
        identity: Optional[str] = None,
        lease_duration_s: int = 30,
        renew_every_s: int = 10,
        retry_interval_s: int = 5,
    ):
        self._api = coordination_api
        self._ns = namespace
        self._identity = identity or os.environ.get("POD_NAME") or socket.getfqdn()
        self._lease_duration = lease_duration_s
        self._renew_every = renew_every_s
        self._retry_interval = retry_interval_s

    @property
    def identity(self) -> str:
        return self._identity

    # ── Public interface ──────────────────────────────────────────────────────

    def acquire_blocking(self) -> None:
        """Block until this instance holds the leader Lease."""
        logger.info(
            "Leader election: competing for %s/%s  (identity=%s)",
            self._ns, LEASE_NAME, self._identity,
        )
        while True:
            if self._try_acquire_or_renew():
                logger.info(
                    "Leader election: acquired lease  (identity=%s)", self._identity
                )
                return
            logger.debug(
                "Leader election: lease held by %s — retrying in %ds",
                self._current_holder(), self._retry_interval,
            )
            time.sleep(self._retry_interval)

    def renew(self) -> bool:
        """
        Renew the leader Lease.

        Returns ``True`` if this instance is still the leader after renewal;
        ``False`` if the lease was lost (stolen by another pod or expired and
        re-acquired by a competitor).

        Call once per control-loop tick *before* doing any work.
        """
        ok = self._try_acquire_or_renew()
        if not ok:
            logger.warning(
                "Leader election: lease renewal failed — stepping down  "
                "(identity=%s)",
                self._identity,
            )
        return ok

    # ── Internal ──────────────────────────────────────────────────────────────

    def _try_acquire_or_renew(self) -> bool:
        now = datetime.now(timezone.utc)
        try:
            lease = self._api.read_namespaced_lease(LEASE_NAME, self._ns)
        except Exception as exc:
            if "Not Found" in str(exc) or "404" in str(exc):
                # Lease doesn't exist yet — race to create it
                return self._create_lease(now)
            logger.warning("Leader election: error reading lease: %s", exc)
            return False

        holder = lease.spec.holder_identity or ""
        renew_time = lease.spec.renew_time
        duration = lease.spec.lease_duration_seconds or self._lease_duration

        # Lease is expired if renew_time is missing or older than duration
        lease_expired = renew_time is None or (
            (now - renew_time).total_seconds() > duration
        )

        if holder == self._identity or lease_expired:
            return self._patch_lease(lease, now)

        # Another active holder owns the lease
        return False

    def _create_lease(self, now: datetime) -> bool:
        body = V1Lease(
            metadata=V1ObjectMeta(name=LEASE_NAME, namespace=self._ns),
            spec=V1LeaseSpec(
                holder_identity=self._identity,
                lease_duration_seconds=self._lease_duration,
                acquire_time=now,
                renew_time=now,
            ),
        )
        try:
            self._api.create_namespaced_lease(self._ns, body)
            logger.debug(
                "Leader election: created lease (identity=%s)", self._identity
            )
            return True
        except Exception as exc:
            # 409 Conflict = another pod created it first
            logger.debug("Leader election: create_lease failed: %s", exc)
            return False

    def _patch_lease(self, lease, now: datetime) -> bool:
        lease.spec.holder_identity = self._identity
        lease.spec.renew_time = now
        lease.spec.lease_duration_seconds = self._lease_duration
        try:
            self._api.replace_namespaced_lease(LEASE_NAME, self._ns, lease)
            logger.debug(
                "Leader election: renewed lease (identity=%s)", self._identity
            )
            return True
        except Exception as exc:
            logger.debug("Leader election: patch_lease failed: %s", exc)
            return False

    def _current_holder(self) -> str:
        try:
            lease = self._api.read_namespaced_lease(LEASE_NAME, self._ns)
            return lease.spec.holder_identity or "unknown"
        except Exception:
            return "unknown"
