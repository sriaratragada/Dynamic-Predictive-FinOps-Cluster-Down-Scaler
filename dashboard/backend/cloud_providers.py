"""
Cloud provider helpers for native EKS and GKE cluster discovery.

Provides functions to list clusters and build kubeconfig strings from
AWS/GCP credentials entered directly in the UI, without relying on
ambient environment credentials.

EKS tokens use the STS presigned-URL mechanism (k8s-aws-v1.* prefix),
valid for ~15 minutes.  Store the returned credentials and call
get_eks_token() periodically to refresh (see controller_runner.py).

GKE tokens are short-lived OAuth2 access tokens from the service account.
google-auth refreshes these automatically when the credentials object is
reused, so no manual refresh loop is needed for GKE.
"""

import base64
import json
import logging

import yaml

logger = logging.getLogger(__name__)


# ── AWS EKS ──────────────────────────────────────────────────────────────────

def list_eks_clusters(region: str, access_key_id: str, secret_access_key: str) -> list[dict]:
    """
    List EKS clusters in *region* using the supplied credentials.
    Returns [{ name, endpoint, status, kubernetes_version }].
    """
    import boto3

    session = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )
    eks = session.client("eks", region_name=region)

    names = eks.list_clusters()["clusters"]
    clusters = []
    for name in names:
        info = eks.describe_cluster(name=name)["cluster"]
        clusters.append({
            "name": info["name"],
            "endpoint": info.get("endpoint", ""),
            "status": info.get("status", ""),
            "kubernetes_version": info.get("version", ""),
        })
    logger.info("Listed %d EKS cluster(s) in %s", len(clusters), region)
    return clusters


def get_eks_token(cluster_name: str, region: str, access_key_id: str, secret_access_key: str) -> str:
    """
    Generate a k8s-aws-v1.* bearer token for *cluster_name* via STS presigned URL.
    Valid for ~15 minutes.  Call this again before expiry to refresh.
    """
    import boto3
    from botocore.signers import RequestSigner

    session = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )
    sts = session.client("sts", region_name=region)
    service_id = sts.meta.service_model.service_id

    signer = RequestSigner(
        service_id,
        region,
        "sts",
        "v4",
        session.get_credentials(),
        session.events,
    )

    signed_url = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": cluster_name},
            "context": {},
        },
        region_name=region,
        expires_in=60,
        operation_name="",
    )

    token = "k8s-aws-v1." + base64.urlsafe_b64encode(signed_url.encode()).rstrip(b"=").decode()
    return token


def kubeconfig_from_eks(
    cluster_name: str, region: str, access_key_id: str, secret_access_key: str
) -> str:
    """
    Build a kubeconfig YAML string for an EKS cluster.
    Fetches the cluster endpoint and CA cert from the EKS API, then
    generates a fresh STS bearer token.
    """
    import boto3

    session = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )
    eks = session.client("eks", region_name=region)
    info = eks.describe_cluster(name=cluster_name)["cluster"]

    endpoint = info["endpoint"]
    ca_data = info["certificateAuthority"]["data"]  # already base64-encoded
    token = get_eks_token(cluster_name, region, access_key_id, secret_access_key)

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": cluster_name, "cluster": {
            "server": endpoint,
            "certificate-authority-data": ca_data,
        }}],
        "users": [{"name": cluster_name, "user": {"token": token}}],
        "contexts": [{"name": cluster_name, "context": {
            "cluster": cluster_name,
            "user": cluster_name,
        }}],
        "current-context": cluster_name,
    }

    logger.info("Built EKS kubeconfig for %s (%s)", cluster_name, region)
    return yaml.dump(kubeconfig, default_flow_style=False)


# ── GCP GKE ───────────────────────────────────────────────────────────────────

def list_gke_clusters(project_id: str, location: str, service_account_json: str) -> list[dict]:
    """
    List GKE clusters in *project_id*/*location* using a service account JSON string.
    Pass location='-' to list across all regions/zones.
    Returns [{ name, endpoint, status, kubernetes_version, location }].
    """
    from google.cloud import container_v1
    from google.oauth2 import service_account

    sa_info = json.loads(service_account_json)
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    client = container_v1.ClusterManagerClient(credentials=creds)
    parent = f"projects/{project_id}/locations/{location}"
    response = client.list_clusters(parent=parent)

    clusters = []
    for cluster in response.clusters:
        clusters.append({
            "name": cluster.name,
            "endpoint": cluster.endpoint,
            "status": cluster.status.name,
            "kubernetes_version": cluster.current_master_version,
            "location": cluster.location,
        })
    logger.info("Listed %d GKE cluster(s) in %s/%s", len(clusters), project_id, location)
    return clusters


def kubeconfig_from_gke(
    project_id: str, location: str, cluster_name: str, service_account_json: str
) -> str:
    """
    Build a kubeconfig YAML string for a GKE cluster.
    Fetches full cluster info (endpoint + CA cert) from the GKE API, then
    generates a short-lived OAuth2 access token from the service account.
    """
    from google.auth.transport.requests import Request
    from google.cloud import container_v1
    from google.oauth2 import service_account

    sa_info = json.loads(service_account_json)
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(Request())

    client = container_v1.ClusterManagerClient(credentials=creds)
    cluster = client.get_cluster(
        name=f"projects/{project_id}/locations/{location}/clusters/{cluster_name}"
    )

    endpoint = cluster.endpoint
    ca_cert = cluster.master_auth.cluster_ca_certificate  # already base64-encoded
    token = creds.token

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": cluster_name, "cluster": {
            "server": f"https://{endpoint}",
            "certificate-authority-data": ca_cert,
        }}],
        "users": [{"name": cluster_name, "user": {"token": token}}],
        "contexts": [{"name": cluster_name, "context": {
            "cluster": cluster_name,
            "user": cluster_name,
        }}],
        "current-context": cluster_name,
    }

    logger.info("Built GKE kubeconfig for %s (%s/%s)", cluster_name, project_id, location)
    return yaml.dump(kubeconfig, default_flow_style=False)
