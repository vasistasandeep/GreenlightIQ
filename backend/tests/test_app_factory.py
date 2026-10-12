"""Smoke tests verifying the ASGI app factory and core wiring import cleanly."""

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.main import create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == get_settings().app_name


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.base_currency == "USD"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.session_idle_timeout_minutes == 30


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()  # second call must be a no-op, not raise


def test_health_route_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
    assert "/health" in paths
