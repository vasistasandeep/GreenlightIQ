#!/usr/bin/env bash
# CineROI AI - one-command demo launcher (Linux/mac/git-bash).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> Checking Docker..."; docker version >/dev/null
echo "==> Building and starting the full stack..."
docker compose up -d --build --wait --wait-timeout 300
echo "==> Verifying health..."
for i in $(seq 1 10); do
  if curl -fsS http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "CineROI AI is UP and healthy."
    echo "  Dashboard : http://localhost:3000/dashboard"
    echo "  Health    : http://localhost:8000/health"
    exit 0
  fi
  sleep 3
done
echo "Health not ok; see: docker compose logs backend" >&2; exit 1