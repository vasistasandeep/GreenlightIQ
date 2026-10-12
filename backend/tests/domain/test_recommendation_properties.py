"""Property-based tests for recommendation determination and explainability.

Covers the pure domain logic in ``app.domain.recommendation``:

* Property 15: Recommendation determination and totality (R8.1-8.5)
* Property 39: Explanation completeness (R30.1)
* Property 40: Dominant factor selection (R30.3)

These tests build Hypothesis strategies that generate lists of
:class:`GuardrailCheck` TypedDicts with varied ``breached`` / ``correctable`` /
``shortfall_magnitude`` combinations (using ``Decimal`` shortfalls) and assert
the universal properties hold across the generated input space.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.recommendation import (
    GREENLIGHT,
    NEGOTIATE_HARD,
    PASS,
    GuardrailCheck,
    determine_recommendation,
)

GUARDRAIL_NAMES = ["CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON"]

VALID_STATUSES = {GREENLIGHT, NEGOTIATE_HARD, PASS}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Decimal shortfall magnitudes. Keep them finite and bounded so comparisons are
# well-defined, but span a wide-enough range to exercise ordering.
shortfall_magnitudes = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)

decimal_values = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


@st.composite
def guardrail_checks(draw: st.DrawFn) -> GuardrailCheck:
    """Generate a single GuardrailCheck with a coherent breached/passed state.

    ``breached`` and ``passed`` are kept mutually consistent (a check is either
    passed or breached). ``correctable`` and ``shortfall_magnitude`` are only
    meaningful for breaches, but we still generate varied values to probe the
    determination logic broadly.
    """
    name = draw(st.sampled_from(GUARDRAIL_NAMES))
    breached = draw(st.booleans())
    threshold = draw(decimal_values)
    computed_value = draw(st.none() | decimal_values)

    if breached:
        correctable = draw(st.sampled_from([True, False, None]))
        shortfall_magnitude = draw(st.none() | shortfall_magnitudes)
    else:
        # A passed check: no classification, no shortfall.
        correctable = None
        shortfall_magnitude = None

    check: GuardrailCheck = {
        "name": name,
        "computed_value": computed_value,
        "threshold": threshold,
        "passed": not breached,
        "breached": breached,
        "shortfall_magnitude": shortfall_magnitude,
        "correctable": correctable,
    }
    return check


check_lists = st.lists(guardrail_checks(), min_size=0, max_size=8)


# ---------------------------------------------------------------------------
# Property 15: Recommendation determination and totality
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 15: Recommendation determination and totality
@settings(max_examples=200)
@given(checks=check_lists)
def test_property_15_recommendation_determination_and_totality(
    checks: list[GuardrailCheck],
) -> None:
    """Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5

    For any set of completed guardrail checks:
      * exactly one of {GREENLIGHT, NEGOTIATE_HARD, PASS} is returned (R8.5);
      * 0 breaches -> GREENLIGHT (R8.1);
      * >=1 breach, every breach correctable -> NEGOTIATE_HARD (R8.2);
      * >=1 non-correctable breach -> PASS (R8.3);
      * any unclassifiable breach (correctable is None) -> PASS + flag (R8.4).
    """
    status, explanation = determine_recommendation(checks)

    # Totality (R8.5): exactly one valid status.
    assert status in VALID_STATUSES

    breaches = [c for c in checks if c["breached"]]
    has_unclassifiable = any(c["correctable"] is None for c in breaches)
    has_non_correctable = any(c["correctable"] is False for c in breaches)

    if not breaches:
        # R8.1
        assert status == GREENLIGHT
        assert explanation["unclassifiable"] is False
    elif has_unclassifiable:
        # R8.4 — unclassifiable forces PASS and sets the flag.
        assert status == PASS
        assert explanation["unclassifiable"] is True
    elif has_non_correctable:
        # R8.3
        assert status == PASS
        assert explanation["unclassifiable"] is False
    else:
        # R8.2 — one or more breaches, all correctable.
        assert status == NEGOTIATE_HARD
        assert explanation["unclassifiable"] is False


# ---------------------------------------------------------------------------
# Property 39: Explanation completeness
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 39: Explanation completeness
@settings(max_examples=200)
@given(checks=check_lists)
def test_property_39_explanation_completeness(
    checks: list[GuardrailCheck],
) -> None:
    """Validates: Requirements 30.1

    The explanation reports the pass/breach status of every input check, with
    the breached checks still carrying their computed value, threshold, and
    shortfall magnitude.
    """
    _status, explanation = determine_recommendation(checks)

    reported = explanation["checks"]

    # Every input check appears, in order, with its pass/breach status intact.
    assert len(reported) == len(checks)
    for original, echoed in zip(checks, reported, strict=True):
        assert echoed["name"] == original["name"]
        assert echoed["passed"] == original["passed"]
        assert echoed["breached"] == original["breached"]
        # pass/breach are complementary for a well-formed check.
        assert echoed["passed"] != echoed["breached"]
        # Breached checks retain the data needed to justify the breach (R30.2).
        if echoed["breached"]:
            assert "computed_value" in echoed
            assert "threshold" in echoed
            assert "shortfall_magnitude" in echoed


# ---------------------------------------------------------------------------
# Property 40: Dominant factor selection
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 40: Dominant factor selection
@settings(max_examples=200)
@given(checks=check_lists)
def test_property_40_dominant_factor_selection(
    checks: list[GuardrailCheck],
) -> None:
    """Validates: Requirements 30.3

    When the status is PASS or NEGOTIATE_HARD, the dominant factor is the
    breached check with the largest shortfall magnitude. When there are no
    breaches (GREENLIGHT), the dominant factor is None.
    """
    status, explanation = determine_recommendation(checks)
    dominant = explanation["dominant_factor"]

    breaches = [c for c in checks if c["breached"]]

    if not breaches:
        # No breaches -> no dominant factor and a GREENLIGHT status.
        assert dominant is None
        assert status == GREENLIGHT
        return

    # With breaches a dominant factor is always identified.
    assert dominant is not None

    breaches_with_magnitude = [
        c for c in breaches if c["shortfall_magnitude"] is not None
    ]

    if breaches_with_magnitude:
        max_magnitude = max(
            c["shortfall_magnitude"] for c in breaches_with_magnitude
        )
        # The dominant factor must name a breached check that carries the
        # maximum observed magnitude. Guardrail names are not unique across
        # checks, so match on (name, magnitude) rather than name alone: the
        # reported name must belong to at least one breach whose magnitude
        # equals the maximum.
        max_magnitude_names = {
            c["name"]
            for c in breaches_with_magnitude
            if c["shortfall_magnitude"] == max_magnitude
        }
        assert dominant in max_magnitude_names
    else:
        # No breach carries a known magnitude: the dominant factor is still one
        # of the breached checks.
        assert dominant in {c["name"] for c in breaches}
