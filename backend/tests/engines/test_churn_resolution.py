"""Engine-level churn-resolution tests for the Churn_Mitigation_Model.

Feature: calculable-churn-model (task 8). Exercises the real
:meth:`app.engines.guardrails.Guardrails_Engine.evaluate` orchestration through
the dependency-injection seam, asserting how churn is resolved and how the
resolution is reflected on the returned :class:`ValuationResult`
(``churn_detail``), the persisted projection ``explanation``, and the audit
"after" snapshot.

The fakes reuse the in-memory style established in
``tests/engines/test_guardrails_properties.py`` (imported directly where
unchanged). Three collaborators needed richer behaviour than those fakes
provide, so they are defined locally:

* :class:`FakeMetadataVectorRepository` — ``list_for_title`` returns metadata
  vectors carrying ``talent_pedigree_score`` / ``production_scale_metric`` /
  ``extraction_status`` / ``created_at`` (the fields ``_resolve_metadata_features``
  reads; it picks the latest SUCCESS by ``created_at``).
* :class:`FakeExclusiveLicenseTermRepository` — ``list_for_title`` returns license
  terms carrying ``is_exclusive`` (and a milestone schedule so payback computes
  without an inputs-supplied schedule).
* :class:`FakeSentimentTelemetryRepository` — ``get_for_genre_territory`` returns a
  reading with ``social_sentiment_index`` plus the ``chart_velocity_score`` /
  ``licensing_inflation_multiplier`` fields the territory-weighting path reads;
  configured per ``(genre, territory)`` so a territory with no reading is
  excluded from the Telemetry_Heat mean.
* :class:`FakeActiveVersioningEngine` — extends the stamp-only
  :class:`FakeVersioningEngine` with ``read_active()`` returning a row whose
  ``guardrail_params`` carries (or omits) a ``churn_model`` dict, driving the
  MODEL_VERSION-vs-DEFAULTS params source.

Coverage (task 8): SUPPLIED wins over features; CALCULATED from features; latest
SUCCESS metadata vector precedence; Telemetry_Heat mean (and empty -> missing);
defaults fallback; persisted explanation shape; audit records the method.
Validates: Requirements 2.1, 3.2, 4.1, 6.1, 6.3, 6.5, 7.2, 7.4.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain.churn import DEFAULT_CHURN_MODEL_PARAMS
from app.engines.guardrails import Guardrails_Engine, ValuationInputs
from tests.engines.test_guardrails_properties import (
    FakeAuditService,
    FakeExchangeRateRepository,
    FakeInputProvider,
    FakeProjectionRepository,
    FakeTitleRepository,
    FakeVersioningEngine,
)


# --------------------------------------------------------------------------- #
# Local fakes (richer than the shared ones imported above)
# --------------------------------------------------------------------------- #


@dataclass
class FakeTitle:
    """A ``titles`` row stand-in with genre + territories so churn feature and
    telemetry resolution exercise real code paths.

    USD-native so cost normalization needs no exchange rate; a genre and target
    territories drive both the territory weighting and Telemetry_Heat; non-zero
    viewing hours keep the CPVH check from short-circuiting the ``evaluate`` run.
    """

    title_id: uuid.UUID
    asset_type: str = "ORIGINAL_SERIES"
    acquisition_cost_or_budget: Decimal = Decimal("1000.00")
    native_currency: str = "USD"
    target_territories: list[str] = field(default_factory=lambda: ["US", "CA"])
    genre_tag: str | None = "DRAMA"
    projected_viewing_hours: Decimal = Decimal("1000")


@dataclass
class FakeMetadataVector:
    """A ``metadata_vectors`` row stand-in read by ``_resolve_metadata_features``."""

    talent_pedigree_score: Decimal | None
    production_scale_metric: Decimal | None
    extraction_status: str
    created_at: datetime


class FakeMetadataVectorRepository:
    """Returns a fixed list of metadata vectors for any title.

    ``_resolve_metadata_features`` filters to ``extraction_status == "SUCCESS"``
    and picks the most recent by ``created_at``.
    """

    def __init__(self, vectors: list[FakeMetadataVector]) -> None:
        self._vectors = vectors

    async def list_for_title(self, title_id: uuid.UUID) -> list[FakeMetadataVector]:
        return list(self._vectors)


@dataclass
class FakeLicenseTerm:
    """A ``license_terms`` row stand-in carrying exclusivity + a payback schedule."""

    is_exclusive: bool | None = True
    milestone_schedule: list[dict[str, Any]] = field(
        default_factory=lambda: [{"month": 1, "amount": Decimal("1"), "currency": "USD"}]
    )


class FakeExclusiveLicenseTermRepository:
    """Returns a configurable list of license terms for any title."""

    def __init__(self, terms: list[FakeLicenseTerm] | None = None) -> None:
        self._terms = (
            terms if terms is not None else [FakeLicenseTerm(is_exclusive=True)]
        )

    async def list_for_title(self, title_id: uuid.UUID) -> list[FakeLicenseTerm]:
        return list(self._terms)


@dataclass
class FakeTelemetryReading:
    """A ``market_telemetry_cache`` row stand-in.

    ``social_sentiment_index`` (0-1) feeds Telemetry_Heat; ``chart_velocity_score``
    and ``licensing_inflation_multiplier`` feed the (neutral-by-default) territory
    weighting so the LTV/CPM blend stays identity when they are 0 / 1.
    """

    social_sentiment_index: Decimal | None
    chart_velocity_score: Decimal = Decimal("0")
    licensing_inflation_multiplier: Decimal = Decimal("1")


class FakeSentimentTelemetryRepository:
    """Returns a reading per ``(genre, territory)`` key, else ``None``.

    A ``None`` return (no key) models a territory with no cached reading, which
    the Telemetry_Heat mean excludes (R6.4) and, when every territory misses,
    treats as a missing feature (R6.5).
    """

    def __init__(self, readings: dict[tuple[str, str], FakeTelemetryReading]) -> None:
        self._readings = readings

    async def get_for_genre_territory(
        self, genre: str, territory: str
    ) -> FakeTelemetryReading | None:
        return self._readings.get((genre, territory))


@dataclass
class FakeActiveModelVersion:
    """A ``model_versions`` row stand-in exposing ``guardrail_params`` JSONB."""

    model_version_id: uuid.UUID
    guardrail_params: dict[str, Any]


class FakeActiveVersioningEngine(FakeVersioningEngine):
    """Stamp-only fake extended with ``read_active()`` for churn params (R3.1).

    ``read_active()`` returns a row whose ``guardrail_params`` carries the given
    ``churn_model`` dict; passing ``churn_model=None`` omits the key so
    ``parse_params`` falls back to the domain defaults with source DEFAULTS
    (R3.2). The stamp used by ``evaluate`` and the ``read_active`` row share a
    model-version id so the persisted ``churn_model.model_version_id`` matches.
    """

    def __init__(self, churn_model: dict[str, Any] | None) -> None:
        super().__init__()
        params: dict[str, Any] = {}
        if churn_model is not None:
            params["churn_model"] = churn_model
        self._active = FakeActiveModelVersion(
            model_version_id=self._stamp, guardrail_params=params
        )

    async def read_active(self) -> FakeActiveModelVersion:
        return self._active


# --------------------------------------------------------------------------- #
# Default-params serialization (what the active model version carries)
# --------------------------------------------------------------------------- #


def _default_churn_model_json() -> dict[str, Any]:
    """Serialize DEFAULT_CHURN_MODEL_PARAMS into a JSON-style ``churn_model`` dict.

    This is the valid, non-negative parameter block parse_params accepts, so the
    resolved params source is MODEL_VERSION and the numbers match the domain
    defaults used elsewhere in the design verification table.
    """
    p = DEFAULT_CHURN_MODEL_PARAMS
    return {
        "intercept": str(p.intercept),
        "asset_offsets": {k: str(v) for k, v in p.asset_offsets.items()},
        "pedigree_weight": str(p.pedigree_weight),
        "scale_weight": str(p.scale_weight),
        "exclusivity_lift": str(p.exclusivity_lift),
        "telemetry_weight": str(p.telemetry_weight),
        "min_churn": str(p.min_churn),
        "max_churn": str(p.max_churn),
    }


# --------------------------------------------------------------------------- #
# Wiring helper
# --------------------------------------------------------------------------- #


def _build_engine(
    inputs: ValuationInputs,
    *,
    title: FakeTitle,
    metadata_vectors: list[FakeMetadataVector] | None = None,
    license_terms: list[FakeLicenseTerm] | None = None,
    telemetry: dict[tuple[str, str], FakeTelemetryReading] | None = None,
    churn_model: dict[str, Any] | None,
) -> tuple[Guardrails_Engine, uuid.UUID, FakeProjectionRepository, FakeAuditService]:
    """Wire the engine against in-memory fakes.

    Returns ``(engine, title_id, projections, audit)``. ``churn_model`` is the
    dict placed under the active version's ``guardrail_params["churn_model"]``
    (``None`` omits it, driving the DEFAULTS fallback).
    """
    projections = FakeProjectionRepository()
    audit = FakeAuditService()
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=projections,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeExclusiveLicenseTermRepository(license_terms),
        telemetry_repository=FakeSentimentTelemetryRepository(telemetry or {}),
        model_versioning_engine=FakeActiveVersioningEngine(churn_model),
        audit_service=audit,
        input_provider=FakeInputProvider(inputs),
        metadata_vector_repo=FakeMetadataVectorRepository(metadata_vectors or []),
    )
    return engine, title.title_id, projections, audit


def _inputs(
    *,
    churn_reduction_pct: Decimal | None,
    talent_pedigree_score: Decimal | None = None,
    production_scale_metric: Decimal | None = None,
    is_exclusive: bool | None = None,
) -> ValuationInputs:
    """Benign LTV/CPM figures; churn is the knob (``None`` => CALCULATED).

    The optional ``talent_pedigree_score`` / ``production_scale_metric`` /
    ``is_exclusive`` model explicit churn feature facts carried on the snapshot
    (calculable-churn-model, R6.1); when set they take precedence over the
    metadata-vector / license-term repositories in ``_resolve_churn``.
    """
    return ValuationInputs(
        churn_reduction_value=Decimal("1"),
        ltv=Decimal("100"),
        watch_time_elasticity=Decimal("1"),
        cpm=Decimal("10"),
        ad_impressions=Decimal("1000"),
        churn_reduction_pct=churn_reduction_pct,
        monthly_margin=Decimal("1000"),
        milestone_schedule=None,  # fall back to the license-term schedule
        talent_pedigree_score=talent_pedigree_score,
        production_scale_metric=production_scale_metric,
        is_exclusive=is_exclusive,
    )


def _reading(index: str) -> FakeTelemetryReading:
    """A telemetry reading with the given sentiment index and neutral weighting."""
    return FakeTelemetryReading(social_sentiment_index=Decimal(index))


def _sum_breakdown(breakdown: dict[str, str]) -> Decimal:
    """Sum the string point values of a persisted churn_breakdown as Decimals."""
    return sum((Decimal(v) for v in breakdown.values()), Decimal("0"))


def _domain_churn(
    *,
    asset_type: str = "ORIGINAL_SERIES",
    pedigree: str = "8.5",
    scale: str = "9.0",
    exclusive: bool = True,
    heat: str | None = "65",
    genre: str | None = "DRAMA",
) -> Decimal:
    """Recompute the expected churn straight from the domain for the given
    features, so the engine tests assert engine == domain rather than a hardcoded
    number that drifts whenever the coefficients are re-tuned."""
    from app.domain.churn import ChurnFeatures, calculate_churn_mitigation

    features = ChurnFeatures(
        asset_type=asset_type,
        pedigree=Decimal(pedigree),
        production_scale=Decimal(scale),
        is_exclusive=exclusive,
        telemetry_heat=None if heat is None else Decimal(heat),
        genre=genre,
    )
    return calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS
    ).churn_reduction_pct


# --------------------------------------------------------------------------- #
# 1. SUPPLIED wins over features (R4.1)
# --------------------------------------------------------------------------- #


async def test_supplied_churn_wins_over_present_features() -> None:
    """Validates: Requirements 4.1, 7.2, 7.4

    When the provider carries a finite Decimal churn, the engine resolves
    SUPPLIED and uses that value exactly, even though metadata/telemetry/license
    features are all present. The breakdown is omitted and the persisted
    explanation records SUPPLIED with a null churn_breakdown.
    """
    title = FakeTitle(title_id=uuid.uuid4())
    engine, title_id, projections, audit = _build_engine(
        _inputs(churn_reduction_pct=Decimal("2.0")),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "SUPPLIED"
    assert result["churn_reduction_pct"] == Decimal("2.0")
    assert detail.churn_reduction_pct == Decimal("2.0")
    assert detail.breakdown is None

    # Persisted explanation: SUPPLIED, no breakdown.
    assert projections.created is not None
    churn_model = projections.created["explanation"]["churn_model"]
    assert churn_model["churn_method"] == "SUPPLIED"
    assert churn_model["churn_breakdown"] is None
    assert churn_model["missing_features"] == []


# --------------------------------------------------------------------------- #
# 2. CALCULATED from features when provider churn is None (R6.1, R6.3)
# --------------------------------------------------------------------------- #


async def test_calculated_from_features_matches_domain() -> None:
    """Validates: Requirements 6.1, 6.3, 7.2

    With no supplied churn, the engine computes CALCULATED from a SUCCESS
    metadata vector (pedigree 8.5, scale 9.0), an exclusive license, DRAMA
    sentiment 0.65 across both territories (heat 65), and ORIGINAL_SERIES: the
    design's Aurora row => 2.11. The breakdown is present, sums (with
    bounds_adjustment) to the final value, and the params source is MODEL_VERSION.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "CALCULATED"
    assert result["churn_reduction_pct"] == _domain_churn()
    assert detail.params_source == "MODEL_VERSION"
    assert detail.breakdown is not None

    # The per-feature points conserve to the final value exactly (R1.8).
    points_sum = sum((c.points for c in detail.breakdown), Decimal("0"))
    assert points_sum == result["churn_reduction_pct"]

    # Persisted breakdown mirrors it and sums as Decimals to churn_reduction_pct.
    churn_model = projections.created["explanation"]["churn_model"]
    assert churn_model["churn_method"] == "CALCULATED"
    assert _sum_breakdown(churn_model["churn_breakdown"]) == result["churn_reduction_pct"]


# --------------------------------------------------------------------------- #
# 3. Latest SUCCESS metadata vector precedence (R6.1)
# --------------------------------------------------------------------------- #


async def test_latest_success_metadata_vector_is_used() -> None:
    """Validates: Requirements 6.1

    When multiple metadata vectors exist, the engine uses the latest SUCCESS by
    ``created_at``, ignoring an even-newer FAILED row and an older SUCCESS. The
    chosen pedigree/scale produce a distinguishable churn (the Aurora 2.11 case),
    which would differ had the older SUCCESS (lower pedigree/scale) been chosen.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, _, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            # Older SUCCESS (would yield a lower churn if chosen).
            FakeMetadataVector(
                talent_pedigree_score=Decimal("4.0"),
                production_scale_metric=Decimal("3.5"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
            # Newer SUCCESS -> the one that must win.
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ),
            # Even newer but FAILED -> must be ignored.
            FakeMetadataVector(
                talent_pedigree_score=Decimal("1.0"),
                production_scale_metric=Decimal("1.0"),
                extraction_status="FAILED",
                created_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            ),
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "CALCULATED"
    # Picks pedigree 8.5 / scale 9.0 (newest SUCCESS) -> 2.11, not the older row.
    assert result["churn_reduction_pct"] == _domain_churn()
    assert "pedigree" not in detail.missing_features
    assert "production_scale" not in detail.missing_features


# --------------------------------------------------------------------------- #
# 4. Telemetry_Heat mean over territories with a reading (R6.3, R6.4)
# --------------------------------------------------------------------------- #


async def test_telemetry_heat_is_mean_of_available_readings() -> None:
    """Validates: Requirements 6.3, 6.4

    Two territories with sentiment 0.60 and 0.70 give a Telemetry_Heat of
    mean(60, 70) = 65.0, so the market_telemetry_heat contribution is
    telemetry_weight * 65 = 0.005 * 65 = 0.325 -> 0.33 at 2 dp. A third territory
    with no reading is excluded from the mean (does not drag it down).
    """
    title = FakeTitle(
        title_id=uuid.uuid4(),
        asset_type="ORIGINAL_SERIES",
        target_territories=["US", "CA", "MX"],  # MX has no reading -> excluded
    )
    engine, title_id, _, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.60"),
            ("DRAMA", "CA"): _reading("0.70"),
            # MX intentionally absent.
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert "telemetry_heat" not in detail.missing_features
    heat = next(c for c in detail.breakdown if c.key == "market_telemetry_heat")
    assert heat.input == Decimal("65.00")  # mean(60, 70), MX excluded
    assert heat.points == Decimal("0.33")  # 0.005 * 65 = 0.325 -> 0.33


# --------------------------------------------------------------------------- #
# 5. Telemetry empty -> missing feature (R6.5)
# --------------------------------------------------------------------------- #


async def test_telemetry_missing_uses_neutral_default() -> None:
    """Validates: Requirements 15.1, 15.2

    When no target territory has a cached reading for the genre, Telemetry_Heat
    is NOT scored zero (which would penalize a data gap): it uses the neutral
    default (50) and is reported in assumed_features, not missing_features. No
    exception is raised (the empty-mean guard holds).
    """
    from app.domain.churn import DEFAULT_TELEMETRY_NEUTRAL

    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={},  # no readings for any (genre, territory)
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert "telemetry_heat" not in detail.missing_features
    assert "telemetry_heat" in detail.assumed_features
    heat = next(c for c in detail.breakdown if c.key == "market_telemetry_heat")
    assert heat.input == DEFAULT_TELEMETRY_NEUTRAL
    expected = (
        DEFAULT_CHURN_MODEL_PARAMS.telemetry_weight * DEFAULT_TELEMETRY_NEUTRAL
    ).quantize(Decimal("0.01"))
    assert heat.points == expected
    # The persisted explanation lists telemetry as assumed, not missing.
    cm = projections.created["explanation"]["churn_model"]
    assert "telemetry_heat" in cm["assumed_features"]
    assert "telemetry_heat" not in cm["missing_features"]


# --------------------------------------------------------------------------- #
# 6. Defaults fallback when churn_model params are absent (R3.2)
# --------------------------------------------------------------------------- #


async def test_defaults_fallback_when_churn_model_params_absent() -> None:
    """Validates: Requirements 3.2

    When the active model version's guardrail_params carries no ``churn_model``
    key, the engine falls back to DEFAULT_CHURN_MODEL_PARAMS: params_source is
    DEFAULTS and the result still computes. The default params equal the design
    constants, so the Aurora feature set still yields 2.11.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=None,  # omit -> DEFAULTS
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "CALCULATED"
    assert detail.params_source == "DEFAULTS"
    assert result["churn_reduction_pct"] == _domain_churn()
    assert projections.created["explanation"]["churn_model"]["params_source"] == "DEFAULTS"


# --------------------------------------------------------------------------- #
# 7. Persisted explanation shape (R7.2)
# --------------------------------------------------------------------------- #


async def test_persisted_explanation_shape_for_calculated() -> None:
    """Validates: Requirements 7.2

    After evaluate, the persisted projection's explanation carries a
    ``churn_model`` object with the documented keys; for a CALCULATED result the
    ``churn_breakdown`` is a dict whose string values sum (as Decimals) to
    ``churn_reduction_pct``, and ``model_version_id`` is the valuation stamp.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)

    assert projections.created is not None
    churn_model = projections.created["explanation"]["churn_model"]

    # Documented keys present.
    assert set(churn_model.keys()) == {
        "churn_method",
        "is_borderline",
        "params_source",
        "model_version_id",
        "missing_features",
        "assumed_features",
        "churn_breakdown",
    }
    assert churn_model["churn_method"] == "CALCULATED"
    assert churn_model["model_version_id"] == str(result["model_version_id"])

    breakdown = churn_model["churn_breakdown"]
    assert isinstance(breakdown, dict)
    # Six feature keys always present (bounds_adjustment only when nonzero).
    assert {
        "base_platform_rate",
        "asset_cadence",
        "talent_pedigree_contribution",
        "production_scale_contribution",
        "exclusivity_lift",
        "market_telemetry_heat",
        "genre_affinity",
    }.issubset(breakdown.keys())
    # String values conserve to the final churn_reduction_pct.
    assert _sum_breakdown(breakdown) == result["churn_reduction_pct"]


# --------------------------------------------------------------------------- #
# 8. Audit records the resolved method (R7.4)
# --------------------------------------------------------------------------- #


async def test_audit_after_payload_records_churn_method() -> None:
    """Validates: Requirements 7.4

    The audit "after" snapshot records ``churn_method`` equal to the resolved
    method, for both a CALCULATED resolution and a SUPPLIED one.
    """
    # CALCULATED path.
    calc_title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    calc_engine, calc_id, _, calc_audit = _build_engine(
        _inputs(churn_reduction_pct=None),
        title=calc_title,
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("8.5"),
                production_scale_metric=Decimal("9.0"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=True)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )
    calc_result = await calc_engine.evaluate(calc_id)
    assert len(calc_audit.records) == 1
    calc_after = calc_audit.records[0]["after"]
    assert calc_after["churn_method"] == "CALCULATED"
    assert calc_after["churn_method"] == calc_result["churn_detail"].method

    # SUPPLIED path.
    sup_title = FakeTitle(title_id=uuid.uuid4())
    sup_engine, sup_id, _, sup_audit = _build_engine(
        _inputs(churn_reduction_pct=Decimal("2.0")),
        title=sup_title,
        churn_model=_default_churn_model_json(),
    )
    sup_result = await sup_engine.evaluate(sup_id)
    assert len(sup_audit.records) == 1
    sup_after = sup_audit.records[0]["after"]
    assert sup_after["churn_method"] == "SUPPLIED"
    assert sup_after["churn_method"] == sup_result["churn_detail"].method


# --------------------------------------------------------------------------- #
# 9. Snapshot-carried feature facts win over the repos (R6.1, R8.1, R8.2)
# --------------------------------------------------------------------------- #


async def test_snapshot_facts_take_precedence_over_repositories() -> None:
    """Validates: Requirements 6.1, 8.1, 8.2

    This mirrors the Asset Studio quick-evaluate path, which creates NO
    metadata-vector or license rows and instead carries the churn feature facts
    (pedigree / production scale / exclusivity) on the snapshot. When those facts
    are present on ``inputs``, ``_resolve_churn`` uses them in preference to the
    metadata-vector and license-term repositories, so a snapshot WITHOUT churn
    computes CALCULATED and matches the domain value for those carried facts.

    The repos here are intentionally populated with *different* facts (lower
    pedigree/scale, non-exclusive) that would yield a different churn; the carried
    Aurora facts (8.5 / 9.0 / exclusive, ORIGINAL_SERIES, heat 65) must win and
    produce 2.11, confirming precedence rather than the repo-derived value.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(
            churn_reduction_pct=None,
            talent_pedigree_score=Decimal("8.5"),
            production_scale_metric=Decimal("9.0"),
            is_exclusive=True,
        ),
        title=title,
        # DB rows carry conflicting facts that must be ignored in favor of the
        # snapshot facts carried on inputs.
        metadata_vectors=[
            FakeMetadataVector(
                talent_pedigree_score=Decimal("4.0"),
                production_scale_metric=Decimal("3.5"),
                extraction_status="SUCCESS",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        license_terms=[FakeLicenseTerm(is_exclusive=False)],
        telemetry={
            ("DRAMA", "US"): _reading("0.65"),
            ("DRAMA", "CA"): _reading("0.65"),
        },
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "CALCULATED"
    # Carried Aurora facts win (8.5 / 9.0 / exclusive) -> 2.11, not the repo set.
    assert result["churn_reduction_pct"] == _domain_churn()
    assert "pedigree" not in detail.missing_features
    assert "production_scale" not in detail.missing_features

    # The exclusivity lift is present (carried is_exclusive=True won over the
    # non-exclusive license term).
    excl = next(c for c in detail.breakdown if c.key == "exclusivity_lift")
    assert excl.points == Decimal("0.25")

    churn_model = projections.created["explanation"]["churn_model"]
    assert churn_model["churn_method"] == "CALCULATED"
    assert _sum_breakdown(churn_model["churn_breakdown"]) == result["churn_reduction_pct"]


async def test_supplied_snapshot_churn_is_supplied_even_with_carried_facts() -> None:
    """Validates: Requirements 4.1, 8.1

    Mirrors the quick-evaluate SUPPLIED path: when the snapshot carries an
    explicit churn value, resolution is SUPPLIED (used exactly, no breakdown),
    regardless of any carried feature facts.
    """
    title = FakeTitle(title_id=uuid.uuid4(), asset_type="ORIGINAL_SERIES")
    engine, title_id, projections, _ = _build_engine(
        _inputs(
            churn_reduction_pct=Decimal("3.25"),
            talent_pedigree_score=Decimal("8.5"),
            production_scale_metric=Decimal("9.0"),
            is_exclusive=True,
        ),
        title=title,
        churn_model=_default_churn_model_json(),
    )

    result = await engine.evaluate(title_id)
    detail = result["churn_detail"]

    assert detail is not None
    assert detail.method == "SUPPLIED"
    assert result["churn_reduction_pct"] == Decimal("3.25")
    assert detail.breakdown is None
    churn_model = projections.created["explanation"]["churn_model"]
    assert churn_model["churn_method"] == "SUPPLIED"
    assert churn_model["churn_breakdown"] is None
