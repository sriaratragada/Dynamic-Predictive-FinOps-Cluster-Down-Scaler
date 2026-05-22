#!/usr/bin/env bash
# FinOps Down-Scaler — single-command local dev startup
# Starts both the backend and frontend dev servers, then cleans up on exit.
# Usage: bash scripts/dev.sh   OR   make dev

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── colours ──────────────────────────────────────────────────────────────────
GRN='\033[0;32m'; CYN='\033[0;36m'; YLW='\033[0;33m'; RST='\033[0m'

echo -e "\n${GRN}FinOps Down-Scaler — hot-reload dev mode${RST}"
echo -e "  Backend  → ${CYN}http://localhost:8090${RST}  (FastAPI + uvicorn)"
echo -e "  Frontend → ${CYN}http://localhost:5173${RST}  (Vite, proxies /api to :8090)"
echo -e "  ${YLW}DEMO_MODE=true${RST} — synthetic data, no K8s or Prometheus needed\n"

# ── install dependencies if needed ──────────────────────────────────────────
echo "  Checking Python dependencies..."
pip install -q -r "$ROOT/dashboard/backend/requirements.txt"

echo "  Checking Node dependencies..."
(cd "$ROOT/dashboard/frontend" && npm install --silent)

echo -e "\n  ${GRN}Starting servers…${RST} (Ctrl+C to stop both)\n"

# ── clean shutdown on exit ────────────────────────────────────────────────────
BACKEND_PID="" FRONTEND_PID=""
cleanup() {
  echo -e "\n  Shutting down…"
  [[ -n "$BACKEND_PID"  ]] && kill "$BACKEND_PID"  2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# ── backend ──────────────────────────────────────────────────────────────────
(
  cd "$ROOT"
  DEMO_MODE=true uvicorn dashboard.backend.app:app \
    --reload \
    --port 8090 \
    --log-level info
) &
BACKEND_PID=$!

# Give uvicorn a moment to bind before Vite starts (avoids confusing startup noise)
sleep 1

# ── frontend ─────────────────────────────────────────────────────────────────
(
  cd "$ROOT/dashboard/frontend"
  npm run dev
) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
