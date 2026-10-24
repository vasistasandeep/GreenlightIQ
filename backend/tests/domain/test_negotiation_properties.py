"""Property-based tests for the Negotiation Playbook domain helpers.

Feature: deal-decision-support. Covers Properties 1-6 and 10 over
``app.domain.negotiation``. Decimal-only generators (floats are rejected).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.negotiation import (
    counter_proposal_levers,
    cpvh_implied_ceiling,
    implied_discount_pct,
    ltv_implied_ceiling,
    target_purchase_ceiling,
)
from app.domain.recommendation import GuardrailCheck

_pos = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("1000000"),
                   allow_nan=False, allow_infinity=False, places=4)
_pos_small = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("100"),
                         allow_nan=False, allow_infinity=False, places=4)
_names = st.sampled_from(["CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON"])
_correctable = st.sampled_from([True, False, None])


def _check(name, breached, correctable, computed=Decimal("1"), threshold=Decimal("1")) -> GuardrailCheck:
    return GuardrailCheck(
        name=name, computed_value=computed, threshold=threshold,
        passed=not breached, breached=breached,
        shortfall_magnitude=None, correctable=correctable,
    )


# Feature: deal-decision-support, Property 1: CPVH-implied ceiling is the cost that lands CPVH on its ceiling
# Validates: Requirements 1.1
@settings(max_examples=200)
@given(cost=_pos, cpvh=_pos_small, ceiling=_pos_small)
def test_property_1_cpvh_implied_ceiling(cost, cpvh, ceiling):
    result = cpvh_implied_ceiling(cost, cpvh, ceiling)
    assert result == cost * (ceiling / cpvh)
    # Returned cost <= original iff CPVH is at or above its ceiling (breach dir).
    assert (result <= cost) == (cpvh >= ceiling)


# Feature: deal-decision-support, Property 2: LTV-implied ceiling lands the multiple on its threshold
# Validates: Requirements 1.2
@settings(max_examples=200)
@given(cost=_pos, multiple=_pos_small, threshold=_pos_small)
def test_property_2_ltv_implied_ceiling(cost, multiple, threshold):
    result = ltv_implied_ceiling(cost, multiple, threshold)
    assert result == cost * (multiple / threshold)
    # At the implied ceiling, the recomputed multiple equals the threshold.
    if result != 0:
        recomputed = multiple * cost / result
        assert abs(recomputed - threshold) <= Decimal("0.0001")


# Feature: deal-decision-support, Property 3: Target purchase ceiling is the binding minimum
# Validates: Requirements 1.3, 1.4, 1.5, 1.6
@settings(max_examples=200)
@given(
    cost=st.decimals(min_value=Decimal("-10"), max_value=Decimal("1000000"),
                     allow_nan=False, allow_infinity=False, places=2),
    cpvh_breached=st.booleans(), cpvh_correctable=_correctable,
    ltv_breached=st.booleans(), ltv_correctable=_correctable,
)
def test_property_3_target_ceiling(cost, cpvh_breached, cpvh_correctable, ltv_breached, ltv_correctable):
    checks = [
        _check("CPVH", cpvh_breached, cpvh_correctable, Decimal("0.25"), Decimal("0.18")),
        _check("LTV_TO_COST", ltv_breached, ltv_correctable, Decimal("2.5"), Decimal("3.2")),
    ]
    result = target_purchase_ceiling(cost, checks)
    candidates = []
    if cost is not None and cost > 0:
        if cpvh_breached and cpvh_correctable is True:
            candidates.append(cpvh_implied_ceiling(cost, Decimal("0.25"), Decimal("0.18")))
        if ltv_breached and ltv_correctable is True:
            candidates.append(ltv_implied_ceiling(cost, Decimal("2.5"), Decimal("3.2")))
    if cost <= 0 or not candidates:
        assert result is None
    else:
        # Production rounds the binding ceiling HALF_UP to whole USD
        # (negotiation._round_usd); mirror that here so the .5 boundary agrees.
        expected = min(candidates).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result == expected
        assert result <= min(candidates) + Decimal("1")


# Feature: deal-decision-support, Property 4: Implied discount non-negative, clamped, rounded, null case
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
@settings(max_examples=200)
@given(
    ask=st.decimals(min_value=Decimal("-10"), max_value=Decimal("1000000"),
                    allow_nan=False, allow_infinity=False, places=2),
    ceiling=st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"),
                        allow_nan=False, allow_infinity=False, places=2),
)
def test_property_4_implied_discount(ask, ceiling):
    result = implied_discount_pct(ask, ceiling)
    if ask <= 0:
        assert result is None
    elif ceiling >= ask:
        assert result == Decimal("0.0")
    else:
        expected = ((ask - ceiling) / ask * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        assert result == expected
        assert result >= 0


# Feature: deal-decision-support, Property 5: One lever per breached check, correctly keyed and classified
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
@settings(max_examples=200)
@given(specs=st.lists(st.tuples(_names, st.booleans(), _correctable), max_size=6))
def test_property_5_levers(specs):
    checks = [_check(n, b, c) for (n, b, c) in specs]
    levers = counter_proposal_levers(checks)
    breached = [(n, c) for (n, b, c) in specs if b]
    assert len(levers) == len(breached)
    for lever, (n, c) in zip(levers, breached):
        assert lever["name"] == n
        assert lever["name"] in {"CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON"}
        assert lever["correctable"] == c
        assert len(lever["message"]) > 0


# Feature: deal-decision-support, Property 6: Lever messages are ASCII only
# Validates: Requirements 3.2, 3.3
@settings(max_examples=200)
@given(specs=st.lists(st.tuples(_names, st.booleans(), _correctable), max_size=6))
def test_property_6_levers_ascii(specs):
    checks = [_check(n, b, c) for (n, b, c) in specs]
    for lever in counter_proposal_levers(checks):
        assert all(ord(ch) < 128 for ch in lever["message"])


# Feature: deal-decision-support, Property 10: Monetary helpers reject floats and compute exactly
# Validates: Requirements 1.7
def test_property_10_negotiation_rejects_floats():
    with pytest.raises(TypeError):
        cpvh_implied_ceiling(1.0, Decimal("0.25"), Decimal("0.18"))
    with pytest.raises(TypeError):
        ltv_implied_ceiling(Decimal("1000"), 2.5, Decimal("3.2"))


@settings(max_examples=100)
@given(cost=_pos, cpvh=_pos_small, ceiling=_pos_small)
def test_property_10_negotiation_exact(cost, cpvh, ceiling):
    result = cpvh_implied_ceiling(cost, cpvh, ceiling)
    assert isinstance(result, Decimal)