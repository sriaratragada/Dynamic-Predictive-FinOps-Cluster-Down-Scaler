"""Cluster connect routes — kubeconfig, EKS, GKE."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config_store, pricing
from ..auth import require_token
from ..controller_runner import get_runner
from ..deps import require_fields
from ..k8s_client import K8sReader
from ..savings_tracker import SavingsTracker
from .. import deps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


async def _activate_cluster(core_v1, apps_v1) -> None:
    """Shared post-connect setup: re-point K8s reader, restart tracker, start loop."""
    deps._k8s = K8sReader(core_v1=core_v1, apps_v1=apps_v1)

    if deps._tracker is not None:
        deps._tracker.stop()
    deps._tracker = SavingsTracker(deps._k8s, pricing.get_hourly_rate)
    asyncio.create_task(deps._tracker.start())

    config_store.patch({"demo_mode": False})

    runner = get_runner()
    await asyncio.to_thread(runner.start, 60)


@router.post("/connect")
async def api_connect(request: Request, _: None = Depends(require_token)):
    """Accept a kubeconfig YAML string and start the embedded controller loop."""
    body = await request.json()
    fields = require_fields(body, "kubeconfig")

    runner = get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, fields["kubeconfig"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    await _activate_cluster(core_v1, apps_v1)
    logger.info("Web-service mode: controller started, K8sReader re-initialised")
    return runner.status().as_dict()


@router.post("/aws/clusters")
async def api_aws_clusters(request: Request, _: None = Depends(require_token)):
    """List EKS clusters in the given region."""
    from .. import cloud_providers

    body = await request.json()
    f = require_fields(body, "region", "access_key_id", "secret_access_key")

    try:
        clusters = await asyncio.to_thread(
            cloud_providers.list_eks_clusters,
            f["region"], f["access_key_id"], f["secret_access_key"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"AWS error: {exc}") from exc

    return {"clusters": clusters}


@router.post("/gcp/clusters")
async def api_gcp_clusters(request: Request, _: None = Depends(require_token)):
    """List GKE clusters using a GCP service account JSON string."""
    from .. import cloud_providers

    body = await request.json()
    f = require_fields(body, "project_id", "service_account_json")
    location = (body.get("location") or "-").strip() or "-"

    try:
        clusters = await asyncio.to_thread(
            cloud_providers.list_gke_clusters,
            f["project_id"], location, f["service_account_json"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GCP error: {exc}") from exc

    return {"clusters": clusters}


@router.post("/connect/eks")
async def api_connect_eks(request: Request, _: None = Depends(require_token)):
    """Connect to an EKS cluster and start the embedded controller loop."""
    from .. import cloud_providers

    body = await request.json()
    f = require_fields(body, "region", "cluster_name", "access_key_id", "secret_access_key")

    try:
        kubeconfig_str = await asyncio.to_thread(
            cloud_providers.kubeconfig_from_eks,
            f["cluster_name"], f["region"], f["access_key_id"], f["secret_access_key"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"EKS kubeconfig error: {exc}") from exc

    runner = get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, kubeconfig_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    runner.set_cloud_creds("eks", {
        "region": f["region"],
        "cluster_name": f["cluster_name"],
        "access_key_id": f["access_key_id"],
        "secret_access_key": f["secret_access_key"],
    })

    await _activate_cluster(core_v1, apps_v1)
    logger.info("EKS cluster connected: %s (%s)", f["cluster_name"], f["region"])
    return runner.status().as_dict()


@router.post("/connect/gke")
async def api_connect_gke(request: Request, _: None = Depends(require_token)):
    """Connect to a GKE cluster and start the embedded controller loop."""
    from .. import cloud_providers

    body = await request.json()
    f = require_fields(body, "project_id", "location", "cluster_name", "service_account_json")

    try:
        kubeconfig_str = await asyncio.to_thread(
            cloud_providers.kubeconfig_from_gke,
            f["project_id"], f["location"], f["cluster_name"], f["service_account_json"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GKE kubeconfig error: {exc}") from exc

    runner = get_runner()
    try:
        core_v1, apps_v1 = await asyncio.to_thread(runner.connect, kubeconfig_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cluster unreachable: {exc}") from exc

    runner.set_cloud_creds("gke", {
        "project_id": f["project_id"],
        "location": f["location"],
        "cluster_name": f["cluster_name"],
        "service_account_json": f["service_account_json"],
    })

    await _activate_cluster(core_v1, apps_v1)
    logger.info("GKE cluster connected: %s (%s/%s)", f["cluster_name"], f["project_id"], f["location"])
    return runner.status().as_dict()
