"""Pure domain functions for the Negotiation Playbook (Deal Decision Support).

When a decision is NEGOTIATE_HARD or PASS driven by a cost-correctable breach,
these helpers compute the target purchase ceiling (the price at which the breached
guardrail would pass), the implied discount versus the current ask, and a set of
plain-language counter-proposal levers keyed to the breached guardrails.

The module is pure: Decimal-only arithmetic, no I/O, no global state, so it is a
direct property-based-testing target. It introduces no new guardrail math - the
ceilings are algebraic rearrangements of the existing CPVH and LTV checks.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional, Sequence, TypedDict

from app.domain.recommendation import GuardrailCheck, GuardrailName

__all__ = [
    "CounterProposalLever",
    "cpvh_implied_ceiling",
    "ltv_implied_ceiling",
    "target_purchase_ceiling",
    "implied_discount_pct",
    "counter_proposal_levers",
]

_USD_QUANTUM = Decimal("1")       # whole United States dollars
_PCT_QUANTUM = Decimal("0.1")     # one decimal place


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


class CounterProposalLever(TypedDict):
    """A single plain-language negotiation lever for a breached guardrail."""

    name: GuardrailName
    correctable: bool | None
    message: str


def cpvh_implied_ceiling(
    normalized_cost_usd: Decimal | int | str,
    computed_cpvh: Decimal | int | str,
    cpvh_ceiling: Decimal | int | str,
) -> Decimal:
    """Cost at which CPVH would sit exactly at its ceiling (R1.1).

    Returns ``normalized_cost_usd * (cpvh_ceiling / computed_cpvh)`` unrounded;
    the caller rounds. Requires ``computed_cpvh > 0``.
    """
    cost = _as_decimal(normalized_cost_usd)
    cpvh = _as_decimal(computed_cpvh)
    ceiling = _as_decimal(cpvh_ceiling)
    if cpvh <= 0:
        raise ValueError("computed_cpvh must be positive")
    return cost * (ceiling / cpvh)


def ltv_implied_ceiling(
    normalized_cost_usd: Decimal | int | str,
    computed_multiple: Decimal | int | str,
    ltv_threshold: Decimal | int | str,
) -> Decimal:
    """Cost at which the LTV-to-Cost multiple would sit at its threshold (R1.2).

    Returns ``normalized_cost_usd * (computed_multiple / ltv_threshold)``
    unrounded. Requires ``ltv_threshold > 0``.
    """
    cost = _as_decimal(normalized_cost_usd)
    multiple = _as_decimal(computed_multiple)
    threshold = _as_decimal(ltv_threshold)
    if threshold <= 0:
        raise ValueError("ltv_threshold must be positive")
    return cost * (multiple / threshold)


def _round_usd(value: Decimal) -> Decimal:
    return value.quantize(_USD_QUANTUM, rounding=ROUND_HALF_UP)


def target_purchase_ceiling(
    normalized_cost_usd: Decimal | int | str | None,
    checks: Sequence[GuardrailCheck],
) -> Optional[Decimal]:
    """Binding (smallest) per-guardrail ceiling over breached, cost-correctable
    CPVH/LTV checks, rounded to whole USD (R1.3, R1.6).

    Returns ``None`` when cost <= 0 (R1.5) or when no cost-correctable CPVH/LTV
    guardrail is breached (R1.4). Only CPVH and LTV_TO_COST yield a closed-form
    cost ceiling; other guardrails are addressed by levers only.
    """
    if normalized_cost_usd is None:
        return None
    cost = _as_decimal(normalized_cost_usd)
    if cost <= 0:
        return None

    candidates: list[Decimal] = []
    for check in checks:
        if not check["breached"] or check["correctable"] is not True:
            continue
        computed = check["computed_value"]
        threshold = check["threshold"]
        if computed is None:
            continue
        if check["name"] == "CPVH":
            if _as_decimal(computed) <= 0:
                continue
            candidates.append(cpvh_implied_ceiling(cost, computed, threshold))
        elif check["name"] == "LTV_TO_COST":
            if _as_decimal(threshold) <= 0:
                continue
            candidates.append(ltv_implied_ceiling(cost, computed, threshold))

    if not candidates:
        return None
    return _round_usd(min(candidates))


def implied_discount_pct(
    current_ask_usd: Decimal | int | str | None,
    ceiling_usd: Decimal | int | str | None,
) -> Optional[Decimal]:
    """Implied discount from the ask to the ceiling, rounded to 1 dp (R2.1, R2.4).

    Returns 0 when the ceiling is at or above the ask (R2.2, never negative);
    ``None`` when the ask <= 0 or the ceiling is ``None`` (R2.3).
    """
    if current_ask_usd is None or ceiling_usd is None:
        return None
    ask = _as_decimal(current_ask_usd)
    ceiling = _as_decimal(ceiling_usd)
    if ask <= 0:
        return None
    if ceiling >= ask:
        return Decimal("0.0")
    pct = (ask - ceiling) / ask * Decimal("100")
    return pct.quantize(_PCT_QUANTUM, rounding=ROUND_HALF_UP)


# Rule table: (guardrail name) -> (correctable message, structural message).
_LEVER_RULES: dict[str, tuple[str, str]] = {
    "CPVH": (
        "Renegotiate the acquisition cost down to the target purchase ceiling to "
        "bring cost-per-viewing-hour under its ceiling.",
        "Secure additional licensed windows or territories to grow projected "
        "viewing hours, since cost alone cannot bring CPVH under its ceiling.",
    ),
    "LTV_TO_COST": (
        "Negotiate a lower upfront fee or add performance step-downs to lift the "
        "LTV-to-cost multiple over its threshold.",
        "Restructure the deal toward revenue-share or add AVOD inventory "
        "commitments, since the multiple cannot be fixed by cost alone.",
    ),
    "CHURN_MITIGATION": (
        "Add exclusivity or holdback terms that raise the modeled churn-reduction "
        "contribution.",
        "Pair the title with complementary catalog or marketing support, since "
        "churn mitigation is intrinsic and not corrected by price.",
    ),
    "PAYBACK_HORIZON": (
        "Restructure the milestone payment schedule to shorten the payback horizon.",
        "Shorten the license term or add renewal options, since the payback "
        "horizon cannot be corrected by price alone.",
    ),
}

_GENERIC_LEVER = "Negotiate contractual terms to bring this check within its threshold."


def counter_proposal_levers(
    checks: Sequence[GuardrailCheck],
) -> list[CounterProposalLever]:
    """One lever per breached check, keyed by guardrail name + correctable flag
    (R3.1-R3.5). Empty list when nothing is breached (GREENLIGHT, R3.5).

    A correctable (True) breach gets the cost/terms message; a non-correctable
    (False) or unclassifiable (None) breach gets the structural message. An
    unknown guardrail name falls back to a generic ASCII message.
    """
    levers: list[CounterProposalLever] = []
    for check in checks:
        if not check["breached"]:
            continue
        rules = _LEVER_RULES.get(check["name"])
        if rules is None:
            message = _GENERIC_LEVER
        else:
            correctable_msg, structural_msg = rules
            message = correctable_msg if check["correctable"] is True else structural_msg
        levers.append(
            CounterProposalLever(
                name=check["name"],
                correctable=check["correctable"],
                message=message,
            )
        )
    return levers