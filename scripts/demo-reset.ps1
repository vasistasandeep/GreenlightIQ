# =============================================================================
# CineROI AI - DEMO STATE RESET (Windows / PowerShell)
# =============================================================================
# Wipes the demo-mutable tables and re-applies the pristine seed so you can
# present again from a clean slate after creating test titles, running
# overrides, calibrations, or sign-offs. Fast (no rebuild): truncates + reseeds
# in place against the running `db` container. The stack must already be up.
#   Usage:  ./scripts/demo-reset.ps1
# =============================================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$seed = Join-Path $root "database/seed/02_seed_data.sql"
if (-not (Test-Path $seed)) { Write-Host "Seed file not found: $seed" -ForegroundColor Red; exit 1 }

Write-Host "`n==> Resetting CineROI AI demo state to the pristine seed..." -ForegroundColor Cyan

$truncate = "TRUNCATE TABLE audit_log, approval_actions, approval_workflows, historical_ground_truth, financial_projections, metadata_vectors, title_versions, titles, jobs, model_versions, exchange_rates, subscriber_clusters, users RESTART IDENTITY CASCADE;"

Write-Host "   - truncating seed-owned tables" -ForegroundColor DarkGray
docker compose exec -T db psql -U cineroi -d cineroi -q -c $truncate | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Truncate failed. Is the stack up? (./scripts/demo-up.ps1)" -ForegroundColor Red; exit 1 }

# Copy the seed into the db container and run it with psql -f. This avoids
# streaming a large file over a shell pipe (which can truncate) and any
# working-directory ambiguity with stdin redirection.
Write-Host "   - re-applying the seed" -ForegroundColor DarkGray
docker compose cp $seed db:/tmp/seed.sql | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Could not copy seed into the db container." -ForegroundColor Red; exit 1 }
docker compose exec -T db psql -U cineroi -d cineroi -q -v ON_ERROR_STOP=1 -f /tmp/seed.sql | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Seed re-apply failed." -ForegroundColor Red; exit 1 }

$titles = (docker compose exec -T db psql -U cineroi -d cineroi -t -A -c "SELECT count(*) FROM titles;").Trim()
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Demo state reset. Pristine titles in pipeline: $titles" -ForegroundColor Green
Write-Host "   Open http://localhost:3000/dashboard" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Green