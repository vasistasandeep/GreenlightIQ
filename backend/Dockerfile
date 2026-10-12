# syntax=docker/dockerfile:1

# =============================================================================
# CineROI AI backend image (FastAPI + Celery) — Requirement 18.2, 18.3
# =============================================================================
# A single image serves both roles in docker-compose.yml:
#   * the API service      -> `uvicorn app.main:app`
#   * the Celery worker(s)  -> `celery -A app.tasks.celery_app:get_celery_app ...`
# The command is supplied by compose, so the image only needs the installed
# package plus the application source.
# =============================================================================

FROM python:3.11-slim AS base

# - PYTHONDONTWRITEBYTECODE: no .pyc files in the image layer
# - PYTHONUNBUFFERED: stream stdout/stderr straight to the container logs
# - PIP_NO_CACHE_DIR: keep the image small
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq runtime is needed by psycopg; curl powers the container HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependency layer: copy only the project metadata first so `pip install` is
# cached and re-runs only when dependencies change, not on every source edit.
# ---------------------------------------------------------------------------
COPY backend/pyproject.toml backend/README.md ./
# An empty package tree lets `pip install .` resolve the project before the
# real sources are copied, keeping the dependency layer cacheable.
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install .

# ---------------------------------------------------------------------------
# Application + database layers.
#   - backend/app : the FastAPI/Celery application package
#   - database/   : Alembic migrations + seed scripts, invoked at startup to
#                   initialize the schema and load mock data (R18.4).
# ---------------------------------------------------------------------------
COPY backend/app ./app
COPY database /database

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /database
USER appuser

EXPOSE 8000

# Default to the API server; compose overrides `command` for the Celery worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
