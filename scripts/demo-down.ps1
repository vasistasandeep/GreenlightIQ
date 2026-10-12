# Stop the CineROI AI demo stack. Add -Clean to also drop the database volume.
param([switch]$Clean)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ($Clean) {
  Write-Host "==> Stopping stack and removing volumes (fresh DB next time)..." -ForegroundColor Yellow
  docker compose down -v
} else {
  Write-Host "==> Stopping stack (database volume preserved)..." -ForegroundColor Yellow
  docker compose down
}
Write-Host "Done." -ForegroundColor Green