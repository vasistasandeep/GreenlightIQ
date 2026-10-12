"""Property-based tests for the CPVH computation and divide-by-zero guard.

# Feature: cineroi-ai, Property 8: CPVH computation and divide-by-zero guard

Property 8 (design.md) -- Validates: Requirements 4.1, 4.5.

* R4.1: for projected_viewing_hours > 0 and a positive normalized cost,
  ``compute_cpvh`` returns ``cost_usd / viewing_hours`` rounded to 4 decimal
  places.
* R4.5: for projected_viewing_hours <= 0 (notably == 0), ``compute_cpvh`` raises
  :class:`CPVHComputationError` -- the divide-by-zero guard -- and yields no value.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.cpvh import CPVH_QUANTUM, CPVHComputationError, compute_cpvh

# Finite, bounded Decimal strategies keep division well-defined and prevent the
# overflow/precision explosions that unbounded or non-finite values would cause.
# Costs span zero and large budgets; the standard default Decimal context (28
# significant digits) comfortably holds a 12-digit numerator / 6-digit divisor.
_cost = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000000000"),  # 1e12
    allow_nan=False,
    allow_infinity=False,
    places=4,
)
# viewing_hours must be strictly positive for the computation branch.
_positive_hours = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000000000"),  # 1e9
    allow_nan=False,
    allow_infinity=False,
    places=4,
)
# Non-positive hours exercise the divide-by-zero guard: zero plus negatives.
_non_positive_hours = st.one_of(
    st.just(Decimal("0")),
    st.decimals(
        min_value=Decimal("-1000000000"),
        max_value=Decimal("0"),
        allow_nan=False,
        allow_infinity=False,
        places=4,
    ),
)


# Feature: cineroi-ai, Property 8: CPVH computation and divide-by-zero guard
@settings(max_examples=200)
@given(cost_usd=_cost, viewing_hours=_positive_hours)
def test_compute_cpvh_is_rounded_quotient_for_positive_hours(
    cost_usd: Decimal, viewing_hours: Decimal
) -> None:
    """R4.1: CPVH == cost / viewing_hours, quantized to 4 decimal places."""
    result = compute_cpvh(cost_usd, viewing_hours)

    expected = (cost_usd / viewing_hours).quantize(
        CPVH_QUANTUM, rounding=ROUND_HALF_UP
    )

    # The relationship: result is exactly the HALF_UP-rounded quotient.
    assert result == expected

    # The rounding: result carries no finer precision than 4 decimal places.
    assert -result.as_tuple().exponent <= 4
    assert result == result.quantize(CPVH_QUANTUM, rounding=ROUND_HALF_UP)

    # The result approximates the true quotient within half a ULP of 1e-4.
    assert abs(result - (cost_usd / viewing_hours)) <= CPVH_QUANTUM / 2


# Feature: cineroi-ai, Property 8: CPVH computation and divide-by-zero guard
@settings(max_examples=200)
@given(cost_usd=_cost, viewing_hours=_non_positive_hours)
def test_compute_cpvh_rejects_non_positive_hours(
    cost_usd: Decimal, viewing_hours: Decimal
) -> None:
    """R4.5: non-positive viewing hours raise the divide-by-zero guard."""
    with pytest.raises(CPVHComputationError):
        compute_cpvh(cost_usd, viewing_hours)


# Feature: cineroi-ai, Property 8: CPVH computation and divide-by-zero guard
def test_compute_cpvh_zero_hours_raises_descriptive_error() -> None:
    """R4.5 (anchor example): viewing_hours == 0 raises CPVHComputationError."""
    with pytest.raises(CPVHComputationError):
        compute_cpvh(Decimal("1000.00"), Decimal("0"))


# Feature: cineroi-ai, Property 8: CPVH computation and divide-by-zero guard
def test_compute_cpvh_known_rounding_example() -> None:
    """R4.1 (anchor example): 1 / 3 rounds half-up to 0.3333 at 4 dp."""
    assert compute_cpvh(Decimal("1"), Decimal("3")) == Decimal("0.3333")
    # 0.00005 -> rounds HALF_UP to 0.0001 (10 / 200000 = 0.00005).
    assert compute_cpvh(Decimal("10"), Decimal("200000")) == Decimal("0.0001")
