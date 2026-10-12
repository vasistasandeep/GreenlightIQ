# =============================================================================
# CineROI AI - one-command DEMO launcher (Windows / PowerShell)
# =============================================================================
# Brings the full stack up, waits until every service is healthy, verifies the
# health endpoint, and prints the URLs. Idempotent and safe to re-run.
#   Usage:  ./scripts/demo-up.ps1
# =============================================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "`n==> CineROI AI demo: checking Docker..." -ForegroundColor Cyan
try { docker version --format '{{.Server.Version}}' | Out-Null }
catch { Write-Host "Docker is not running. Start Docker Desktop and retry." -ForegroundColor Red; exit 1 }

Write-Host "==> Building and starting the full stack (this can take a minute on first run)..." -ForegroundColor Cyan
docker compose up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) {
  Write-Host "`nStack did not come up healthy. Recent logs:" -ForegroundColor Red
  docker compose ps
  docker compose logs --tail 40
  exit 1
}

Write-Host "==> Verifying health endpoint..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
  try {
    $h = (Invoke-WebRequest -UseBasicParsing http://localhost:8000/health -TimeoutSec 5).Content | ConvertFrom-Json
    if ($h.status -eq "ok") { $ok = $true; break }
  } catch {}
  Start-Sleep -Seconds 3
}
if (-not $ok) { Write-Host "Health endpoint not ok. Run: docker compose logs backend" -ForegroundColor Red; exit 1 }

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " CineROI AI is UP and healthy." -ForegroundColor Green
Write-Host "   Dashboard : http://localhost:3000/dashboard"
Write-Host "   API docs  : http://localhost:8000/api/v1/openapi.json"
Write-Host "   Health    : http://localhost:8000/health"
Write-Host "`n Stop with : ./scripts/demo-down.ps1" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Green