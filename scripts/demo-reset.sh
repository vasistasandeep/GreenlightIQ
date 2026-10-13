#!/usr/bin/env bash
# =============================================================================
# CineROI AI - DEMO STATE RESET (bash)
# =============================================================================
# Wipes the demo-mutable tables and re-applies the pristine seed so you can
# present again from a clean slate. Fast (no rebuild). The stack must be up.
#   Usage:  ./scripts/demo-reset.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Resetting CineROI AI demo state to the pristine seed..."

docker compose exec -T db psql -U cineroi -d cineroi -q -c \
  "TRUNCATE TABLE audit_log, approval_actions, approval_workflows, historical_ground_truth, financial_projections, metadata_vectors, title_versions, titles, jobs, model_versions, exchange_rates, subscriber_clusters, users RESTART IDENTITY CASCADE;"

docker compose cp database/seed/02_seed_data.sql db:/tmp/seed.sql
docker compose exec -T db psql -U cineroi -d cineroi -q -v ON_ERROR_STOP=1 -f /tmp/seed.sql

titles=$(docker compose exec -T db psql -U cineroi -d cineroi -t -A -c "SELECT count(*) FROM titles;" | tr -d '[:space:]')
echo "============================================================"
echo " Demo state reset. Pristine titles in pipeline: ${titles}"
echo "   Open http://localhost:3000/dashboard"
echo "============================================================"