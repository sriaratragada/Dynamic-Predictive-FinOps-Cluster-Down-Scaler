# DynaPredictingDownScaler

A Kubernetes controller that watches Prometheus for cluster activity, predicts upcoming idle windows, and proactively scales down non-essential workloads and cordons underutilised nodes — reversing everything ahead of the next business-hours window.

## How it works

```
Every 60 s (configurable):
  1. Check whether "now" is inside the configured business-hours schedule
  2. If entering an idle window:
       • Scale all opt-in Deployments to MIN_REPLICA_FLOOR
       • Cordon + drain nodes whose CPU is below NODE_UTILISATION_THRESHOLD
  3. PREWARM_MINUTES before the active window restarts:
       • Uncordon previously cordoned nodes
       • Restore all Deployments to their saved replica counts
```

State (original replica counts, list of cordoned nodes) is stored in a ConfigMap so the controller survives pod restarts without losing track.

---

## Prerequisites

- Kubernetes cluster (any distribution)
- Prometheus reachable from inside the cluster (standard `kube-prometheus-stack` endpoint assumed)
- `kubectl` access with cluster-admin to apply RBAC

---

## Quick start

### 1. Build and push the image

```bash
docker build -t finops-scaler:latest .
# Push to your registry if running in a real cluster:
# docker tag finops-scaler:latest <registry>/finops-scaler:latest
# docker push <registry>/finops-scaler:latest
```

### 2. Edit the ConfigMap

Open [`manifests/configmap.yaml`](manifests/configmap.yaml) and set at minimum:

| Key | Default | Description |
|-----|---------|-------------|
| `PROMETHEUS_URL` | `http://prometheus-operated.monitoring…:9090` | Prometheus endpoint |
| `BUSINESS_HOURS_START` | `07:00` | Start of active window (24-h HH:MM) |
| `BUSINESS_HOURS_END` | `19:00` | End of active window |
| `BUSINESS_DAYS` | `0,1,2,3,4` | Active weekdays (0=Mon … 6=Sun) |
| `TIMEZONE` | `UTC` | IANA timezone name |
| `PREWARM_MINUTES` | `15` | Minutes before BH start to begin scale-up |
| `MIN_REPLICA_FLOOR` | `0` | Minimum replicas during off-hours |
| `NODE_UTILISATION_THRESHOLD` | `0.10` | Cordon nodes below this CPU fraction |

### 3. Apply manifests

```bash
kubectl apply -f manifests/rbac.yaml
kubectl apply -f manifests/configmap.yaml
kubectl apply -f manifests/deployment.yaml
```

### 4. Opt in your Deployments

Add this label to any Deployment you want the scaler to manage:

```yaml
metadata:
  labels:
    finops.io/scaledown-eligible: "true"
```

Or patch an existing Deployment:

```bash
kubectl label deployment <name> -n <namespace> finops.io/scaledown-eligible=true
```

---

## Configuration reference

All settings are environment variables injected from `finops-scaler-config` ConfigMap.

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_URL` | `http://prometheus:9090` | Prometheus base URL |
| `BUSINESS_HOURS_START` | `07:00` | Active window start |
| `BUSINESS_HOURS_END` | `19:00` | Active window end |
| `BUSINESS_DAYS` | `0,1,2,3,4` | Comma-separated weekday numbers |
| `PREWARM_MINUTES` | `15` | Pre-warm lead time in minutes |
| `LOOP_INTERVAL_SECONDS` | `60` | Control-loop tick interval |
| `NAMESPACE_FILTER` | _(all)_ | Restrict scaledown to one namespace |
| `MIN_REPLICA_FLOOR` | `0` | Minimum replicas during idle windows |
| `NODE_UTILISATION_THRESHOLD` | `0.10` | CPU fraction below which nodes are cordoned |
| `STATE_CONFIGMAP_NAME` | `finops-scaler-state` | ConfigMap used as state store |
| `STATE_CONFIGMAP_NS` | `kube-system` | Namespace of the state ConfigMap |
| `TIMEZONE` | `UTC` | Schedule timezone (IANA name) |
| `ENABLE_METRIC_OVERRIDE` | `false` | Allow Prometheus data to override schedule |

### Metric override (optional)

When `ENABLE_METRIC_OVERRIDE=true`, the controller also checks the 7-day rolling average of cluster CPU. If live usage drops below 10 % of the baseline *during* business hours, it treats the period as idle and scales down anyway — useful for holiday closures or unexpected quiet days.

---

## Verification

### Smoke-test off-hours scaling

Temporarily shrink the active window to a one-minute range that has already passed:

```bash
kubectl set env deployment/finops-scaler -n kube-system \
  BUSINESS_HOURS_START=00:00 BUSINESS_HOURS_END=00:01
```

Watch logs — eligible Deployments should scale to 0 within 60 s:

```bash
kubectl logs -f deployment/finops-scaler -n kube-system
```

Restore:

```bash
kubectl set env deployment/finops-scaler -n kube-system \
  BUSINESS_HOURS_START=07:00 BUSINESS_HOURS_END=19:00
```

### Pre-warm timing

```bash
kubectl set env deployment/finops-scaler -n kube-system PREWARM_MINUTES=2
```

Check logs confirm scale-up fires 2 minutes before the active window reopens.

### State persistence across restarts

```bash
kubectl delete pod -n kube-system -l app=finops-scaler
kubectl get configmap finops-scaler-state -n kube-system -o yaml
```

The saved replica counts survive the restart and are used to restore Deployments correctly.

### Node cordon verification

```bash
kubectl get nodes
# SchedulingDisabled nodes appear during the idle window
# Ready nodes return after uncordon at pre-warm time
```

### PodDisruptionBudget safety

Create a PDB with `minAvailable: 1` on a single-replica Deployment. The controller will log a warning (`PDB prevented eviction`) and skip that pod rather than crashing.

---

## Project layout

```
DynaPredictingDownScaler/
├── controller/
│   ├── __init__.py
│   ├── main.py          # control loop entry-point
│   ├── config.py        # env-var configuration
│   ├── metrics.py       # Prometheus HTTP API client
│   ├── predictor.py     # schedule-based activity predictor
│   ├── scaler.py        # Deployment replica management
│   ├── node_manager.py  # cordon / drain / uncordon
│   └── state_store.py   # replica-count persistence in a ConfigMap
├── manifests/
│   ├── rbac.yaml        # ServiceAccount + ClusterRole + binding
│   ├── configmap.yaml   # tuning knobs
│   └── deployment.yaml  # controller Deployment
├── Dockerfile
├── requirements.txt
└── README.md
```
