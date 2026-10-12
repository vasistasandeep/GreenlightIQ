# CineROI AI — Backend

FastAPI (async) decision-support service for OTT content acquisition, licensing,
greenlighting, and historical backtesting.

## Layout

```
backend/
├── app/
│   ├── api/            # Routers (task 16)
│   ├── core/           # config, settings, logging, security stubs
│   ├── engines/        # ingestion, extraction, vector search, guardrails, ... (tasks 7-15)
│   ├── domain/         # pure functions: cpvh, ltv, mape, currency, windowing (PBT targets, tasks 3-4)
│   ├── models/         # SQLAlchemy ORM models (task 2)
│   ├── schemas/        # Pydantic request/response models (task 16)
│   ├── tasks/          # Celery task definitions (task 15)
│   ├── repositories/   # async DB access layer (task 6)
│   └── main.py         # ASGI app factory
├── tests/              # pytest + hypothesis
└── pyproject.toml
```

## Setup

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health`

## Test

```bash
pytest
```
