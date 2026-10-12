"""API router package and the aggregated core API router (task 16).

Routers are split into the **core** surface (task 16.1) â€” ingestion dispatch,
valuation, backtest audit, and market telemetry â€” and the **supporting** surface
(task 16.2) â€” jobs, auth, approvals, model versions, calibration, audit lineage,
title versions, and health.

:func:`get_core_router` returns an :class:`~fastapi.APIRouter` mounting the core
routers under the ``/api/v1`` prefix; :func:`app.main.create_app` includes it and
registers the shared error-envelope handlers (:func:`register_exception_handlers`)
so every endpoint shares the same auth / RBAC / audit middleware and error shape.
Supporting routers (task 16.2) are mounted alongside via a sibling aggregator.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import backtest, market, quick_evaluate, titles, valuation


def get_core_router() -> APIRouter:
    """Return the aggregated core API router (task 16.1).

    Mounts the documented core routers (titles / valuation / backtest / market).
    The caller includes this under the configured ``/api/v1`` prefix.
    """
    router = APIRouter()
    router.include_router(titles.router)
    router.include_router(quick_evaluate.router)
    router.include_router(valuation.router)
    router.include_router(backtest.router)
    router.include_router(market.router)
    return router


__all__ = ["get_core_router"]
