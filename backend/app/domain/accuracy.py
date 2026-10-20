"""Pure domain helper for the dashboard verdict-match accuracy figure
(dashboard-accuracy-and-payback-audit).

The Executive Command Dashboard surfaces a "Model Accuracy" KPI. This module
computes that figure honestly: for a title that has real observed outcomes
(ground truth), it recomputes an *actual* recommendation from those actual metric
values and compares it against the title's stored *predicted* recommendation. The
share of such titles whose actual verdict matches the predicted verdict is the
Verdict_Match_Rate.

The honesty-critical nuance (resolved here): the recommendation rule
(:func:`app.domain.recommendation.determine_recommendation`) does NOT consume raw
metric values -- it consumes classified :class:`~app.domain.recommendation.GuardrailCheck`
objects (threshold + passed/breached + correctable). ``historical_ground_truth``
stores only raw actual metric values. So this module classifies the ACTUAL metric
values into checks using the SAME thresholds and the SAME correctability rules the
live valuation path applies (imported from :mod:`app.engines.guardrails`,
:mod:`app.domain.cpvh`, and :mod:`app.domain.ltv` -- never re-declared), then feeds
those checks to the unchanged ``determine_recommendation``. Because a ground-truth
value is already a realized metric output, classification is value-vs-threshold
only; the CPVH/LTV formulas are never re-run.

Eligibility is strict so no verdict is inferred from absent data: a title is
classifiable only when ALL four guardrail metrics (``cpvh``, ``ltv_to_cost``,
``churn_reduction``, ``payback_horizon``) are present, and when the asset type has
an applicable CPVH ceiling. A missing metric could flip the verdict (an unobserved
churn value could be a non-correctable breach forcing PASS), so a partial title is
excluded rather than counted.

This module is pure: no I/O, no database access, no async, no global mutable state.
It imports only the Python standard library plus existing project domain/engine
modules, so it is importable without the application framework.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.cpvh import AssetType, cpvh_breaches, cpvh_ceiling
from app.domain.ltv import LTV_TO_COST_THRESHOLD
from app.domain.recommendation import (
    GuardrailCheck,
    RecommendationStatus,
    determine_recommendation,
)
from app.engines.guardrails import (
    CHURN_MITIGATION_THRESHOLD,
    PAYBACK_TARGET_MAX_MONTHS,
)

__all__ = [
    "ACCURACY_DECIMAL_PLACES",
    "REQUIRED_METRICS",
    "actual_verdict",
    "verdict_match_rate",
]

#: Fixed rounding for the emitted rate, matching the existing
#: ``portfolio_risk_exposure`` rounding in the dashboard handler so the value is
#: stable across runs.
ACCURACY_DECIMAL_PLACES = 4

#: Every one of these four ground-truth metrics must be present for a title's
#: Actual_Verdict to be classifiable (see module docstring).
REQUIRED_METRICS: tuple[str, ...] = (
    "cpvh",
    "ltv_to_cost",
    "churn_reduction",
    "payback_horizon",
)


def _normalized_shortfall(distance: Decimal, threshold: Decimal) -> Decimal:
    """Mirror of ``Guardrails_Engine._normalized_shortfall`` (verdict-neutral).

    Only affects the explanation's dominant factor, never the terminal status,
    but kept consistent with the live helper for faithful checks.
    """
    magnitude = abs(distance)
    if threshold and threshold != 0:
        return magnitude / abs(threshold)
    return magnitude


def actual_verdict(
    asset_type: str,
    actuals: dict[str, Decimal],
) -> RecommendationStatus | None:
    """Recompute the recommendation from ACTUAL ground-truth metric values.

    Classifies each actual metric into a ``GuardrailCheck`` using the live
    thresholds (asset-type CPVH ceiling, the 3.2 LTV floor, the 1.5 churn hurdle,
    and the 12-month payback max) and the live correctability rules
    (CPVH/LTV/payback correctable, churn non-correctable), then returns
    :func:`determine_recommendation`'s verdict.

    Returns ``None`` (not classifiable) when any of :data:`REQUIRED_METRICS` is
    absent, or when the asset type has no applicable CPVH ceiling.
    """
    # Strict eligibility: every required metric must be present.
    if any(metric not in actuals or actuals[metric] is None for metric in REQUIRED_METRICS):
        return None

    try:
        asset = AssetType(asset_type)
    except ValueError:
        return None

    ceiling = cpvh_ceiling(asset)
    if ceiling is None:
        # No applicable ceiling -> CPVH check cannot be classified against a real
        # ceiling; treat the title as not classifiable rather than inventing one.
        return None

    cpvh = Decimal(actuals["cpvh"])
    ltv = Decimal(actuals["ltv_to_cost"])
    churn = Decimal(actuals["churn_reduction"])
    payback = Decimal(actuals["payback_horizon"])

    # CPVH: breach when strictly > ceiling; correctable.
    cpvh_breached = cpvh_breaches(cpvh, ceiling)
    cpvh_check: GuardrailCheck = {
        "name": "CPVH",
        "computed_value": cpvh,
        "threshold": ceiling,
        "passed": not cpvh_breached,
        "breached": cpvh_breached,
        "shortfall_magnitude": _normalized_shortfall(cpvh - ceiling, ceiling) if cpvh_breached else None,
        "correctable": True if cpvh_breached else None,
    }

    # LTV-to-cost: breach when strictly < 3.2 floor; correctable.
    ltv_breached = ltv < LTV_TO_COST_THRESHOLD
    ltv_check: GuardrailCheck = {
        "name": "LTV_TO_COST",
        "computed_value": ltv,
        "threshold": LTV_TO_COST_THRESHOLD,
        "passed": not ltv_breached,
        "breached": ltv_breached,
        "shortfall_magnitude": _normalized_shortfall(LTV_TO_COST_THRESHOLD - ltv, LTV_TO_COST_THRESHOLD) if ltv_breached else None,
        "correctable": True if ltv_breached else None,
    }

    # Churn mitigation: breach when strictly < 1.5 hurdle; NON-correctable.
    churn_breached = churn < CHURN_MITIGATION_THRESHOLD
    churn_check: GuardrailCheck = {
        "name": "CHURN_MITIGATION",
        "computed_value": churn,
        "threshold": CHURN_MITIGATION_THRESHOLD,
        "passed": not churn_breached,
        "breached": churn_breached,
        "shortfall_magnitude": _normalized_shortfall(CHURN_MITIGATION_THRESHOLD - churn, CHURN_MITIGATION_THRESHOLD) if churn_breached else None,
        "correctable": False if churn_breached else None,
    }

    # Payback horizon: breach when strictly > 12 months; correctable.
    payback_max = Decimal(PAYBACK_TARGET_MAX_MONTHS)
    payback_breached = payback > payback_max
    payback_check: GuardrailCheck = {
        "name": "PAYBACK_HORIZON",
        "computed_value": payback,
        "threshold": payback_max,
        "passed": not payback_breached,
        "breached": payback_breached,
        "shortfall_magnitude": _normalized_shortfall(payback - payback_max, payback_max) if payback_breached else None,
        "correctable": True if payback_breached else None,
    }

    status, _ = determine_recommendation(
        [cpvh_check, ltv_check, churn_check, payback_check]
    )
    return status


def verdict_match_rate(
    pairs: list[tuple[str | None, str | None]],
) -> float | None:
    """Return the fraction of eligible pairs whose verdicts match, or ``None``.

    Each pair is ``(predicted_verdict, actual_verdict)`` for a title that has
    ground truth. The eligible subset is the pairs where BOTH verdicts are
    present (non-``None``); an absent predicted verdict (no stored
    ``recommendation_status``) or an unclassifiable actual verdict excludes the
    title. Returns ``round(matches / eligible_count, ACCURACY_DECIMAL_PLACES)``,
    or ``None`` when the eligible subset is empty. Never returns ``0.0`` to mean
    "not yet measured" -- absence of a basis is ``None``.
    """
    eligible = [
        (pred, act)
        for pred, act in pairs
        if pred is not None and act is not None
    ]
    if not eligible:
        return None
    matches = sum(1 for pred, act in eligible if pred == act)
    return round(matches / len(eligible), ACCURACY_DECIMAL_PLACES)