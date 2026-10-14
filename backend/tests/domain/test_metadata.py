"""Tests for the shared Asset Studio metadata-radar derivations.

Targets ``app.domain.derive_production_scale``: the production-scale axis that
was previously inlined in ``app/api/quick_evaluate.py``'s ``_metadata_profile``.
These tests assert the extracted helper reproduces the prior inline formula
exactly on representative inputs, so the radar's ``production_scale`` value is
byte-for-byte identical after the extraction.

The expected values are computed independently here (reproducing the original
inline formula and its plain ``.quantize(Decimal("0.1"))`` default rounding)
rather than importing the helper's own logic, so the test genuinely pins the
behavior instead of tautologically echoing it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.metadata import derive_production_scale


def _expected(pedigree: Decimal, synopsis: str) -> Decimal:
    """Reproduce the former inline production-scale formula independently.

    Mirrors the exact arithmetic and the plain ``quantize(Decimal("0.1"))``
    (default context rounding, ROUND_HALF_EVEN) used by the original code.
    """
    synopsis_rich = min(Decimal("10"), Decimal(len(synopsis)) / Decimal("25"))
    production = min(Decimal("10"), (pedigree + synopsis_rich) / Decimal("2"))
    return production.quantize(Decimal("0.1"))


# Representative inputs covering the required cases:
# - a blank-ish short synopsis (synopsis_rich near 0)
# - a long synopsis (>250 chars) so synopsis_rich caps at 10
# - pedigree at the 0 / 5 / 10 endpoints and midpoint
# - a case where (pedigree + synopsis_rich) / 2 exceeds 10 so the outer min caps
_SHORT = "x"  # len 1 -> synopsis_rich = 0.04
_MEDIUM = "a" * 100  # len 100 -> synopsis_rich = 4.0
_LONG = "y" * 300  # len 300 -> synopsis_rich capped at 10


@pytest.mark.parametrize(
    "pedigree, synopsis",
    [
        # blank-ish short synopsis across pedigree endpoints
        (Decimal("0"), _SHORT),
        (Decimal("5"), _SHORT),
        (Decimal("10"), _SHORT),
        # long synopsis (>250 chars) so synopsis_rich caps at 10
        (Decimal("0"), _LONG),
        (Decimal("5"), _LONG),
        # pedigree 10 + capped synopsis_rich 10 -> (10 + 10) / 2 = 10, outer min holds
        (Decimal("10"), _LONG),
        # medium synopsis, midrange pedigree
        (Decimal("5"), _MEDIUM),
        (Decimal("7.5"), _MEDIUM),
    ],
)
def test_matches_prior_inline_formula(pedigree: Decimal, synopsis: str) -> None:
    assert derive_production_scale(pedigree, synopsis) == _expected(pedigree, synopsis)


def test_long_synopsis_caps_synopsis_rich_at_ten() -> None:
    # len 300 / 25 = 12 which exceeds 10, so synopsis_rich is pinned to 10.
    # With pedigree 10 the inner average is (10 + 10) / 2 = 10 exactly.
    assert derive_production_scale(Decimal("10"), "z" * 300) == Decimal("10.0")


def test_outer_min_caps_production_at_ten() -> None:
    # An over-large pedigree would push (pedigree + synopsis_rich) / 2 above 10;
    # the outer min must clamp the result to 10.0.
    result = derive_production_scale(Decimal("30"), "z" * 300)
    assert result == Decimal("10.0")
    assert result == _expected(Decimal("30"), "z" * 300)


def test_zero_pedigree_short_synopsis() -> None:
    # pedigree 0, synopsis len 1 -> synopsis_rich 0.04 -> (0 + 0.04)/2 = 0.02
    # quantize to 0.1 (half-even) -> 0.0
    assert derive_production_scale(Decimal("0"), "x") == Decimal("0.0")
