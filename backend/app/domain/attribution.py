"""Pure domain function for the LTV-to-Cost attribution breakdown.

Decomposes the LTV-to-Cost numerator into its subscription (SVOD) and advertising
(AVOD) contributions. The operand order mirrors ``compute_ltv_to_cost`` exactly so
the resulting multiple agrees with the authoritative engine multiple by
construction. Decimal-only, pure, a property-based-testing target.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

__all__ = ["LtvAttribution", "ltv_attribution"]


def _as_decimal(value: Decimal | int | str) -> Decimal:
    """Coerce to Decimal without binary-float error; reject float/bool."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean is not a valid numeric input")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(
        f"expected Decimal, int, or str to preserve precision, got {type(value).__name__}"
    )


class LtvAttribution(TypedDict):
    """The decomposed LTV-to-Cost numerator and resulting multiple."""

    subscription_value: Decimal
    advertising_value: Decimal
    total_modeled_value: Decimal
    normalized_cost_usd: Decimal
    multiple: Decimal


def ltv_attribution(
    churn_reduction_value: Decimal | int | str,
    ltv: Decimal | int | str,
    watch_time_elasticity: Decimal | int | str,
    cpm: Decimal | int | str,
    ad_impressions: Decimal | int | str,
    cost_usd: Decimal | int | str,
) -> LtvAttribution:
    """Decompose the LTV-to-Cost numerator (R5.1-R5.4).

    ``subscription_value = churn_reduction_value * ltv`` and
    ``advertising_value = watch_time_elasticity * cpm * ad_impressions`` use the
    same operand order as ``compute_ltv_to_cost``, so the returned ``multiple``
    equals that function for identical inputs (R5.5).

    Raises:
        ZeroDivisionError: when ``cost_usd`` is zero (R5 parity).
        TypeError: on float/bool inputs (R5.6).
    """
    churn = _as_decimal(churn_reduction_value)
    ltv_d = _as_decimal(ltv)
    elasticity = _as_decimal(watch_time_elasticity)
    cpm_d = _as_decimal(cpm)
    impressions = _as_decimal(ad_impressions)
    cost = _as_decimal(cost_usd)

    if cost == 0:
        raise ZeroDivisionError("cost_usd must be non-zero to compute attribution")

    subscription_value = churn * ltv_d
    advertising_value = elasticity * cpm_d * impressions
    total = subscription_value + advertising_value
    return LtvAttribution(
        subscription_value=subscription_value,
        advertising_value=advertising_value,
        total_modeled_value=total,
        normalized_cost_usd=cost,
        multiple=total / cost,
    )