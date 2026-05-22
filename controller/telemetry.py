import logging

from prometheus_client import Counter, Gauge, start_http_server

logger = logging.getLogger(__name__)

scaledown_events = Counter(
    "finops_scaledown_events_total",
    "Number of completed scale-down cycles",
)
scaleup_events = Counter(
    "finops_scaleup_events_total",
    "Number of completed scale-up / restore cycles",
)
deployments_scaled = Counter(
    "finops_deployments_scaled_total",
    "Deployments scaled down, partitioned by namespace",
    ["namespace"],
)
nodes_cordoned = Gauge(
    "finops_nodes_cordoned",
    "Number of nodes currently cordoned by the scaler",
)
replicas_saved = Gauge(
    "finops_replicas_saved",
    "Total replica count held in the state store (sum across all deployments)",
)
controller_errors = Counter(
    "finops_controller_errors_total",
    "Unhandled errors caught in the main control loop",
)


def start_metrics_server(port: int):
    start_http_server(port)
    logger.info("Prometheus metrics server started on :%d/metrics", port)
