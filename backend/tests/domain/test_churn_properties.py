"""Property-based tests for the Churn_Mitigation_Model domain module.

# Feature: calculable-churn-model

Targets the pure :mod:`app.domain.churn` module (task 1). The eight properties
below map to the design's "Correctness Properties" section (Properties 1-8) and
pin down the churn math independently of the engine, before any orchestration is
wired. All tests are self-contained Hypothesis targets that import only the pure
domain module -- no database, no app framework.

Each test carries a leading ``# Feature: calculable-churn-model, Property N: ...``
comment matching the house convention and a docstring citing the acceptance
criteria it exercises (Validates: Requirements 13.1 plus the specific Rx.y).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.churn import (
    CHURN_MITIGATION_THRESHOLD,
    DEFAULT_CHURN_MODEL_PARAMS,
    MAX_CHURN,
    MIN_CHURN,
    ChurnFeatures,
    ChurnModelParams,
    calculate_churn_mitigation,
    coerce_supplied,
    is_borderline,
    parse_params,
    resolve_churn,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# The four known asset types plus unknown/None cases that exercise the zero
# offset + "asset_type" missing path.
_ASSET_TYPES = (
    "ORIGINAL_SERIES",
    "CO_PRODUCTION",
    "ORIGINAL_FILM",
    "LICENSED_LIBRARY",
)
_asset_type = st.one_of(
    st.sampled_from(_ASSET_TYPES),
    st.none(),
    st.just("UNKNOWN_TYPE"),
)

# In-domain feature values (pedigree/scale in [0, 10], heat in [0, 100]). A
# ``None`` represents a missing feature.
_pedigree = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("10"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
_scale = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("10"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
_heat = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)

# Out-of-domain feature values that must still be clamped and bounded: well
# above the valid ceiling and negative. None included to mix missing features.
_wild_pedigree = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("-50"),
        max_value=Decimal("500"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
_wild_scale = _wild_pedigree
_wild_heat = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("-500"),
        max_value=Decimal("5000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)

# A non-negative delta applied in isolation to a single feature for monotonicity.
_delta = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("200"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


def _in_domain_features(draw: st.DrawFn) -> ChurnFeatures:
    """A ChurnFeatures with every numeric feature present and in-domain."""
    return ChurnFeatures(
        asset_type=draw(st.sampled_from(_ASSET_TYPES)),
        pedigree=draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("10"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            )
        ),
        production_scale=draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("10"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            )
        ),
        is_exclusive=draw(st.booleans()),
        telemetry_heat=draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("100"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            )
        ),
    )


# ---------------------------------------------------------------------------
# Property 1: Monotonicity (R1.5)
# ---------------------------------------------------------------------------


# Feature: calculable-churn-model, Property 1: Monotonicity
@settings(max_examples=200)
@given(data=st.data())
def test_increasing_any_single_feature_never_decreases_churn(data: st.DataObject) -> None:
    """Validates: Requirements 13.1, 1.5

    For fixed params and other features, increasing pedigree, OR production
    scale, OR telemetry heat (each in isolation) by a non-negative delta never
    decreases the calculated churn_reduction_pct.
    """
    base = _in_domain_features(data.draw)
    delta = data.draw(_delta)
    which = data.draw(st.sampled_from(("pedigree", "production_scale", "telemetry_heat")))

    if which == "pedigree":
        bumped = ChurnFeatures(
            asset_type=base.asset_type,
            pedigree=base.pedigree + delta,
            production_scale=base.production_scale,
            is_exclusive=base.is_exclusive,
            telemetry_heat=base.telemetry_heat,
        )
    elif which == "production_scale":
        bumped = ChurnFeatures(
            asset_type=base.asset_type,
            pedigree=base.pedigree,
            production_scale=base.production_scale + delta,
            is_exclusive=base.is_exclusive,
            telemetry_heat=base.telemetry_heat,
        )
    else:  # telemetry_heat
        bumped = ChurnFeatures(
            asset_type=base.asset_type,
            pedigree=base.pedigree,
            production_scale=base.production_scale,
            is_exclusive=base.is_exclusive,
            telemetry_heat=base.telemetry_heat + delta,
        )

    low = calculate_churn_mitigation(base, DEFAULT_CHURN_MODEL_PARAMS)
    high = calculate_churn_mitigation(bumped, DEFAULT_CHURN_MODEL_PARAMS)

    assert high.churn_reduction_pct >= low.churn_reduction_pct


# ---------------------------------------------------------------------------
# Property 2: Boundedness (R1.7)
# ---------------------------------------------------------------------------


# Feature: calculable-churn-model, Property 2: Boundedness
@settings(max_examples=200)
@given(
    asset_type=_asset_type,
    pedigree=_wild_pedigree,
    production_scale=_wild_scale,
    is_exclusive=st.booleans(),
    telemetry_heat=_wild_heat,
)
def test_calculated_churn_is_within_output_bounds(
    asset_type: str | None,
    pedigree: Decimal | None,
    production_scale: Decimal | None,
    is_exclusive: bool,
    telemetry_heat: Decimal | None,
) -> None:
    """Validates: Requirements 13.1, 1.7

    A CALCULATED result's churn_reduction_pct always lies in the inclusive
    output bounds [MIN_CHURN, MAX_CHURN] = [0.10, 5.00], even for out-of-domain
    features (far above the ceiling, negative, or missing).
    """
    features = ChurnFeatures(
        asset_type=asset_type,
        pedigree=pedigree,
        production_scale=production_scale,
        is_exclusive=is_exclusive,
        telemetry_heat=telemetry_heat,
    )
    result = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)

    assert MIN_CHURN == Decimal("0.10")
    assert MAX_CHURN == Decimal("5.00")
    assert MIN_CHURN <= result.churn_reduction_pct <= MAX_CHURN


# ---------------------------------------------------------------------------
# Property 3: Breakdown conservation (R1.8)
# ---------------------------------------------------------------------------


# Feature: calculable-churn-model, Property 3: Breakdown conservation
@settings(max_examples=200)
@given(
    asset_type=_asset_type,
    pedigree=_wild_pedigree,
    production_scale=_wild_scale,
    is_exclusive=st.booleans(),
    telemetry_heat=_wild_heat,
)
def test_breakdown_sums_exactly_to_final_value(
    asset_type: str | None,
    pedigree: Decimal | None,
    production_scale: Decimal | None,
    is_exclusive: bool,
    telemetry_heat: Decimal | None,
) -> None:
    """Validates: Requirements 13.1, 1.8

    The sum of the quantized breakdown entries (including bounds_adjustment when
    present) equals churn_reduction_pct EXACTLY at 2 dp, for arbitrary features
    including clamped extremes and missing features.
    """
    features = ChurnFeatures(
        asset_type=asset_type,
        pedigree=pedigree,
        production_scale=production_scale,
        is_exclusive=is_exclusive,
        telemetry_heat=telemetry_heat,
    )
    result = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)

    assert result.breakdown is not None
    total = sum((c.points for c in result.breakdown), Decimal("0"))

    # Primary assertion: exact Decimal equality at 2 dp.
    assert total == result.churn_reduction_pct

    # Documented safety net: the residual is never more than one cent.
    assert abs(total - result.churn_reduction_pct) <= Decimal("0.01")


# ---------------------------------------------------------------------------
# Property 4: Determinism (R1.4)
# ---------------------------------------------------------------------------


# Feature: calculable-churn-model, Property 4: Determinism
@settings(max_examples=200)
@given(
    asset_type=_asset_type,
    pedigree=_wild_pedigree,
    production_scale=_wild_scale,
    is_exclusive=st.booleans(),
    telemetry_heat=_wild_heat,
)
def test_calculation_is_deterministic(
    asset_type: str | None,
    pedigree: Decimal | None,
    production_scale: Decimal | None,
    is_exclusive: bool,
    telemetry_heat: Decimal | None,
) -> None:
    """Validates: Requirements 13.1, 1.4

    calculate_churn_mitigation called twice with identical inputs returns an
    equal result across every observable field.
    """
    features = ChurnFeatures(
        asset_type=asset_type,
        pedigree=pedigree,
        production_scale=production_scale,
        is_exclusive=is_exclusive,
        telemetry_heat=telemetry_heat,
    )
    first = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)
    second = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)

    assert first.churn_reduction_pct == second.churn_reduction_pct
    assert first.method == second.method
    assert first.is_borderline == second.is_borderline
    assert first.breakdown == second.breakdown
    assert first.missing_features == second.missing_features
    # Frozen dataclasses compare by value, so the whole result is equal too.
    assert first == second


# ---------------------------------------------------------------------------
# Property 5: Non-negative coefficients (R1.3, R3.2)
# ---------------------------------------------------------------------------

# A valid, non-negative param mapping (plain JSON-ish values the parser coerces).
_valid_param_mapping = st.fixed_dictionaries(
    {
        "intercept": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("2"), allow_nan=False,
            allow_infinity=False, places=2,
        ),
        "pedigree_weight": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1"), allow_nan=False,
            allow_infinity=False, places=3,
        ),
        "scale_weight": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1"), allow_nan=False,
            allow_infinity=False, places=3,
        ),
        "exclusivity_lift": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1"), allow_nan=False,
            allow_infinity=False, places=2,
        ),
        "telemetry_weight": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1"), allow_nan=False,
            allow_infinity=False, places=3,
        ),
        "min_churn": st.just(Decimal("0.10")),
        "max_churn": st.just(Decimal("5.00")),
        "asset_offsets": st.fixed_dictionaries(
            {
                name: st.decimals(
                    min_value=Decimal("0"), max_value=Decimal("1"),
                    allow_nan=False, allow_infinity=False, places=2,
                )
                for name in _ASSET_TYPES
            }
        ),
    }
)

# The scalar weight/offset keys that can be made negative one at a time.
_NEGATABLE_SCALAR_KEYS = (
    "intercept",
    "pedigree_weight",
    "scale_weight",
    "exclusivity_lift",
    "telemetry_weight",
)


# Feature: calculable-churn-model, Property 5: Non-negative coefficients
@settings(max_examples=200)
@given(data=st.data())
def test_negative_coefficient_falls_back_to_defaults(data: st.DataObject) -> None:
    """Validates: Requirements 13.1, 1.3, 3.2

    When exactly one weight/offset in an otherwise-valid mapping is negative,
    parse_params rejects the mapping and returns (DEFAULT_CHURN_MODEL_PARAMS,
    "DEFAULTS").
    """
    mapping: dict[str, object] = dict(data.draw(_valid_param_mapping))
    # Deep-copy the asset offsets so we can mutate independently.
    mapping["asset_offsets"] = dict(mapping["asset_offsets"])  # type: ignore[arg-type]

    negative = data.draw(
        st.decimals(
            min_value=Decimal("-5"),
            max_value=Decimal("-0.01"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        )
    )
    target = data.draw(
        st.sampled_from(_NEGATABLE_SCALAR_KEYS + ("asset_offset",))
    )
    if target == "asset_offset":
        which = data.draw(st.sampled_from(_ASSET_TYPES))
        mapping["asset_offsets"][which] = negative  # type: ignore[index]
    else:
        mapping[target] = negative

    params, source = parse_params(mapping)

    assert source == "DEFAULTS"
    assert params == DEFAULT_CHURN_MODEL_PARAMS


# Feature: calculable-churn-model, Property 5: Non-negative coefficients
@settings(max_examples=200)
@given(mapping=_valid_param_mapping)
def test_valid_non_negative_mapping_round_trips(mapping: dict[str, object]) -> None:
    """Validates: Requirements 13.1, 1.3, 3.2

    A fully-valid non-negative mapping parses to ("MODEL_VERSION") and round-trips
    the supplied values into the resulting ChurnModelParams.
    """
    params, source = parse_params(mapping)

    assert source == "MODEL_VERSION"
    assert params.intercept == mapping["intercept"]
    assert params.pedigree_weight == mapping["pedigree_weight"]
    assert params.scale_weight == mapping["scale_weight"]
    assert params.exclusivity_lift == mapping["exclusivity_lift"]
    assert params.telemetry_weight == mapping["telemetry_weight"]
    assert params.min_churn == mapping["min_churn"]
    assert params.max_churn == mapping["max_churn"]
    assert dict(params.asset_offsets) == mapping["asset_offsets"]


# ---------------------------------------------------------------------------
# Property 6: Supplied precedence (R4.1, R4.4)
# ---------------------------------------------------------------------------

# Any finite Decimal supplied value, spanning 0, in-band, and out-of-[0.10,5.00].
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


# Feature: calculable-churn-model, Property 6: Supplied precedence
@settings(max_examples=200)
@given(supplied=_supplied_value, data=st.data())
def test_supplied_finite_value_returned_exactly(
    supplied: Decimal, data: st.DataObject
) -> None:
    """Validates: Requirements 13.1, 4.1, 4.4

    For any finite Decimal supplied value (including 0 and values outside the
    [0.10, 5.00] bounds), resolve_churn returns method SUPPLIED with the value
    unchanged (no clamp, no re-round), breakdown None, and no missing features.
    """
    features = _in_domain_features(data.draw)
    result = resolve_churn(
        supplied, features, DEFAULT_CHURN_MODEL_PARAMS, "MODEL_VERSION"
    )

    assert result.method == "SUPPLIED"
    assert result.churn_reduction_pct == supplied  # exact, no clamp/re-round
    assert result.breakdown is None
    assert result.missing_features == ()
    assert result.is_borderline == is_borderline(supplied)


# ---------------------------------------------------------------------------
# Property 7: Not-supplied fallthrough (R4.3)
# ---------------------------------------------------------------------------

# Blank / None / non-numeric strings / bools -> treated as not supplied.
_not_supplied = st.one_of(
    st.none(),
    st.just(""),
    st.just("   "),
    st.text(alphabet=st.characters(blacklist_categories=("Nd",)), min_size=1, max_size=8),
    st.sampled_from(["abc", "N/A", "none", "n/a", "--"]),
    st.booleans(),
)


# Feature: calculable-churn-model, Property 7: Not-supplied fallthrough
@settings(max_examples=200)
@given(supplied=_not_supplied, data=st.data())
def test_not_supplied_falls_through_to_calculated(
    supplied: object, data: st.DataObject
) -> None:
    """Validates: Requirements 13.1, 4.3

    For a blank, None, non-numeric string, or boolean supplied value,
    resolve_churn falls through to a CALCULATED result.
    """
    # Guard: a random text string could in principle parse as a number; skip
    # those so the strategy only exercises genuinely non-numeric inputs.
    assume(coerce_supplied(supplied) is None)

    features = _in_domain_features(data.draw)
    result = resolve_churn(
        supplied, features, DEFAULT_CHURN_MODEL_PARAMS, "MODEL_VERSION"
    )

    assert result.method == "CALCULATED"
    assert result.breakdown is not None


# ---------------------------------------------------------------------------
# Property 8: Borderline iff in band (R5.1, R5.2)
# ---------------------------------------------------------------------------

# Values spanning the borderline band [1.45, 1.55] and its surroundings.
_near_hurdle = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("3.00"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


# Feature: calculable-churn-model, Property 8: Borderline iff in band
@settings(max_examples=200)
@given(value=_near_hurdle)
def test_is_borderline_true_exactly_within_band(value: Decimal) -> None:
    """Validates: Requirements 13.1, 5.1, 5.2

    is_borderline(v) is True exactly when 1.45 <= v <= 1.55.
    """
    expected = Decimal("1.45") <= value <= Decimal("1.55")
    assert is_borderline(value) is expected
    # Cross-check against the published band definition.
    assert is_borderline(value) == (
        abs(value - CHURN_MITIGATION_THRESHOLD) <= Decimal("0.05")
    )


# Feature: calculable-churn-model, Property 8: Borderline iff in band
@settings(max_examples=200)
@given(supplied=_supplied_value, data=st.data())
def test_result_borderline_flag_matches_its_value(
    supplied: Decimal, data: st.DataObject
) -> None:
    """Validates: Requirements 13.1, 5.1, 5.2

    A resolved result (SUPPLIED or CALCULATED) carries an is_borderline flag
    consistent with its own churn_reduction_pct.
    """
    features = _in_domain_features(data.draw)

    supplied_result = resolve_churn(
        supplied, features, DEFAULT_CHURN_MODEL_PARAMS, "MODEL_VERSION"
    )
    assert supplied_result.is_borderline == is_borderline(
        supplied_result.churn_reduction_pct
    )

    calc_result = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)
    assert calc_result.is_borderline == is_borderline(
        calc_result.churn_reduction_pct
    )


# Two distinct out-of-domain feature values that both clamp to the SAME in-domain
# boundary, giving two results that differ in their raw features yet land on an
# identical final churn_reduction_pct. This constructs the collision directly
# instead of relying on `assume`, which would filter out almost every example.
_above_ceiling_pair = st.lists(
    st.decimals(
        min_value=Decimal("10.01"),
        max_value=Decimal("500"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    min_size=2,
    max_size=2,
    unique=True,
)


# Feature: calculable-churn-model, Property 8: Borderline iff in band
@settings(max_examples=200)
@given(pair=_above_ceiling_pair, data=st.data())
def test_results_landing_on_same_value_share_borderline_flag(
    pair: list[Decimal], data: st.DataObject
) -> None:
    """Validates: Requirements 13.1, 5.1, 5.2

    Two CALCULATED results that differ only in their features but land on the
    same final churn_reduction_pct share the same borderline flag (the flag is a
    pure function of the final value). The collision is forced via clamping: two
    distinct above-ceiling pedigree values both clamp to 10, so the two results
    have differing raw inputs yet an identical final value.
    """
    base = _in_domain_features(data.draw)
    high_a, high_b = pair[0], pair[1]

    a = calculate_churn_mitigation(
        ChurnFeatures(
            asset_type=base.asset_type,
            pedigree=high_a,
            production_scale=base.production_scale,
            is_exclusive=base.is_exclusive,
            telemetry_heat=base.telemetry_heat,
        ),
        DEFAULT_CHURN_MODEL_PARAMS,
    )
    b = calculate_churn_mitigation(
        ChurnFeatures(
            asset_type=base.asset_type,
            pedigree=high_b,
            production_scale=base.production_scale,
            is_exclusive=base.is_exclusive,
            telemetry_heat=base.telemetry_heat,
        ),
        DEFAULT_CHURN_MODEL_PARAMS,
    )

    # The two raw pedigree inputs differ but both clamp to the [0, 10] ceiling,
    # so the final values coincide and the flags must therefore agree.
    assert high_a != high_b
    assert a.churn_reduction_pct == b.churn_reduction_pct
    assert a.is_borderline == b.is_borderline
