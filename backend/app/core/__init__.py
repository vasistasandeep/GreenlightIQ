"""Core cross-cutting concerns: configuration, settings, logging, security, errors."""

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    ConflictError,
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    OptimisticLockError,
    UnauthenticatedError,
    register_exception_handlers,
)
from app.core.logging import configure_logging, get_logger

__all__ = [
    "Settings",
    "get_settings",
    "configure_logging",
    "get_logger",
    "ErrorEnvelope",
    "AppError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "OptimisticLockError",
    "UnauthenticatedError",
    "register_exception_handlers",
]
