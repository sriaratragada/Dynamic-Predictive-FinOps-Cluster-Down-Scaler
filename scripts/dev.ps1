# FinOps Down-Scaler — single-command local dev startup (Windows PowerShell)
# Starts backend and frontend in separate windows, then waits.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#   OR:  make dev-win

$Root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "FinOps Down-Scaler — hot-reload dev mode" -ForegroundColor Green
Write-Host "  Backend  -> http://localhost:8090  (FastAPI + uvicorn)"
Write-Host "  Frontend -> http://localhost:5173  (Vite, proxies /api to :8090)"
Write-Host "  DEMO_MODE=true — synthetic data, no K8s or Prometheus needed" -ForegroundColor Yellow
Write-Host ""

# ── install dependencies ──────────────────────────────────────────────────────
Write-Host "  Checking Python dependencies..." -ForegroundColor Cyan
pip install -q -r "$Root\dashboard\backend\requirements.txt"

Write-Host "  Checking Node dependencies..." -ForegroundColor Cyan
Push-Location "$Root\dashboard\frontend"
npm install --silent
Pop-Location

Write-Host ""
Write-Host "  Starting servers in separate windows. Close them to stop." -ForegroundColor Green
Write-Host ""

# ── backend window ────────────────────────────────────────────────────────────
$backendCmd = @"
`$env:DEMO_MODE='true'
Set-Location '$Root'
uvicorn dashboard.backend.app:app --reload --port 8090 --log-level info
"@

$backendProc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd `
  -PassThru -WindowStyle Normal

# Give uvicorn a moment to bind
Start-Sleep -Seconds 2

# ── frontend window ───────────────────────────────────────────────────────────
$frontendCmd = @"
Set-Location '$Root\dashboard\frontend'
npm run dev
"@

$frontendProc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd `
  -PassThru -WindowStyle Normal

Write-Host "  Backend  PID: $($backendProc.Id)"
Write-Host "  Frontend PID: $($frontendProc.Id)"
Write-Host ""
Write-Host "  Press Enter to stop both servers and exit." -ForegroundColor Yellow
$null = Read-Host

# ── shutdown ──────────────────────────────────────────────────────────────────
Write-Host "  Stopping servers..." -ForegroundColor Cyan
Stop-Process -Id $backendProc.Id  -ErrorAction SilentlyContinue
Stop-Process -Id $frontendProc.Id -ErrorAction SilentlyContinue
Write-Host "  Done." -ForegroundColor Green
