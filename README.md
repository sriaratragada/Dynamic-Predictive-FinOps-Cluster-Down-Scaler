# Dynamic Predictive FinOps Cluster Down-Scaler

> **Automatically hibernate your Kubernetes cluster during off-hours — then wake it back up before your team arrives.**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)
![Kubernetes](https://img.shields.io/badge/Kubernetes-operator-326CE5?style=flat&logo=kubernetes&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat&logo=fastapi&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-metrics-E6522C?style=flat&logo=prometheus&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-pricing-FF9900?style=flat&logo=amazon-aws&logoColor=white)
![GCP](https://img.shields.io/badge/GCP-pricing-4285F4?style=flat&logo=google-cloud&logoColor=white)
![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?style=flat&logo=github-actions&logoColor=white)

| | | | |
|:---:|:---:|:---:|:---:|
| **Save up to 70% overnight** | **Zero-downtime scale-up** | **AWS EKS + GCP GKE** | **Configure from the browser** |
| Idle nodes cordoned + workloads scaled to zero during off-hours | Pre-warm fires 15 min before business hours — cluster ready on time | Native cloud provider connect — enter credentials, pick a cluster, done | Live settings panel — no YAML or env vars needed |

---

## Quick start

**No Kubernetes, no Prometheus, no cloud account required — just Docker:**

```bash
git clone <repo-url>
cd DynaPredictingDownScaler
docker compose up        # or:  make demo
```

Open **http://localhost:8090** — a fully live dashboard backed by synthetic cluster data, with 30 days of pre-seeded savings history and scale-down/up events on the chart.

**macOS / Linux — hot-reload dev (backend + frontend in one command):**

```bash
make dev
# backend → http://localhost:8090   (FastAPI, auto-reloads on save)
# frontend → http://localhost:5173  (Vite, HMR)
```

**Windows:**

```powershell
make dev-win   # opens backend and frontend in separate PowerShell windows
```

See **[SETUP.md](SETUP.md)** for all setup paths including full cluster deployment and Prophet ML mode.

---

## What it does

- **☁️ Native cloud connect** — enter AWS IAM credentials to browse and connect to EKS clusters, or drop in a GCP service account JSON for GKE — no manual kubeconfig wrangling; EKS tokens auto-refresh every 13 minutes
- **⏰ Schedule-based hibernation** — evaluates a timezone-aware business-hours window (Mon–Fri 07:00–19:00 by default) every 60 seconds
- **🔮 Prophet ML forecasting** *(optional)* — trains a Facebook Prophet time-series model on your Prometheus history; predicts idle windows from actual usage patterns instead of a fixed clock
- **📊 Quiet-day detection** *(optional)* — if live CPU drops below 10 % of a 7-day rolling baseline during business hours, treats it as idle (handles bank holidays automatically)
- **🔒 Safe scale-down** — only targets Deployments labelled `finops.io/scaledown-eligible=true`; PDB-safe eviction with 5-minute drain timeout
- **🏷 Namespace auto-labeller** *(optional)* — annotate a namespace with `finops.io/scaledown-namespace=true` and the controller automatically labels all its Deployments; no per-Deployment YAML changes needed
- **🔗 HPA suspend/resume** — sets HPA `minReplicas: 0` on scale-down so HPAs can't fight the controller; restores the original value on scale-up
- **🌅 Pre-warm** — uncordons nodes and restores replica counts `PREWARM_MINUTES` (default 15) before the active window opens
- **💰 Real-time cost tracking** — prices each cordon/uncordon cycle against live AWS/GCP rates; accumulates totals (all-time / this week / this month)
- **📋 Audit log** — every cordon/uncordon event is recorded with timestamps, duration, and dollars saved; exposed via `GET /api/events` and visible in the dashboard
- **💾 Restart-safe** — all state persisted in a Kubernetes ConfigMap; survives controller pod restarts
- **🧪 Demo mode** — full synthetic cluster simulation; no Kubernetes or Prometheus needed
- **⚡ Smart Pre-Warm Engine** *(optional, high-conversion pages only)* — watches for early user-intent signals (login, hover, input focus) and proactively boots Knative AI containers before the user submits a prompt; eliminates cold-start latency on the pages where it costs the most
- **🗳 Leader election** — `coordination.k8s.io/v1` Lease ensures only one replica runs the control loop; set `replicaCount: 2` in Helm for zero-downtime HA
- **📣 Kubernetes Events** — every scale-down, scale-up, cordon, and uncordon fires a native K8s Event visible via `kubectl get events -n kube-system`
- **🔔 Webhook notifications** — Slack-compatible HTTP POST on every scale event; works with Slack Incoming Webhooks, PagerDuty, or any HTTP receiver
- **✅ Pre-flight validation** — structured PASS/WARN/FAIL checks at startup: schedule sanity, Prometheus reachability, eligible deployment count, Prophet install, HPA RBAC, and state ConfigMap

---

## Configuring

No YAML or environment variable editing required. Click **⚙ Settings** in the dashboard header to configure everything from the browser:

| Section | What you set |
|:--------|:-------------|
| **Cluster Connection** | Choose provider (Kubeconfig / AWS EKS / GCP GKE) · enter credentials · one-click connect · "Get credentials" sidebar with step-by-step setup |
| **Scale Schedule** | Business hours · active days · timezone · pre-warm minutes |
| **Data Source** | Toggle demo mode · Prometheus URL |
| **Controller** | Namespace filter · min replica floor · poll interval |
| **Prediction** | Metric override · Prophet ML on/off · training window · idle threshold · AI Pre-Warm Engine |
| **Fine-tuning** | Node utilisation threshold · advanced controller options |

Changes apply immediately — no restart needed. For Docker and Helm deployments, environment variables and `.env` file options are documented in [SETUP.md](SETUP.md).

---

## Deployment paths

| | No cluster | Real cluster | Real cluster + ML |
|:--|:--:|:--:|:--:|
| **Docker demo** (`docker compose up`) | ✅ synthetic data | — | — |
| **Web service** (`docker run` + paste kubeconfig) | — | ✅ no in-cluster install | ✅ |
| **In-cluster — Helm** (`helm install`) | — | ✅ recommended | ✅ |
| **In-cluster — manifests** (`kubectl apply`) | — | ✅ | ✅ |

See [SETUP.md](SETUP.md) for step-by-step instructions for every path.

---

## Architecture

See **[OVERVIEW.md](OVERVIEW.md)** for the decision algorithm, system architecture diagram, tech stack breakdown, and Prometheus metrics.

---

## Project layout

```
DynaPredictingDownScaler/
├── controller/
│   ├── main.py              # Control loop — _tick() every 60 s
│   ├── predictor.py         # Schedule + metric-override + Prophet gate
│   ├── prophet_predictor.py # ProphetPredictor — train, forecast, cache
│   ├── scaler.py            # Deployment replica mgmt + HPA suspend/resume
│   ├── auto_labeller.py     # Namespace-annotation-driven deployment labeller
│   ├── node_manager.py      # Node cordon · drain · uncordon
│   ├── state_store.py       # ConfigMap persistence (replicas · nodes · HPA state)
│   ├── metrics.py           # Prometheus HTTP client (query + query_range)
│   ├── telemetry.py         # Self-expose finops_* metrics on :8080/metrics
│   ├── config.py            # Env-var backed Config dataclass
│   ├── preflight.py         # Startup PASS/WARN/FAIL checks (schedule · prom · RBAC · prophet)
│   ├── k8s_events.py        # Native K8s Event emitter (scale/cordon transitions)
│   ├── webhook.py           # Slack-compatible HTTP POST notifier (fire-and-forget)
│   ├── leader_election.py   # coordination.k8s.io/v1 Lease — HA leader election
│   └── demo_stub.py         # Synthetic K8s + Prometheus stubs (DEMO_MODE)
├── dashboard/
│   ├── backend/
│   │   ├── app.py              # FastAPI — 15 routes + React SPA serving
│   │   ├── auth.py             # Bearer-token middleware (API_TOKEN)
│   │   ├── cloud_providers.py  # EKS/GKE cluster discovery, kubeconfig generation, STS token
│   │   ├── config_store.py     # Hot-patchable DashboardConfig (GET/PATCH /api/config)
│   │   ├── controller_runner.py# Embedded controller loop + EKS token auto-refresh thread
│   │   ├── demo_stub.py        # DemoK8sReader + synthetic Prometheus responses
│   │   ├── prewarm.py          # PrewarmController — warm cache + async Knative ping
│   │   ├── k8s_client.py       # Read state + savings ConfigMaps · list nodes
│   │   ├── savings_tracker.py  # Async cordon-transition cost accumulator
│   │   └── pricing.py          # AWS / GCP / manual pricing with 1-hour cache
│   ├── frontend/src/
│   │   ├── App.tsx                     # Polling · settings state · layout
│   │   ├── api.ts                      # Typed fetch helpers + all interface types
│   │   ├── hooks/
│   │   │   └── useAnimatedValue.ts     # rAF-based easing hook for animated KPI numbers
│   │   └── components/
│   │       ├── MetricsBar.tsx          # 4-tile animated KPI bar (saved/month/rate/cordoned)
│   │       ├── NodeTopology.tsx        # Physics-based SVG force graph — CPU arcs, cordon hatch, drag
│   │       ├── DemandCapacityChart.tsx # Recharts ComposedChart + event markers
│   │       ├── AuditLog.tsx            # Cordon event history table (reverse-chron)
│   │       ├── ClusterPage.tsx         # Cluster Connection page — hero connect, provider cards, credentials drawer
│   │       ├── ConnectCard.tsx         # Inline connect card (demo banner flow)
│   │       ├── ConnectPanel.tsx        # Header drawer — connection method only
│   │       ├── DashboardConfig.tsx     # Controller dashboard config (schedule section)
│   │       ├── SettingsPanel.tsx       # Slide-in fine-tuning drawer
│   │       ├── DemoBanner.tsx          # "Running in demo mode" — opens Cluster page
│   │       └── Toggle.tsx              # Animated accessible toggle switch
│   └── Dockerfile               # Node 20-alpine builds React → Python 3.12-slim serves
├── helm/finops-scaler/          # Helm chart (values.yaml + 6 templates)
├── manifests/                   # Raw Kubernetes YAML (controller + dashboard)
├── tests/                       # 168 pytest tests · freezegun · pytest-mock
├── scripts/
│   ├── dev.sh                   # One-command local dev (macOS/Linux)
│   └── dev.ps1                  # One-command local dev (Windows)
├── docker-compose.yml           # Demo mode default · 'full' profile adds controller
├── Makefile                     # make demo · dev · build · test · stop · logs
├── .env.example                 # Annotated env var template
├── requirements.txt             # Controller dependencies
├── requirements-prophet.txt     # Optional: prophet + pandas
├── requirements-dev.txt         # Test dependencies
├── OVERVIEW.md                  # Architecture, diagrams, tech stack
└── SETUP.md                     # Full installation guide
```

---

## Verify it's working

```bash
curl http://localhost:8090/health               # {"status":"ok"}
curl http://localhost:8090/api/status           # cluster state JSON
curl http://localhost:8090/api/savings          # cost savings JSON
curl http://localhost:8090/api/events           # cordon/uncordon audit log
curl http://localhost:8090/api/config           # live configuration
curl http://localhost:8090/api/controller       # embedded controller loop status
```

**Label individual workloads** for scale-down eligibility (full cluster mode):

```bash
kubectl label deployment my-api finops.io/scaledown-eligible=true
```

**Or opt in a whole namespace** using the auto-labeller (set `ENABLE_AUTO_LABEL=true`):

```bash
kubectl annotate namespace staging finops.io/scaledown-namespace=true
# → controller auto-labels every Deployment in that namespace each tick
```
