"""Integration tests for Guardrails_Engine persistence, retries, and concurrency.

Targets :class:`app.engines.guardrails.Guardrails_Engine.evaluate` and its
persistence path (``_persist``). Per the design testing strategy ("engine
orchestration tested via in-memory repository fakes"), these tests wire the
engine with in-memory fakes for every injected collaborator and inspect the
captured projection write. The fakes mirror the pattern established in
``tests/engines/test_guardrails_properties.py``.

Coverage map:

* **Persistence of all computed columns** (R4.8, R5.4, R7.4, R8.6): the engine
  persists ``calculated_cpvh`` / ``ltv_to_cost_multiple`` / ``churn_reduction_pct``
  / ``payback_horizon_months`` / ``recommendation_status`` / ``normalized_cost_usd``
  / ``exchange_rate_id`` / ``model_version_id`` / ``explanation`` to
  ``financial_projections``.
* **Retry preserving prior value** (R8.7): a projection repository whose first
  one or two persistence attempts raise, then succeeds, drives the engine's
  up-to-3-attempt retry loop; a repository that always fails raises
  :class:`GuardrailPersistenceError` after exactly 3 attempts with the prior
  stored value untouched.
* **CPVH null when viewing hours = 0** (R4.5): ``calculated_cpvh`` is ``None`` and
  is persisted as ``None`` (no value is stamped).
* **Concurrency / no partial writes** (R27.3): a fake-based, deterministic test
  asserts the engine takes the optimistic-lock ``update_with_version`` path when
  a projection already exists, so concurrent valuations cannot produce partial
  writes. A clearly-skippable ``@pytest.mark.integration`` placeholder documents
  the real row-level-locking angle, which needs a live database.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from app.engines.guardrails import (
    Guardrails_Engine,
    GuardrailPersistenceError,
    ValuationInputs,
)


# --------------------------------------------------------------------------- #
# In-memory fakes for the injected collaborators (mirrors test_guardrails_properties)
# --------------------------------------------------------------------------- #


@dataclass
class FakeTitle:
    """A minimal stand-in for a ``titles`` row the engine reads via getattr.

    USD-native so cost normalization needs no exchange rate; no genre/territories
    so territory weighting is the identity; viewing hours configurable so the
    CPVH check can either compute or short-circuit (R4.5).
    """

    title_id: uuid.UUID
    asset_type: str = "ORIGINAL_FILM"
    acquisition_cost_or_budget: Decimal = Decimal("100.00")
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
    """Captures the create persistence write; no prior projection exists."""

    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.model_calls = 0

    async def get_latest_for_title(self, title_id: uuid.UUID) -> None:
        return None

    def model(self, **values: Any) -> _CapturedProjection:
        self.model_calls += 1
        return _CapturedProjection(values=values)

    async def create(self, projection: _CapturedProjection) -> _CapturedProjection:
        self.created = projection.values
        return projection


class FakeExchangeRateRepository:
    """Never consulted for USD-native titles; returns no rate if asked."""

    async def get_rate(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None

    async def get_latest_rate(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
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

    def __init__(self, stamp: uuid.UUID | None = None) -> None:
        self._stamp = stamp or uuid.uuid4()

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


# --- failure-injecting projection repositories (retry path, R8.7) ---------- #


@dataclass
class _ExistingProjection:
    """A pre-existing ``financial_projections`` row for the update path."""

    projection_id: uuid.UUID
    row_version: int
    values: dict[str, Any]


class FlakyCreateProjectionRepository:
    """Fails the first ``fail_times`` create attempts, then captures the write.

    Exercises the retry-on-failure path for the first-write (``create``) case:
    there is no prior projection, so each attempt tries ``create`` and the engine
    retries up to 3 times (R8.7).
    """

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.create_attempts = 0
        self.created: dict[str, Any] | None = None

    async def get_latest_for_title(self, title_id: uuid.UUID) -> None:
        return None

    def model(self, **values: Any) -> _CapturedProjection:
        return _CapturedProjection(values=values)

    async def create(self, projection: _CapturedProjection) -> _CapturedProjection:
        self.create_attempts += 1
        if self.create_attempts <= self._fail_times:
            raise RuntimeError(
                f"injected create failure #{self.create_attempts}"
            )
        self.created = projection.values
        return projection


class AlwaysFailingProjectionRepository:
    """Every persistence attempt raises; the prior stored value is left intact.

    Models the "all retries fail" case (R8.7): a prior projection exists, each
    ``update_with_version`` attempt raises, and because the engine's attempt is
    all-or-nothing the stored ``values`` are never mutated.
    """

    def __init__(self, prior: _ExistingProjection) -> None:
        self._prior = prior
        self.update_attempts = 0

    async def get_latest_for_title(self, title_id: uuid.UUID) -> _ExistingProjection:
        return self._prior

    def model(self, **values: Any) -> _CapturedProjection:  # pragma: no cover
        return _CapturedProjection(values=values)

    async def create(self, projection: _CapturedProjection) -> None:  # pragma: no cover
        raise AssertionError("create should not be called when a prior projection exists")

    async def update_with_version(
        self, projection_id: uuid.UUID, row_version: int, **values: Any
    ) -> None:
        self.update_attempts += 1
        # Never mutate the prior stored value -- the attempt is all-or-nothing.
        raise RuntimeError(f"injected update failure #{self.update_attempts}")

    @property
    def prior_values(self) -> dict[str, Any]:
        return self._prior.values


class VersionUpdateProjectionRepository:
    """A prior projection exists; captures the optimistic-lock update path.

    Lets the concurrency test assert the engine persists via
    ``update_with_version`` (optimistic locking) rather than ``create`` when a
    projection already exists -- the mechanism that keeps concurrent valuations
    from producing partial writes (R27.3).
    """

    def __init__(self, prior: _ExistingProjection) -> None:
        self._prior = prior
        self.update_calls: list[dict[str, Any]] = []
        self.create_calls = 0

    async def get_latest_for_title(self, title_id: uuid.UUID) -> _ExistingProjection:
        return self._prior

    def model(self, **values: Any) -> _CapturedProjection:
        return _CapturedProjection(values=values)

    async def create(self, projection: _CapturedProjection) -> None:
        self.create_calls += 1
        raise AssertionError("create must not be used when a prior projection exists")

    async def update_with_version(
        self, projection_id: uuid.UUID, row_version: int, **values: Any
    ) -> None:
        self.update_calls.append(
            {
                "projection_id": projection_id,
                "row_version": row_version,
                "values": values,
            }
        )


# --------------------------------------------------------------------------- #
# Wiring helpers
# --------------------------------------------------------------------------- #


def _build_engine(
    inputs: ValuationInputs,
    *,
    title: FakeTitle | None = None,
    projections: Any | None = None,
    stamp: uuid.UUID | None = None,
) -> tuple[Guardrails_Engine, uuid.UUID, Any, uuid.UUID]:
    """Wire the engine against in-memory fakes.

    Returns ``(engine, title_id, projection_repo, stamp)``.
    """
    title_id = uuid.uuid4()
    the_title = title or FakeTitle(title_id=title_id)
    # Keep the title id consistent with the one we return.
    the_title.title_id = title_id
    projection_repo = projections if projections is not None else FakeProjectionRepository()
    versioning = FakeVersioningEngine(stamp=stamp)
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(the_title),
        projection_repository=projection_repo,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=versioning,
        audit_service=FakeAuditService(),
        input_provider=FakeInputProvider(inputs),
    )
    return engine, title_id, projection_repo, versioning._stamp


def _base_inputs(
    *,
    churn_reduction_pct: Decimal = Decimal("2.0"),
    monthly_margin: Decimal = Decimal("1000"),
    milestone_schedule: list[dict[str, Any]] | None = None,
) -> ValuationInputs:
    """ValuationInputs with benign figures; a comfortably-passing payback schedule."""
    if milestone_schedule is None:
        milestone_schedule = [{"month": 1, "amount": Decimal("1"), "currency": "USD"}]
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


# --------------------------------------------------------------------------- #
# Persistence of all computed columns (R4.8, R5.4, R7.4, R8.6)
# --------------------------------------------------------------------------- #


async def test_persists_all_computed_columns() -> None:
    """Validates: Requirements 4.8, 5.4, 7.4, 8.6

    After ``evaluate`` completes, the engine persists every computed scorecard
    column to ``financial_projections``: calculated_cpvh (R4.8),
    ltv_to_cost_multiple (R5.4), payback_horizon_months (R7.4),
    recommendation_status (R8.6), plus churn_reduction_pct, normalized_cost_usd,
    exchange_rate_id, model_version_id, and the explanation. The persisted values
    mirror the returned :class:`ValuationResult`.
    """
    inputs = _base_inputs(
        churn_reduction_pct=Decimal("2.0"),
        monthly_margin=Decimal("1000"),
        milestone_schedule=[{"month": 1, "amount": Decimal("500"), "currency": "USD"}],
    )
    engine, title_id, projections, stamp = _build_engine(inputs)

    result = await engine.evaluate(title_id)

    assert projections.created is not None
    persisted = projections.created

    # Every documented column is present in the write.
    expected_columns = {
        "calculated_cpvh",
        "ltv_to_cost_multiple",
        "churn_reduction_pct",
        "payback_horizon_months",
        "recommendation_status",
        "normalized_cost_usd",
        "exchange_rate_id",
        "model_version_id",
        "explanation",
    }
    assert expected_columns.issubset(persisted.keys())

    # The persisted values mirror the returned result (R4.8, R5.4, R7.4, R8.6).
    assert persisted["calculated_cpvh"] == result["calculated_cpvh"]
    assert persisted["ltv_to_cost_multiple"] == result["ltv_to_cost_multiple"]
    assert persisted["churn_reduction_pct"] == result["churn_reduction_pct"]
    assert persisted["payback_horizon_months"] == result["payback_horizon_months"]
    assert persisted["recommendation_status"] == result["recommendation_status"]
    assert persisted["normalized_cost_usd"] == result["normalized_cost_usd"]
    assert persisted["exchange_rate_id"] == result["exchange_rate_id"]
    assert persisted["model_version_id"] == result["model_version_id"] == stamp

    # CPVH is a concrete value for a title with positive viewing hours (R4.8).
    assert persisted["calculated_cpvh"] is not None

    # The explanation is persisted as a JSON-serializable structure (JSONB).
    assert isinstance(persisted["explanation"], dict)
    assert "checks" in persisted["explanation"]
    assert "dominant_factor" in persisted["explanation"]
    assert "unclassifiable" in persisted["explanation"]


# --------------------------------------------------------------------------- #
# Retry-on-failure preserving prior value (R8.7)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fail_times", [1, 2])
async def test_persist_retries_then_succeeds(fail_times: int) -> None:
    """Validates: Requirements 8.7

    When the first one or two persistence attempts fail, the engine retries
    (up to 3 attempts total) and ultimately persists the projection. The final
    captured write holds the computed scorecard, confirming the retry succeeded
    without losing data.
    """
    inputs = _base_inputs()
    projections = FlakyCreateProjectionRepository(fail_times=fail_times)
    engine, title_id, repo, _ = _build_engine(inputs, projections=projections)

    result = await engine.evaluate(title_id)

    # It retried exactly (fail_times) extra times before succeeding.
    assert repo.create_attempts == fail_times + 1
    assert repo.create_attempts <= 3
    assert repo.created is not None
    assert repo.created["recommendation_status"] == result["recommendation_status"]


async def test_persist_exhausts_retries_and_preserves_prior_value() -> None:
    """Validates: Requirements 8.7

    When every persistence attempt fails, the engine raises
    :class:`GuardrailPersistenceError` after exactly 3 attempts, identifies the
    affected title, and leaves the previously stored projection value untouched
    (the retry path never partially overwrites it).
    """
    prior_values = {
        "calculated_cpvh": Decimal("0.1000"),
        "ltv_to_cost_multiple": Decimal("4.0"),
        "churn_reduction_pct": Decimal("2.0"),
        "payback_horizon_months": 10,
        "recommendation_status": "GREENLIGHT",
        "normalized_cost_usd": Decimal("100.00"),
        "exchange_rate_id": None,
        "model_version_id": uuid.uuid4(),
        "explanation": {"checks": [], "dominant_factor": None, "unclassifiable": False},
    }
    # Snapshot of what the prior row holds, for an untouched-after assertion.
    prior_snapshot = dict(prior_values)
    prior = _ExistingProjection(
        projection_id=uuid.uuid4(), row_version=7, values=prior_values
    )
    projections = AlwaysFailingProjectionRepository(prior)

    inputs = _base_inputs()
    engine, title_id, repo, _ = _build_engine(inputs, projections=projections)

    with pytest.raises(GuardrailPersistenceError) as excinfo:
        await engine.evaluate(title_id)

    # Exactly 3 attempts were made (R8.7).
    assert repo.update_attempts == 3
    err = excinfo.value
    assert err.title_id == title_id
    assert err.attempts == 3
    # The error identifies the affected title in its message.
    assert str(title_id) in str(err)
    # The previously stored value is preserved, byte-for-byte.
    assert repo.prior_values == prior_snapshot


# --------------------------------------------------------------------------- #
# CPVH null when projected_viewing_hours == 0 (R4.5)
# --------------------------------------------------------------------------- #


async def test_cpvh_null_and_not_persisted_as_value_when_viewing_hours_zero() -> None:
    """Validates: Requirements 4.5

    When ``projected_viewing_hours`` is zero, CPVH cannot be computed: the result
    carries ``calculated_cpvh = None`` and the persisted projection stores
    ``None`` (no calculated_cpvh value is stamped). The CPVH check is marked
    failed.
    """
    title = FakeTitle(title_id=uuid.uuid4(), projected_viewing_hours=Decimal("0"))
    inputs = _base_inputs()
    engine, title_id, projections, _ = _build_engine(inputs, title=title)

    result = await engine.evaluate(title_id)

    # No CPVH value is produced (R4.5).
    assert result["calculated_cpvh"] is None

    # And nothing is persisted as a calculated_cpvh value.
    assert projections.created is not None
    assert projections.created["calculated_cpvh"] is None

    # The CPVH check is recorded as failed/breached in the explanation.
    cpvh_check = next(
        c for c in result["explanation"]["checks"] if c["name"] == "CPVH"
    )
    assert cpvh_check["passed"] is False
    assert cpvh_check["breached"] is True
    assert cpvh_check["computed_value"] is None


# --------------------------------------------------------------------------- #
# Concurrency: no partial writes via optimistic locking (R27.3)
# --------------------------------------------------------------------------- #


async def test_uses_optimistic_lock_update_path_when_projection_exists() -> None:
    """Validates: Requirements 27.3

    When a projection already exists for the title, the engine persists through
    the optimistic-lock ``update_with_version(projection_id, row_version, ...)``
    path rather than ``create``. This is the mechanism that lets concurrent
    valuations of the same title complete without producing corrupted or
    partially written data: a stale row_version makes the losing writer's update
    fail cleanly instead of clobbering the row. We assert the engine takes this
    path and forwards the existing row's id and version.

    Deterministic fake-based test (preferred over a live-DB test for the
    concurrency angle); the real row-level-locking test is the skippable
    integration placeholder below.
    """
    existing = _ExistingProjection(
        projection_id=uuid.uuid4(),
        row_version=3,
        values={"recommendation_status": "GREENLIGHT"},
    )
    projections = VersionUpdateProjectionRepository(existing)

    inputs = _base_inputs()
    engine, title_id, repo, _ = _build_engine(inputs, projections=projections)

    result = await engine.evaluate(title_id)

    # The create path was never used; the optimistic-lock update path was.
    assert repo.create_calls == 0
    assert len(repo.update_calls) == 1

    call = repo.update_calls[0]
    assert call["projection_id"] == existing.projection_id
    assert call["row_version"] == existing.row_version
    # The full scorecard is written atomically in a single update (no partial write).
    assert call["values"]["recommendation_status"] == result["recommendation_status"]
    assert "calculated_cpvh" in call["values"]
    assert "ltv_to_cost_multiple" in call["values"]
    assert "payback_horizon_months" in call["values"]


@pytest.mark.integration
async def test_concurrent_valuations_no_partial_writes_real_db() -> None:
    """Validates: Requirements 27.3

    Real row-level-locking behaviour needs a live PostgreSQL instance. This test
    skips cleanly when no database is configured (no CINEROI_DATABASE_URL /
    TEST_DATABASE_URL), so the suite runs fast without a DB. The deterministic
    optimistic-lock assertion above covers the engine-contract angle.
    """
    db_url = os.environ.get("CINEROI_DATABASE_URL") or os.environ.get(
        "TEST_DATABASE_URL"
    )
    if not db_url:
        pytest.skip(
            "no database configured (set CINEROI_DATABASE_URL or TEST_DATABASE_URL "
            "to exercise real row-level-locking concurrency)"
        )
    # When a DB is available this would run two concurrent evaluate() calls
    # against the same title and assert exactly one row with a consistent,
    # fully-written scorecard remains. Left as a documented placeholder; the
    # fake-based optimistic-lock test covers the engine contract deterministically.
    pytest.skip("real-DB concurrency harness not wired in this fast suite")
