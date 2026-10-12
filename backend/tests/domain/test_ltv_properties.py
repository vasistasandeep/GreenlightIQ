"""Property-based tests for the LTV-to-Cost guardrail domain functions.

Covers Property 11 (LTV-to-Cost formula, R5.1) and Property 12 (LTV-to-Cost
breach boundary, R5.3) from the cineroi-ai design document, exercising
``app.domain.ltv.compute_ltv_to_cost`` and ``app.domain.ltv.is_ltv_breach``.

``compute_ltv_to_cost`` rejects float inputs to avoid binary-float error, so all
generators here produce :class:`decimal.Decimal` values (or ints) only.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.ltv import (
    LTV_TO_COST_THRESHOLD,
    compute_ltv_to_cost,
    is_ltv_breach,
)

# Bounded, finite Decimal money/scalar values. No NaN/Infinity so arithmetic and
# comparisons stay well-defined. Values are kept in a sane magnitude range to
# avoid pathological precision blow-ups while still covering zero and negatives.
_decimals = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)

# Cost must be strictly positive to avoid ZeroDivisionError (Property 11 is
# scoped to "positive normalized cost").
_positive_cost = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)

# Multiples spanning both sides of the 3.2 threshold, including the exact
# boundary, so the iff relationship in Property 12 is fully exercised.
_multiples = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


# Feature: cineroi-ai, Property 11: LTV-to-Cost formula
# Validates: Requirements 5.1
@settings(max_examples=200)
@given(
    churn_reduction_value=_decimals,
    ltv=_decimals,
    watch_time_elasticity=_decimals,
    cpm=_decimals,
    ad_impressions=_decimals,
    cost_usd=_positive_cost,
)
def test_compute_ltv_to_cost_matches_formula(
    churn_reduction_value: Decimal,
    ltv: Decimal,
    watch_time_elasticity: Decimal,
    cpm: Decimal,
    ad_impressions: Decimal,
    cost_usd: Decimal,
) -> None:
    """compute_ltv_to_cost equals the exact design formula over Decimal inputs."""
    expected = (
        (churn_reduction_value * ltv)
        + (watch_time_elasticity * cpm * ad_impressions)
    ) / cost_usd

    result = compute_ltv_to_cost(
        churn_reduction_value,
        ltv,
        watch_time_elasticity,
        cpm,
        ad_impressions,
        cost_usd,
    )

    assert result == expected


# Feature: cineroi-ai, Property 12: LTV-to-Cost breach boundary
# Validates: Requirements 5.3
@settings(max_examples=200)
@given(multiple=_multiples)
def test_is_ltv_breach_iff_below_threshold(multiple: Decimal) -> None:
    """A breach is reported if and only if the multiple is strictly below 3.2.

    A multiple exactly equal to the threshold must pass (no breach).
    """
    assert is_ltv_breach(multiple) == (multiple < LTV_TO_COST_THRESHOLD)


# Feature: cineroi-ai, Property 12: LTV-to-Cost breach boundary
# Validates: Requirements 5.3
def test_is_ltv_breach_threshold_boundary_passes() -> None:
    """The exact threshold value (3.2) is a pass, not a breach."""
    assert is_ltv_breach(LTV_TO_COST_THRESHOLD) is False
    assert is_ltv_breach(Decimal("3.2")) is False
    # Just below the threshold is a breach; just above passes.
    assert is_ltv_breach(Decimal("3.1999")) is True
    assert is_ltv_breach(Decimal("3.2001")) is False
