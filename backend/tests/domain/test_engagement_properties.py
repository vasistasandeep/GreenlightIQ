"""Property-based tests for the engagement Content_Eval_Models.

# Feature: content-eval-model

Targets the pure :mod:`app.domain.engagement` module (task 3): the additive
Watch_Time_Elasticity model and the unit-centred Ad_Load_Receptivity multiplier.
Feature inputs are built through the shared
:func:`app.domain.features.derive_features` contract (task 1), so the tests
exercise exactly the vector the engine path, dataset generator, and harness
share.

The properties below map to the design's "Correctness Properties" section and
mirror the depth of the churn model's suite
(``test_churn_properties.py``). Each test carries a leading
``# Feature: content-eval-model, Property N: ...`` comment matching the house
convention and a docstring citing the acceptance criteria it exercises.

Properties covered here (for BOTH engagement drivers):
- P1 Determinism (Requirements 1.2)
- P2 Additive breakdown conservation, sum(breakdown.points) == value exactly
  (Requirements 1.3)
- P4 Monotonicity in a non-negative-coefficient feature (Requirements 4.3)
- P5 Domain safety / output clamped to the documented domain (Requirements 1.1,
  2.1)
- P6 Precedence, SUPPLIED-wins (Requirements 1.5, 1.6, 8.3)
- P7 Graceful degradation on partial/empty raw features (Requirements 2.4)
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain import engagement as eng
from app.domain import features as featmod

# ---------------------------------------------------------------------------
# Shared strategies -- raw feature mappings fed through derive_features.
# ---------------------------------------------------------------------------

_GENRES = (
    "drama",
    "crime",
    "comedy",
    "documentary",
    "sci-fi",
    "thriller",
    "reality",
    "sports",
    "live-sports",
)
_ASSET_TYPES = ("ORIGINAL_SERIES", "CO_PRODUCTION", "ORIGINAL_FILM", "LICENSED_LIBRARY")
_FORMATS = (
    "scripted-series",
    "limited-series",
    "reality-competition",
    "live-sports",
    "original-film",
    "library",
)


def _dec(min_value: str, max_value: str, places: int = 2) -> st.SearchStrategy:
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        allow_nan=False,
        allow_infinity=False,
        places=places,
    )


_rating = _dec("0", "1", places=3)
_runtime = _dec("0", "400", places=1)

# A raw mapping where every key may be present or absent (covers partial/empty).
_raw_feature_mapping = st.fixed_dictionaries(
    {},
    optional={
        "asset_type": st.sampled_from(_ASSET_TYPES),
        "genre": st.sampled_from(_GENRES),
        "content_format": st.sampled_from(_FORMATS),
        "runtime_minutes": _runtime,
        "is_exclusive": st.booleans(),
        "production_scale": _dec("0", "10"),
        "talent_pedigree": _dec("0", "10"),
        "normalized_rating": _rating,
        "log_vote_count": _dec("0", "15", places=3),
        "franchise_flag": st.booleans(),
        "award_signal": _dec("0", "1", places=3),
        "release_year": st.integers(min_value=1950, max_value=2030),
    },
)


def _vector(raw: dict | None) -> featmod.FeatureVector:
    return featmod.derive_features(raw)


# ===========================================================================
# Watch_Time_Elasticity (additive model)
# ===========================================================================


# Feature: content-eval-model, Property 1: Determinism (watch_time_elasticity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_wte_calculation_is_deterministic(raw: dict) -> None:
    """Validates: Requirements 1.2

    calculate_watch_time_elasticity called twice on an identical FeatureVector
    and params returns an equal result across every observable field.
    """
    vector = _vector(raw)
    first = eng.calculate_watch_time_elasticity(
        vector, eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    second = eng.calculate_watch_time_elasticity(
        vector, eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert first == second


# Feature: content-eval-model, Property 2: Additive conservation (watch_time_elasticity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_wte_breakdown_sums_exactly_to_value(raw: dict) -> None:
    """Validates: Requirements 1.3

    The sum of the quantized breakdown entries (including bounds_adjustment when
    present) equals watch_time_elasticity EXACTLY at 2 dp, for arbitrary
    partial/full feature inputs, with the residual never more than one cent.
    """
    vector = _vector(raw)
    result = eng.calculate_watch_time_elasticity(
        vector, eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert result.breakdown is not None
    total = sum((c.points for c in result.breakdown), Decimal("0"))
    assert total == result.watch_time_elasticity
    assert abs(total - result.watch_time_elasticity) <= Decimal("0.01")


# Feature: content-eval-model, Property 4: Monotonicity (watch_time_elasticity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping, data=st.data())
def test_wte_increasing_a_non_negative_feature_never_decreases_value(
    raw: dict, data: st.DataObject
) -> None:
    """Validates: Requirements 4.3

    Increasing runtime OR the normalized rating (both non-negative-weighted),
    all else held constant, never decreases watch_time_elasticity. The unclamped
    value is checked (to avoid a clamp plateau masking the relation) AND the
    clamped value is checked to be non-decreasing.
    """
    which = data.draw(st.sampled_from(("runtime_minutes", "normalized_rating")))
    base_raw = dict(raw)
    if which == "normalized_rating":
        low = data.draw(_dec("0", "0.4", places=3))
        high = data.draw(_dec("0.6", "1", places=3))
    else:
        low = data.draw(_dec("1", "60", places=1))
        high = data.draw(_dec("90", "300", places=1))
    assume(high > low)

    base_raw[which] = low
    bumped_raw = dict(base_raw)
    bumped_raw[which] = high

    low_res = eng.calculate_watch_time_elasticity(
        _vector(base_raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    high_res = eng.calculate_watch_time_elasticity(
        _vector(bumped_raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert high_res.unclamped is not None and low_res.unclamped is not None
    assert high_res.unclamped >= low_res.unclamped
    assert high_res.watch_time_elasticity >= low_res.watch_time_elasticity


# Feature: content-eval-model, Property 4: Monotonicity (franchise lift, WTE)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_wte_franchise_flag_never_decreases_value(raw: dict) -> None:
    """Validates: Requirements 4.3

    Turning the franchise flag on (0 -> 1) with a non-negative franchise lift,
    all else constant, never decreases watch_time_elasticity.
    """
    off_raw = {**raw, "franchise_flag": False}
    on_raw = {**raw, "franchise_flag": True}
    off = eng.calculate_watch_time_elasticity(
        _vector(off_raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    on = eng.calculate_watch_time_elasticity(
        _vector(on_raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert on.unclamped >= off.unclamped
    assert on.watch_time_elasticity >= off.watch_time_elasticity


# Feature: content-eval-model, Property 5: Domain safety (watch_time_elasticity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_wte_output_within_documented_domain(raw: dict) -> None:
    """Validates: Requirements 1.1, 2.1

    A CALCULATED watch_time_elasticity always lies in the inclusive documented
    output domain [WTE_MIN, WTE_MAX] for arbitrary in-range feature inputs.
    """
    vector = _vector(raw)
    result = eng.calculate_watch_time_elasticity(
        vector, eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert eng.WTE_MIN <= result.watch_time_elasticity <= eng.WTE_MAX


# Feature: content-eval-model, Property 6: Precedence (watch_time_elasticity)
_supplied_value = st.one_of(
    st.just(Decimal("0")),
    st.decimals(
        min_value=Decimal("-100"),
        max_value=Decimal("1000"),
        allow_nan=False,
        allow_infinity=False,
        places=4,
    ),
)

_not_supplied = st.one_of(
    st.none(),
    st.just(""),
    st.just("   "),
    st.sampled_from(["abc", "N/A", "none", "n/a", "--"]),
    st.booleans(),
)


@settings(max_examples=200)
@given(supplied=_supplied_value, raw=_raw_feature_mapping)
def test_wte_supplied_value_returned_exactly(supplied: Decimal, raw: dict) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    Any finite supplied value (including 0) returns exactly with method SUPPLIED,
    no breakdown, and no missing/assumed features.
    """
    result = eng.resolve_watch_time_elasticity(
        supplied, _vector(raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, "MODEL_VERSION"
    )
    assert result.method == "SUPPLIED"
    assert result.watch_time_elasticity == supplied
    assert result.breakdown is None
    assert result.missing_features == ()
    assert result.assumed_features == ()


@settings(max_examples=200)
@given(supplied=_not_supplied, raw=_raw_feature_mapping)
def test_wte_not_supplied_falls_through_to_calculated(
    supplied: object, raw: dict
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    A blank/None/non-numeric/boolean supplied value falls through to CALCULATED.
    """
    assume(eng.coerce_supplied(supplied) is None)
    result = eng.resolve_watch_time_elasticity(
        supplied, _vector(raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, "MODEL_VERSION"
    )
    assert result.method == "CALCULATED"
    assert result.breakdown is not None


# Feature: content-eval-model, Property 7: Graceful degradation (watch_time_elasticity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_wte_partial_raw_never_raises_and_conserves(raw: dict) -> None:
    """Validates: Requirements 2.4

    An arbitrary partial/empty raw mapping never raises, produces a conserving
    in-domain result, and reports the model's assumed features for the inputs
    that fell back to neutral defaults.
    """
    vector = _vector(raw)
    result = eng.calculate_watch_time_elasticity(
        vector, eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert result.breakdown is not None
    total = sum((c.points for c in result.breakdown), Decimal("0"))
    assert total == result.watch_time_elasticity
    assert eng.WTE_MIN <= result.watch_time_elasticity <= eng.WTE_MAX
    # An absent runtime/rating/franchise input is surfaced as assumed on the
    # vector and consulted by the model (neutral default, not a hard failure).
    for name in ("runtime_minutes", "normalized_rating", "franchise_flag"):
        if name not in raw:
            assert name in vector.assumed_features


def test_wte_empty_and_none_raw_conserve_without_raising() -> None:
    """Validates: Requirements 2.4

    A fully empty mapping and a None raw both produce a conserving in-domain
    result without raising.
    """
    for raw in ({}, None):
        result = eng.calculate_watch_time_elasticity(
            _vector(raw), eng.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
        )
        total = sum((c.points for c in result.breakdown), Decimal("0"))
        assert total == result.watch_time_elasticity
        assert eng.WTE_MIN <= result.watch_time_elasticity <= eng.WTE_MAX


# ===========================================================================
# Ad_Load_Receptivity (unit-centred multiplier)
# ===========================================================================


# Feature: content-eval-model, Property 1: Determinism (ad_load_receptivity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_receptivity_calculation_is_deterministic(raw: dict) -> None:
    """Validates: Requirements 1.2

    calculate_ad_load_receptivity called twice on identical inputs returns an
    equal result across every observable field.
    """
    vector = _vector(raw)
    first = eng.calculate_ad_load_receptivity(
        vector, eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    second = eng.calculate_ad_load_receptivity(
        vector, eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert first == second


# Feature: content-eval-model, Property 2: Additive conservation (ad_load_receptivity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_receptivity_breakdown_sums_exactly_to_value(raw: dict) -> None:
    """Validates: Requirements 1.3

    The sum of the quantized breakdown entries (including bounds_adjustment when
    present) equals ad_load_receptivity EXACTLY at 2 dp, for arbitrary feature
    inputs, with the residual never more than one cent.
    """
    vector = _vector(raw)
    result = eng.calculate_ad_load_receptivity(
        vector, eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert result.breakdown is not None
    total = sum((c.points for c in result.breakdown), Decimal("0"))
    assert total == result.ad_load_receptivity
    assert abs(total - result.ad_load_receptivity) <= Decimal("0.01")


# Feature: content-eval-model, Property 4: Monotonicity (ad_load_receptivity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping, data=st.data())
def test_receptivity_increasing_a_non_negative_feature_never_decreases_value(
    raw: dict, data: st.DataObject
) -> None:
    """Validates: Requirements 4.3

    The rating and runtime receptivity weights are non-negative magnitudes
    applied to centred deltas, so above their neutral centres increasing the
    feature never decreases receptivity. The bump is applied on the high side of
    the centre (rating >= 0.5, runtime >= reference) so the signed delta stays
    non-negative and the relation is monotone. Checks unclamped and clamped.
    """
    which = data.draw(st.sampled_from(("runtime_minutes", "normalized_rating")))
    base_raw = dict(raw)
    if which == "normalized_rating":
        # Stay at/above the 0.5 centre so the signed (rating - centre) delta is >= 0.
        low = data.draw(_dec("0.5", "0.7", places=3))
        high = data.draw(_dec("0.8", "1", places=3))
    else:
        # Stay at/above the reference runtime (60 min) so (score - 1) delta is >= 0.
        low = data.draw(_dec("60", "90", places=1))
        high = data.draw(_dec("120", "300", places=1))
    assume(high > low)

    base_raw[which] = low
    bumped_raw = dict(base_raw)
    bumped_raw[which] = high

    low_res = eng.calculate_ad_load_receptivity(
        _vector(base_raw), eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    high_res = eng.calculate_ad_load_receptivity(
        _vector(bumped_raw), eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert high_res.unclamped is not None and low_res.unclamped is not None
    assert high_res.unclamped >= low_res.unclamped
    assert high_res.ad_load_receptivity >= low_res.ad_load_receptivity


# Feature: content-eval-model, Property 5: Domain safety (ad_load_receptivity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_receptivity_output_within_documented_domain(raw: dict) -> None:
    """Validates: Requirements 1.1, 2.1

    A CALCULATED ad_load_receptivity multiplier always lies in the inclusive
    documented domain [RECEPTIVITY_MIN, RECEPTIVITY_MAX] for arbitrary in-range
    feature inputs -- it never emits a value outside the sensible band.
    """
    vector = _vector(raw)
    result = eng.calculate_ad_load_receptivity(
        vector, eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert (
        eng.RECEPTIVITY_MIN
        <= result.ad_load_receptivity
        <= eng.RECEPTIVITY_MAX
    )


# Feature: content-eval-model, Property 6: Precedence (ad_load_receptivity)
@settings(max_examples=200)
@given(supplied=_supplied_value, raw=_raw_feature_mapping)
def test_receptivity_supplied_value_returned_exactly(
    supplied: Decimal, raw: dict
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    Any finite supplied value (including 0) returns exactly with method SUPPLIED,
    no breakdown, and no missing/assumed features.
    """
    result = eng.resolve_ad_load_receptivity(
        supplied, _vector(raw), eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, "MODEL_VERSION"
    )
    assert result.method == "SUPPLIED"
    assert result.ad_load_receptivity == supplied
    assert result.breakdown is None
    assert result.missing_features == ()
    assert result.assumed_features == ()


@settings(max_examples=200)
@given(supplied=_not_supplied, raw=_raw_feature_mapping)
def test_receptivity_not_supplied_falls_through_to_calculated(
    supplied: object, raw: dict
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3

    A blank/None/non-numeric/boolean supplied value falls through to CALCULATED.
    """
    assume(eng.coerce_supplied(supplied) is None)
    result = eng.resolve_ad_load_receptivity(
        supplied, _vector(raw), eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, "MODEL_VERSION"
    )
    assert result.method == "CALCULATED"
    assert result.breakdown is not None


# Feature: content-eval-model, Property 7: Graceful degradation (ad_load_receptivity)
@settings(max_examples=200)
@given(raw=_raw_feature_mapping)
def test_receptivity_partial_raw_never_raises_and_conserves(raw: dict) -> None:
    """Validates: Requirements 2.4

    An arbitrary partial/empty raw mapping never raises and produces a conserving
    in-domain multiplier.
    """
    vector = _vector(raw)
    result = eng.calculate_ad_load_receptivity(
        vector, eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert result.breakdown is not None
    total = sum((c.points for c in result.breakdown), Decimal("0"))
    assert total == result.ad_load_receptivity
    assert (
        eng.RECEPTIVITY_MIN
        <= result.ad_load_receptivity
        <= eng.RECEPTIVITY_MAX
    )


def test_receptivity_empty_and_none_raw_conserve_without_raising() -> None:
    """Validates: Requirements 2.4

    A fully empty mapping and a None raw both produce a conserving in-domain
    multiplier without raising.
    """
    for raw in ({}, None):
        result = eng.calculate_ad_load_receptivity(
            _vector(raw), eng.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
        )
        total = sum((c.points for c in result.breakdown), Decimal("0"))
        assert total == result.ad_load_receptivity
        assert (
            eng.RECEPTIVITY_MIN
            <= result.ad_load_receptivity
            <= eng.RECEPTIVITY_MAX
        )
