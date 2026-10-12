"""Pure domain functions for the LTV-to-Cost guardrail (Requirement 5).

The LTV-to-Cost multiple blends subscription-driven value (churn reduction x LTV)
with advertising-driven value (watch-time elasticity x CPM x ad impressions),
divided by the normalized acquisition cost in USD. The guardrail breaches when the
multiple falls strictly below the threshold of 3.2 (R5.3).

All arithmetic uses :class:`decimal.Decimal` to preserve exact monetary precision.
This module is pure: no I/O, no database access, no global state.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "LTV_TO_COST_THRESHOLD",
    "compute_ltv_to_cost",
    "is_ltv_breach",
]

# Minimum acceptable LTV-to-Cost multiple over a 12-to-24-month window (R5.2).
# A title breaches the guardrail when its multiple is strictly below this value.
LTV_TO_COST_THRESHOLD: Decimal = Decimal("3.2")


def _as_decimal(value: Decimal | int | str) -> Decimal:
    """Coerce a numeric input to Decimal without introducing binary-float error.

    Accepts Decimal/int/str directly. Floats are rejected because they would
    silently inject representation error into monetary computations.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is a subclass of int; disallow it explicitly
        raise TypeError("boolean is not a valid numeric input")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(
        f"expected Decimal, int, or str to preserve precision, got {type(value).__name__}"
    )


def compute_ltv_to_cost(
    churn_reduction_value: Decimal | int | str,
    ltv: Decimal | int | str,
    watch_time_elasticity: Decimal | int | str,
    cpm: Decimal | int | str,
    ad_impressions: Decimal | int | str,
    cost_usd: Decimal | int | str,
) -> Decimal:
    """Compute the LTV-to-Cost multiple for a title (R5.1).

    Formula::

        ((churn_reduction_value * ltv) + (watch_time_elasticity * cpm * ad_impressions))
        / cost_usd

    All inputs are expected to be already normalized to USD by the caller
    (the Guardrails_Engine normalizes cost to USD first, per R21.2). CPM and LTV
    are territory-weighted upstream (R21.3); this function treats them as scalars.

    Args:
        churn_reduction_value: Subscription churn reduction value contribution.
        ltv: Subscriber lifetime value.
        watch_time_elasticity: Watch-time elasticity coefficient.
        cpm: Cost per mille (advertising) in USD.
        ad_impressions: Projected advertising impressions.
        cost_usd: Normalized acquisition cost or budget in USD. Must be non-zero.

    Returns:
        The LTV-to-Cost multiple as a Decimal.

    Raises:
        ZeroDivisionError: If ``cost_usd`` is zero.
        TypeError: If any input is a float or other precision-lossy type.
    """
    churn = _as_decimal(churn_reduction_value)
    ltv_d = _as_decimal(ltv)
    elasticity = _as_decimal(watch_time_elasticity)
    cpm_d = _as_decimal(cpm)
    impressions = _as_decimal(ad_impressions)
    cost = _as_decimal(cost_usd)

    if cost == 0:
        raise ZeroDivisionError("cost_usd must be non-zero to compute LTV-to-Cost")

    subscription_value = churn * ltv_d
    advertising_value = elasticity * cpm_d * impressions
    return (subscription_value + advertising_value) / cost


def is_ltv_breach(multiple: Decimal | int | str) -> bool:
    """Return True when the LTV-to-Cost multiple breaches the guardrail (R5.3).

    A breach occurs when the multiple is strictly below
    :data:`LTV_TO_COST_THRESHOLD` (3.2). A multiple equal to the threshold passes.
    """
    return _as_decimal(multiple) < LTV_TO_COST_THRESHOLD
