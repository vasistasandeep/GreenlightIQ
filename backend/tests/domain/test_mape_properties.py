"""Property-based tests for the pure MAPE domain function.

Targets ``app.domain.mape.compute_mape`` and ``NO_ELIGIBLE_METRICS``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.mape import NO_ELIGIBLE_METRICS, compute_mape

_PRECISION = Decimal("0.01")

# Decimal strategy for actual/predicted values. Bounded, finite, with a couple
# of decimal places so pairs stay in the realistic metric input space while
# still exercising rounding behaviour.
_decimals = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# A mix of zero and non-zero actuals: ~1 in 4 pairs has a zero actual so the
# exclusion path (R11.7) is routinely exercised alongside eligible pairs.
_actuals = st.one_of(
    st.just(Decimal("0")),
    _decimals.filter(lambda d: d != 0),
    _decimals.filter(lambda d: d != 0),
    _decimals.filter(lambda d: d != 0),
)

_pair = st.tuples(_actuals, _decimals)
_pairs = st.lists(_pair, max_size=20)


def _expected_mape(pairs: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    """Independently recompute MAPE per the R11.5 formula over eligible pairs."""
    eligible = [(a, p) for (a, p) in pairs if a != 0]
    n = len(eligible)
    if n == 0:
        return None
    total = Decimal(0)
    for actual, predicted in eligible:
        total += abs((actual - predicted) / actual)
    mape = (total / Decimal(n)) * Decimal(100)
    return mape.quantize(_PRECISION, rounding=ROUND_HALF_UP)


# Feature: cineroi-ai, Property 16: MAPE computation with zero-actual exclusion
@given(pairs=_pairs)
@settings(max_examples=200)
def test_mape_zero_actual_exclusion(pairs: list[tuple[Decimal, Decimal]]) -> None:
    """Validates: Requirements 11.5, 11.7, 11.8

    * Pairs with ``actual == 0`` are excluded (R11.7).
    * When all pairs are excluded (or input empty), result is ``None`` (R11.8).
    * For eligible pairs, result matches the R11.5 formula recomputed
      independently with Decimal.
    """
    result = compute_mape(pairs)

    eligible = [(a, p) for (a, p) in pairs if a != 0]

    # R11.7 / R11.8: with no eligible pairs, MAPE is undefined -> None.
    if not eligible:
        assert result is None
        return

    # R11.5: result equals the independently recomputed formula over eligibles.
    assert result == _expected_mape(pairs)
    # Equivalently, zero-actual pairs do not affect the outcome: computing over
    # only the eligible pairs yields the same value (R11.7 exclusion).
    assert result == compute_mape(eligible)


# Feature: cineroi-ai, Property 16: MAPE computation with zero-actual exclusion
@given(
    zeros=st.lists(
        st.tuples(st.just(Decimal("0")), _decimals),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=200)
def test_mape_all_zero_actuals_returns_none(
    zeros: list[tuple[Decimal, Decimal]],
) -> None:
    """Validates: Requirements 11.7, 11.8

    When every pair has ``actual == 0``, every pair is excluded and MAPE is
    undefined, so ``compute_mape`` returns ``None`` (R11.8).
    """
    assert compute_mape(zeros) is None


# Feature: cineroi-ai, Property 16: MAPE computation with zero-actual exclusion
def test_mape_empty_input_returns_none() -> None:
    """Validates: Requirements 11.8 — empty input has no eligible metrics."""
    assert compute_mape([]) is None


def test_no_eligible_metrics_indicator_is_stable() -> None:
    """The reason code paired with a ``None`` MAPE (R11.8) is a stable string."""
    assert NO_ELIGIBLE_METRICS == "no_eligible_metrics"
