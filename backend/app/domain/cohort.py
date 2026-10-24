"""Pure domain helpers for absolute churn-cohort numbers (Deal Decision Support).

Derives an approximate retained-subscriber count from a modeled cohort size and
the churn-reduction percentage, and provides a documented, clearly-labeled
derivation of a modeled cohort size when no explicit figure is supplied. These are
Derived_Figures: they never influence any guardrail or recommendation and are
always flagged as derived where they surface. Decimal-only, pure, PBT target.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

__all__ = ["retained_subscribers", "derive_modeled_cohort_size"]

_WHOLE = Decimal("1")


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


def retained_subscribers(
    modeled_cohort_size: Decimal | int | str | None,
    churn_reduction_pct: Decimal | int | str | None,
) -> Decimal | None:
    """Absolute retained subscribers = ``size * (pct / 100)``, whole number
    (R7.1, R7.2).

    Returns ``None`` when the cohort size <= 0 or is ``None`` (R7.3); returns 0
    when the percentage <= 0 and the size > 0 (R7.4). Decimal-only (R7.5).
    """
    if modeled_cohort_size is None:
        return None
    size = _as_decimal(modeled_cohort_size)
    if size <= 0:
        return None
    if churn_reduction_pct is None:
        return Decimal("0")
    pct = _as_decimal(churn_reduction_pct)
    if pct <= 0:
        return Decimal("0")
    retained = size * (pct / Decimal("100"))
    return retained.quantize(_WHOLE, rounding=ROUND_HALF_UP)


def derive_modeled_cohort_size(
    normalized_cost_usd: Decimal | int | str | None,
) -> Decimal | None:
    """Documented, deterministic fallback cohort size (R8.1), a Derived_Figure.

    One modeled addressable subscriber per whole USD of normalized acquisition
    cost: ``floor(normalized_cost_usd)``. A transparent placeholder sizing that
    never feeds any guardrail or recommendation; always flagged derived where it
    surfaces. Returns ``None`` when cost <= 0 or ``None``.
    """
    if normalized_cost_usd is None:
        return None
    cost = _as_decimal(normalized_cost_usd)
    if cost <= 0:
        return None
    return cost.quantize(_WHOLE, rounding=ROUND_FLOOR)