"""Property-based tests for the Guardrails_Engine churn + payback boundaries.

Targets :class:`app.engines.guardrails.Guardrails_Engine` and the two guardrail
checks it builds through the real ``evaluate`` orchestration:

* **Churn mitigation** (R6.3): a churn-mitigation breach is recorded if and only
  if the modeled cohort monthly churn-reduction percentage is strictly below the
  ``CHURN_MITIGATION_THRESHOLD`` of 1.5; a value of exactly 1.5 passes.
* **Payback horizon** (R7.3): a payback-horizon breach is recorded if and only if
  the computed ``payback_horizon_months`` strictly exceeds the
  ``PAYBACK_TARGET_MAX_MONTHS`` of 12; a horizon of exactly 12 passes.

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests exercise the dependency-injection seam: the
engine is wired with in-memory fakes for every injected collaborator (title /
projection / exchange-rate / license-term / telemetry repositories, the
model-versioning stamp, the audit service, and a ``ValuationInputProvider``).
The title is USD-native so no exchange-rate lookup happens, the title has no
genre/territories so territory weighting is the identity, and viewing hours are
present so the CPVH check never short-circuits the run. We then call
``evaluate`` and inspect the resulting ``explanation.checks`` (and the captured
persisted projection) for the churn and payback checks.

Payback is driven exactly as the real engine computes it (``compute_payback_horizon``
walks the milestone schedule against the monthly margin): a single milestone of
amount ``margin * (horizon - 1)`` disbursed at month 1 yields a payback horizon of
exactly ``horizon`` months, letting us place the computed horizon below, at, and
above the 12-month boundary deterministically.

Covers design Property 13 (Churn mitigation breach boundary) and Property 14
(Payback horizon breach boundary), validating Requirements 6.3 and 7.3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.guardrails import (
    CHURN_MITIGATION_THRESHOLD,
    PAYBACK_TARGET_MAX_MONTHS,
    Guardrails_Engine,
    ValuationInputs,
)


# --------------------------------------------------------------------------- #
# In-memory fakes for the injected collaborators
# --------------------------------------------------------------------------- #


@dataclass
class FakeTitle:
    """A minimal stand-in for a ``titles`` row the engine reads via getattr.

    USD-native so cost normalization needs no exchange rate; no genre/territories
    so territory weighting is the identity; non-zero viewing hours so the CPVH
    check computes rather than short-circuiting the ``evaluate`` run.
    """

    title_id: uuid.UUID
    asset_type: str = "ORIGINAL_FILM"
    acquisition_cost_or_budget: Decimal = Decimal("1000.00")
    native_currency: str = "USD"
    target_territories: list[str] = field(default_factory=list)
    genre_tag: str | None = None
    projected_viewing_hours: Decimal = Decimal("1000")


class FakeTitleRepository:
    """Returns a single pre-registered title by id."""

    def __init__(self, title: FakeTitle) -> None:
        self._title = title

    async def get(self, title_id: uuid.UUID) -> FakeTitle | None:
        return self._title if title_id == self._title.title_id else None


@dataclass
class _CapturedProjection:
    """Captures the keyword values a projection write received."""

    values: dict[str, Any]


class FakeProjectionRepository:
    """Captures the first (create) persistence write; no prior projection exists."""

    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None

    async def get_latest_for_title(self, title_id: uuid.UUID) -> None:
        return None

    def model(self, **values: Any) -> _CapturedProjection:
        return _CapturedProjection(values=values)

    async def create(self, projection: _CapturedProjection) -> _CapturedProjection:
        self.created = projection.values
        return projection


class FakeExchangeRateRepository:
    """Never consulted for USD-native titles; returns no rate if asked."""

    async def get_rate(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None


class FakeLicenseTermRepository:
    """Not consulted when a milestone schedule is supplied via inputs."""

    async def list_for_title(self, title_id: uuid.UUID) -> list[Any]:  # pragma: no cover
        return []


class FakeTelemetryRepository:
    """No cached telemetry -> neutral (identity) territory weighting."""

    async def get_for_genre_territory(self, genre: str, territory: str) -> None:
        return None


class FakeVersioningEngine:
    """Returns a fixed model-version stamp uuid."""

    def __init__(self) -> None:
        self._stamp = uuid.uuid4()

    async def stamp(self) -> uuid.UUID:
        return self._stamp


class FakeAuditService:
    """Captures append-only audit records emitted by the engine."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(
        self,
        actor: Any,
        action: Any,
        before: Any,
        after: Any,
        *,
        model_version_id: Any = None,
        subject_id: Any = None,
    ) -> None:
        self.records.append(
            {
                "actor": actor,
                "action": action,
                "before": before,
                "after": after,
                "model_version_id": model_version_id,
                "subject_id": subject_id,
            }
        )


class FakeInputProvider:
    """Supplies a fixed :class:`ValuationInputs` for the title under test."""

    def __init__(self, inputs: ValuationInputs) -> None:
        self._inputs = inputs

    async def get_inputs(self, title_id: uuid.UUID) -> ValuationInputs:
        return self._inputs


def _build_engine(inputs: ValuationInputs) -> tuple[Guardrails_Engine, uuid.UUID, FakeProjectionRepository]:
    """Wire the engine against in-memory fakes; return (engine, title_id, projections)."""
    title_id = uuid.uuid4()
    title = FakeTitle(title_id=title_id)
    projections = FakeProjectionRepository()
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=projections,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=FakeVersioningEngine(),
        audit_service=FakeAuditService(),
        input_provider=FakeInputProvider(inputs),
    )
    return engine, title_id, projections


def _base_inputs(
    *,
    churn_reduction_pct: Decimal,
    monthly_margin: Decimal,
    milestone_schedule: list[dict[str, Any]] | None,
) -> ValuationInputs:
    """ValuationInputs with benign LTV/CPM figures; churn + payback are the knobs."""
    return ValuationInputs(
        churn_reduction_value=Decimal("1"),
        ltv=Decimal("100"),
        watch_time_elasticity=Decimal("1"),
        cpm=Decimal("10"),
        ad_impressions=Decimal("1000"),
        churn_reduction_pct=churn_reduction_pct,
        monthly_margin=monthly_margin,
        milestone_schedule=milestone_schedule,
    )


def _churn_check(result_explanation: dict[str, Any]) -> dict[str, Any]:
    """Extract the CHURN_MITIGATION check from an evaluate() explanation."""
    for check in result_explanation["checks"]:
        if check["name"] == "CHURN_MITIGATION":
            return check
    raise AssertionError("CHURN_MITIGATION check missing from explanation")


def _payback_check(result_explanation: dict[str, Any]) -> dict[str, Any]:
    """Extract the PAYBACK_HORIZON check from an evaluate() explanation."""
    for check in result_explanation["checks"]:
        if check["name"] == "PAYBACK_HORIZON":
            return check
    raise AssertionError("PAYBACK_HORIZON check missing from explanation")


# --------------------------------------------------------------------------- #
# Property 13: Churn mitigation breach boundary (R6.3)
# --------------------------------------------------------------------------- #

# Churn percentages spanning strictly below, exactly at, and above 1.5 at the
# NUMERIC-style precision the modeled value carries. Three-decimal places let the
# generator land arbitrarily close to the boundary on both sides.
_churn_pct = st.decimals(
    min_value=Decimal("0.000"),
    max_value=Decimal("3.000"),
    allow_nan=False,
    allow_infinity=False,
    places=3,
)


# Feature: cineroi-ai, Property 13: Churn mitigation breach boundary
@given(churn_reduction_pct=_churn_pct)
@settings(max_examples=200)
async def test_churn_breach_iff_below_threshold(churn_reduction_pct: Decimal) -> None:
    """Validates: Requirements 6.3

    Through the real ``evaluate`` orchestration, the churn-mitigation check is
    breached if and only if the modeled churn-reduction percentage is strictly
    below 1.5; a value of exactly 1.5 passes (not a breach).
    """
    # A payback schedule that comfortably passes so churn is the isolated knob.
    inputs = _base_inputs(
        churn_reduction_pct=churn_reduction_pct,
        monthly_margin=Decimal("1000"),
        milestone_schedule=[{"month": 1, "amount": Decimal("1"), "currency": "USD"}],
    )
    engine, title_id, projections = _build_engine(inputs)

    result = await engine.evaluate(title_id)
    check = _churn_check(result["explanation"])

    expected_breach = churn_reduction_pct < CHURN_MITIGATION_THRESHOLD

    assert check["breached"] is expected_breach
    assert check["passed"] is (not expected_breach)
    # The boundary is exclusive-below: exactly 1.5 is a pass.
    if churn_reduction_pct == CHURN_MITIGATION_THRESHOLD:
        assert check["breached"] is False
    # The computed value and threshold are reported faithfully.
    assert check["computed_value"] == churn_reduction_pct
    assert check["threshold"] == CHURN_MITIGATION_THRESHOLD
    # The persisted projection mirrors the modeled churn pct.
    assert projections.created is not None
    assert projections.created["churn_reduction_pct"] == churn_reduction_pct


# --------------------------------------------------------------------------- #
# Property 14: Payback horizon breach boundary (R7.3)
# --------------------------------------------------------------------------- #

# Target payback horizons spanning below, exactly at, and above the 12-month
# boundary. We drive the engine's milestone-based computation to land on each.
_target_horizon = st.integers(min_value=1, max_value=24)

# Positive monthly contribution margins (whole USD) so the milestone amount
# ``margin * (horizon - 1)`` yields a horizon of exactly ``horizon`` months.
_monthly_margin = st.integers(min_value=1, max_value=5000).map(Decimal)


# Feature: cineroi-ai, Property 14: Payback horizon breach boundary
@given(target_horizon=_target_horizon, monthly_margin=_monthly_margin)
@settings(max_examples=200)
async def test_payback_breach_iff_above_twelve(
    target_horizon: int, monthly_margin: Decimal
) -> None:
    """Validates: Requirements 7.3

    Through the real ``evaluate`` orchestration, the payback-horizon check is
    breached if and only if the computed ``payback_horizon_months`` strictly
    exceeds 12; a horizon of exactly 12 passes (not a breach).

    The milestone schedule is constructed so the engine's milestone-based
    payback computation yields exactly ``target_horizon`` months: a single
    disbursement of ``monthly_margin * (target_horizon - 1)`` at month 1 turns
    cumulative contribution positive precisely at month ``target_horizon``.
    """
    milestone_amount = monthly_margin * Decimal(target_horizon - 1)
    inputs = _base_inputs(
        churn_reduction_pct=Decimal("2.0"),  # passes churn so payback is isolated
        monthly_margin=monthly_margin,
        milestone_schedule=[
            {"month": 1, "amount": milestone_amount, "currency": "USD"}
        ],
    )
    engine, title_id, projections = _build_engine(inputs)

    result = await engine.evaluate(title_id)
    check = _payback_check(result["explanation"])

    # The engine computed the horizon we engineered.
    assert result["payback_horizon_months"] == target_horizon

    expected_breach = target_horizon > PAYBACK_TARGET_MAX_MONTHS

    assert check["breached"] is expected_breach
    assert check["passed"] is (not expected_breach)
    # The boundary is exclusive-above: exactly 12 is a pass.
    if target_horizon == PAYBACK_TARGET_MAX_MONTHS:
        assert check["breached"] is False
    assert check["computed_value"] == Decimal(target_horizon)
    assert check["threshold"] == Decimal(PAYBACK_TARGET_MAX_MONTHS)
    # The persisted projection mirrors the computed horizon.
    assert projections.created is not None
    assert projections.created["payback_horizon_months"] == target_horizon
