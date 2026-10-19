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
  ``401 CREDENTIAL_EXPIRED`` â€” both via the error envelope (task 6.2).
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

from app.core.config import get_settings
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
    envelope: a missing/invalid credential â†’ ``401 UNAUTHENTICATED`` (R19.3); an
    expired/revoked one â†’ ``401 CREDENTIAL_EXPIRED`` (R19.6).

    Raises:
        UnauthenticatedError: No or malformed credential was presented (R19.3).
        CredentialExpiredError: The credential is expired or revoked (R19.6).
    """
    credential, is_service = _extract_credential(authorization, x_service_credential)
    if not credential:
        # DEV/DEMO ONLY: resolve a synthetic demo principal so the UI works
        # without a live SSO session. Gated to non-production and off by
        # default; production_safety_errors() hard-blocks it in prod.
        settings = get_settings()
        if settings.demo_auth_bypass and not settings.is_production:
            from app.core.security import UserRole

            # The synthetic demo principal is a CFO so a single demo session can
            # exercise the whole app: valuation/audit, model calibration
            # (CALIBRATE is reserved for DATA_ANALYST / CHIEF_CONTENT_OFFICER /
            # CFO), recommendation overrides, executive sign-off, and
            # confidential reads. Still DEV/DEMO ONLY and hard-blocked in prod by
            # production_safety_errors().
            return UserContext(
                user_id=uuid.uuid5(uuid.NAMESPACE_URL, "demo:cfo"),
                display_name="Demo CFO",
                role=UserRole.CFO,
                authorized_territories=(),
            )
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
    source snapshot â€” the as-submitted manifest captured at ingestion â€” reading
    the modeling fields when present and applying conservative defaults when they
    are absent, so a valuation can always be produced for a persisted title.

    When a richer financial-modeling pipeline lands it replaces this provider via
    the :func:`get_input_provider` override point without any router change.
    """

    session: AsyncSession

    async def get_inputs(self, title_id: uuid.UUID) -> Any:
        from app.domain.churn import coerce_supplied
        from app.engines.guardrails import ValuationInputs
        from app.repositories.titles import TitleVersionRepository

        def _opt_decimal(value: Any) -> Decimal | None:
            """Coerce an optional snapshot value to a finite Decimal, else None."""
            if value is None:
                return None
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError):
                return None
            return parsed if parsed.is_finite() else None

        active = await TitleVersionRepository(self.session).get_active(title_id)
        snapshot: dict[str, Any] = (
            dict(active.source_snapshot)
            if active is not None and active.source_snapshot
            else {}
        )

        milestone_schedule = snapshot.get("milestone_schedule")
        if not isinstance(milestone_schedule, list):
            milestone_schedule = None

        # Optional explicit rate date (e.g. the quick-evaluate path resolves the
        # latest available rate for a non-USD currency and stamps it here).
        from datetime import date as _date

        rate_date = None
        raw_rate_date = snapshot.get("rate_date")
        if raw_rate_date:
            try:
                rate_date = _date.fromisoformat(str(raw_rate_date))
            except ValueError:
                rate_date = None

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
            # Optional carried churn (calculable-churn-model, R4.6): a snapshot
            # WITHOUT churn yields None (CALCULATED, computed by the engine in a
            # later task); a snapshot WITH a value yields a Decimal (SUPPLIED).
            # Today's seed snapshots carry churn_reduction_pct, so this preserves
            # current seeded behavior (SUPPLIED with the stored value).
            churn_reduction_pct=coerce_supplied(snapshot.get("churn_reduction_pct")),
            monthly_margin=_coerce_decimal(snapshot.get("monthly_margin"), Decimal("0")),
            milestone_schedule=milestone_schedule,
            rate_date=rate_date,
            # calculable-churn-model (R6.1): surface the explicit churn feature
            # facts a snapshot may carry (the Asset Studio quick-evaluate path
            # writes these, creating no metadata-vector / license rows) so the
            # engine computes the same CALCULATED churn from them. Absent facts
            # stay None and the engine falls back to the metadata/license repos.
            talent_pedigree_score=_opt_decimal(snapshot.get("talent_pedigree_score")),
            production_scale_metric=_opt_decimal(
                snapshot.get("production_scale_metric")
            ),
            is_exclusive=(
                bool(snapshot["is_exclusive"])
                if snapshot.get("is_exclusive") is not None
                else None
            ),
            # calculable-churn-model (R17): OTT content format for the churn lift.
            content_format=(
                str(snapshot["content_format"])
                if snapshot.get("content_format") is not None
                else None
            ),
        )


# --------------------------------------------------------------------------- #
# Content_Eval provider: SUPPLIED > FITTED > FALLBACK precedence (R1.4-R1.6)
# --------------------------------------------------------------------------- #

#: Base_Retained_Cohort_Value Platform_Rate (USD) used by the opt-in churn<->LTV
#: linkage (design Component 4). It is the per-title subscription value a one-
#: percentage-point churn reduction retains -- conceptually ``subscribers-at-risk
#: x per-subscriber value`` for the platform/territory. Like ``LTV`` / ``CPM`` /
#: ``Ad_Impressions`` it is a CONFIGURED rate, not a modeled quantity, so it lives
#: here as a documented constant rather than being learned by a Content_Eval_
#: Model. A deployment may override it per title via a ``base_retained_cohort_
#: value`` key on the title's source snapshot (the same place the other Platform_
#: Rates are carried); absent/invalid -> this default. The link is OFF by default
#: (``link_churn_to_ltv`` false), so this constant is inert for the demo.
DEFAULT_BASE_RETAINED_COHORT_VALUE = Decimal("1000000")


@dataclass
class ContentEvalValuationInputProvider:
    """Applies the Content_Eval_System precedence over the snapshot provider (R1.4).

    Wraps :class:`SnapshotValuationInputProvider` and, for each
    Modeled_Engagement_Driver, applies the strict precedence
    ``SUPPLIED > FITTED > FALLBACK`` (design Component 8, Property 6):

    * **SUPPLIED** -- a finite, valid value is present on the title's source
      snapshot. The snapshot provider already surfaces it, so this provider
      leaves it untouched (the pure ``resolve_*`` SUPPLIED-wins path confirms it).
    * **FITTED** -- a fitted ``content_eval`` model version is active AND the
      features the driver needs are derivable from the title's attributes. The
      per-driver pure model computes the value and a conserving breakdown.
    * **FALLBACK** -- otherwise the existing snapshot/placeholder value the
      snapshot provider produced (today's behavior) is preserved exactly.

    Each driver that resolves to FITTED contributes its breakdown to
    :attr:`ValuationInputs.driver_explanations` (threaded through the engine by
    task 12 into ``explanation["content_eval"]``). The provider also implements
    the opt-in churn<->LTV linkage (design Component 4): when
    ``link_churn_to_ltv`` is on and no ``churn_reduction_value`` was supplied, it
    sets ``churn_reduction_value = Base_Retained_Cohort_Value * (churn_reduction_
    pct / 100)``.

    Critical default-off invariant (Property 12): with NO active fitted
    ``content_eval`` version and ``link_churn_to_ltv`` false (the seeded default),
    this provider returns a :class:`ValuationInputs` BYTE-IDENTICAL to what the
    wrapped snapshot provider produces today, with ``driver_explanations`` left
    ``None``. Only a deliberately activated fitted version and/or the opt-in
    toggle changes any output.

    The guardrail thresholds, the recommendation logic, the governance gates, and
    the churn resolution inside the engine are never touched -- this is a
    provider-layer change only.
    """

    session: AsyncSession

    async def get_inputs(self, title_id: uuid.UUID) -> Any:
        from app.domain import content_eval as cemod
        from app.domain import engagement as engmod
        from app.domain import features as featmod
        from app.domain import viewing_hours as vhmod
        from app.engines.model_versioning import ModelVersioningEngine
        from app.repositories.model_versions import ModelVersionRepository
        from app.repositories.titles import TitleVersionRepository

        base = SnapshotValuationInputProvider(self.session)
        inputs = await base.get_inputs(title_id)

        # Read the active model version's content_eval params (churn-style full
        # fallback). No active version, or no content_eval block, yields the
        # illustrative defaults with source DEFAULTS and link OFF -- the inert
        # default-off path.
        active = await ModelVersioningEngine(
            ModelVersionRepository(self.session)
        ).read_active()
        raw_ce = (
            (active.guardrail_params or {}).get("content_eval")
            if active is not None
            else None
        )
        params = cemod.parse_content_eval_params(raw_ce)

        fitted_active = params.source == cemod._SOURCE_MODEL_VERSION

        # DEFAULT-OFF INVARIANT (Property 12): no fitted version active and the
        # churn<->LTV link off -> return the snapshot inputs byte-identical, with
        # no driver_explanations attached. This short-circuit guarantees the demo
        # verdicts, projections, and explanation JSON never move.
        if not fitted_active and not params.link_churn_to_ltv:
            return inputs

        # Resolve the title's active source snapshot so we can both derive
        # features for the FITTED path and read any explicit Base_Retained_Cohort_
        # Value Platform_Rate the deployment carried.
        active_version = await TitleVersionRepository(self.session).get_active(title_id)
        snapshot: dict[str, Any] = (
            dict(active_version.source_snapshot)
            if active_version is not None and active_version.source_snapshot
            else {}
        )

        features = featmod.derive_features(snapshot)
        driver_explanations: dict[str, Any] = {}

        # Only a fitted version drives the FITTED path. Without one, every driver
        # falls back to the snapshot value (no model override, no breakdown).
        if fitted_active:
            self._apply_viewing_hours(
                inputs, snapshot, features, params, driver_explanations, vhmod
            )
            inputs = self._apply_watch_time_elasticity(
                inputs, snapshot, features, params, driver_explanations, engmod
            )
            inputs = self._apply_ad_load_receptivity(
                inputs, snapshot, features, params, driver_explanations, engmod
            )

        # Opt-in churn<->LTV linkage (design Component 4): only when the toggle is
        # on, only when no churn_reduction_value was SUPPLIED on the snapshot, and
        # only when a churn_reduction_pct is available. SUPPLIED still wins at the
        # field level, so a snapshot that carries churn_reduction_value is left
        # untouched (today's behavior for every seeded title).
        inputs = self._apply_churn_to_ltv_link(inputs, snapshot, params)

        from dataclasses import replace

        inputs = replace(
            inputs,
            driver_explanations=(driver_explanations or None),
        )
        return inputs

    # -- per-driver FITTED resolution -------------------------------------- #

    @staticmethod
    def _apply_viewing_hours(
        inputs: Any,
        snapshot: dict[str, Any],
        features: Any,
        params: Any,
        driver_explanations: dict[str, Any],
        vhmod: Any,
    ) -> None:
        """Record the viewing-hours breakdown under ``projected_viewing_hours``.

        Viewing hours are not a ``ValuationInputs`` field (they live on the title
        row / snapshot and feed CPVH downstream), so the FITTED path here does not
        mutate ``inputs``; it surfaces the model's hour-space breakdown for the
        explanation only, honoring SUPPLIED-wins: a snapshot-supplied value yields
        a SUPPLIED result with no breakdown and nothing is attached.
        """
        result = vhmod.resolve_viewing_hours(
            snapshot.get("projected_viewing_hours"),
            features,
            params.viewing_hours,
            params.viewing_hours_source,
        )
        if result.method == "CALCULATED" and result.breakdown is not None:
            driver_explanations["projected_viewing_hours"] = _driver_explanation(
                value=result.viewing_hours,
                method="FITTED",
                version_label=params.version_label,
                label_type=params.dominant_label_type,
                params_source=result.params_source,
                breakdown=[
                    {
                        "key": c.key,
                        "label": c.label,
                        "input": _jsonable_decimal(c.input),
                        "coefficient": _jsonable_decimal(c.coefficient),
                        "hours": _jsonable_decimal(c.hours),
                    }
                    for c in result.breakdown
                ],
                missing_features=list(result.missing_features),
                assumed_features=list(result.assumed_features),
            )

    @staticmethod
    def _apply_watch_time_elasticity(
        inputs: Any,
        snapshot: dict[str, Any],
        features: Any,
        params: Any,
        driver_explanations: dict[str, Any],
        engmod: Any,
    ) -> Any:
        """Override ``watch_time_elasticity`` with the fitted model when unsupplied.

        SUPPLIED-wins: when the snapshot carried a finite elasticity the pure
        ``resolve_*`` returns it as SUPPLIED and this leaves ``inputs`` unchanged.
        Otherwise the additive engagement model computes the value, which replaces
        the snapshot placeholder and contributes its conserving breakdown.
        """
        result = engmod.resolve_watch_time_elasticity(
            snapshot.get("watch_time_elasticity"),
            features,
            params.watch_time_elasticity,
            params.watch_time_elasticity_source,
        )
        if result.method != "CALCULATED" or result.breakdown is None:
            return inputs
        driver_explanations["watch_time_elasticity"] = _driver_explanation(
            value=result.watch_time_elasticity,
            method="FITTED",
            version_label=params.version_label,
            label_type=params.dominant_label_type,
            params_source=result.params_source,
            breakdown=[
                {
                    "key": c.key,
                    "label": c.label,
                    "input": _jsonable_decimal(c.input),
                    "coefficient": _jsonable_decimal(c.coefficient),
                    "points": _jsonable_decimal(c.points),
                }
                for c in result.breakdown
            ],
            missing_features=list(result.missing_features),
            assumed_features=list(result.assumed_features),
        )
        from dataclasses import replace

        return replace(inputs, watch_time_elasticity=result.watch_time_elasticity)

    @staticmethod
    def _apply_ad_load_receptivity(
        inputs: Any,
        snapshot: dict[str, Any],
        features: Any,
        params: Any,
        driver_explanations: dict[str, Any],
        engmod: Any,
    ) -> Any:
        """Scale ``cpm`` by the fitted ad-load receptivity multiplier.

        Ad_Load_Receptivity is a UNIT-CENTERED multiplier (default 1.0) that
        SCALES the configured CPM Platform_Rate -- it never emits a dollar CPM
        (honoring the Platform_Rate boundary, R1.1). The receptivity itself is
        never a SUPPLIED snapshot field (the snapshot carries ``cpm`` directly),
        so when no ``ad_load_receptivity`` is supplied the model computes the
        scalar and this multiplies the base ``cpm`` by it. A receptivity of
        exactly 1.0 leaves ``cpm`` unchanged.
        """
        result = engmod.resolve_ad_load_receptivity(
            snapshot.get("ad_load_receptivity"),
            features,
            params.ad_load_receptivity,
            params.ad_load_receptivity_source,
        )
        if result.method != "CALCULATED" or result.breakdown is None:
            return inputs
        scaled_cpm = inputs.cpm * result.ad_load_receptivity
        driver_explanations["ad_load_receptivity"] = _driver_explanation(
            value=result.ad_load_receptivity,
            method="FITTED",
            version_label=params.version_label,
            label_type=params.dominant_label_type,
            params_source=result.params_source,
            breakdown=[
                {
                    "key": c.key,
                    "label": c.label,
                    "input": _jsonable_decimal(c.input),
                    "coefficient": _jsonable_decimal(c.coefficient),
                    "points": _jsonable_decimal(c.points),
                }
                for c in result.breakdown
            ],
            missing_features=list(result.missing_features),
            assumed_features=list(result.assumed_features),
            extra={
                "base_cpm": _jsonable_decimal(inputs.cpm),
                "scaled_cpm": _jsonable_decimal(scaled_cpm),
            },
        )
        from dataclasses import replace

        return replace(inputs, cpm=scaled_cpm)

    # -- opt-in churn<->LTV linkage (design Component 4) ------------------- #

    @staticmethod
    def _apply_churn_to_ltv_link(
        inputs: Any,
        snapshot: dict[str, Any],
        params: Any,
    ) -> Any:
        """Derive ``churn_reduction_value`` from modeled churn when opted-in.

        When ``link_churn_to_ltv`` is on AND no ``churn_reduction_value`` was
        SUPPLIED on the snapshot AND a ``churn_reduction_pct`` is available, set

            churn_reduction_value = Base_Retained_Cohort_Value * (pct / 100)

        using the configured :data:`DEFAULT_BASE_RETAINED_COHORT_VALUE` Platform_
        Rate (overridable per title via a ``base_retained_cohort_value`` snapshot
        key). When the toggle is off this is a no-op and today's independent,
        snapshot-sourced ``churn_reduction_value`` is preserved EXACTLY, so demo
        verdicts never move.

        SUPPLIED-wins is enforced at the field level: a snapshot that carried an
        explicit ``churn_reduction_value`` (every seeded title does) is left
        untouched even with the toggle on.
        """
        if not params.link_churn_to_ltv:
            return inputs

        # SUPPLIED value for churn_reduction_value wins -- do not overwrite it.
        if snapshot.get("churn_reduction_value") is not None:
            return inputs

        pct = inputs.churn_reduction_pct
        if pct is None:
            return inputs

        base_rate = _coerce_decimal(
            snapshot.get("base_retained_cohort_value"),
            DEFAULT_BASE_RETAINED_COHORT_VALUE,
        )
        linked_value = base_rate * (pct / Decimal("100"))

        from dataclasses import replace

        return replace(inputs, churn_reduction_value=linked_value)


def _jsonable_decimal(value: Any) -> Any:
    """Render a Decimal as a JSON string (mirrors the engine's Decimal policy)."""
    if isinstance(value, Decimal):
        return str(value)
    return value


def _driver_explanation(
    *,
    value: Decimal,
    method: str,
    version_label: str,
    label_type: str,
    params_source: str,
    breakdown: list[dict[str, Any]],
    missing_features: list[str],
    assumed_features: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-driver explanation payload attached to ``driver_explanations``.

    Shape mirrors the engine's ``churn_model`` block: the resolved value, the
    resolution ``method`` (FITTED here), the fitted ``version_label`` and honesty
    ``label_type`` (so PROXY accuracy is never shown as real-world), the params
    source, the conserving per-feature ``breakdown``, and the missing/assumed
    feature lists. All Decimals are rendered as JSON strings.
    """
    payload: dict[str, Any] = {
        "value": _jsonable_decimal(value),
        "method": method,
        "version_label": version_label,
        "label_type": label_type,
        "params_source": params_source,
        "breakdown": breakdown,
        "missing_features": missing_features,
        "assumed_features": assumed_features,
    }
    if extra:
        payload.update(extra)
    return payload


def get_input_provider(session: SessionDep) -> Any:
    """Return the request-scoped :class:`ValuationInputProvider` (R9).

    Returns the :class:`ContentEvalValuationInputProvider`, which wraps the
    :class:`SnapshotValuationInputProvider` and applies the Content_Eval_System
    precedence (``SUPPLIED > FITTED > FALLBACK``) and the opt-in churn<->LTV link
    (design Component 8). With no fitted ``content_eval`` version active and
    ``link_churn_to_ltv`` off (the seeded default) it returns inputs byte-
    identical to the snapshot provider, so the demo path is inert (Property 12).
    """
    return ContentEvalValuationInputProvider(session)


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
    from app.repositories.metadata_vectors import MetadataVectorRepository
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
        metadata_vector_repo=MetadataVectorRepository(session),
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
