"""Pure domain functions for Recommendation Status determination and
explainability (Requirements 8 and 30).

The Guardrails_Engine evaluates a set of guardrail checks (CPVH, LTV-to-Cost,
churn mitigation, payback horizon). This module projects those checks into a
single Recommendation_Status plus a structured :class:`Explanation`:

* 0 breaches                               -> GREENLIGHT (R8.1)
* >=1 breach, all breaches correctable     -> NEGOTIATE_HARD (R8.2)
* >=1 breach that is non-correctable       -> PASS (R8.3)
* a breach cannot be classified (missing / invalid data; ``correctable is None``)
  -> PASS plus the ``unclassifiable`` flag (R8.4)

Exactly one of {GREENLIGHT, NEGOTIATE_HARD, PASS} is always returned (R8.5).

The explanation reports per-check pass/breach status (R30.1) and, for the
PASS / NEGOTIATE_HARD cases, the dominant contributing factor: the breached
check with the largest normalized shortfall magnitude (R30.2, R30.3).

This module is pure: no I/O, no database access, no global state.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict

__all__ = [
    "GuardrailCheck",
    "Explanation",
    "RecommendationStatus",
    "GREENLIGHT",
    "NEGOTIATE_HARD",
    "PASS",
    "determine_recommendation",
]

GREENLIGHT = "GREENLIGHT"
NEGOTIATE_HARD = "NEGOTIATE_HARD"
PASS = "PASS"

RecommendationStatus = Literal["GREENLIGHT", "NEGOTIATE_HARD", "PASS"]

GuardrailName = Literal["CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON"]


class GuardrailCheck(TypedDict):
    """A single guardrail evaluation result.

    Attributes:
        name: Which guardrail this check represents.
        computed_value: The computed metric value, or None when it could not be
            computed (e.g. CPVH with zero viewing hours).
        threshold: The applicable threshold for this guardrail.
        passed: True when the check passed.
        breached: True when the check breached its threshold.
        shortfall_magnitude: Normalized distance past the threshold for a breach
            (R30.2), or None when the check passed or the magnitude is unknown.
        correctable: True when the breach is correctable through renegotiated cost,
            False when non-correctable, or None when it cannot be classified due to
            missing or invalid input data (R8.2 / R8.3 / R8.4).
    """

    name: GuardrailName
    computed_value: Decimal | None
    threshold: Decimal
    passed: bool
    breached: bool
    shortfall_magnitude: Decimal | None
    correctable: bool | None


class Explanation(TypedDict):
    """Structured explainability payload for a recommendation (R30).

    Attributes:
        checks: Every guardrail check with its pass/breach status (R30.1).
        dominant_factor: Name of the breached check with the largest normalized
            shortfall magnitude, or None when there are no breaches (R30.3).
        unclassifiable: True when at least one breach could not be classified as
            correctable or non-correctable (R8.4).
    """

    checks: list[GuardrailCheck]
    dominant_factor: str | None
    unclassifiable: bool


def _dominant_factor(breaches: list[GuardrailCheck]) -> str | None:
    """Return the name of the breach with the largest normalized shortfall (R30.3).

    Breaches whose ``shortfall_magnitude`` is None are treated as the smallest
    possible magnitude so a breach with a known magnitude is always preferred.
    When no breach carries a magnitude, the first breach is returned so a
    dominant factor is still identified for a non-GREENLIGHT status. Ties are
    broken by preserving the input ordering (stable: first wins).
    """
    if not breaches:
        return None

    best: GuardrailCheck | None = None
    best_magnitude: Decimal | None = None
    for check in breaches:
        magnitude = check["shortfall_magnitude"]
        if best is None:
            best, best_magnitude = check, magnitude
            continue
        # Prefer a known magnitude over an unknown one.
        if magnitude is None:
            continue
        if best_magnitude is None or magnitude > best_magnitude:
            best, best_magnitude = check, magnitude

    return best["name"] if best is not None else None


def determine_recommendation(
    checks: list[GuardrailCheck],
) -> tuple[RecommendationStatus, Explanation]:
    """Determine the Recommendation_Status and build its explanation (R8, R30).

    Decision logic:
        * No breaches                                   -> GREENLIGHT (R8.1)
        * All breaches classified correctable           -> NEGOTIATE_HARD (R8.2)
        * Any breach non-correctable                    -> PASS (R8.3)
        * Any breach unclassifiable (correctable None)  -> PASS + flag (R8.4)

    Totality (R8.5): exactly one of {GREENLIGHT, NEGOTIATE_HARD, PASS} is
    always returned.

    Classification precedence: an unclassifiable breach forces PASS and sets the
    ``unclassifiable`` flag even when another breach is non-correctable, because
    missing or invalid data means the status cannot be trusted as a clean PASS.
    Both routes resolve to PASS, so the terminal status is unaffected; the flag
    simply records that classification was incomplete.

    Args:
        checks: The complete list of guardrail checks for a title.

    Returns:
        A tuple of (recommendation_status, explanation).
    """
    breaches = [check for check in checks if check["breached"]]

    unclassifiable = any(check["correctable"] is None for check in breaches)

    if not breaches:
        status: RecommendationStatus = GREENLIGHT
    elif unclassifiable:
        # At least one breach cannot be classified -> PASS + flag (R8.4).
        status = PASS
    elif any(check["correctable"] is False for check in breaches):
        # At least one definitively non-correctable breach -> PASS (R8.3).
        status = PASS
    else:
        # One or more breaches, every one correctable -> NEGOTIATE_HARD (R8.2).
        status = NEGOTIATE_HARD

    explanation: Explanation = {
        "checks": list(checks),
        "dominant_factor": _dominant_factor(breaches),
        "unclassifiable": unclassifiable,
    }
    return status, explanation
