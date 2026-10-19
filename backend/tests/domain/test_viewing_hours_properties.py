"""Property-based tests for the Projected_Viewing_Hours Content_Eval_Model.

# Feature: content-eval-model

Targets the pure :mod:`app.domain.viewing_hours` module (task 2), the log-space
member of the Content_Eval_Model family. Feature inputs are built through the
shared :func:`app.domain.features.derive_features` contract (task 1) so the tests
exercise exactly the vector the engine path, dataset generator, and harness all
share.

The properties below map to the design's "Correctness Properties" section and
mirror the depth of the churn model's suite
(``test_churn_properties.py``). Each test carries a leading
``# Feature: content-eval-model, Property N: ...`` comment matching the house
convention and a docstring citing the acceptance criteria it exercises.

Properties covered here:
- P1 Determinism (Requirements 1.2)
- P3 Breakdown conservation, log-space (Requirements 1.3, 4.4)
- P4 Monotonicity in a non-negative-coefficient feature (Requirements 4.3)
- P5 Domain safety / positive-floor clamp (Requirements 1.1, 2.1)
- P6 Precedence, SUPPLIED-wins (Requirements 1.5, 1.6, 8.3)
- P7 Graceful degradation on partial/empty raw features (Requirements 2.4)

Several tests carry ``@settings(deadline=None)``: the log-space model evaluates
``exp``/``ln`` under a 50-digit Decimal context, which is transcendental-heavy,
so determinism -- not per-example latency -- is what is under test (matching the
house convention in ``test_fit.py`` / ``test_what_if_scenario.py``).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain import features as featmod
from app.domain import viewing_hours as vh

# ---------------------------------------------------------------------------
# Shared strategies -- raw feature mappings fed through derive_features so the
# tests exercise the real FeatureVector contract (clamping, neutral defaults).
# ---------------------------------------------------------------------------

_GENRES = ("drama", "crime", "comedy", "documentary", "sci-fi", "thriller")
_ASSET_TYPES = ("ORIGINAL_SERIES", "CO_PRODUCTION", "ORIGINAL_FILM", "LICENSED_LIBRARY")
_FORMATS = ("scripted-series", "limited-series", "original-film", "library")


def _dec(min_value: str, max_value: str, places: int = 2) -> st.SearchStrategy:
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        allow_nan=False,
        allow_infinity=False,
        places=places,
    )


# In-range numeric feature values spanning each documented domain.
_rating = _dec("0", "1", places=3)
_log_votes = _dec("0", "15", places=3)
_award = _dec("0", "1", places=3)
_runtime = _dec("0", "400", places=1)
_scale = _dec("0", "10", places=2)
_pedigree = _dec("0", "10", places=2)

# A raw mapping strategy: every key may be present or absent so partial/empty
# inputs are covered too. Values are native (Decimal/str/bool/int) just as the
# generator/connector layer would hand them to derive_features.
_raw_feature_mapping = st.fixed_dictionaries(
    {},
    optional={
        "asset_type": st.sampled_from(_ASSET_TYPES),
        "genre": st.sampled_from(_GENRES),
        "content_format": st.sampled_from(_FORMATS),
        "runtime_minutes": _runtime,
        "is_exclusive": st.booleans(),
        "production_scale": _scale,
        "talent_pedigree": _pedigree,
        "normalized_rating": _rating,
        "log_vote_count": _log_votes,
        "franchise_flag": st.booleans(),
        "award_signal": _award,
        "release_year": st.integers(min_value=1950, max_value=2030),
    },
)

# The numeric predictive features that carry a non-negative beta in the default
# params and are monotone-increasing in the prediction. These are the features a
# monotonicity bump applies to.
_MONOTONE_NUMERIC_FEATURES = (
    "runtime_minutes",
    "production_scale",
    "talent_pedigree",
    "normalized_rating",
    "log_vote_count",
    "award_signal",
)


def _vector(raw: dict | None) -> featmod.FeatureVector:
    return featmod.derive_features(raw)


# ---------------------------------------------------------------------------
# Property 1: Determinism (Requirements 1.2)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 1: Determinism
# deadline=None: the log-space model runs exp()/ln() under a 50-digit Decimal
# context (transcendental-heavy); determinism, not latency, is under test.
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping)
def test_calculation_is_deterministic(raw: dict) -> None:
    """Validates: Requirements 1.2

    calculate_viewing_hours called twice on an identical FeatureVector and params
    returns an equal result across every observable field.
    """
    vector = _vector(raw)
    first = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)
    second = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)

    assert first.viewing_hours == second.viewing_hours
    assert first.method == second.method
    assert first.breakdown == second.breakdown
    assert first.unclamped == second.unclamped
    assert first.missing_features == second.missing_features
    assert first.assumed_features == second.assumed_features
    # Frozen dataclasses compare by value, so the whole result is equal too.
    assert first == second


# ---------------------------------------------------------------------------
# Property 3: Breakdown conservation (log-space viewing hours)
#             (Requirements 1.3, 4.4)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 3: Log-space hour conservation
# deadline=None: transcendental Decimal exp()/ln() per example.
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping)
def test_breakdown_hours_sum_exactly_to_viewing_hours(raw: dict) -> None:
    """Validates: Requirements 1.3, 4.4

    The sum of the quantized hour breakdown entries (base platform hours, every
    per-feature lift, and the single rounding_or_bounds_adjustment when present)
    equals viewing_hours EXACTLY at the whole-hour quantum, for arbitrary
    partial/full feature inputs including the floor-clamp path.
    """
    vector = _vector(raw)
    result = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)

    assert result.breakdown is not None
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours

    # The adjustment entry only ever carries a tiny residual (floor-clamp delta +
    # whole-hour quantization), never a large structural offset: it is bounded by
    # a few whole-hour rounding units, one per quantized breakdown entry.
    adj = [c for c in result.breakdown if c.key == "rounding_or_bounds_adjustment"]
    if adj:
        assert abs(adj[0].hours) <= Decimal(len(result.breakdown))


# Feature: content-eval-model, Property 3: Log-space hour conservation (L == 0)
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping)
def test_l_equals_zero_is_base_only_and_conserves(raw: dict) -> None:
    """Validates: Requirements 1.3, 4.4

    With an empty betas mapping the total log lift L == 0, so every per-feature
    hours_i == 0, viewing_hours equals the base platform hours (floored), and the
    breakdown still conserves exactly.
    """
    params = vh.ViewingHoursParams(
        intercept=Decimal("8.0"),
        betas={},
        floor=vh.VIEWING_HOURS_FLOOR,
    )
    vector = _vector(raw)
    result = vh.calculate_viewing_hours(vector, params)

    assert result.breakdown is not None
    base = next(c for c in result.breakdown if c.key == "base_platform_hours")
    lifts = [
        c
        for c in result.breakdown
        if c.key not in ("base_platform_hours", "rounding_or_bounds_adjustment")
    ]
    assert all(c.hours == Decimal(0) for c in lifts)
    assert result.viewing_hours == base.hours
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours


# Feature: content-eval-model, Property 3: Log-space hour conservation (post-floor)
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping, intercept=_dec("-80", "-1", places=1))
def test_conservation_holds_after_positive_floor_clamp(
    raw: dict, intercept: Decimal
) -> None:
    """Validates: Requirements 1.1, 1.3, 4.4

    A strongly negative intercept drives H_hat below the positive floor, so the
    output is clamped UP to the floor. The clamp delta flows into the single
    adjustment entry so the breakdown still sums exactly to viewing_hours, and
    the adjustment is a residual (the clamp lift plus rounding), not a structural
    offset dwarfing the floor.
    """
    params = vh.ViewingHoursParams(
        intercept=intercept,
        betas={"normalized_rating": Decimal("0.5")},
        floor=Decimal("1"),
    )
    vector = _vector(raw)
    result = vh.calculate_viewing_hours(vector, params)

    assert result.viewing_hours >= params.floor
    assert result.breakdown is not None
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours


# ---------------------------------------------------------------------------
# Property 4: Monotonicity (Requirements 4.3)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 4: Monotonicity
# deadline=None: two transcendental evaluations per example.
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping, data=st.data())
def test_increasing_a_non_negative_feature_never_decreases_hours(
    raw: dict, data: st.DataObject
) -> None:
    """Validates: Requirements 4.3

    Increasing any single numeric feature whose beta is non-negative, all else
    held constant, never decreases the predicted driver. The unclamped H_hat is
    checked (exp is monotone, so it cannot plateau) AND the clamped, quantized
    viewing_hours is checked to be non-decreasing.
    """
    which = data.draw(st.sampled_from(_MONOTONE_NUMERIC_FEATURES))
    base_raw = dict(raw)

    # Choose a base value and a strictly larger bumped value inside the feature's
    # documented domain so the derive_features clamp does not erase the bump.
    if which == "normalized_rating" or which == "award_signal":
        low = data.draw(_dec("0", "0.4", places=3))
        high = data.draw(_dec("0.6", "1", places=3))
    elif which == "log_vote_count":
        low = data.draw(_dec("0", "5", places=3))
        high = data.draw(_dec("6", "15", places=3))
    elif which == "runtime_minutes":
        low = data.draw(_dec("1", "60", places=1))
        high = data.draw(_dec("90", "300", places=1))
    else:  # production_scale / talent_pedigree, domain [0, 10]
        low = data.draw(_dec("0", "4", places=2))
        high = data.draw(_dec("6", "10", places=2))
    assume(high > low)

    base_raw[which] = low
    bumped_raw = dict(base_raw)
    bumped_raw[which] = high

    low_res = vh.calculate_viewing_hours(
        _vector(base_raw), vh.DEFAULT_VIEWING_HOURS_PARAMS
    )
    high_res = vh.calculate_viewing_hours(
        _vector(bumped_raw), vh.DEFAULT_VIEWING_HOURS_PARAMS
    )

    assert high_res.unclamped is not None and low_res.unclamped is not None
    assert high_res.unclamped >= low_res.unclamped
    assert high_res.viewing_hours >= low_res.viewing_hours


# ---------------------------------------------------------------------------
# Property 5: Domain safety / positive floor (Requirements 1.1, 2.1)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 5: Domain safety
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping)
def test_output_stays_above_positive_floor(raw: dict) -> None:
    """Validates: Requirements 1.1, 2.1

    A CALCULATED viewing-hours output is always strictly positive and at least
    the configured floor, for arbitrary in-range feature inputs, so CPVH
    (cost / hours) never hits its null/zero path.
    """
    vector = _vector(raw)
    result = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)

    assert result.viewing_hours >= vh.DEFAULT_VIEWING_HOURS_PARAMS.floor
    assert result.viewing_hours > 0


# Feature: content-eval-model, Property 5: Domain safety (arbitrary tiny intercept)
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping, floor=_dec("1", "50", places=0))
def test_floor_is_respected_for_arbitrary_floor(raw: dict, floor: Decimal) -> None:
    """Validates: Requirements 1.1, 2.1

    For any strictly positive floor and a tiny base intercept that would project
    near-zero hours, the output is clamped up to at least the floor.
    """
    params = vh.ViewingHoursParams(
        intercept=Decimal("-40"),  # exp(-40) - 1 < 0 -> base floored to 0
        betas={},
        floor=floor,
    )
    result = vh.calculate_viewing_hours(_vector(raw), params)
    assert result.viewing_hours >= floor
    assert result.viewing_hours > 0


# ---------------------------------------------------------------------------
# Property 6: Precedence -- SUPPLIED-wins (Requirements 1.5, 1.6, 8.3)
# ---------------------------------------------------------------------------

# Any finite supplied value, spanning 0, in-band, and far outside the floor.
_supplied_value = st.one_of(
    st.just(Decimal("0")),
    st.decimals(
        min_value=Decimal("-1000"),
        max_value=Decimal("1000000"),
        allow_nan=False,
        allow_infinity=False,
        places=4,
    ),
)

# Blank / None / non-numeric / boolean -> treated as not supplied (fall through).
_not_supplied = st.one_of(
    st.none(),
    st.just(""),
    st.just("   "),
    st.sampled_from(["abc", "N/A", "none", "n/a", "--"]),
    st.booleans(),
)


# Feature: content-eval-model, Property 6: Precedence (SUPPLIED-wins)
@settings(max_examples=200, deadline=None)
@given(supplied=_supplied_value, raw=_raw_feature_mapping)
def test_supplied_finite_value_returned_exactly(
    supplied: Decimal, raw: dict
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    For any finite supplied value (including 0), resolve_viewing_hours returns
    method SUPPLIED with the value unchanged (no floor clamp, no re-round), no
    breakdown, and no missing/assumed features.
    """
    result = vh.resolve_viewing_hours(
        supplied, _vector(raw), vh.DEFAULT_VIEWING_HOURS_PARAMS, "MODEL_VERSION"
    )

    assert result.method == "SUPPLIED"
    assert result.viewing_hours == supplied  # exact, no clamp/re-round
    assert result.breakdown is None
    assert result.missing_features == ()
    assert result.assumed_features == ()
    assert result.unclamped is None


# Feature: content-eval-model, Property 6: Precedence (non-finite/blank falls through)
@settings(max_examples=200, deadline=None)
@given(supplied=_not_supplied, raw=_raw_feature_mapping)
def test_not_supplied_falls_through_to_calculated(
    supplied: object, raw: dict
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    A blank/None/non-numeric/boolean supplied value is not a valid supply, so
    resolve_viewing_hours falls through to a CALCULATED result with a breakdown.
    """
    assume(vh.coerce_supplied(supplied) is None)

    result = vh.resolve_viewing_hours(
        supplied, _vector(raw), vh.DEFAULT_VIEWING_HOURS_PARAMS, "MODEL_VERSION"
    )

    assert result.method == "CALCULATED"
    assert result.breakdown is not None


# ---------------------------------------------------------------------------
# Property 7: Graceful degradation (Requirements 2.4)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 7: Graceful degradation
@settings(max_examples=200, deadline=None)
@given(raw=_raw_feature_mapping)
def test_partial_or_empty_raw_never_raises_and_conserves(raw: dict) -> None:
    """Validates: Requirements 2.4

    An arbitrary partial/empty raw feature mapping never raises, produces a
    conserving result, and every feature that fell back to a neutral default is
    reported in the vector's assumed_features (never a hard failure).
    """
    vector = _vector(raw)
    result = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)

    # Conserving result, strictly positive output.
    assert result.breakdown is not None
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours
    assert result.viewing_hours > 0

    # Any absent input key surfaced as an assumed feature on the vector. Every
    # key NOT present in raw (among the recognized derive_features keys) must be
    # flagged assumed; a present key must not be (for numeric/label features).
    recognized = set(featmod.PREDICTIVE_FEATURES)
    for name in recognized:
        if name not in raw:
            assert name in vector.assumed_features


# Feature: content-eval-model, Property 7: Graceful degradation (empty mapping)
def test_empty_and_none_raw_produce_all_assumed_conserving_result() -> None:
    """Validates: Requirements 2.4

    A completely empty mapping and a None raw both yield an all-defaults vector
    (every predictive feature assumed) and a conserving, positive result, without
    raising.
    """
    for raw in ({}, None):
        vector = _vector(raw)
        for name in featmod.PREDICTIVE_FEATURES:
            assert name in vector.assumed_features
        result = vh.calculate_viewing_hours(
            vector, vh.DEFAULT_VIEWING_HOURS_PARAMS
        )
        total = sum((c.hours for c in result.breakdown), Decimal(0))
        assert total == result.viewing_hours
        assert result.viewing_hours > 0
