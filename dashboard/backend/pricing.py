import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_cached_rate: Optional[float] = None
_cache_ts: float = 0.0
_CACHE_TTL = 3600.0  # refresh rate once per hour


def get_hourly_rate() -> float:
    global _cached_rate, _cache_ts
    if _cached_rate is not None and (time.monotonic() - _cache_ts) < _CACHE_TTL:
        return _cached_rate
    rate = _fetch_rate()
    _cached_rate = rate
    _cache_ts = time.monotonic()
    return rate


def get_provider_info() -> dict:
    return {
        "provider": os.environ.get("CLOUD_PROVIDER", "manual").lower(),
        "instance_type": os.environ.get("NODE_INSTANCE_TYPE", ""),
        "region": os.environ.get("AWS_REGION", ""),
        "manual_rate": float(os.environ.get("NODE_HOURLY_COST", "0.192")),
    }


def _fetch_rate() -> float:
    info = get_provider_info()
    provider = info["provider"]
    fallback = info["manual_rate"]

    if provider == "aws":
        try:
            return _aws_rate(info["instance_type"], info["region"], fallback)
        except Exception as exc:
            logger.warning("AWS pricing fetch failed, falling back to manual: %s", exc)
            return fallback

    if provider == "gcp":
        try:
            return _gcp_rate(info["instance_type"], fallback)
        except Exception as exc:
            logger.warning("GCP pricing fetch failed, falling back to manual: %s", exc)
            return fallback

    return fallback


def _aws_rate(instance_type: str, region: str, fallback: float) -> float:
    import boto3  # noqa: PLC0415

    _REGION_NAMES = {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-1": "US West (N. California)",
        "us-west-2": "US West (Oregon)",
        "eu-west-1": "EU (Ireland)",
        "eu-central-1": "EU (Frankfurt)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
        "ap-south-1": "Asia Pacific (Mumbai)",
    }
    location = _REGION_NAMES.get(region, "US East (N. Virginia)")
    instance_type = instance_type or "m5.xlarge"

    client = boto3.client("pricing", region_name="us-east-1")
    response = client.get_products(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "instanceType",    "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "location",        "Value": location},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw",  "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "tenancy",         "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus",  "Value": "Used"},
        ],
        MaxResults=1,
    )

    for price_str in response.get("PriceList", []):
        price_data = json.loads(price_str)
        for term in price_data.get("terms", {}).get("OnDemand", {}).values():
            for dim in term.get("priceDimensions", {}).values():
                usd = float(dim["pricePerUnit"].get("USD", "0"))
                if usd > 0:
                    logger.info("AWS price: %s in %s = $%.4f/hr", instance_type, region, usd)
                    return usd

    logger.warning("AWS pricing: no result for %s/%s, using fallback", instance_type, region)
    return fallback


def _gcp_rate(instance_type: str, fallback: float) -> float:
    from google.cloud import billing_v1  # noqa: PLC0415

    instance_type = instance_type or "n2-standard-4"
    family = instance_type.split("-")[0].upper()  # e.g. "N2"

    catalog = billing_v1.CloudCatalogClient()
    # GCE Compute Engine service ID
    service = "services/6F81-5844-456A"

    total = 0.0
    for sku in catalog.list_skus(parent=service):
        desc = sku.description
        if family not in desc or "Instance" not in desc:
            continue
        for pi in sku.pricing_info:
            expr = pi.pricing_expression
            if expr.usage_unit != "h":
                continue
            for tier in expr.tiered_rates:
                units = tier.unit_price.units
                nanos = tier.unit_price.nanos
                total += units + nanos / 1e9
        if total > 0:
            break

    if total > 0:
        logger.info("GCP price: %s = $%.4f/hr", instance_type, total)
        return total

    logger.warning("GCP pricing: no result for %s, using fallback", instance_type)
    return fallback


def get_spot_prices(instance_type: str = "", region: str = "") -> dict:
    """Fetch current spot prices by AZ. Returns {az: price_per_hour}."""
    instance_type = instance_type or os.environ.get("NODE_INSTANCE_TYPE", "m5.xlarge")
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3  # noqa: PLC0415
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_spot_price_history(
            InstanceTypes=[instance_type],
            ProductDescriptions=["Linux/UNIX"],
            MaxResults=20,
        )
        prices = {}
        for item in response.get("SpotPriceHistory", []):
            az = item["AvailabilityZone"]
            price = float(item["SpotPrice"])
            if az not in prices or price < prices[az]:
                prices[az] = price
        return prices
    except Exception as exc:
        logger.warning("Spot price fetch failed: %s", exc)
        return {}
