"""Unit tests for the pure engagement Content_Eval models.

# Feature: content-eval-model

Targets :mod:`app.domain.engagement` (task 3): the additive Watch_Time_Elasticity
model and the unit-centred Ad_Load_Receptivity multiplier. These are
example-based sanity tests that pin the documented behavior; the formal
property tests (P1, P2, P4, P6) for this module are added in task 4. They import
only the pure domain modules -- no database, no app framework.

They exercise: additive breakdown conservation (``sum(breakdown) == value``),
SUPPLIED-wins precedence (including a supplied 0), output-domain clamping, the
neutral-centre default of the receptivity multiplier, that the receptivity model
emits a multiplier (never a dollar CPM / Platform_Rate boundary), full fallback
to illustrative defaults on invalid params, and graceful degradation on an
all-defaults feature vector.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.engagement import (
    DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS,
    DEFAULT_WATCH_TIME_ELASTICITY_PARAMS,
    RECEPTIVITY_CENTRE,
    RECEPTIVITY_MAX,
    RECEPTIVITY_MIN,
    WTE_MAX,
    WTE_MIN,
    calculate_ad_load_receptivity,
    calculate_watch_time_elasticity,
    parse_ad_load_receptivity_params,
    parse_watch_time_elasticity_params,
    resolve_ad_load_receptivity,
    resolve_watch_time_elasticity,
)
from app.domain.features import derive_features


def _sum_breakdown(result) -> Decimal:
    return sum((c.points for c in result.breakdown), Decimal("0"))


# ---------------------------------------------------------------------------
# Watch_Time_Elasticity
# ---------------------------------------------------------------------------


def test_wte_breakdown_conserves_to_value() -> None:
    features = derive_features(
        {
            "genre": "crime",
            "content_format": "scripted-series",
            "runtime_minutes": 55,
            "normalized_rating": "0.82",
            "franchise_flag": True,
        }
    )
    result = calculate_watch_time_elasticity(
        features, DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert result.method == "CALCULATED"
    assert _sum_breakdown(result) == result.watch_time_elasticity


def test_wte_output_within_domain() -> None:
    # Max-ish signals must stay inside [WTE_MIN, WTE_MAX].
    features = derive_features(
        {
            "genre": "crime",
            "content_format": "scripted-series",
            "runtime_minutes": 600,
            "normalized_rating": "1",
            "franchise_flag": True,
        }
    )
    result = calculate_watch_time_elasticity(
        features, DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert WTE_MIN <= result.watch_time_elasticity <= WTE_MAX


def test_wte_supplied_wins_including_zero() -> None:
    features = derive_features({"genre": "drama"})
    for supplied in ("1.37", Decimal("0"), 0, "0.0"):
        result = resolve_watch_time_elasticity(
            supplied, features, DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, "DEFAULTS"
        )
        assert result.method == "SUPPLIED"
        assert result.breakdown is None
        assert result.watch_time_elasticity == Decimal(str(supplied))


def test_wte_invalid_supplied_falls_back_to_calculation() -> None:
    features = derive_features({"genre": "drama"})
    result = resolve_watch_time_elasticity(
        "not-a-number", features, DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, "DEFAULTS"
    )
    assert result.method == "CALCULATED"
    assert result.breakdown is not None


def test_wte_graceful_degradation_all_defaults() -> None:
    features = derive_features(None)
    result = calculate_watch_time_elasticity(
        features, DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    # Does not raise; conserves; reports assumed/missing features.
    assert _sum_breakdown(result) == result.watch_time_elasticity
    assert "genre" in result.assumed_features


# ---------------------------------------------------------------------------
# Ad_Load_Receptivity
# ---------------------------------------------------------------------------


def test_receptivity_defaults_to_neutral_centre_when_no_signal() -> None:
    # An all-defaults vector with a neutral (unknown) genre stays at the centre.
    features = derive_features({"runtime_minutes": 60})  # reference runtime -> 0 lift
    result = calculate_ad_load_receptivity(
        features, DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert result.ad_load_receptivity == RECEPTIVITY_CENTRE


def test_receptivity_breakdown_conserves_to_value() -> None:
    features = derive_features(
        {
            "genre": "live-sports",
            "runtime_minutes": 120,
            "normalized_rating": "0.9",
            "franchise_flag": True,
        }
    )
    result = calculate_ad_load_receptivity(
        features, DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert _sum_breakdown(result) == result.ad_load_receptivity


def test_receptivity_is_a_bounded_multiplier_not_a_cpm() -> None:
    # Even with every positive signal maxed, the output is a bounded multiplier
    # near 1.0 -- never a dollar CPM.
    features = derive_features(
        {
            "genre": "live-sports",
            "runtime_minutes": 600,
            "normalized_rating": "1",
            "franchise_flag": True,
        }
    )
    result = calculate_ad_load_receptivity(
        features, DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert RECEPTIVITY_MIN <= result.ad_load_receptivity <= RECEPTIVITY_MAX


def test_receptivity_ad_sensitive_genre_dips_below_centre() -> None:
    features = derive_features({"genre": "drama", "runtime_minutes": 60})
    result = calculate_ad_load_receptivity(
        features, DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert result.ad_load_receptivity < RECEPTIVITY_CENTRE


def test_receptivity_supplied_wins_including_zero() -> None:
    features = derive_features({"genre": "comedy"})
    for supplied in ("1.2", Decimal("0"), 0):
        result = resolve_ad_load_receptivity(
            supplied, features, DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, "DEFAULTS"
        )
        assert result.method == "SUPPLIED"
        assert result.ad_load_receptivity == Decimal(str(supplied))


# ---------------------------------------------------------------------------
# Param parsing / full fallback
# ---------------------------------------------------------------------------


def test_params_fallback_on_invalid() -> None:
    wte, src = parse_watch_time_elasticity_params({"intercept": "oops"})
    assert src == "DEFAULTS"
    assert wte is DEFAULT_WATCH_TIME_ELASTICITY_PARAMS

    recv, src2 = parse_ad_load_receptivity_params(None)
    assert src2 == "DEFAULTS"
    assert recv is DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS


def test_params_valid_parse_reports_model_version() -> None:
    wte, src = parse_watch_time_elasticity_params(
        {
            "intercept": "0.9",
            "runtime_weight": "0.1",
            "serialization_lift": "0.1",
            "rating_weight": "0.2",
            "franchise_lift": "0.1",
            "min_value": "0",
            "max_value": "3",
        }
    )
    assert src == "MODEL_VERSION"
    assert wte.intercept == Decimal("0.9")

    recv, src2 = parse_ad_load_receptivity_params(
        {
            "centre": "1",
            "rating_weight": "0.1",
            "runtime_weight": "0.05",
            "franchise_lift": "0.03",
            "min_value": "0.5",
            "max_value": "1.5",
            "genre_offsets": {"drama": "-0.06"},
        }
    )
    assert src2 == "MODEL_VERSION"
    assert recv.genre_offsets["drama"] == Decimal("-0.06")
