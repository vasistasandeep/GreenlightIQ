"""Pure scenario-scaling helper for What-If Sensitivity analysis.

Applies bounded scenario multipliers to a title's base valuation inputs so the
Guardrails_Engine can recompute a scorecard under alternative assumptions without
mutating any stored record. This module is pure (no I/O, no persistence) and a
direct property-test target, mirroring the other `app/domain/*` modules.

Cost scaling is intentionally NOT performed here: the acquisition cost is
normalized to USD by the engine (async I/O), so the engine scales the already
normalized USD amount by the cost multiplier. The three remaining scalings are
pure field arithmetic and live here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal

from app.engines.guardrails import ValuationInputs

__all__ = ["MULTIPLIER_MIN", "MULTIPLIER_MAX", "ScaledInputs", "scale_inputs"]

# Inclusive multiplier bounds; both ends and 1.0 are valid scenario values.
MULTIPLIER_MIN: Decimal = Decimal("0.5")
MULTIPLIER_MAX: Decimal = Decimal("2.0")


@dataclass(frozen=True)
class ScaledInputs:
    """Scenario-scaled inputs: the scaled ValuationInputs plus scaled viewing
    hours (hours live on the title, not on ValuationInputs, so they travel
    alongside)."""

    inputs: ValuationInputs
    viewing_hours: Decimal | None


def _as_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean is not a valid numeric input")
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(
        f"expected Decimal, int, or str to preserve precision, got {type(value).__name__}"
    )


def scale_inputs(
    base: ValuationInputs,
    base_viewing_hours: Decimal | int | str | None,
    *,
    cost_multiplier: Decimal,
    viewership_multiplier: Decimal,
    churn_multiplier: Decimal,
) -> ScaledInputs:
    """Return a scaled COPY of ``base`` without mutating it (R5.5).

    Scaling model (R5.2-R5.4):
      * ad_impressions      *= viewership_multiplier
      * churn_reduction_pct *= churn_multiplier
      * viewing_hours       *= viewership_multiplier  (None -> None)

    The cost multiplier is accepted for signature symmetry but is applied by the
    engine to the normalized USD cost, not here.
    """
    _ = cost_multiplier  # applied by the engine to the normalized USD amount
    vm = _as_decimal(viewership_multiplier)
    cm = _as_decimal(churn_multiplier)

    # churn_reduction_pct is now optional (calculable-churn-model, R4.6): a
    # Decimal is a supplied value we scale; None means "resolve and compute" and
    # must not be multiplied here. The what-if resolve-then-scale is handled in a
    # later task; for now a None churn is carried through unchanged.
    scaled_churn = (
        None
        if base.churn_reduction_pct is None
        else _as_decimal(base.churn_reduction_pct) * cm
    )

    scaled = dataclasses.replace(
        base,
        ad_impressions=_as_decimal(base.ad_impressions) * vm,
        churn_reduction_pct=scaled_churn,
    )
    scaled_hours = (
        None
        if base_viewing_hours is None
        else _as_decimal(base_viewing_hours) * vm
    )
    return ScaledInputs(inputs=scaled, viewing_hours=scaled_hours)