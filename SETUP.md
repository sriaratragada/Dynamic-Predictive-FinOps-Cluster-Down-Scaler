# Setup & Installation Guide

---

## Which path?

| Path | When to use | Command |
|:-----|:-----------|:--------|
| **Docker demo** | See it immediately, no installs | `docker compose up` |
| **Web service** | Connect any cluster from the browser, no in-cluster install | `docker run -p 8090:8090 ghcr.io/your-org/finops-scaler:latest` |
| **Local dev** | Hot-reload development | `make dev` / `make dev-win` |
| **In-cluster — Helm** | Production; recommended | `helm install finops-scaler ./helm/finops-scaler` |
| **In-cluster — manifests** | Production; manual YAML | `kubectl apply -f manifests/` |

---

## Prerequisites

| Requirement | Demo | Web Service | Local Dev | In-Cluster |
|:-----------|:----:|:-----------:|:---------:|:----------:|
| Docker Desktop | ✅ | ✅ | ❌ | ❌ |
| Python 3.10+ | ❌ | ❌ | ✅ | ✅ |
| Node.js 18+ | ❌ | ❌ | ✅ | ❌ |
| Kubernetes cluster | ❌ | ✅ external | ❌ | ✅ |
| Prometheus | ❌ | optional | ❌ | ✅ |
| AWS or GCP account | ❌ | optional | ❌ | optional |

---

## 1 — Docker demo

No Python, Node.js, Kubernetes, or Prometheus needed.

```bash
git clone <repo-url>
cd DynaPredictingDownScaler
docker compose up          # or:  make demo
```

Open **http://localhost:8090** — pre-seeded with 30 days of savings history and a synthetic 3-node cluster.

```bash
docker compose down        # stop
```

---

## 2 — Web service mode

Run one container outside the cluster. Connect to any Kubernetes cluster from the browser — paste a kubeconfig, or authenticate natively with AWS EKS or GCP GKE.

```bash
docker run -p 8090:8090 ghcr.io/your-org/finops-scaler:latest
```

Open **http://localhost:8090** → navigate to the **// CONN** tab.

**Three connection methods:**

| Method | What you provide |
|:-------|:-----------------|
| **Kubeconfig** | Paste raw kubeconfig YAML |
| **AWS EKS** | IAM access key + secret → pick cluster from list |
| **GCP GKE** | Service account JSON key → pick cluster from list |

EKS STS bearer tokens (valid 15 min) are auto-refreshed every 13 min — no reconnect needed.

**API endpoints for web service mode:**

| Method | Path | Description |
|:-------|:-----|:------------|
| `POST` | `/api/connect` | Kubeconfig YAML → validate + start loop |
| `POST` | `/api/connect/eks` | IAM key → EKS kubeconfig → start loop |
| `POST` | `/api/connect/gke` | Service account JSON → GKE kubeconfig → start loop |
| `POST` | `/api/aws/clusters` | List EKS clusters by region |
| `POST` | `/api/gcp/clusters` | List GKE clusters by project/location |
| `GET` | `/api/controller` | Loop status (connected, running, last tick, error) |
| `POST` | `/api/controller/stop` | Stop loop, keep connection |

**Verify:**

```bash
curl http://localhost:8090/api/controller
# {"running": true, "connected": true, "last_action": "no-op", "error": null}
```

**Web service vs in-cluster:**

| Capability | Web Service | In-Cluster |
|:-----------|:-----------:|:----------:|
| Schedule-based scale-down | ✅ | ✅ |
| Savings tracking | ✅ (file) | ✅ (ConfigMap) |
| HPA suspend/resume | ❌ | ✅ |
| Leader election (HA) | ❌ | ✅ |
| Webhook notifications | ❌ | ✅ |
| Prophet ML | ❌ | ✅ |

---

## 3 — Local dev

Hot-reload backend + frontend together. Requires Python 3.10+ and Node 18+.

```bash
make dev          # macOS/Linux — backend :8090 + frontend :5173, Ctrl+C stops both
make dev-win      # Windows — opens each in a separate PowerShell window
```

Without make:

```bash
bash scripts/dev.sh                                                  # macOS/Linux
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1             # Windows
```

Vite proxies all `/api/*` requests to `:8090` — no CORS config needed.

---

## 4 — Settings UI

Once the dashboard is open, click the **// CONN** nav tab for cluster connection or **⚙ Settings** for fine-tuning.

**Cluster Connection page:**

| Section | What you configure |
|:--------|:------------|
| **Connection method** | Kubeconfig / AWS EKS / GCP GKE · credentials · one-click connect |
| **Get credentials** | Step-by-step sidebar for each provider |
| **Scale schedule** | Business hours · active days · timezone · pre-warm minutes |
| **Data source** | Demo mode toggle · Prometheus URL |
| **Controller settings** | Namespace filter · min replica floor · poll interval |

**Settings drawer (⚙ button):**

| Section | What you configure |
|:--------|:------------|
| **// PRED** | Metric override · Prophet ML · training weeks · idle threshold |
| **// UI** | Node utilisation threshold · display options |

Changes apply immediately — no restart needed.

---

## 5 — Prophet ML mode

Prophet trains on your Prometheus history and learns your actual idle patterns, handling bank holidays and irregular demand automatically. Requires ≥ 4 weeks of Prometheus data.

**Install:**

```bash
pip install -r requirements-prophet.txt
# First install takes 2–5 min (Stan compilation)
```

**Run:**

```bash
ENABLE_PROPHET=true PROMETHEUS_URL=http://localhost:9090 python -m controller.main
```

**Tune:**

- Prophet marks too many hours as idle → raise `PROPHET_IDLE_THRESHOLD_CORES` (e.g. `2.0`)
- Prophet never triggers → lower it (e.g. `0.3`)
- Falls back automatically to schedule-based predictor if training fails or data is insufficient

---

## 6 — In-cluster deployment

### Label your workloads

```bash
# Option A — individual deployments:
kubectl label deployment my-api finops.io/scaledown-eligible=true

# Option B — entire namespace (auto-labeller):
#   Set ENABLE_AUTO_LABEL=true, then annotate the namespace:
kubectl annotate namespace staging finops.io/scaledown-namespace=true
```

### Helm (recommended)

```bash
helm install finops-scaler ./helm/finops-scaler \
  --set config.prometheusUrl=http://prometheus-operated.monitoring.svc.cluster.local:9090 \
  --set config.timezone=America/New_York \
  --set config.businessHoursStart=08:00 \
  --set config.businessHoursEnd=18:00

# Enable Prophet ML:
helm upgrade finops-scaler ./helm/finops-scaler --set config.enableProphet=true

# Enable auto-labeller:
helm upgrade finops-scaler ./helm/finops-scaler --set config.enableAutoLabel=true
```

### Raw manifests

```bash
kubectl apply -f manifests/rbac.yaml
kubectl apply -f manifests/configmap.yaml
kubectl apply -f manifests/deployment.yaml
kubectl apply -f manifests/dashboard-rbac.yaml
kubectl apply -f manifests/dashboard-configmap.yaml
kubectl apply -f manifests/dashboard-deployment.yaml
kubectl apply -f manifests/dashboard-service.yaml
```

### Verify

```bash
kubectl logs -f deployment/finops-scaler -n kube-system
kubectl port-forward svc/finops-dashboard 8090:8090 -n kube-system

curl http://localhost:8090/health           # {"status":"ok"}
curl http://localhost:8090/api/status       # cluster state
curl http://localhost:8090/api/savings      # cost savings
curl http://localhost:8090/api/events       # audit log
```

---

## 7 — Dry-run (recommended before go-live)

```bash
helm upgrade finops-scaler ./helm/finops-scaler --set config.dryRun=true

kubectl logs -f deployment/finops-scaler -n kube-system | grep DRY-RUN
# [DRY-RUN] Would set default/api-server replicas → 0
# [DRY-RUN] Would cordon node-2
```

---

## Makefile reference

```bash
make demo      # docker compose up — demo mode → http://localhost:8090
make full      # docker compose with controller profile
make dev       # hot-reload: backend :8090 + frontend :5173 (macOS/Linux)
make dev-win   # hot-reload: Windows PowerShell
make build     # npm ci + npm run build (production bundle)
make test      # pytest tests/ -v
make stop      # docker compose down
make logs      # docker compose logs -f
make clean     # remove containers, images, dist/
```

---

## Configuration reference

### Schedule

| Variable | Default | Description |
|:---------|:--------|:------------|
| `BUSINESS_HOURS_START` | `07:00` | Active window start (HH:MM) |
| `BUSINESS_HOURS_END` | `19:00` | Active window end (HH:MM) |
| `BUSINESS_DAYS` | `0,1,2,3,4` | Active weekdays (0=Mon…6=Sun) |
| `TIMEZONE` | `UTC` | IANA timezone (e.g. `America/New_York`) |
| `PREWARM_MINUTES` | `15` | Scale-up lead time before window start |

### Scaling

| Variable | Default | Description |
|:---------|:--------|:------------|
| `MIN_REPLICA_FLOOR` | `0` | Floor replicas during scale-down |
| `NODE_UTILISATION_THRESHOLD` | `0.10` | Cordon nodes below this CPU fraction |
| `NAMESPACE_FILTER` | *(all)* | Restrict to one namespace |
| `ENABLE_METRIC_OVERRIDE` | `false` | Quiet-day detection via Prometheus CPU baseline |
| `ENABLE_HPA_SUSPEND` | `true` | Patch HPA `minReplicas: 0` on scale-down; restore on scale-up |
| `ENABLE_AUTO_LABEL` | `false` | Auto-label Deployments in annotated namespaces |
| `ENABLE_K8S_EVENTS` | `true` | Emit native K8s Events for scale/cordon transitions |
| `WEBHOOK_URL` | *(empty)* | Slack-compatible endpoint for scale-event notifications |
| `ENABLE_LEADER_ELECTION` | `true` | Lease-based HA leader election |
| `ENABLE_PREFLIGHT` | `true` | Startup PASS/WARN/FAIL checks |

### Operations

| Variable | Default | Description |
|:---------|:--------|:------------|
| `DRY_RUN` | `false` | Log mutations, apply none |
| `DEMO_MODE` | `false` | Synthetic data, no cluster needed |
| `LOOP_INTERVAL_SECONDS` | `60` | Controller poll cadence |
| `METRICS_PORT` | `8080` | Prometheus scrape port |

### Prophet

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ENABLE_PROPHET` | `false` | Activate ML forecasting |
| `PROPHET_TRAINING_WEEKS` | `4` | Training window length |
| `PROPHET_IDLE_THRESHOLD_CORES` | `0.5` | yhat below this = idle |
| `PROPHET_RETRAIN_HOURS` | `6` | Model refresh interval |

### Pricing

| Variable | Default | Description |
|:---------|:--------|:------------|
| `CLOUD_PROVIDER` | `manual` | `aws` · `gcp` · `manual` |
| `NODE_INSTANCE_TYPE` | — | e.g. `m5.xlarge`, `n2-standard-4` |
| `AWS_REGION` | — | e.g. `us-east-1` |
| `NODE_HOURLY_COST` | `0.192` | Fallback rate (USD/hr per node) |

> All settings can also be configured live via the dashboard — no restart needed.

---

## Troubleshooting

**Dashboard shows no data**

```bash
curl http://localhost:8090/health      # → {"status":"ok"}
curl http://localhost:8090/api/status
```

**"Prophet not installed" warning**

```bash
pip install -r requirements-prophet.txt
# Stan compilation fails on Linux:
sudo apt-get install -y build-essential && pip install pystan==3.8.0 prophet
```

**Controller CrashLoopBackOff**

```bash
kubectl logs deployment/finops-scaler -n kube-system --previous
```

Common causes: RBAC binding missing (`kubectl get clusterrolebinding finops-scaler`), Prometheus unreachable, empty `BUSINESS_DAYS`.

**Dashboard shows $0.00 savings**

The savings tracker accumulates from the first cordon → uncordon cycle. Use demo mode for pre-seeded history.
