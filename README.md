# CineROI AI

Internal decision-support platform for OTT programming executives, content
buyers, and data science teams. CineROI AI ingests content manifests, extracts
semantic metadata vectors, evaluates titles against quantitative financial
guardrails, produces greenlight recommendations, and backtests predictions
against historical ground truth to auto-calibrate the model.

## Monorepo layout

```
/
├── backend/            # FastAPI (async) service — API, engines, pure domain functions
│   └── Dockerfile      #   API + Celery worker image
├── frontend/           # Next.js (App Router) + TypeScript UI
│   └── Dockerfile      #   standalone production image
├── database/           # Alembic migrations + schema init / seed scripts
├── docker-compose.yml  # orchestrates Postgres+pgvector, Redis, backend, worker, frontend
├── presentation/       # self-contained interactive overview deck (index.html)
└── README.md
```

See `backend/README.md`, `frontend/README.md`, and `database/README.md` for
deeper per-service detail.

## Architecture at a glance

Three deployable units plus an async worker fleet:

| Service    | Image / build        | Port | Role |
|------------|----------------------|------|------|
| `db`       | `pgvector/pgvector:pg16` | 5432 | PostgreSQL 16 + pgvector (1536-dim embeddings, cosine search) |
| `redis`    | `redis:7-alpine`     | 6379 | Celery broker (db 0) + result backend (db 1) |
| `db-init`  | `backend/Dockerfile` | —    | One-shot: `alembic upgrade head` + seed scripts, then exits |
| `backend`  | `backend/Dockerfile` | 8000 | FastAPI API; `GET /health` reports DB / queue / telemetry status |
| `worker`   | `backend/Dockerfile` | —    | Celery worker across `ingest`, `extract`, `audit`, `telemetry` queues |
| `frontend` | `frontend/Dockerfile`| 3000 | Next.js executive decision-support UI |

Heavy operations (batch ingestion, feature extraction, backtest audits,
telemetry polling) run asynchronously on the Celery workers; interactive reads
and single-title valuations run synchronously in the API.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 24+ and the Docker Compose v2
  plugin (`docker compose`).
- Ports `3000`, `5432`, `6379`, and `8000` free on the host (adjust the
  `ports` mappings in `docker-compose.yml` if any are taken).

## Quick start (Docker Compose)

From the repo root:

```bash
docker compose up --build
```

On first boot the stack:

1. Starts **PostgreSQL + pgvector** and **Redis**, waiting until both report
   healthy.
2. Runs the **`db-init`** one-shot job, which executes
   `python /database/seed/seed.py` — `alembic upgrade head` to build the schema,
   then `database/seed/01_schema.sql` (pgvector + subscriber clusters) and the
   generated `database/seed/02_seed_data.sql` (users per role, an active model
   version, exchange rates, titles with vectors / projections / license terms,
   and subscriber-cluster preference vectors).
3. Starts the **backend** API and the **Celery worker**, each waiting for
   `db-init` to complete successfully.
4. Starts the **frontend**.

Once healthy:

- Frontend UI: <http://localhost:3000>
- Backend API: <http://localhost:8000>
- Health probe: <http://localhost:8000/health>
- OpenAPI docs: <http://localhost:8000/docs>

Verify readiness:

```bash
curl http://localhost:8000/health
```

A healthy response reports `status: "ok"` with per-component `database`,
`task_queue`, and `telemetry` detail.

### Common operations

```bash
# Rebuild images after dependency changes
docker compose build

# Follow logs for one service
docker compose logs -f backend

# Re-run DB initialization / re-seed (idempotent SQL)
docker compose run --rm db-init

# Stop the stack (keeps the database volume)
docker compose down

# Stop and wipe the database volume for a clean re-init
docker compose down -v
```

The PostgreSQL data lives in the named volume `pgdata`; because the seed SQL is
idempotent (`CREATE ... IF NOT EXISTS`, deterministic PKs with
`ON CONFLICT DO NOTHING`), re-running `db-init` against an existing database is
safe.

## Environment configuration

Compose supplies in-cluster defaults, so no `.env` file is required to boot
locally. Override any value by creating a root `.env` file (read automatically
by `docker compose`) or by exporting variables in your shell. Templates live at
`backend/.env.example` and `frontend/.env.example`.

| Variable | Default (compose) | Purpose |
|----------|-------------------|---------|
| `CINEROI_ENVIRONMENT` | `development` | Deployment environment label |
| `CINEROI_DEBUG` | `false` | FastAPI debug mode |
| `CINEROI_DATABASE_URL` | `postgresql+psycopg://cineroi:cineroi@db:5432/cineroi` | Async Postgres DSN (points at the `db` service) |
| `CINEROI_BROKER_URL` | `redis://redis:6379/0` | Celery broker |
| `CINEROI_RESULT_BACKEND_URL` | `redis://redis:6379/1` | Celery result backend |
| `CINEROI_SECRET_KEY` | `change-me-in-production` | Session / token signing secret — **set a real value in production** |
| `CINEROI_SESSION_IDLE_TIMEOUT_MINUTES` | `30` | Session idle expiry |
| `CINEROI_ENCRYPTION_KEY` | _(unset)_ | Fernet key for encryption at rest; generate with the command below |
| `CINEROI_ENCRYPTION_REQUIRED` | `false` (dev) | When `true`, using an encrypted column without a key is a hard error — **set `true` in production** |
| `CINEROI_LOG_LEVEL` | `INFO` | Log level |
| `CINEROI_LOG_JSON` | `true` | Emit structured JSON logs |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend base URL baked into the frontend at build time |

Generate an encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Production notes.** Replace `CINEROI_SECRET_KEY`, set
> `CINEROI_ENCRYPTION_REQUIRED=true` with a real `CINEROI_ENCRYPTION_KEY`,
> change the PostgreSQL credentials in `docker-compose.yml`, and front the stack
> with TLS termination. The `NEXT_PUBLIC_API_BASE_URL` build arg must point at
> the browser-reachable backend URL (it is embedded in the client bundle, not
> read at runtime).

## Local development without Docker

Run the services directly for a faster edit loop. You still need a reachable
PostgreSQL 16 + pgvector and Redis (the `db` and `redis` compose services work
well for this: `docker compose up db redis`).

```bash
# Backend
cd backend
pip install -e ".[dev]"
export CINEROI_DATABASE_URL=postgresql+psycopg://cineroi:cineroi@localhost:5432/cineroi
python ../database/seed/seed.py          # migrate + seed
uvicorn app.main:app --reload

# Celery worker (separate shell)
cd backend
celery -A app.tasks.celery_app:get_celery_app worker \
  --loglevel=info --queues=ingest,extract,audit,telemetry

# Frontend (separate shell)
cd frontend
npm install
npm run dev
```

## Tests

```bash
# Backend: unit + property-based (Hypothesis) tests
cd backend && pytest

# Frontend: type check + lint
cd frontend && npm run typecheck && npm run lint
```

Integration tests marked `@pytest.mark.integration` require a reachable
PostgreSQL 16 + pgvector instance (via Docker/testcontainers or
`CINEROI_DATABASE_URL`) and skip cleanly when none is available.

## Documentation & demo deck

- **Interactive overview deck**: a self-contained 13-slide HTML presentation
  (`presentation/index.html`) that walks anyone through the product, including a
  draggable live verdict demo. Published at
  <https://vasistasandeep.github.io/GreenlightIQ> (push to `main`
  to update). It uses illustrative sample data, not production figures; see
  `presentation/SPEAKER_NOTES.md` for controls and the live-portal link setup.
- **Knowledge base**: `CineROI_AI_Complete_Knowledge_Base.md` (full reference).
- **Architecture & data flow**: `CineROI_AI_Architecture_And_Data_Flow.md`.
- **Calculations reference**: `CineROI_AI_Calculations_Reference.md` (every
  formula, threshold, and worked example). Mirrored in the in-portal **How It
  Works** guide (`/guide`).