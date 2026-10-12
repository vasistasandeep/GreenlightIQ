"""Structured logging configuration.

Provides a single ``configure_logging`` entry point used by the ASGI app factory
and a ``get_logger`` helper for modules. Uses structlog for structured output
when available (declared in ``pyproject.toml``) and falls back to stdlib logging
otherwise, so the package remains importable in minimal environments.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.config import get_settings

try:  # structlog is a declared dependency; degrade gracefully if absent.
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover - exercised only without structlog
    structlog = None  # type: ignore[assignment]
    _HAS_STRUCTLOG = False

_CONFIGURED = False


def configure_logging() -> None:
    """Configure stdlib logging and (if available) structlog processors.

    Idempotent: repeated calls are no-ops after the first successful setup.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    if _HAS_STRUCTLOG:
        renderer = (
            structlog.processors.JSONRenderer()
            if settings.log_json
            else structlog.dev.ConsoleRenderer()
        )
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger, or a stdlib logger as a fallback."""
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)
