"""Property-based tests for calibration weight bounds and out-of-range rejection.

Targets the pure calibration domain in ``app.domain.weights``:
``apply_offsets``, ``normalize_weights``, ``validate_offset`` /
``validate_offsets``, :class:`CoupledWeights`, :class:`OffsetOutOfRangeError`,
:class:`WeightOutOfRangeError`, and the bounds constants
``OFFSET_MIN``/``OFFSET_MAX``/``WEIGHT_MIN``/``WEIGHT_MAX``/``WEIGHT_SUM``.

Covers design Property 18 (Calibration weight bounds and normalization) and
Property 19 (Calibration out-of-range rejection), validating Requirements
12.1, 12.2, and 12.4.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.weights import (
    OFFSET_MAX,
    OFFSET_MIN,
    WEIGHT_MAX,
    WEIGHT_MIN,
    WEIGHT_SUM,
    CoupledWeights,
    OffsetOutOfRangeError,
    WeightOutOfRangeError,
    apply_offsets,
)

_QUANTUM = Decimal("0.01")


def _active_weights() -> st.SearchStrategy[tuple[Decimal, Decimal]]:
    """A pair of coupled active weights, each in [0.00, 1.00] summing to 1.00.

    The talent-pedigree weight is drawn at two-decimal precision and the
    narrative-trope weight is derived as its complement so the active pair
    already satisfies the coupled invariant the Calibration_Controller forks
    from (R12.2).
    """
    return st.decimals(
        min_value=WEIGHT_MIN,
        max_value=WEIGHT_MAX,
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ).map(lambda t: (t, WEIGHT_SUM - t))


# Offsets strictly inside [-1.00, 1.00] at two-decimal precision (R12.1 accept).
_in_range_offset = st.decimals(
    min_value=OFFSET_MIN,
    max_value=OFFSET_MAX,
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Offsets strictly outside [-1.00, 1.00] on either side (R12.1 reject branch).
_out_of_range_offset = st.one_of(
    st.decimals(
        min_value=Decimal("-100.00"),
        max_value=Decimal("-1.01"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    st.decimals(
        min_value=Decimal("1.01"),
        max_value=Decimal("100.00"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)


# Feature: cineroi-ai, Property 18: Calibration weight bounds and normalization
@given(active=_active_weights(), t_offset=_in_range_offset, n_offset=_in_range_offset)
@settings(max_examples=200)
def test_apply_offsets_bounds_and_normalization(
    active: tuple[Decimal, Decimal],
    t_offset: Decimal,
    n_offset: Decimal,
) -> None:
    """Validates: Requirements 12.1, 12.2

    For valid offsets within [-1.00, 1.00] that keep both adjusted weights at or
    above 0.00, ``apply_offsets`` returns a :class:`CoupledWeights` whose weights
    each lie within [0.00, 1.00] and sum to exactly 1.00.
    """
    talent_weight, narrative_weight = active

    # Confine this test to the accept branch: both adjusted weights must stay
    # at or above WEIGHT_MIN (the reject branch is Property 19 below). Mirror the
    # module's two-decimal quantization before the bound check.
    adjusted_talent = (talent_weight + t_offset).quantize(_QUANTUM)
    adjusted_narrative = (narrative_weight + n_offset).quantize(_QUANTUM)
    assume(adjusted_talent >= WEIGHT_MIN and adjusted_narrative >= WEIGHT_MIN)
    # normalize_weights cannot rescale a pair that sums to zero.
    assume(adjusted_talent + adjusted_narrative > WEIGHT_MIN)

    result = apply_offsets(talent_weight, narrative_weight, t_offset, n_offset)

    assert isinstance(result, CoupledWeights)
    # Each resulting weight is within [0.00, 1.00] (R12.2).
    assert WEIGHT_MIN <= result.talent_pedigree <= WEIGHT_MAX
    assert WEIGHT_MIN <= result.narrative_trope <= WEIGHT_MAX
    # The coupled pair sums to exactly 1.00 at two-decimal precision (R12.2).
    assert result.talent_pedigree + result.narrative_trope == WEIGHT_SUM
    # Results carry the NUMERIC(4,2) precision of the weight columns.
    assert result.talent_pedigree == result.talent_pedigree.quantize(_QUANTUM)
    assert result.narrative_trope == result.narrative_trope.quantize(_QUANTUM)


# Feature: cineroi-ai, Property 19: Calibration out-of-range rejection
@given(
    active=_active_weights(),
    bad_offset=_out_of_range_offset,
    other_offset=_in_range_offset,
    bad_on_talent=st.booleans(),
)
@settings(max_examples=200)
def test_apply_offsets_rejects_offset_outside_allowed_range(
    active: tuple[Decimal, Decimal],
    bad_offset: Decimal,
    other_offset: Decimal,
    bad_on_talent: bool,
) -> None:
    """Validates: Requirements 12.4

    An offset outside [-1.00, 1.00] is rejected with
    :class:`OffsetOutOfRangeError` before any weight is adjusted, so the prior
    weights are left unchanged (R12.1 bound enforced by R12.4 rejection).
    """
    talent_weight, narrative_weight = active

    if bad_on_talent:
        t_offset, n_offset = bad_offset, other_offset
    else:
        t_offset, n_offset = other_offset, bad_offset

    with pytest.raises(OffsetOutOfRangeError):
        apply_offsets(talent_weight, narrative_weight, t_offset, n_offset)


# Feature: cineroi-ai, Property 19: Calibration out-of-range rejection
@given(active=_active_weights(), t_offset=_in_range_offset, n_offset=_in_range_offset)
@settings(max_examples=200)
def test_apply_offsets_rejects_weight_driven_below_zero(
    active: tuple[Decimal, Decimal],
    t_offset: Decimal,
    n_offset: Decimal,
) -> None:
    """Validates: Requirements 12.4

    When an in-range offset would drive either coupled weight below 0.00, the
    calibration is rejected with :class:`WeightOutOfRangeError` and no partial
    result is returned, so the caller retains the prior weights unchanged.
    """
    talent_weight, narrative_weight = active

    adjusted_talent = (talent_weight + t_offset).quantize(_QUANTUM)
    adjusted_narrative = (narrative_weight + n_offset).quantize(_QUANTUM)

    # Confine this test to the weight-underflow reject branch: the offsets are
    # themselves valid (in range) but at least one adjusted weight falls below
    # the lower bound.
    assume(adjusted_talent < WEIGHT_MIN or adjusted_narrative < WEIGHT_MIN)

    with pytest.raises(WeightOutOfRangeError):
        apply_offsets(talent_weight, narrative_weight, t_offset, n_offset)
