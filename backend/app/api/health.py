"""Health router: DB / queue / telemetry readiness (R29.4).

Exposes ``GET /health`` from the design's "Added endpoints": an aggregate
readiness probe reporting the status of the three external dependencies the
platform relies on (R29.4):

* **database** — a trivial ``SELECT 1`` against the async engine confirms the
  connection pool can reach PostgreSQL.
* **task_queue** — the Celery broker connection is probed (best-effort, with a
  short timeout) so a wedged broker surfaces as degraded rather than silently
  dropping async work.
* **telemetry** — the ``market_telemetry_cache`` is inspected for any row whose
  source was last marked unavailable (R13.4), reflecting whether external
  telemetry feeds are currently healthy.

The endpoint never raises: each probe is isolated so one failing dependency
reports ``"down"`` for that component while the others still report accurately.
The top-level ``status`` is ``"ok"`` only when every component is healthy, else
``"degraded"`` — the body always renders so a load balancer / smoke test can read
the per-component detail.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger

router = APIRouter(tags=["system"])

_log = get_logger("health")

_STATUS_UP = "up"
_STATUS_DOWN = "down"


class ComponentHealth(BaseModel):
    """Readiness of a single external dependency."""

    status: str = Field(description='"up" or "down".')
    detail: str | None = None


class HealthResponse(BaseModel):
    """Aggregate readiness across DB, task queue, and telemetry (R29.4)."""

    status: str = Field(description='"ok" when all components are up, else "degraded".')
    service: str
    database: ComponentHealth
    task_queue: ComponentHealth
    telemetry: ComponentHealth


async def _check_database() -> ComponentHealth:
    """Probe DB connectivity with a trivial query (R29.4)."""
    try:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return ComponentHealth(status=_STATUS_UP)
    except Exception as exc:  # noqa: BLE001 - report, never raise
        _log.warning("health_db_down error=%s", exc)
        return ComponentHealth(status=_STATUS_DOWN, detail="database unreachable")


def _check_task_queue() -> ComponentHealth:
    """Probe the Celery broker connection, best-effort (R29.4).

    Opens and immediately releases a broker connection with a short timeout. A
    broker that is unconfigured or unreachable reports ``down`` rather than
    failing the whole probe.
    """
    try:
        from app.tasks.celery_app import get_celery_app

        app = get_celery_app()
        conn = app.connection()
        try:
            conn.ensure_connection(max_retries=1, timeout=2)
        finally:
            conn.release()
        return ComponentHealth(status=_STATUS_UP)
    except Exception as exc:  # noqa: BLE001 - report, never raise
        _log.warning("health_queue_down error=%s", exc)
        return ComponentHealth(status=_STATUS_DOWN, detail="broker unreachable")


async def _check_telemetry() -> ComponentHealth:
    """Report whether external telemetry feeds are currently healthy (R13.4, R29.4).

    Reads the ``market_telemetry_cache`` for any row flagged
    ``source_available = False`` by the most recent poll. Presence of such a row
    marks telemetry ``down`` (feeds degraded but cache retained); no such row (or
    an empty cache) reports ``up``.
    """
    try:
        from app.models.market_telemetry_cache import MarketTelemetryCache

        session_factory = get_sessionmaker()
        async with session_factory() as session:
            stmt = select(MarketTelemetryCache.telemetry_id).where(
                MarketTelemetryCache.source_available.is_(False)
            ).limit(1)
            result = await session.execute(stmt)
            unavailable = result.first() is not None
        if unavailable:
            return ComponentHealth(
                status=_STATUS_DOWN, detail="one or more telemetry sources unavailable"
            )
        return ComponentHealth(status=_STATUS_UP)
    except Exception as exc:  # noqa: BLE001 - report, never raise
        _log.warning("health_telemetry_unknown error=%s", exc)
        return ComponentHealth(status=_STATUS_DOWN, detail="telemetry status unknown")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Aggregate readiness probe for DB, task queue, and telemetry (R29.4)."""
    settings = get_settings()
    database = await _check_database()
    task_queue = _check_task_queue()
    telemetry = await _check_telemetry()

    all_up = all(
        c.status == _STATUS_UP for c in (database, task_queue, telemetry)
    )
    return HealthResponse(
        status="ok" if all_up else "degraded",
        service=settings.app_name,
        database=database,
        task_queue=task_queue,
        telemetry=telemetry,
    )
