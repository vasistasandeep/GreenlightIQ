"""Shared error envelope and HTTP exception mapping.

Defines the canonical error response envelope ``{error_code, message, details}``
and the hierarchy of typed application exceptions, each mapped to an HTTP status
code per the design's Error Handling table. ``register_exception_handlers``
wires those exceptions into a FastAPI app so every handler renders the same
envelope.

Design mapping (Error Handling table):

===========================================  ====  =============================
Condition                                    HTTP  error_code
===========================================  ====  =============================
Unsupported ingest format (R1.4)             415   UNSUPPORTED_FORMAT
CSV row limit exceeded (R1.5)                422   ROW_LIMIT_EXCEEDED
Exchange rate unavailable (R21.5)            422   EXCHANGE_RATE_UNAVAILABLE
Windowing exceeds license (R22.4)            422   WINDOWING_EXCEEDS_LICENSE
Ground-truth invalid (R11.2)                 422   GROUND_TRUTH_INVALID
Calibration out of range (R12.4)             422   CALIBRATION_OUT_OF_RANGE
Title not found (R9.3, R10.3)                404   TITLE_NOT_FOUND
Ground-truth missing (R11.4)                 404   GROUND_TRUTH_MISSING
Stale optimistic-lock update (R27.2)         409   STALE_VERSION
Approvals outstanding (R20.5)                409   APPROVALS_PENDING
Unauthenticated (R19.3)                      401   UNAUTHENTICATED
Credential expired/revoked (R19.6)           401   CREDENTIAL_EXPIRED
Unauthorized override / role (R20.2)         403   FORBIDDEN_OVERRIDE
Internal fallthrough                          500   INTERNAL_ERROR
===========================================  ====  =============================

Partial-failure operations (batch ingest, audit) are intentionally *not*
errors: they return ``200`` with a per-item accepted/rejected summary rather
than failing the whole batch (R1.*). The batch summary is a success payload, so
no exception type here represents it. Only whole-request guards — unsupported
format (415) and row-limit exceeded (422) — fail the request outright.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.logging import get_logger

__all__ = [
    "ErrorEnvelope",
    "AppError",
    "UnsupportedFormatError",
    "ValidationFailedError",
    "RowLimitExceededError",
    "GroundTruthInvalidError",
    "CalibrationOutOfRangeError",
    "ExchangeRateUnavailableError",
    "WindowingExceedsLicenseError",
    "NotFoundError",
    "TitleNotFoundError",
    "GroundTruthMissingError",
    "ConflictError",
    "OptimisticLockError",
    "StaleVersionError",
    "ApprovalsPendingError",
    "UnauthenticatedError",
    "CredentialExpiredError",
    "ForbiddenError",
    "ForbiddenOverrideError",
    "register_exception_handlers",
]


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    """The canonical error response body.

    Every error response in the API shares this shape so clients can rely on a
    single contract: a machine-readable ``error_code``, a human-readable
    ``message``, and an optional free-form ``details`` object for structured
    context (e.g. the offending field, the stale/current version numbers).
    """

    error_code: str = Field(..., description="Stable machine-readable error identifier.")
    message: str = Field(..., description="Human-readable description of the error.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured context about the error.",
    )


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AppError(Exception):
    """Base class for all typed application errors.

    Subclasses declare their ``status_code`` and ``error_code`` as class
    attributes; instances carry a ``message`` and optional ``details`` that are
    rendered into an :class:`ErrorEnvelope`.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"
    #: Clean, user-facing fallback used when no explicit message is supplied.
    #: (Docstrings document the class for developers and are not shown to clients.)
    default_message: str = "An internal error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)

    def to_envelope(self) -> ErrorEnvelope:
        """Render this error as an :class:`ErrorEnvelope`."""
        return ErrorEnvelope(
            error_code=self.error_code,
            message=self.message,
            details=self.details,
        )


# --- 415 Unsupported Media Type ------------------------------------------- #


class UnsupportedFormatError(AppError):
    """The ingestion payload is in a format the platform does not support (R1.4)."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    error_code = "UNSUPPORTED_FORMAT"
    default_message = "The ingestion payload format is not supported."


# --- 422 Unprocessable Entity --------------------------------------------- #


class ValidationFailedError(AppError):
    """A request was well-formed but failed domain validation."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_FAILED"
    default_message = "The request failed validation."


class RowLimitExceededError(ValidationFailedError):
    """The uploaded CSV exceeds the maximum allowed number of rows (R1.5)."""

    error_code = "ROW_LIMIT_EXCEEDED"
    default_message = "The uploaded file exceeds the maximum allowed number of rows."


class GroundTruthInvalidError(ValidationFailedError):
    """The submitted ground-truth record failed validation (R11.2)."""

    error_code = "GROUND_TRUTH_INVALID"
    default_message = "The submitted ground-truth record is invalid."


class CalibrationOutOfRangeError(ValidationFailedError):
    """A requested calibration offset is outside the permitted range (R12.4)."""

    error_code = "CALIBRATION_OUT_OF_RANGE"
    default_message = "The requested calibration offset is outside the permitted range."


class ExchangeRateUnavailableError(ValidationFailedError):
    """No exchange rate is available to normalize cost to USD (R21.5)."""

    error_code = "EXCHANGE_RATE_UNAVAILABLE"
    default_message = "No exchange rate is available to normalize cost to USD."


class WindowingExceedsLicenseError(ValidationFailedError):
    """A requested distribution window exceeds the licensed term (R22.4)."""

    error_code = "WINDOWING_EXCEEDS_LICENSE"
    default_message = "The requested distribution window exceeds the licensed term."


# --- 404 Not Found -------------------------------------------------------- #


class NotFoundError(AppError):
    """A requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


class TitleNotFoundError(NotFoundError):
    """The referenced title does not exist (R9.3, R10.3)."""

    error_code = "TITLE_NOT_FOUND"
    default_message = "The requested title was not found."


class GroundTruthMissingError(NotFoundError):
    """No ground-truth record exists for the requested subject (R11.4)."""

    error_code = "GROUND_TRUTH_MISSING"
    default_message = "No ground-truth record exists for the requested subject."


# --- 409 Conflict --------------------------------------------------------- #


class ConflictError(AppError):
    """A request conflicts with the current state of a resource."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    default_message = "The request conflicts with the current state of the resource."


class OptimisticLockError(ConflictError):
    """An update carried a stale ``row_version`` and was rejected (R27.2).

    This is the canonical optimistic-lock exception shared by the repository
    layer (which raises it when a versioned ``UPDATE`` affects zero rows) and
    the API layer (which maps it to ``409 STALE_VERSION``). ``details`` may
    carry ``expected_version`` / ``current_version`` for diagnostics.
    """

    error_code = "STALE_VERSION"
    default_message = (
        "The record was modified by another operation; reload and retry with the "
        "current version."
    )


# Alias so call sites can name the HTTP semantics directly if they prefer.
StaleVersionError = OptimisticLockError


class ApprovalsPendingError(ConflictError):
    """Finalization was attempted while required approvals remain outstanding (R20.5).

    A high-budget GREENLIGHT decision cannot be finalized until every required
    sign-off role has recorded an approval. When one or more required approvals
    are still missing, finalization is rejected with ``409 APPROVALS_PENDING``;
    ``details`` carries the ``outstanding_roles`` still owed so the caller (and
    the sign-off UI) can report exactly which approvals remain.
    """

    error_code = "APPROVALS_PENDING"
    default_message = (
        "The decision cannot be finalized while required approvals remain "
        "outstanding."
    )


# --- 401 Unauthorized ----------------------------------------------------- #


class UnauthenticatedError(AppError):
    """The request lacks a valid credential (R19.3)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHENTICATED"
    default_message = "Authentication is required to perform this operation."


class CredentialExpiredError(UnauthenticatedError):
    """The supplied credential is expired or revoked (R19.6)."""

    error_code = "CREDENTIAL_EXPIRED"
    default_message = "The supplied credential is expired or revoked."


# --- 403 Forbidden -------------------------------------------------------- #


class ForbiddenError(AppError):
    """The authenticated actor is not permitted to perform this operation."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    default_message = "You are not permitted to perform this operation."


class ForbiddenOverrideError(ForbiddenError):
    """The actor's role may not perform this override/operation (R20.2)."""

    error_code = "FORBIDDEN_OVERRIDE"
    default_message = "Your role is not permitted to perform this override."


# ---------------------------------------------------------------------------
# FastAPI handler registration
# ---------------------------------------------------------------------------


def _envelope_response(status_code: int, envelope: ErrorEnvelope) -> JSONResponse:
    """Serialize an envelope into a JSON response at the given status."""
    return JSONResponse(status_code=status_code, content=jsonable_encoder(envelope))


def register_exception_handlers(app: FastAPI) -> None:
    """Register the shared exception handlers on a FastAPI app.

    Wires:

    * :class:`AppError` (and every subclass) → its declared ``status_code`` and
      ``error_code``, rendered as an :class:`ErrorEnvelope`.
    * FastAPI's :class:`RequestValidationError` (request-shape validation) →
      ``422`` with ``error_code='VALIDATION_FAILED'``, carrying the raw
      validation errors in ``details``.
    * Any uncaught :class:`Exception` → ``500`` with
      ``error_code='INTERNAL_ERROR'`` and a generic message (internal details
      are logged, never leaked to the client).
    """
    log = get_logger("errors")

    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # Client/domain errors (4xx) are expected; log at a low level. Any
        # AppError that resolves to 5xx is a genuine server fault.
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            log.error("app_error", error_code=exc.error_code, message=exc.message)
        else:
            log.info("app_error", error_code=exc.error_code, status=exc.status_code)
        return _envelope_response(exc.status_code, exc.to_envelope())

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error_code="VALIDATION_FAILED",
            message="Request validation failed.",
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return _envelope_response(status.HTTP_422_UNPROCESSABLE_ENTITY, envelope)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Fallthrough: never expose internal exception text to the client.
        log.error("unhandled_exception", exc_info=exc)
        envelope = ErrorEnvelope(
            error_code="INTERNAL_ERROR",
            message="An internal error occurred.",
        )
        return _envelope_response(status.HTTP_500_INTERNAL_SERVER_ERROR, envelope)
