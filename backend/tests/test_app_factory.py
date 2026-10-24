"""Smoke tests verifying the ASGI app factory and core wiring import cleanly."""

import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.main import create_app

#: The four Advanced_Content_Eval_Drivers per-driver kill-switches (R7.1).
_DRIVER_FLAGS = (
    "enable_comps",
    "enable_lineage",
    "enable_momentum",
    "enable_macro_modifiers",
)


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == get_settings().app_name


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.base_currency == "USD"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.session_idle_timeout_minutes == 30


def test_driver_flags_default_false() -> None:
    """All four per-driver kill-switches default off (R7.1)."""
    settings = Settings()
    for flag in _DRIVER_FLAGS:
        assert getattr(settings, flag) is False, flag


@pytest.mark.parametrize("target", _DRIVER_FLAGS)
def test_driver_flags_are_independently_togglable(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """Enabling one driver flag leaves the other three off (R7.1, R7.4).

    The flags are independent: enabling one neither requires nor enables
    another. Each is driven by its own ``CINEROI_`` env var.
    """
    monkeypatch.setenv(f"CINEROI_{target.upper()}", "true")
    settings = Settings()
    assert getattr(settings, target) is True, target
    for other in _DRIVER_FLAGS:
        if other != target:
            assert getattr(settings, other) is False, other


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()  # second call must be a no-op, not raise


def test_health_route_registered() -> None:
    app = create_app()
    # Newer Starlette appends lazy ``_IncludedRouter`` wrappers (no ``.path``)
    # to ``app.routes`` instead of flattening child routes, so the resolved
    # routing table is read from the OpenAPI schema. ``getattr(..., "path")``
    # still guards the top-level routes that do expose a path.
    paths = {getattr(route, "path", None) for route in app.routes}  # type: ignore[attr-defined]
    paths |= set(app.openapi().get("paths", {}))
    assert "/health" in paths
