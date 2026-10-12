"""Registration entry point for the supporting routers (task 16.2).

Task 16.1 owns ``app/main.py`` and ``app/api/__init__.py``; to avoid stepping on
those files this module exposes a single :func:`register_support_routers` that
``main.py`` (or ``__init__.py``) can call to mount this task's routers in one
line:

    from app.api.support_routers import register_support_routers
    register_support_routers(app)

Routers mounted (design "Added endpoints"):

* jobs       — ``GET /jobs/{id}``, ``POST /jobs/{id}/retry`` (R23.4, R29.5)
* auth       — ``POST /auth/login|logout``, ``GET /auth/session`` (R19)
* decisions  — override / approve / reject / finalization (R20.2, R20.4, R20.5)
* versions   — model-version catalog + ``GET /titles/{id}/versions`` (R26.3, R24.5)
* calibration— ``POST /calibration/apply`` (R12, R16.3)
* audit      — ``GET /audit/lineage/{subject_id}`` (R25.4)
* health     — ``GET /health`` DB/queue/telemetry status (R29.4)

All business routers are mounted under the configured API prefix
(``Settings.api_v1_prefix``, default ``/api/v1``). The health probe is mounted at
the application root (``/health``) per the design's deployment smoke test (R18.4,
R29.4); if the app already exposes a root ``/health`` placeholder it is replaced
so the expanded probe wins.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api import audit, auth, calibration, decisions, health, jobs, versions
from app.core.config import get_settings

__all__ = ["register_support_routers", "build_support_router"]

#: The business routers mounted under the API prefix (health is mounted at root).
_PREFIXED_ROUTERS: tuple[APIRouter, ...] = (
    jobs.router,
    auth.router,
    decisions.router,
    versions.router,
    calibration.router,
)


def build_support_router() -> APIRouter:
    """Return a single combined router of the prefixed supporting endpoints.

    Useful for callers that prefer to ``include_router`` one aggregate router
    (e.g. an ``app.api.__init__`` that composes core + supporting routers under a
    shared prefix) rather than call :func:`register_support_routers` directly.
    The health probe is intentionally excluded here because it mounts at the app
    root, not under the API prefix.
    """
    combined = APIRouter()
    for router in _PREFIXED_ROUTERS:
        combined.include_router(router)
    combined.include_router(audit.router)
    return combined


def register_support_routers(app: FastAPI, *, prefix: str | None = None) -> None:
    """Mount every supporting router onto ``app`` (idempotent-safe).

    Args:
        app: The FastAPI application to mount onto.
        prefix: API prefix for the business routers; defaults to
            ``Settings.api_v1_prefix`` (``/api/v1``).
    """
    api_prefix = prefix if prefix is not None else get_settings().api_v1_prefix

    for router in _PREFIXED_ROUTERS:
        app.include_router(router, prefix=api_prefix)
    app.include_router(audit.router, prefix=api_prefix)

    _mount_health(app)


def _mount_health(app: FastAPI) -> None:
    """Mount the expanded ``/health`` probe at the app root (R29.4).

    If a prior ``/health`` route exists (e.g. the bootstrap placeholder in the
    app factory), drop it first so the expanded DB/queue/telemetry probe is the
    one that answers.
    """
    existing = [
        r
        for r in app.router.routes
        if getattr(r, "path", None) == "/health"
    ]
    for route in existing:
        app.router.routes.remove(route)
    app.include_router(health.router)
