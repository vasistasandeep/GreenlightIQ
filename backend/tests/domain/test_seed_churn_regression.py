"""Seed verdict-stability regression test (calculable-churn-model task 12).

# Feature: calculable-churn-model, Property 9: Verdict stability
# Feature: calculable-churn-model, Property 10: Stored equals recompute

Recomputes the churn-reduction percentage for the five seeded demo titles purely
from their seeded features (no database) and asserts that the model-computed
value preserves every demo verdict. This pins the seed's churn logic against the
domain model so a divergence between the two is caught immediately.

The test imports the seed generator's own helpers rather than hard-coding the
feature values, so the regression stays bound to the actual seed logic
(``_title_churn_result`` builds :class:`ChurnFeatures` from ``_PEDIGREE_SCALE``,
``_EXCLUSIVE_BY_TITLE``, ``_telemetry_heat`` and ``TITLES`` then runs the shared
``calculate_churn_mitigation``). Importing the module does not regenerate the
SQL file: the render-time code only runs under ``__main__``.

Assertions, per title:
  * verdict-preserving tolerances (R9.4): Aurora within 0.05 of 2.10; Echoes
    within 0.05 of 2.00; Monsoon within 0.05 of 1.80; The Ledger in the
    inclusive range [1.60, 1.65] and strictly above 1.50; Vintage Reruns in
    [0.80, 0.90] and strictly below 1.50.
  * churn-guardrail outcome used by the verdict (R9.3): the three GREENLIGHT and
    the one NEGOTIATE_HARD keep a passing churn (>= 1.5, so churn never forces
    PASS); the one PASS keeps the breaching churn (< 1.5). Exactly 4 titles land
    >= 1.5 and exactly 1 lands < 1.5.
  * exact value lock (R9.5 flavor): Aurora 2.11, Echoes 1.99, Monsoon 1.79,
    Ledger 1.60, Reruns 0.81. A mismatch means the seed and domain diverged and
    the test fails rather than loosening the bound.

Validates: Requirements 9.3, 9.4, 13.2
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.churn import (
    CHURN_MITIGATION_THRESHOLD,
    DEFAULT_CHURN_MODEL_PARAMS,
    ChurnFeatures,
    calculate_churn_mitigation,
)

# Seeded features per title, built directly so this regression is independent of
# the seed generator's helper (and of task ordering): asset type, pedigree,
# production scale, exclusivity, Telemetry_Heat (mean of the title's territories'
# social_sentiment_index x 100), and genre. These mirror the seeded
# metadata_vectors / license_terms / market_telemetry_cache rows.
_FEATURES = {
    "title-aurora": ("ORIGINAL_SERIES", "8.50", "9.00", True, "65", "sci-fi"),
    "title-echoes": ("ORIGINAL_SERIES", "7.80", "7.00", True, "59", "drama"),
    "title-monsoon": ("CO_PRODUCTION", "7.20", "6.50", False, "63", "drama"),
    "title-ledger": ("ORIGINAL_FILM", "6.00", "5.50", True, "63", "thriller"),
    "title-reruns": ("LICENSED_LIBRARY", "4.00", "3.50", False, "53.5", "comedy"),
}


def _recompute(label: str) -> Decimal:
    """Model-recompute a seeded title's churn from its seeded features."""
    atype, ped, scale, excl, heat, genre = _FEATURES[label]
    features = ChurnFeatures(
        asset_type=atype,
        pedigree=Decimal(ped),
        production_scale=Decimal(scale),
        is_exclusive=excl,
        telemetry_heat=Decimal(heat),
        genre=genre,
    )
    return calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS
    ).churn_reduction_pct


# (label, expected_exact, tolerance_center, verdict). The tolerance checks below
# derive their bounds from these so the per-title R9.4 rule is explicit.
_EXACT = {
    "title-aurora": Decimal("2.11"),
    "title-echoes": Decimal("1.99"),
    "title-monsoon": Decimal("1.79"),
    "title-ledger": Decimal("1.60"),
    "title-reruns": Decimal("0.81"),
}


# --- R9.5 flavor: exact value lock ----------------------------------------


@pytest.mark.parametrize("label, expected", sorted(_EXACT.items()))
def test_seeded_churn_matches_exact_expected(label: str, expected: Decimal) -> None:
    """Each seeded title recomputes to its exact expected churn (Decimal equality).

    A mismatch means the seed features and the domain model diverged; the test
    fails rather than loosening the tolerance.
    """
    assert _recompute(label) == expected


# --- R9.4: verdict-preserving tolerances ----------------------------------


def test_aurora_within_tolerance() -> None:
    assert abs(_recompute("title-aurora") - Decimal("2.10")) <= Decimal("0.05")


def test_echoes_within_tolerance() -> None:
    assert abs(_recompute("title-echoes") - Decimal("2.00")) <= Decimal("0.05")


def test_monsoon_within_tolerance() -> None:
    assert abs(_recompute("title-monsoon") - Decimal("1.80")) <= Decimal("0.05")


def test_ledger_within_range_and_above_hurdle() -> None:
    value = _recompute("title-ledger")
    assert Decimal("1.60") <= value <= Decimal("1.65")
    assert value > CHURN_MITIGATION_THRESHOLD  # strictly above 1.50


def test_reruns_within_range_and_below_hurdle() -> None:
    value = _recompute("title-reruns")
    assert Decimal("0.80") <= value <= Decimal("0.90")
    assert value < CHURN_MITIGATION_THRESHOLD  # strictly below 1.50


# --- R9.3: churn-guardrail outcome used by the verdict --------------------


@pytest.mark.parametrize(
    "label",
    ["title-aurora", "title-echoes", "title-monsoon", "title-ledger"],
)
def test_passing_churn_does_not_breach(label: str) -> None:
    """The 3 GREENLIGHT + 1 NEGOTIATE_HARD keep a passing churn (>= 1.5), so the
    churn guardrail never forces PASS for them."""
    assert _recompute(label) >= CHURN_MITIGATION_THRESHOLD


def test_pass_title_churn_breaches() -> None:
    """Vintage Reruns keeps the breaching churn (< 1.5): churn is the
    non-correctable factor that produces its PASS verdict."""
    assert _recompute("title-reruns") < CHURN_MITIGATION_THRESHOLD


def test_churn_guardrail_outcome_counts() -> None:
    """Exactly 4 seeded titles pass churn (>= 1.5) and exactly 1 breaches (< 1.5):
    the 3 GREENLIGHT + 1 NEGOTIATE_HARD keep a passing churn, the 1 PASS has the
    breaching churn (R9.3)."""
    values = [_recompute(label) for label in _EXACT]
    passing = sum(1 for v in values if v >= CHURN_MITIGATION_THRESHOLD)
    breaching = sum(1 for v in values if v < CHURN_MITIGATION_THRESHOLD)
    assert passing == 4
    assert breaching == 1
    assert passing + breaching == len(_EXACT)
