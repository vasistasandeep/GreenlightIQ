"""Pure domain helpers for Asset Studio metadata-radar derivations.

This module is intentionally free of any I/O, database access, or framework
dependencies (stdlib + :mod:`decimal` only), so it can be imported without the
app framework and exercised directly by unit tests.

It currently holds a single shared derivation, :func:`derive_production_scale`,
which was previously inlined in ``app/api/quick_evaluate.py``'s
``_metadata_profile``. Extracting it removes the duplication between the
metadata radar's production-scale axis and the churn model's production-scale
feature, guaranteeing the explained input equals the displayed input.

The derivation reproduces the former inline formula bit-for-bit, including the
same quantization: a plain ``Decimal.quantize(Decimal("0.1"))`` using the
default decimal-context rounding (ROUND_HALF_EVEN). Preserving that exact
rounding keeps the radar's ``production_scale`` value byte-for-byte identical to
before the extraction -- the point of the extraction is deduplication, not a
behavior change.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["derive_production_scale"]


def derive_production_scale(pedigree: Decimal, synopsis: str) -> Decimal:
    """Derive the 0-10 production-scale radar axis from pedigree and synopsis.

    Formula (reproduced exactly from the former inline derivation)::

        synopsis_rich = min(10, len(synopsis) / 25)
        production    = min(10, (pedigree + synopsis_rich) / 2)
        result        = production.quantize(Decimal("0.1"))

    The quantization uses a plain ``Decimal.quantize(Decimal("0.1"))`` with the
    default decimal-context rounding (ROUND_HALF_EVEN), matching the existing
    behavior so the radar value does not change.

    :param pedigree: the talent-pedigree score as a :class:`~decimal.Decimal`
        (callers default a blank pedigree to ``Decimal("5")`` before calling).
    :param synopsis: the title synopsis; only its character length is used.
    :returns: the production-scale value quantized to one decimal place.
    """
    synopsis_rich = min(Decimal("10"), Decimal(len(synopsis)) / Decimal("25"))
    production = min(Decimal("10"), (pedigree + synopsis_rich) / Decimal("2"))
    return production.quantize(Decimal("0.1"))
