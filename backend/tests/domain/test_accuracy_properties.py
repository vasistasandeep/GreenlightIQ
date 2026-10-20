"""Property-based tests for the dashboard verdict-match accuracy helper.

Feature: dashboard-accuracy-and-payback-audit. Covers Properties 1-5 over
``app.domain.accuracy``.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.accuracy import (
    ACCURACY_DECIMAL_PLACES,
    REQUIRED_METRICS,
    actual_verdict,
    verdict_match_rate,
)
from app.domain.recommendation import GREENLIGHT, NEGOTIATE_HARD, PASS

_VERDICTS = (GREENLIGHT, NEGOTIATE_HARD, PASS)
_PREMIUM_ASSETS = ("ORIGINAL_SERIES", "ORIGINAL_FILM", "CO_PRODUCTION")

# Verdict or None (an unclassifiable / absent actual, or an absent prediction).
_verdict_or_none = st.sampled_from([*_VERDICTS, None])
_pair = st.tuples(_verdict_or_none, _verdict_or_none)


# Feature: dashboard-accuracy-and-payback-audit, Property 1: Model_Accuracy_Rate is null or a float in [0, 1], and null iff the eligible subset is empty
# Validates: Requirements 2.4, 2.5, 2.6
@settings(max_examples=200)
@given(pairs=st.lists(_pair, max_size=40))
def test_property_1_fraction_or_null(pairs):
    rate = verdict_match_rate(pairs)
    eligible = [(p, a) for p, a in pairs if p is not None and a is not None]
    if not eligible:
        assert rate is None
    else:
        assert rate is not None
        assert 0.0 <= rate <= 1.0


# Feature: dashboard-accuracy-and-payback-audit, Property 2: a title with no/partial ground truth (an unclassifiable or absent verdict) is counted neither as a match nor a miss
# Validates: Requirements 2.1, 2.2, 2.3
@settings(max_examples=200)
@given(pairs=st.lists(_pair, max_size=40), pred=_verdict_or_none)
def test_property_2_eligibility_excludes_insufficient(pairs, pred):
    # Adding a pair whose actual verdict is None (unclassifiable / absent ground
    # truth) must not change the rate: it is neither a match nor a miss.
    base = verdict_match_rate(pairs)
    with_partial = verdict_match_rate([*pairs, (pred, None)])
    assert base == with_partial


# Feature: dashboard-accuracy-and-payback-audit, Property 3: for a non-empty eligible subset, the rate equals round(matches / eligible_count, 4)
# Validates: Requirements 1.1, 1.3, 2.5, 3.3
@settings(max_examples=200)
@given(pairs=st.lists(_pair, min_size=1, max_size=40))
def test_property_3_rate_equals_matches_over_eligible(pairs):
    rate = verdict_match_rate(pairs)
    eligible = [(p, a) for p, a in pairs if p is not None and a is not None]
    if eligible:
        matches = sum(1 for p, a in eligible if p == a)
        assert rate == round(matches / len(eligible), ACCURACY_DECIMAL_PLACES)
    else:
        assert rate is None


# Feature: dashboard-accuracy-and-payback-audit, Property 4: computing the rate twice over the same inputs yields the identical value (determinism)
# Validates: Requirements 3.1, 3.2
@settings(max_examples=200)
@given(pairs=st.lists(_pair, max_size=40))
def test_property_4_determinism(pairs):
    assert verdict_match_rate(list(pairs)) == verdict_match_rate(list(pairs))


_metric_value = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("50"),
    allow_nan=False, allow_infinity=False, places=2,
)


# Feature: dashboard-accuracy-and-payback-audit, Property 5: actual_verdict reuses the live rule (churn non-correctable; all-pass -> GREENLIGHT; a churn-only breach -> PASS)
# Validates: Requirements 1.2, 5.3
@settings(max_examples=200)
@given(asset=st.sampled_from(_PREMIUM_ASSETS))
def test_property_5_reuses_live_rule(asset):
    # All four pass a premium ceiling (0.18) -> GREENLIGHT.
    all_pass = {
        "cpvh": Decimal("0.10"),
        "ltv_to_cost": Decimal("4.00"),
        "churn_reduction": Decimal("2.00"),
        "payback_horizon": Decimal("8"),
    }
    assert actual_verdict(asset, all_pass) == GREENLIGHT

    # Only churn breaches -> non-correctable -> PASS.
    churn_only = {**all_pass, "churn_reduction": Decimal("0.50")}
    assert actual_verdict(asset, churn_only) == PASS

    # Only CPVH breaches -> correctable -> NEGOTIATE_HARD.
    cpvh_only = {**all_pass, "cpvh": Decimal("0.50")}
    assert actual_verdict(asset, cpvh_only) == NEGOTIATE_HARD

    # Missing any required metric -> not classifiable -> None.
    for metric in REQUIRED_METRICS:
        partial = {k: v for k, v in all_pass.items() if k != metric}
        assert actual_verdict(asset, partial) is None


def test_no_cpvh_ceiling_asset_is_unclassifiable():
    # An unknown asset type yields no CPVH ceiling -> not classifiable -> None.
    all_pass = {
        "cpvh": Decimal("0.10"),
        "ltv_to_cost": Decimal("4.00"),
        "churn_reduction": Decimal("2.00"),
        "payback_horizon": Decimal("8"),
    }
    assert actual_verdict("NOT_A_REAL_TYPE", all_pass) is None