"""Property-based tests for the LTV-to-Cost attribution helper.

Feature: deal-decision-support. Covers Properties 7, 8, 10 over
``app.domain.attribution.ltv_attribution``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.attribution import ltv_attribution
from app.domain.ltv import compute_ltv_to_cost

_vals = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"),
                    allow_nan=False, allow_infinity=False, places=4)
_pos_cost = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("1000000"),
                        allow_nan=False, allow_infinity=False, places=4)


# Feature: deal-decision-support, Property 7: Attribution decomposes the numerator exactly
# Validates: Requirements 5.1, 5.2, 5.3, 5.4
@settings(max_examples=200)
@given(churn=_vals, ltv=_vals, elasticity=_vals, cpm=_vals, impressions=_vals, cost=_pos_cost)
def test_property_7_decomposition(churn, ltv, elasticity, cpm, impressions, cost):
    attr = ltv_attribution(churn, ltv, elasticity, cpm, impressions, cost)
    assert attr["subscription_value"] == churn * ltv
    assert attr["advertising_value"] == elasticity * cpm * impressions
    assert attr["total_modeled_value"] == attr["subscription_value"] + attr["advertising_value"]
    assert attr["multiple"] == attr["total_modeled_value"] / cost


# Feature: deal-decision-support, Property 8: Attribution multiple agrees with compute_ltv_to_cost
# Validates: Requirements 5.5
@settings(max_examples=200)
@given(churn=_vals, ltv=_vals, elasticity=_vals, cpm=_vals, impressions=_vals, cost=_pos_cost)
def test_property_8_consistency(churn, ltv, elasticity, cpm, impressions, cost):
    attr = ltv_attribution(churn, ltv, elasticity, cpm, impressions, cost)
    assert attr["multiple"] == compute_ltv_to_cost(churn, ltv, elasticity, cpm, impressions, cost)


# Feature: deal-decision-support, Property 10: Attribution rejects floats and computes exactly
# Validates: Requirements 5.6
def test_property_10_attribution_rejects_floats():
    with pytest.raises(TypeError):
        ltv_attribution(1.0, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))


@settings(max_examples=100)
@given(churn=_vals, ltv=_vals, elasticity=_vals, cpm=_vals, impressions=_vals, cost=_pos_cost)
def test_property_10_attribution_exact(churn, ltv, elasticity, cpm, impressions, cost):
    attr = ltv_attribution(churn, ltv, elasticity, cpm, impressions, cost)
    assert all(isinstance(attr[k], Decimal) for k in attr)