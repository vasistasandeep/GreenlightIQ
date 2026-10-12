"""ASGI application factory for the CineROI AI backend.

Builds and configures the FastAPI application. Heavy wiring (routers, auth
middleware, DB session lifecycle, task queue) is added in later tasks; this
factory establishes the bootable shell with configuration, logging, and a
health endpoint.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import get_core_router
from app.api.support_routers import register_support_routers
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown lifecycle hook."""
    log = get_logger("lifespan")
    log.info("startup", app=app.title)
    yield
    log.info("shutdown", app=app.title)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance.

    Args:
        settings: Optional settings override (useful for tests). Defaults to the
            cached application settings.

    Returns:
        A configured :class:`FastAPI` app.
    """
    configure_logging()
    settings = settings or get_settings()

    # Fail fast: never boot a production process with insecure dev defaults.
    safety_errors = settings.production_safety_errors()
    if safety_errors:
        log = get_logger("startup")
        for problem in safety_errors:
            log.error("insecure_production_config", problem=problem)
        raise RuntimeError(
            "Refusing to start in production with insecure configuration: "
            + "; ".join(safety_errors)
        )

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    # Shared error-envelope handlers: every AppError, request-validation error,
    # and uncaught exception renders the canonical {error_code, message, details}
    # envelope (task 6.2). Registered here so the core routers (task 16.1) and the
    # supporting routers (task 16.2) share one error contract.
    # Host-header allowlist: rejects requests with an unexpected Host (defense
    # against host-header injection). "*" (dev default) accepts any host.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    # CORS: a browser frontend on a different origin can only call the API when
    # its origin is allow-listed. Empty list (dev default) = same-origin only.
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    # Core API routers (task 16.1): titles ingestion, valuation, backtest audit,
    # and market telemetry, mounted under the configured /api/v1 prefix.
    app.include_router(get_core_router(), prefix=settings.api_v1_prefix)

    # Supporting routers (task 16.2): jobs, auth, decisions (override / approve /
    # reject / finalization), model-version catalog + calibration apply, audit
    # lineage, and title versions under the API prefix, plus the expanded
    # /health probe (DB / queue / telemetry status) at the app root (R29.4).
    register_support_routers(app, prefix=settings.api_v1_prefix)

    return app


app = create_app()
