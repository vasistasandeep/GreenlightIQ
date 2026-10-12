"""Pure domain functions for Calibration_Controller weight normalization (R12).

This module is intentionally free of any I/O, database access, or framework
dependencies: it contains only deterministic functions over typed inputs so it
can be exhaustively exercised by property-based tests (design Properties 18-19).

The Calibration_Controller never mutates feature-extraction weights in place; it
forks a new immutable ``model_versions`` row (R26). Before that row is created
it must settle the two *coupled* weights -- ``talent_pedigree_weight`` and
``narrative_trope_weight`` -- which the database constrains to
``NUMERIC(4,2)``, each ``CHECK BETWEEN 0.00 AND 1.00`` and together
``talent_pedigree_weight + narrative_trope_weight = 1.00`` (R12.2). The pure
functions here produce exactly such a pair, or refuse:

* ``validate_offset`` / ``validate_offsets`` -- a weight-adjustment offset is a
  value within ``[-1.00, 1.00]`` (R12.1). Anything outside that range is
  rejected with :class:`OffsetOutOfRangeError`.
* ``apply_offsets`` -- apply offsets to the active coupled weights, round each to
  two decimal places, and guarantee the resulting pair sums to exactly ``1.00``.
  If applying an offset would move either weight outside ``[0.00, 1.00]`` the
  calibration is rejected with :class:`WeightOutOfRangeError` and no partial
  result is returned, so the caller retains the prior weights unchanged (R12.4).
* ``normalize_weights`` -- re-weight an arbitrary non-negative pair into the
  coupled ``[0.00, 1.00]`` / sum-``1.00`` shape used to seed or repair a version.

All values use :class:`decimal.Decimal` for exact precision; results are
quantized to two decimal places to match the ``NUMERIC(4,2)`` column precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

__all__ = [
    "CalibrationError",
    "OffsetOutOfRangeError",
    "WeightOutOfRangeError",
    "WEIGHT_QUANTUM",
    "OFFSET_MIN",
    "OFFSET_MAX",
    "WEIGHT_MIN",
    "WEIGHT_MAX",
    "WEIGHT_SUM",
    "CoupledWeights",
    "validate_offset",
    "validate_offsets",
    "normalize_weights",
    "apply_offsets",
]


# Two decimal places, matching the NUMERIC(4,2) weight columns (R12.2).
WEIGHT_QUANTUM: Decimal = Decimal("0.01")

# Offsets are bounded to [-1.00, 1.00] (R12.1).
OFFSET_MIN: Decimal = Decimal("-1.00")
OFFSET_MAX: Decimal = Decimal("1.00")

# Each resulting weight is bounded to [0.00, 1.00] and the coupled pair sums to
# exactly 1.00 (R12.2 / DB CHECK talent_pedigree_weight + narrative_trope_weight).
WEIGHT_MIN: Decimal = Decimal("0.00")
WEIGHT_MAX: Decimal = Decimal("1.00")
WEIGHT_SUM: Decimal = Decimal("1.00")


class CalibrationError(ValueError):
    """Base class for calibration weight-normalization failures (R12).

    Subclasses map to the two distinct rejection reasons the Calibration_Controller
    surfaces: an offset outside its allowed range, and a resulting weight outside
    the ``[0.00, 1.00]`` bound.
    """


class OffsetOutOfRangeError(CalibrationError):
    """Raised when a weight-adjustment offset falls outside ``[-1.00, 1.00]`` (R12.1).

    A computed offset must be a value within the inclusive range ``[-1.00, 1.00]``;
    any value beyond it is not a valid adjustment and the calibration is rejected
    before any new model version is contemplated.
    """


class WeightOutOfRangeError(CalibrationError):
    """Raised when a resulting weight would fall outside ``[0.00, 1.00]`` (R12.4).

    If applying a computed offset would move either coupled weight outside the
    inclusive range ``[0.00, 1.00]``, the calibration is rejected atomically: no
    partial result is returned so the caller retains the prior weights unchanged
    and returns an out-of-range error.
    """


class CoupledWeights(NamedTuple):
    """The two coupled feature-extraction weights after normalization (R12.2).

    ``talent_pedigree`` and ``narrative_trope`` are each in ``[0.00, 1.00]`` and
    together sum to exactly ``1.00`` at two-decimal precision, mirroring the
    ``model_versions`` columns and their DB CHECK constraint.
    """

    talent_pedigree: Decimal
    narrative_trope: Decimal


def _quantize(value: Decimal) -> Decimal:
    """Quantize a value to two decimal places using HALF_UP rounding."""
    return value.quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


def validate_offset(offset: Decimal, *, name: str = "offset") -> Decimal:
    """Validate a single weight-adjustment offset and return it quantized (R12.1).

    Args:
        offset: The proposed offset.
        name: A label used in the error message to identify the offset.

    Returns:
        The offset quantized to two decimal places.

    Raises:
        OffsetOutOfRangeError: If the offset is outside ``[-1.00, 1.00]``.
    """
    quantized = _quantize(offset)
    if quantized < OFFSET_MIN or quantized > OFFSET_MAX:
        raise OffsetOutOfRangeError(
            f"{name} {offset} is outside the allowed range "
            f"[{OFFSET_MIN}, {OFFSET_MAX}] (R12.1)."
        )
    return quantized


def validate_offsets(offsets: dict[str, Decimal]) -> dict[str, Decimal]:
    """Validate a mapping of named offsets, each within ``[-1.00, 1.00]`` (R12.1).

    Args:
        offsets: A mapping of parameter name to proposed offset.

    Returns:
        A new mapping with every offset quantized to two decimal places.

    Raises:
        OffsetOutOfRangeError: If any offset is outside ``[-1.00, 1.00]``. The
            check is all-or-nothing: the first offending offset aborts the batch.
    """
    return {name: validate_offset(value, name=name) for name, value in offsets.items()}


def normalize_weights(
    talent_pedigree: Decimal, narrative_trope: Decimal
) -> CoupledWeights:
    """Re-weight a non-negative pair into coupled weights summing to ``1.00`` (R12.2).

    The two inputs are treated as relative weights and rescaled so that the pair
    is each within ``[0.00, 1.00]`` and sums to exactly ``1.00`` at two-decimal
    precision. ``talent_pedigree`` is rounded and ``narrative_trope`` is derived
    as ``1.00 - talent_pedigree`` so the sum is exact regardless of rounding.

    Args:
        talent_pedigree: Relative talent-pedigree weight; must be non-negative.
        narrative_trope: Relative narrative-trope weight; must be non-negative.

    Returns:
        The normalized :class:`CoupledWeights`.

    Raises:
        WeightOutOfRangeError: If either input is negative or both are zero (there
            is no meaningful way to normalize a zero/negative pair into the bound).
    """
    if talent_pedigree < 0 or narrative_trope < 0:
        raise WeightOutOfRangeError(
            f"weights ({talent_pedigree}, {narrative_trope}) must be non-negative "
            "to normalize (R12.2)."
        )

    total = talent_pedigree + narrative_trope
    if total == 0:
        raise WeightOutOfRangeError(
            "cannot normalize a pair of weights that both sum to zero (R12.2)."
        )

    talent = _quantize(talent_pedigree / total)
    # Derive the partner so the pair sums to exactly 1.00 after rounding.
    narrative = _quantize(WEIGHT_SUM - talent)
    return _check_bounds(talent, narrative)


def apply_offsets(
    talent_pedigree_weight: Decimal,
    narrative_trope_weight: Decimal,
    talent_pedigree_offset: Decimal,
    narrative_trope_offset: Decimal,
) -> CoupledWeights:
    """Apply offsets to the active coupled weights, normalized to sum ``1.00`` (R12.2).

    Each offset is validated against ``[-1.00, 1.00]`` (R12.1) and added to its
    corresponding active weight. The adjusted pair is then re-weighted so both
    results are within ``[0.00, 1.00]`` and sum to exactly ``1.00``.

    If applying an offset drives either adjusted weight below ``0.00`` -- i.e.
    outside the valid bound before normalization -- the calibration is rejected
    with :class:`WeightOutOfRangeError` and no result is returned, so the caller
    keeps the prior weights unchanged (R12.4).

    Args:
        talent_pedigree_weight: The active talent-pedigree weight.
        narrative_trope_weight: The active narrative-trope weight.
        talent_pedigree_offset: The computed offset for the talent-pedigree weight.
        narrative_trope_offset: The computed offset for the narrative-trope weight.

    Returns:
        The resulting normalized :class:`CoupledWeights`.

    Raises:
        OffsetOutOfRangeError: If either offset is outside ``[-1.00, 1.00]`` (R12.1).
        WeightOutOfRangeError: If applying an offset would move either weight
            outside ``[0.00, 1.00]`` (R12.4).
    """
    talent_delta = validate_offset(
        talent_pedigree_offset, name="talent_pedigree_offset"
    )
    narrative_delta = validate_offset(
        narrative_trope_offset, name="narrative_trope_offset"
    )

    adjusted_talent = _quantize(talent_pedigree_weight + talent_delta)
    adjusted_narrative = _quantize(narrative_trope_weight + narrative_delta)

    # An offset that pushes a weight below zero cannot be normalized back into
    # range without inverting its sign; reject rather than silently clamp (R12.4).
    if adjusted_talent < WEIGHT_MIN or adjusted_narrative < WEIGHT_MIN:
        raise WeightOutOfRangeError(
            "applying the offsets would move a weight outside "
            f"[{WEIGHT_MIN}, {WEIGHT_MAX}] "
            f"(talent={adjusted_talent}, narrative={adjusted_narrative}); "
            "the prior weights are retained (R12.4)."
        )

    return normalize_weights(adjusted_talent, adjusted_narrative)


def _check_bounds(talent: Decimal, narrative: Decimal) -> CoupledWeights:
    """Assert the coupled invariant and return the validated pair (R12.2, R12.4).

    Both weights must be within ``[0.00, 1.00]`` and sum to exactly ``1.00``.
    """
    if (
        talent < WEIGHT_MIN
        or talent > WEIGHT_MAX
        or narrative < WEIGHT_MIN
        or narrative > WEIGHT_MAX
    ):
        raise WeightOutOfRangeError(
            f"resulting weights (talent={talent}, narrative={narrative}) fall "
            f"outside [{WEIGHT_MIN}, {WEIGHT_MAX}] (R12.4)."
        )
    if talent + narrative != WEIGHT_SUM:
        raise WeightOutOfRangeError(
            f"resulting weights (talent={talent}, narrative={narrative}) do not "
            f"sum to {WEIGHT_SUM} (R12.2)."
        )
    return CoupledWeights(talent_pedigree=talent, narrative_trope=narrative)
