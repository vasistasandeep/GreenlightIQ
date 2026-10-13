"""Property-based tests for the churn-cohort domain helpers.

Feature: deal-decision-support. Covers Properties 9 and 10 over
``app.domain.cohort``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.cohort import derive_modeled_cohort_size, retained_subscribers

_size = st.decimals(min_value=Decimal("-100"), max_value=Decimal("1000000"),
                    allow_nan=False, allow_infinity=False, places=2)
_pct = st.decimals(min_value=Decimal("-5"), max_value=Decimal("100"),
                   allow_nan=False, allow_infinity=False, places=2)


# Feature: deal-decision-support, Property 9: Retained subscribers non-negative whole number, boundary cases
# Validates: Requirements 7.1, 7.2, 7.3, 7.4
@settings(max_examples=200)
@given(size=_size, pct=_pct)
def test_property_9_retained(size, pct):
    result = retained_subscribers(size, pct)
    if size <= 0:
        assert result is None
    elif pct <= 0:
        assert result == Decimal("0")
    else:
        expected = (size * (pct / Decimal("100"))).quantize(Decimal("1"))
        assert result == expected
        assert result >= 0
        assert result == result.to_integral_value()


# Feature: deal-decision-support, Property 10: Cohort rejects floats and computes exactly
# Validates: Requirements 7.5
def test_property_10_cohort_rejects_floats():
    with pytest.raises(TypeError):
        retained_subscribers(1000.0, Decimal("2.1"))
    with pytest.raises(TypeError):
        retained_subscribers(Decimal("1000"), 2.1)


@settings(max_examples=100)
@given(cost=st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"),
                        allow_nan=False, allow_infinity=False, places=2))
def test_derive_modeled_cohort_size(cost):
    result = derive_modeled_cohort_size(cost)
    if cost <= 0:
        assert result is None
    else:
        assert result == cost.to_integral_value(rounding="ROUND_FLOOR")