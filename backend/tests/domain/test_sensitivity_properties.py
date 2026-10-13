"""Property-based tests for the pure scenario-scaling helper.

Feature: what-if-sensitivity. Covers Property 2 (field scaling) and Property 3
(base immutability) over ``app.domain.sensitivity.scale_inputs``.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.sensitivity import scale_inputs
from app.engines.guardrails import ValuationInputs

_vals = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"),
                    allow_nan=False, allow_infinity=False, places=4)
_mult = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("2.0"),
                    allow_nan=False, allow_infinity=False, places=2)
_hours = st.one_of(st.none(), st.decimals(min_value=Decimal("1"), max_value=Decimal("1000000"),
                                          allow_nan=False, allow_infinity=False, places=0))


def _inputs(churn_value, ltv, elasticity, cpm, impressions, churn_pct) -> ValuationInputs:
    return ValuationInputs(
        churn_reduction_value=churn_value,
        ltv=ltv,
        watch_time_elasticity=elasticity,
        cpm=cpm,
        ad_impressions=impressions,
        churn_reduction_pct=churn_pct,
        monthly_margin=Decimal("10"),
        milestone_schedule=None,
    )


# Feature: what-if-sensitivity, Property 2: Scaling applies each multiplier to its target field exactly
# Validates: Requirements 5.2, 5.3, 5.4
@settings(max_examples=200)
@given(
    churn_value=_vals, ltv=_vals, elasticity=_vals, cpm=_vals, impressions=_vals,
    churn_pct=_vals, hours=_hours,
    cost_m=_mult, view_m=_mult, churn_m=_mult,
)
def test_property_2_field_scaling(churn_value, ltv, elasticity, cpm, impressions, churn_pct, hours, cost_m, view_m, churn_m):
    base = _inputs(churn_value, ltv, elasticity, cpm, impressions, churn_pct)
    scaled = scale_inputs(base, hours, cost_multiplier=cost_m, viewership_multiplier=view_m, churn_multiplier=churn_m)
    assert scaled.inputs.ad_impressions == impressions * view_m
    assert scaled.inputs.churn_reduction_pct == churn_pct * churn_m
    if hours is None:
        assert scaled.viewing_hours is None
    else:
        assert scaled.viewing_hours == hours * view_m


# Feature: what-if-sensitivity, Property 3: Scaling never mutates the base inputs
# Validates: Requirements 5.5
@settings(max_examples=200)
@given(
    churn_value=_vals, ltv=_vals, elasticity=_vals, cpm=_vals, impressions=_vals,
    churn_pct=_vals, hours=_hours,
    cost_m=_mult, view_m=_mult, churn_m=_mult,
)
def test_property_3_base_immutable(churn_value, ltv, elasticity, cpm, impressions, churn_pct, hours, cost_m, view_m, churn_m):
    base = _inputs(churn_value, ltv, elasticity, cpm, impressions, churn_pct)
    snapshot = dataclasses.asdict(base)
    scale_inputs(base, hours, cost_multiplier=cost_m, viewership_multiplier=view_m, churn_multiplier=churn_m)
    assert dataclasses.asdict(base) == snapshot