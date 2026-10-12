"""Pure domain functions for the Cost-Per-Viewing-Hour (CPVH) guardrail (R4).

This module is intentionally free of any I/O, database access, or framework
dependencies: it contains only deterministic functions over typed inputs so it
can be exhaustively exercised by property-based tests (design Properties 8-10).

The three concerns captured here:

* ``compute_cpvh`` -- divide normalized cost by projected viewing hours and round
  to four decimal places (R4.1). The caller is responsible for the zero-viewing-
  hours case (R4.5); this function enforces the positive-hours precondition and
  raises :class:`CPVHComputationError` if it is violated.
* ``cpvh_ceiling`` -- select the applicable ceiling by asset classification:
  0.18 USD for a Premium_Original, 0.05 USD for a Library_Filler, and ``None``
  when no classification applies (R4.2, R4.3, R4.4).
* ``cpvh_breaches`` -- the breach boundary: a CPVH strictly greater than the
  ceiling breaches (R4.6); a CPVH less than or equal to the ceiling passes (R4.7).

All monetary values use :class:`decimal.Decimal` for exact precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

__all__ = [
    "AssetType",
    "CPVHComputationError",
    "CPVH_QUANTUM",
    "PREMIUM_ORIGINAL_CEILING",
    "LIBRARY_FILLER_CEILING",
    "compute_cpvh",
    "cpvh_ceiling",
    "cpvh_breaches",
    "cpvh_passes",
]


class AssetType(str, Enum):
    """The enumerated set of asset classifications (R17.4).

    Premium_Original titles are ``ORIGINAL_SERIES``, ``ORIGINAL_FILM``, and
    ``CO_PRODUCTION``; the sole Library_Filler classification is
    ``LICENSED_LIBRARY``.
    """

    ORIGINAL_SERIES = "ORIGINAL_SERIES"
    ORIGINAL_FILM = "ORIGINAL_FILM"
    LICENSED_LIBRARY = "LICENSED_LIBRARY"
    CO_PRODUCTION = "CO_PRODUCTION"


class CPVHComputationError(ValueError):
    """Raised when CPVH cannot be computed because viewing hours are not positive.

    The CPVH formula divides cost by projected viewing hours, so a value of zero
    (or negative) has no defined result (R4.5). Callers are expected to detect
    the zero-viewing-hours case and mark the CPVH check failed rather than relying
    on this exception for control flow, but the guard exists to make misuse loud.
    """


# Round to four decimal places (R4.1). HALF_UP gives predictable monetary rounding.
CPVH_QUANTUM: Decimal = Decimal("0.0001")

# Applicable ceilings in United States dollars (R4.2, R4.3).
PREMIUM_ORIGINAL_CEILING: Decimal = Decimal("0.18")
LIBRARY_FILLER_CEILING: Decimal = Decimal("0.05")

# Classification groupings for ceiling selection.
_PREMIUM_ORIGINAL_TYPES: frozenset[AssetType] = frozenset(
    {AssetType.ORIGINAL_SERIES, AssetType.ORIGINAL_FILM, AssetType.CO_PRODUCTION}
)
_LIBRARY_FILLER_TYPES: frozenset[AssetType] = frozenset({AssetType.LICENSED_LIBRARY})


def compute_cpvh(cost_usd: Decimal, viewing_hours: Decimal) -> Decimal:
    """Compute Cost-Per-Viewing-Hour, rounded to four decimal places (R4.1).

    CPVH is ``cost_usd / viewing_hours``. ``viewing_hours`` must be strictly
    positive; the zero case is the caller's responsibility (R4.5) and raises
    :class:`CPVHComputationError` here as a precondition guard.

    Args:
        cost_usd: The normalized acquisition cost or budget in USD.
        viewing_hours: Projected viewing hours; must be greater than zero.

    Returns:
        The CPVH as a :class:`~decimal.Decimal` quantized to four decimal places.

    Raises:
        CPVHComputationError: If ``viewing_hours`` is less than or equal to zero.
    """
    if viewing_hours <= 0:
        raise CPVHComputationError(
            "CPVH cannot be computed when projected viewing hours are not positive "
            f"(got {viewing_hours}); the caller must handle the zero case (R4.5)."
        )

    return (cost_usd / viewing_hours).quantize(CPVH_QUANTUM, rounding=ROUND_HALF_UP)


def cpvh_ceiling(asset_type: AssetType) -> Decimal | None:
    """Return the applicable CPVH ceiling for an asset classification.

    * Premium_Original (``ORIGINAL_SERIES``, ``ORIGINAL_FILM``, ``CO_PRODUCTION``)
      -> ``Decimal('0.18')`` (R4.2).
    * Library_Filler (``LICENSED_LIBRARY``) -> ``Decimal('0.05')`` (R4.3).
    * Any value matching no classification -> ``None`` (R4.4).

    Args:
        asset_type: The title's asset classification.

    Returns:
        The ceiling in USD, or ``None`` when no classification applies. A ``None``
        result signals that the CPVH check should be marked failed with a
        no-applicable-ceiling error (R4.4).
    """
    if asset_type in _PREMIUM_ORIGINAL_TYPES:
        return PREMIUM_ORIGINAL_CEILING
    if asset_type in _LIBRARY_FILLER_TYPES:
        return LIBRARY_FILLER_CEILING
    return None


def cpvh_breaches(cpvh: Decimal, ceiling: Decimal) -> bool:
    """Return ``True`` when the computed CPVH breaches the ceiling (R4.6).

    A breach occurs if and only if the CPVH is strictly greater than the ceiling.
    At or below the ceiling the check passes (R4.7).
    """
    return cpvh > ceiling


def cpvh_passes(cpvh: Decimal, ceiling: Decimal) -> bool:
    """Return ``True`` when the computed CPVH passes the ceiling (R4.7).

    The CPVH check passes if and only if the CPVH is less than or equal to the
    ceiling -- the exact complement of :func:`cpvh_breaches`.
    """
    return cpvh <= ceiling
