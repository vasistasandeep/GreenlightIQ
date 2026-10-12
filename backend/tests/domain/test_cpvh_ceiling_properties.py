"""Property-based tests for CPVH ceiling selection and breach boundary (R4).

Covers design Properties 9 and 10 for the pure domain functions in
``app.domain.cpvh``:

* Property 9 -- ``cpvh_ceiling`` maps asset classifications to the applicable
  ceiling: 0.18 USD for a Premium_Original, 0.05 USD for a Library_Filler, and
  ``None`` when no classification applies (R4.2, R4.3, R4.4).
* Property 10 -- ``cpvh_breaches`` / ``cpvh_passes`` form the breach boundary:
  strictly greater than the ceiling breaches, less-than-or-equal passes, and the
  two helpers are exact complements (R4.6, R4.7).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.cpvh import (
    LIBRARY_FILLER_CEILING,
    PREMIUM_ORIGINAL_CEILING,
    AssetType,
    cpvh_breaches,
    cpvh_ceiling,
    cpvh_passes,
)

# Classification groupings mirrored from the requirements (R4.2, R4.3) so the
# tests assert against an independently stated expectation rather than importing
# the module's own private groupings.
_PREMIUM_ORIGINAL = frozenset(
    {AssetType.ORIGINAL_SERIES, AssetType.ORIGINAL_FILM, AssetType.CO_PRODUCTION}
)
_LIBRARY_FILLER = frozenset({AssetType.LICENSED_LIBRARY})

# A Decimal strategy over a broad monetary range around the ceilings, including
# negatives and zero, quantized to four decimal places (CPVH's own precision).
_decimal_money = st.decimals(
    min_value=Decimal("-1000"),
    max_value=Decimal("1000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)

# A ceiling strategy that keeps generated ceilings positive and near realistic
# values while still exercising the boundary logic.
_ceiling_money = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("100"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


# Feature: cineroi-ai, Property 9: CPVH ceiling selection
@settings(max_examples=200)
@given(asset_type=st.sampled_from(list(AssetType)))
def test_cpvh_ceiling_selection_by_classification(asset_type: AssetType) -> None:
    """Premium_Original -> 0.18, Library_Filler -> 0.05 for every known type.

    **Validates: Requirements 4.2, 4.3**
    """
    result = cpvh_ceiling(asset_type)

    if asset_type in _PREMIUM_ORIGINAL:
        assert result == PREMIUM_ORIGINAL_CEILING
        assert result == Decimal("0.18")
    elif asset_type in _LIBRARY_FILLER:
        assert result == LIBRARY_FILLER_CEILING
        assert result == Decimal("0.05")
    else:  # pragma: no cover - defensive: every AssetType is classified today
        raise AssertionError(f"unexpected AssetType in known enum: {asset_type!r}")


# Feature: cineroi-ai, Property 9: CPVH ceiling selection
@settings(max_examples=200)
@given(asset_type=st.sampled_from(list(AssetType)))
def test_cpvh_ceiling_known_types_are_never_none(asset_type: AssetType) -> None:
    """Every defined AssetType resolves to a concrete, positive ceiling (R4.2, R4.3).

    None is reserved exclusively for the unclassified case (R4.4), which the
    enum cannot produce; this anchors that distinction.

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    result = cpvh_ceiling(asset_type)

    assert result is not None
    assert result in {PREMIUM_ORIGINAL_CEILING, LIBRARY_FILLER_CEILING}
    assert result > Decimal("0")


class _UnclassifiedAssetType(str):
    """A stand-in for an asset value that matches no defined classification.

    ``cpvh_ceiling`` performs membership tests against the Premium_Original and
    Library_Filler frozensets; any value absent from both must yield ``None``
    (R4.4). This string subclass is deliberately not an ``AssetType`` member.
    """


# Feature: cineroi-ai, Property 9: CPVH ceiling selection
@settings(max_examples=200)
@given(label=st.text(min_size=0, max_size=24))
def test_cpvh_ceiling_unclassified_returns_none(label: str) -> None:
    """Any value matching no classification yields None (R4.4).

    **Validates: Requirements 4.4**
    """
    unclassified = _UnclassifiedAssetType(label)

    assert cpvh_ceiling(unclassified) is None  # type: ignore[arg-type]


# Feature: cineroi-ai, Property 10: CPVH breach boundary
@settings(max_examples=200)
@given(cpvh=_decimal_money, ceiling=_ceiling_money)
def test_cpvh_breach_boundary_strictly_greater(cpvh: Decimal, ceiling: Decimal) -> None:
    """A breach occurs iff CPVH is strictly greater than the ceiling (R4.6, R4.7).

    **Validates: Requirements 4.6, 4.7**
    """
    assert cpvh_breaches(cpvh, ceiling) == (cpvh > ceiling)
    assert cpvh_passes(cpvh, ceiling) == (cpvh <= ceiling)


# Feature: cineroi-ai, Property 10: CPVH breach boundary
@settings(max_examples=200)
@given(cpvh=_decimal_money, ceiling=_ceiling_money)
def test_cpvh_breach_and_pass_are_exact_complements(cpvh: Decimal, ceiling: Decimal) -> None:
    """``cpvh_breaches`` and ``cpvh_passes`` partition every input exactly once.

    For any CPVH/ceiling pair precisely one of breach/pass holds -- never both,
    never neither (R4.6, R4.7).

    **Validates: Requirements 4.6, 4.7**
    """
    breaches = cpvh_breaches(cpvh, ceiling)
    passes = cpvh_passes(cpvh, ceiling)

    assert breaches is not passes
    assert breaches ^ passes


# Feature: cineroi-ai, Property 10: CPVH breach boundary
@settings(max_examples=200)
@given(ceiling=_ceiling_money)
def test_cpvh_exactly_at_ceiling_passes(ceiling: Decimal) -> None:
    """CPVH equal to the ceiling passes and does not breach (R4.7).

    This pins the boundary itself -- the discriminating case between ``>`` and
    ``>=`` -- which random sampling rarely hits exactly.

    **Validates: Requirements 4.6, 4.7**
    """
    assert cpvh_passes(ceiling, ceiling) is True
    assert cpvh_breaches(ceiling, ceiling) is False
