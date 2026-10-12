"""Shared API dependencies: auth, RBAC, audit, and engine wiring (task 16.1).

This module is the single composition root for the REST API. Both the core
routers (task 16.1) and the supporting routers (task 16.2) build their engines
and enforce their cross-cutting concerns through the dependencies defined here,
so the auth / RBAC / audit behavior and the error-envelope mapping are
consistent across every endpoint.

Cross-cutting concerns wired here
---------------------------------
* **Authentication (R19.3, R19.6).** :func:`get_current_user` extracts the
  session token (``Authorization: Bearer`` or an internal service credential),
  validates it through the :class:`~app.engines.auth.AuthService`, and yields the
  request :class:`~app.core.security.UserContext`. A missing/invalid credential
  maps to ``401 UNAUTHENTICATED``; an expired/revoked one to
  ``401 CREDENTIAL_EXPIRED`` — both via the error envelope (task 6.2).
* **Authorization (R20).** :func:`require_operation` returns a dependency that
  authorizes the actor for a specific :class:`~app.engines.rbac.Operation`
  before the handler runs, raising ``403`` through the envelope on denial.
* **Audit (R25).** The :class:`~app.engines.audit.AuditLogService` is exposed as
  a dependency so state-changing handlers record an append-only entry.

Engines are constructed per-request against the request-scoped
:class:`~sqlalchemy.ext.asyncio.AsyncSession` (:func:`get_db_session`); the
surrounding request owns the transaction boundary (engines/repositories flush,
they do not commit), so a successful handler commits once at the end.

Testability
-----------
Every dependency is overridable via FastAPI's ``app.dependency_overrides`` so
router tests can inject in-memory fakes without a live database, broker, or SSO
provider. The job-dispatch indirection (:func:`get_task_dispatcher`) is likewise
overridable so tests assert *that* a task was enqueued without a running worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, AsyncIterator, Callable

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.errors import (
    CredentialExpiredError,
    UnauthenticatedError,
)
from app.core.security import (
    AuthError,
    JwtOidcProvider,
    SsoProvider,
    UserContext,
)
from app.engines.audit import AuditLogService
from app.engines.auth import AuthService
from app.engines.rbac import Operation, RBACService
from app.repositories.users import SessionRepository, UserRepository


# --------------------------------------------------------------------------- #
# Session dependency (re-export under the API namespace)
# --------------------------------------------------------------------------- #

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
"""Request-scoped async DB session; the request owns the transaction boundary."""


# --------------------------------------------------------------------------- #
# Auth: SSO provider, AuthService, current-user, and RBAC
# --------------------------------------------------------------------------- #


def get_sso_provider() -> SsoProvider:
    """Return the SSO provider the :class:`AuthService` verifies assertions with.

    Defaults to the OIDC JWT provider (R19.1). Overridden in tests with a double
    so no real IdP is required.
    """
    return JwtOidcProvider()


def get_auth_service(
    session: SessionDep,
    sso_provider: Annotated[SsoProvider, Depends(get_sso_provider)],
) -> AuthService:
    """Construct the request-scoped :class:`AuthService` (R19)."""
    return AuthService(
        users=UserRepository(session),
        sessions=SessionRepository(session),
        sso_provider=sso_provider,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _extract_credential(
    authorization: str | None,
    x_service_credential: str | None,
) -> tuple[str | None, bool]:
    """Return ``(credential, is_service)`` from the auth headers.

    A ``Authorization: Bearer <token>`` header carries a user session token; an
    ``X-Service-Credential`` header carries an internal service-to-service
    credential (R19.5). The bearer token takes precedence when both are present.
    """
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip(), False
        # A bare token without the Bearer scheme is still accepted.
        return authorization.strip(), False
    if x_service_credential:
        return x_service_credential.strip(), True
    return None, False


#: Territories a service-credential actor is scoped to. Service integrations act
#: with organization-wide read access; the user path remains the gate for
#: confidential/territory-scoped data.
_SERVICE_ROLE_TERRITORIES: tuple[str, ...] = ()


async def get_current_user(
    auth_service: AuthServiceDep,
    authorization: Annotated[str | None, Header()] = None,
    x_service_credential: Annotated[str | None, Header()] = None,
) -> UserContext:
    """Authenticate the request and return the actor :class:`UserContext` (R19.3).

    Resolves a user session token or an internal service credential, validating
    it through the :class:`AuthService`. Authentication failures are translated
    from the engine's :class:`~app.core.security.AuthError` into the shared error
    envelope: a missing/invalid credential → ``401 UNAUTHENTICATED`` (R19.3); an
    expired/revoked one → ``401 CREDENTIAL_EXPIRED`` (R19.6).

    Raises:
        UnauthenticatedError: No or malformed credential was presented (R19.3).
        CredentialExpiredError: The credential is expired or revoked (R19.6).
    """
    credential, is_service = _extract_credential(authorization, x_service_credential)
    if not credential:
        raise UnauthenticatedError("Authentication is required.")

    try:
        if is_service:
            service_name = auth_service.authenticate_service(credential)
            # Service callers act as a synthetic, least-surprising principal: a
            # stable id derived from the service name and the data-analyst role
            # (non-confidential read/ingest scope). Elevated actions still flow
            # through user sessions.
            from app.core.security import UserRole

            return UserContext(
                user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"service:{service_name}"),
                display_name=service_name,
                role=UserRole.DATA_ANALYST,
                authorized_territories=_SERVICE_ROLE_TERRITORIES,
            )
        return await auth_service.validate(credential)
    except AuthError as exc:
        if exc.revoked_or_expired:
            raise CredentialExpiredError(str(exc)) from exc
        raise UnauthenticatedError(str(exc)) from exc


CurrentUser = Annotated[UserContext, Depends(get_current_user)]


def get_rbac_service() -> RBACService:
    """Return the stateless :class:`RBACService` policy evaluator (R20, R28)."""
    return RBACService()


RBACServiceDep = Annotated[RBACService, Depends(get_rbac_service)]


def require_operation(operation: Operation | str) -> Callable[..., None]:
    """Build a dependency authorizing the actor for ``operation`` (R20.1, R20.2).

    Usage::

        @router.post(..., dependencies=[Depends(require_operation(Operation.INGEST))])

    The returned dependency resolves the current user and the RBAC service and
    raises through the error envelope (``403 FORBIDDEN`` / ``FORBIDDEN_OVERRIDE``)
    when the actor's role is not permitted the operation.
    """

    def _dependency(
        actor: CurrentUser,
        rbac: RBACServiceDep,
    ) -> None:
        rbac.authorize(actor, operation)

    return _dependency


# --------------------------------------------------------------------------- #
# Audit service dependency (R25)
# --------------------------------------------------------------------------- #


def get_audit_service(session: SessionDep) -> AuditLogService:
    """Construct the request-scoped append-only :class:`AuditLogService` (R25)."""
    return AuditLogService(session)


AuditServiceDep = Annotated[AuditLogService, Depends(get_audit_service)]


# --------------------------------------------------------------------------- #
# Task-queue dispatch indirection (R23.1)
# --------------------------------------------------------------------------- #


class TaskDispatcher:
    """Enqueues heavy operations onto the Task_Queue by job id (R23.1).

    The default implementation hands the job id (plus any task arguments) to the
    corresponding Celery task's ``.delay``. It is a thin indirection so routers
    never import Celery directly and tests can override it to assert dispatch
    without a running broker.
    """

    def dispatch_ingest(
        self, job_id: uuid.UUID, payload: bytes, content_type: str, idempotency_key: str
    ) -> None:
        from app.tasks.jobs import ingest_batch

        ingest_batch.delay(str(job_id), payload, content_type, idempotency_key)

    def dispatch_backtest(self, job_id: uuid.UUID, title_id: uuid.UUID) -> None:
        from app.tasks.jobs import run_backtest_audit

        run_backtest_audit.delay(str(job_id), str(title_id))


def get_task_dispatcher() -> TaskDispatcher:
    """Return the Task_Queue dispatcher (overridable in tests)."""
    return TaskDispatcher()


TaskDispatcherDep = Annotated[TaskDispatcher, Depends(get_task_dispatcher)]


# --------------------------------------------------------------------------- #
# Guardrails engine + production ValuationInputProvider (R9)
# --------------------------------------------------------------------------- #


def _coerce_decimal(value: Any, default: Decimal) -> Decimal:
    """Parse ``value`` into a finite Decimal, falling back to ``default``."""
    if value is None:
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default
    return parsed if parsed.is_finite() else default


@dataclass
class SnapshotValuationInputProvider:
    """Supplies modeled financial inputs for a valuation from stored data (R9).

    The modeled figures the LTV / churn / payback math consumes
    (``churn_reduction_value``, ``ltv``, ``cpm``, ad impressions, churn-reduction
    percentage, monthly margin, milestone schedule) are not columns on ``titles``.
    This provider sources them from the title's active ``title_versions``
    source snapshot — the as-submitted manifest captured at ingestion — reading
    the modeling fields when present and applying conservative defaults when they
    are absent, so a valuation can always be produced for a persisted title.

    When a richer financial-modeling pipeline lands it replaces this provider via
    the :func:`get_input_provider` override point without any router change.
    """

    session: AsyncSession

    async def get_inputs(self, title_id: uuid.UUID) -> Any:
        from app.engines.guardrails import ValuationInputs
        from app.repositories.titles import TitleVersionRepository

        active = await TitleVersionRepository(self.session).get_active(title_id)
        snapshot: dict[str, Any] = (
            dict(active.source_snapshot)
            if active is not None and active.source_snapshot
            else {}
        )

        milestone_schedule = snapshot.get("milestone_schedule")
        if not isinstance(milestone_schedule, list):
            milestone_schedule = None

        return ValuationInputs(
            churn_reduction_value=_coerce_decimal(
                snapshot.get("churn_reduction_value"), Decimal("0")
            ),
            ltv=_coerce_decimal(snapshot.get("ltv"), Decimal("0")),
            watch_time_elasticity=_coerce_decimal(
                snapshot.get("watch_time_elasticity"), Decimal("1")
            ),
            cpm=_coerce_decimal(snapshot.get("cpm"), Decimal("0")),
            ad_impressions=_coerce_decimal(snapshot.get("ad_impressions"), Decimal("0")),
            churn_reduction_pct=_coerce_decimal(
                snapshot.get("churn_reduction_pct"), Decimal("0")
            ),
            monthly_margin=_coerce_decimal(snapshot.get("monthly_margin"), Decimal("0")),
            milestone_schedule=milestone_schedule,
        )


def get_input_provider(session: SessionDep) -> Any:
    """Return the request-scoped :class:`ValuationInputProvider` (R9)."""
    return SnapshotValuationInputProvider(session)


InputProviderDep = Annotated[Any, Depends(get_input_provider)]


def get_guardrails_engine(
    session: SessionDep,
    audit: AuditServiceDep,
    input_provider: InputProviderDep,
) -> Any:
    """Construct the request-scoped :class:`Guardrails_Engine` (R9, R21, R25).

    Wires every injected collaborator against the request session so the whole
    valuation (projection write + audit entry) is one atomic transaction owned by
    the request.
    """
    from app.engines.guardrails import Guardrails_Engine
    from app.engines.model_versioning import ModelVersioningEngine
    from app.repositories.exchange_rates import ExchangeRateRepository
    from app.repositories.financial_projections import FinancialProjectionRepository
    from app.repositories.license_terms import LicenseTermRepository
    from app.repositories.model_versions import ModelVersionRepository
    from app.repositories.telemetry import TelemetryRepository
    from app.repositories.titles import TitleRepository

    return Guardrails_Engine(
        title_repository=TitleRepository(session),
        projection_repository=FinancialProjectionRepository(session),
        exchange_rate_repository=ExchangeRateRepository(session),
        license_term_repository=LicenseTermRepository(session),
        telemetry_repository=TelemetryRepository(session),
        model_versioning_engine=ModelVersioningEngine(ModelVersionRepository(session)),
        audit_service=audit,
        input_provider=input_provider,
    )


GuardrailsEngineDep = Annotated[Any, Depends(get_guardrails_engine)]


# --------------------------------------------------------------------------- #
# Backtesting + telemetry engine dependencies (R11, R13)
# --------------------------------------------------------------------------- #


def get_backtesting_module(session: SessionDep) -> Any:
    """Construct the request-scoped :class:`Backtesting_Module` (R11)."""
    from app.engines.backtesting import Backtesting_Module

    return Backtesting_Module(session)


BacktestingDep = Annotated[Any, Depends(get_backtesting_module)]


def get_telemetry_connector(session: SessionDep) -> Any:
    """Construct the request-scoped :class:`TelemetryConnector` (R13)."""
    from app.engines.telemetry import TelemetryConnector

    return TelemetryConnector(session)


TelemetryConnectorDep = Annotated[Any, Depends(get_telemetry_connector)]


# --------------------------------------------------------------------------- #
# Request-id helper (used in structured logs / audit context)
# --------------------------------------------------------------------------- #


def get_request_id(request: Request) -> str:
    """Return a stable per-request id for correlation (falls back to a new UUID)."""
    header = request.headers.get("x-request-id")
    return header or str(uuid.uuid4())
