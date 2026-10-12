# CineROI AI - CTO Demo Walkthrough

A fool-proof, one-command demo. Everything below runs locally with Docker; no
secrets, cloud accounts, or external services required.

## Before the meeting (2 minutes)

```powershell
# Windows / PowerShell
./scripts/demo-up.ps1
```

```bash
# macOS / Linux / git-bash
./scripts/demo-up.sh
```

The script builds the stack, waits until every container is healthy, verifies
`GET /health` returns ok, and prints the URLs. If anything fails it prints the
relevant logs and exits non-zero, so you know *before* the meeting, not during.

Open and leave ready:
- **Dashboard**: http://localhost:3000/dashboard
- **Health**: http://localhost:8000/health

## Suggested 5-minute flow

1. **Executive Command Dashboard** (`/dashboard`) - KPI cards (pipeline
   valuation, avg LTV-to-Cost, risk exposure, model accuracy) and the sortable
   asset grid with GREENLIGHT / NEGOTIATE HARD / PASS badges. Click a row.
2. **Title Evaluation** (`/titles/[id]`) - metadata radar, financial accordion
   (CPVH ceiling checks, churn curves, payback timeline), negotiation leverage,
   and the explanation panel showing computed-vs-threshold and the dominant
   factor behind the recommendation.
3. **Backtest & Calibration Studio** (`/backtest`) - submit ground truth, watch
   predicted-vs-actual variance charts, request auto-calibration, and see the
   high-budget sign-off panel (CCO + CFO gating over $25M).
4. **Health endpoint** - show `GET /health` reporting database, task queue, and
   telemetry all up. This is the same probe a load balancer uses.

## If asked "is this production ready?"

Short answer: the application is complete and verified end to end
(property-based tests on the financial core, integration tests, and a live
deployment smoke test). Going live needs real credentials and managed infra -
all abstracted behind clean wiring points and documented in `docs/PRODUCTION.md`
with a pre-launch checklist. There is also a `docker-compose.prod.yml` with
nginx TLS, host/CORS hardening, and a startup guard that refuses to boot with
insecure defaults.

## Reset / stop

```powershell
./scripts/demo-down.ps1            # stop, keep data
./scripts/demo-down.ps1 -Clean     # stop and wipe the DB for a fresh demo
```

## Troubleshooting

- **Docker not running** - the launcher tells you; start Docker Desktop, re-run.
- **Port in use (3000/8000/5432/6379)** - stop the conflicting process or run
  `./scripts/demo-down.ps1` first.
- **First build is slow** - images build once; subsequent runs are seconds.