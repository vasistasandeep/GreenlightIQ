"""Pure MAPE (Mean Absolute Percentage Error) computation.

Deterministic, dependency-free domain function used by the Backtesting_Module.
No database access and no I/O — a property-based-testing target.

MAPE is defined (Requirement 11.5) as::

    (1 / n) * sum(|(actual - predicted) / actual|) * 100

computed over the eligible metric pairs, expressed as a percentage rounded to
2 decimal places.

Eligibility (Requirement 11.7): a pair whose actual value is zero is excluded
from the computation (its term is undefined). When every pair is excluded,
there are no eligible metrics and MAPE is undefined; this function returns
``None`` (Requirement 11.8). Callers (see the Backtesting_Module, task 12.1)
surface this as the ``NO_ELIGIBLE_METRICS`` indicator in the audit scorecard.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = ["NO_ELIGIBLE_METRICS", "compute_mape"]

# Indicator reported by callers when all pairs are excluded and MAPE is undefined
# (Requirement 11.8). Pairing with a ``None`` return keeps this module pure while
# giving the Backtesting_Module a stable reason code for the scorecard.
NO_ELIGIBLE_METRICS = "no_eligible_metrics"

# Two decimal places (Requirement 11.5).
_PRECISION = Decimal("0.01")


def compute_mape(pairs: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    """Compute MAPE over ``(actual, predicted)`` pairs.

    Args:
        pairs: A list of ``(actual, predicted)`` metric pairs.

    Returns:
        The MAPE as a percentage rounded to 2 decimal places, or ``None`` when
        no pairs are eligible (every pair has a zero actual value, or the input
        is empty), indicating no eligible metrics (Requirement 11.8).
    """
    # Exclude pairs with a zero actual value (Requirement 11.7); the percentage
    # error term is undefined when the denominator is zero.
    eligible = [(actual, predicted) for actual, predicted in pairs if actual != 0]

    n = len(eligible)
    if n == 0:
        return None

    total = Decimal(0)
    for actual, predicted in eligible:
        total += abs((actual - predicted) / actual)

    mape = (total / Decimal(n)) * Decimal(100)
    return mape.quantize(_PRECISION, rounding=ROUND_HALF_UP)
