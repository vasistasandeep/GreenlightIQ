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
  * exact value lock (R9.5 flavor): Aurora 2.11, Echoes 1.96, Monsoon 1.76,
    Ledger 1.62, Reruns 0.88. A mismatch means the seed and domain diverged and
    the test fails rather than loosening the bound.

Validates: Requirements 9.3, 9.4, 13.2
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Put the seed generator directory on sys.path so we can import its helpers.
# Mirror how the generator itself locates the backend: compute the repo root
# from __file__ (this file lives at backend/tests/domain/) and append the
# database/seed directory. Importing the module runs only module-level
# definitions; the SQL render runs under __main__, so no file is regenerated.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED_DIR = _REPO_ROOT / "database" / "seed"
if str(_SEED_DIR) not in sys.path:
    sys.path.insert(0, str(_SEED_DIR))

import generate_seed_sql as seed  # noqa: E402

from app.domain.churn import CHURN_MITIGATION_THRESHOLD  # noqa: E402

# Title lookup by seed label (TITLES tuple layout: label, name, asset_type, ...,
# target_territories, genre_tag, ...).
_TITLE_BY_LABEL = {t[0]: t for t in seed.TITLES}


def _recompute(label: str) -> Decimal:
    """Model-recompute a seeded title's churn from its seeded features."""
    _l, _name, atype, _cost, _cur, territories, genre, *_rest = _TITLE_BY_LABEL[label]
    return seed._title_churn_result(label, atype, genre, territories).churn_reduction_pct


# (label, expected_exact, tolerance_center, verdict). The tolerance checks below
# derive their bounds from these so the per-title R9.4 rule is explicit.
_EXACT = {
    "title-aurora": Decimal("2.11"),
    "title-echoes": Decimal("1.96"),
    "title-monsoon": Decimal("1.76"),
    "title-ledger": Decimal("1.62"),
    "title-reruns": Decimal("0.88"),
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
