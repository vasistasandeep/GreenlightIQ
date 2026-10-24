"""Pure domain module for Driver_Input_Capture (the write side of the drivers).

This module is the single shared validation + mapping core used by the Asset
Studio quick-evaluate path (``app.api.quick_evaluate``) and the batch ingest path
(``app.engines.ingestion``) to turn a loose mapping of user-supplied driver facts
into the exact, provider-expected ``source_snapshot`` shape the flag-gated
``AdvancedDriversValuationInputProvider`` already reads. No provider or engine
change is needed: the twelve snapshot keys are the complete integration seam.

It mirrors the ``momentum.py`` / ``lineage.py`` / ``macro_modifiers.py`` style:
frozen constants, ``coerce_*`` helpers that never raise, pure ``Decimal``
arithmetic under a fixed :class:`decimal.Context`, and no I/O.

Twelve driver facts (exact snapshot keys), with the write-side validation and the
provider-expected JSON serialization type (R5.1-R5.7, R6.1):

===============================  ============  =========================  ==================
Snapshot key                     Input         Validation (R5)            Serialized type
===============================  ============  =========================  ==================
``is_franchise``                 bool          --                         native bool
``franchise_order``              int           integer >= 1 (R5.2)        native int
``parent_title_viewing_hours``   decimal       finite, >= 0 (R5.6)        string ``"6000.00"``
``parent_completion_rate``       decimal       finite, in [0, 1] (R5.3)   string ``"0.80"``
``production_stage``             enum          in Production_Stage (R5.1) native string
``v_trailer``                    decimal       finite, >= 0 (R5.6)        string
``e_ratio``                      decimal       finite, >= 0 (R5.6)        string
``s_velocity``                   decimal       finite, >= 0 (R5.6)        string
``source_ip_provenance``         enum          in IP set (R5.1)           native string
``release_window``               enum          in window set (R5.1)       native string
``release_month``                int | null    in 1..12, absent -> null   native int (omit on null)
``vernacular_track_count``       int           integer >= 1 (R5.4)        native int
===============================  ============  =========================  ==================

Lineage parent fields (``franchise_order``, ``parent_title_viewing_hours``,
``parent_completion_rate``) are considered only when ``is_franchise`` is true; an
unset / false ``is_franchise`` omits them without error (R1.6).

The Buzz_Level mapping constant :data:`BUZZ_LEVEL_SIGNALS` expands the friendly
Asset Studio {LOW, MEDIUM, HIGH} control into the three raw momentum signals; the
arithmetic is verified against the real ``momentum.DEFAULT_MOMENTUM_PARAMS`` (see
the design's "Buzz_Level mapping constant" section): LOW -> multiplier 1.00,
MEDIUM -> 1.1850, HIGH -> 1.4450 at a non-excluded stage.

This module is pure: no I/O, no database access, no async, no global mutable
state. All decimal arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``). Inputs are never
mutated; coercion never raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from app.domain.momentum import Production_Stage

__all__ = [
    "DECIMAL_CONTEXT_PRECISION",
    "SOURCE_IP_PROVENANCE_SET",
    "RELEASE_WINDOW_SET",
    "RELEASE_MONTH_MIN",
    "RELEASE_MONTH_MAX",
    "COMPLETION_RATE_MIN",
    "COMPLETION_RATE_MAX",
    "DRIVER_FACT_KEYS",
    "BuzzLevel",
    "BuzzSignals",
    "BUZZ_LEVEL_SIGNALS",
    "FieldError",
    "coerce_decimal",
    "coerce_int",
    "build_driver_facts",
]

DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

# ---------------------------------------------------------------------------
# Canonical enum domains (mirror the provider's / macro module's expectations).
# ---------------------------------------------------------------------------

#: Source-IP provenance members accepted on the macro driver (R1.3, R5.1).
SOURCE_IP_PROVENANCE_SET: frozenset[str] = frozenset(
    {
        "ORIGINAL_SCREENPLAY",
        "BESTSELLER_BOOK",
        "TRUE_CRIME_IP",
        "WEBTOON_MANGA",
        "PUBLIC_DOMAIN",
    }
)

#: Release-window members accepted on the macro driver (R1.4, R5.1).
RELEASE_WINDOW_SET: frozenset[str] = frozenset(
    {
        "DIRECT_TO_STREAMING",
        "DAY_AND_DATE",
        "THEATRICAL_30D",
        "THEATRICAL_60D_PLUS",
    }
)

# Inclusive validation bounds (R5.3, R5.5).
RELEASE_MONTH_MIN = 1
RELEASE_MONTH_MAX = 12
COMPLETION_RATE_MIN = Decimal("0")
COMPLETION_RATE_MAX = Decimal("1")

#: The twelve driver-fact snapshot keys, in canonical order (R6.1).
DRIVER_FACT_KEYS: tuple[str, ...] = (
    "is_franchise",
    "franchise_order",
    "parent_title_viewing_hours",
    "parent_completion_rate",
    "production_stage",
    "v_trailer",
    "e_ratio",
    "s_velocity",
    "source_ip_provenance",
    "release_window",
    "release_month",
    "vernacular_track_count",
)

# ---------------------------------------------------------------------------
# Buzz_Level mapping (R2.3) -- verified arithmetic (see module docstring).
# ---------------------------------------------------------------------------

BuzzLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True)
class BuzzSignals:
    """The three raw momentum signals a Buzz_Level expands to (all Decimal)."""

    v_trailer: Decimal
    e_ratio: Decimal
    s_velocity: Decimal


#: The single documented Buzz_Level -> raw-signals mapping the Asset Studio path
#: uses (R2.3). Verified against ``momentum.DEFAULT_MOMENTUM_PARAMS``:
#: LOW -> 1.00, MEDIUM -> 1.1850, HIGH -> 1.4450 (multiplier, non-excluded stage).
BUZZ_LEVEL_SIGNALS: dict[str, BuzzSignals] = {
    "LOW": BuzzSignals(Decimal("0.50"), Decimal("0.02"), Decimal("0.50")),
    "MEDIUM": BuzzSignals(Decimal("1.00"), Decimal("0.05"), Decimal("1.10")),
    "HIGH": BuzzSignals(Decimal("2.00"), Decimal("0.10"), Decimal("1.50")),
}

# ---------------------------------------------------------------------------
# Validation error surface.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldError:
    """A per-field validation failure: the offending field and the reason.

    Converted to the batch path's ``RejectionDetail{row_index, field, reason}``
    and surfaced as the Asset Studio 422 detail (R3.5, R5.1-R5.6).
    """

    field: str
    reason: str


# ---------------------------------------------------------------------------
# Coercion helpers (never raise; mirror the sibling driver modules).
# ---------------------------------------------------------------------------


def coerce_decimal(raw: object) -> Decimal | None:
    """Coerce a raw value to a finite :class:`Decimal`, else ``None`` (never raises).

    Booleans are rejected (``True``/``False`` are not numeric facts). Blank /
    whitespace-only strings and non-finite values return ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        return raw if raw.is_finite() else None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
        return value if value.is_finite() else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        return value if value.is_finite() else None
    return None


def coerce_int(raw: object) -> int | None:
    """Coerce a raw value to an ``int`` only when it is integral, else ``None``.

    Booleans are rejected. A Decimal / numeric string with a fractional part
    (e.g. ``1.5``) is NOT integral and returns ``None`` so it is reported as
    non-integer rather than silently truncated (R5.2, R5.4).
    """
    if isinstance(raw, bool):
        return None
    value = coerce_decimal(raw)
    if value is None or value != value.to_integral_value():
        return None
    return int(value)


def _is_blank(raw: object) -> bool:
    """A value that should be treated as absent: ``None`` or a blank string."""
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    return False


def _normalize_enum(raw: object) -> str | None:
    """Trim + uppercase an enum-text value to its lookup key, else ``None``."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().upper()
    return text or None


def _serialize_decimal(value: Decimal) -> str:
    """Serialize a finite Decimal to its canonical string under the fixed context."""
    with localcontext(_CTX):
        # +value applies the context (normalizes to a plain, finite string form)
        # without altering the mathematical value; JSONB stores it as a string.
        return format(+value, "f")


# ---------------------------------------------------------------------------
# The fact-dict builder -- the heart of the feature.
# ---------------------------------------------------------------------------


def build_driver_facts(raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[FieldError]]:
    """Validate + coerce a loose mapping of candidate facts into the snapshot shape.

    For each of the twelve driver keys this (1) skips the key entirely when the
    input is absent / blank (omitted, never written as a neutral literal --
    R1.5, R2.5, R3.4), (2) validates against the documented bound, appending a
    :class:`FieldError` naming the field and the violated bound on failure
    (R5.1-R5.6), and (3) on success emits the value in the provider-expected JSON
    type per the serialization table (R5.7): decimal facts as strings, booleans /
    integers native, enum facts as their literal uppercase string.

    Lineage parent fields are considered only when ``is_franchise`` is truthy; an
    unset / false ``is_franchise`` omits them without error (R1.6).

    Returns ``(facts, errors)``. ``facts`` holds only the successfully validated
    keys; a key with a :class:`FieldError` is never present in ``facts``. The
    function is pure and never raises.
    """
    facts: dict[str, Any] = {}
    errors: list[FieldError] = []

    # --- Lineage (Driver B) -------------------------------------------------
    is_franchise_raw = raw.get("is_franchise")
    is_franchise = False
    if not _is_blank(is_franchise_raw):
        is_franchise = bool(is_franchise_raw)
        facts["is_franchise"] = is_franchise

    # Parent fields only matter when the title is a franchise entry (R1.6).
    if is_franchise:
        order_raw = raw.get("franchise_order")
        if not _is_blank(order_raw):
            order = coerce_int(order_raw)
            if order is None or order < 1:
                errors.append(
                    FieldError(
                        "franchise_order",
                        "franchise_order must be an integer greater than or equal to 1",
                    )
                )
            else:
                facts["franchise_order"] = order

        hours_raw = raw.get("parent_title_viewing_hours")
        if not _is_blank(hours_raw):
            hours = coerce_decimal(hours_raw)
            if hours is None or hours < 0:
                errors.append(
                    FieldError(
                        "parent_title_viewing_hours",
                        "parent_title_viewing_hours must be finite and non-negative",
                    )
                )
            else:
                facts["parent_title_viewing_hours"] = _serialize_decimal(hours)

        rate_raw = raw.get("parent_completion_rate")
        if not _is_blank(rate_raw):
            rate = coerce_decimal(rate_raw)
            if (
                rate is None
                or rate < COMPLETION_RATE_MIN
                or rate > COMPLETION_RATE_MAX
            ):
                errors.append(
                    FieldError(
                        "parent_completion_rate",
                        "parent_completion_rate must be within the inclusive range [0, 1]",
                    )
                )
            else:
                facts["parent_completion_rate"] = _serialize_decimal(rate)

    # --- Momentum (Driver C) ------------------------------------------------
    stage_raw = raw.get("production_stage")
    if not _is_blank(stage_raw):
        stage_key = _normalize_enum(stage_raw)
        if stage_key is None or stage_key not in Production_Stage.__members__:
            errors.append(
                FieldError(
                    "production_stage",
                    "production_stage must be one of "
                    f"{sorted(Production_Stage.__members__)}",
                )
            )
        else:
            facts["production_stage"] = Production_Stage(stage_key).value

    for signal in ("v_trailer", "e_ratio", "s_velocity"):
        signal_raw = raw.get(signal)
        if _is_blank(signal_raw):
            continue
        value = coerce_decimal(signal_raw)
        if value is None or value < 0:
            errors.append(
                FieldError(signal, f"{signal} must be finite and non-negative")
            )
        else:
            facts[signal] = _serialize_decimal(value)

    # --- Macro (Driver D) ---------------------------------------------------
    ip_raw = raw.get("source_ip_provenance")
    if not _is_blank(ip_raw):
        ip_key = _normalize_enum(ip_raw)
        if ip_key is None or ip_key not in SOURCE_IP_PROVENANCE_SET:
            errors.append(
                FieldError(
                    "source_ip_provenance",
                    "source_ip_provenance must be one of "
                    f"{sorted(SOURCE_IP_PROVENANCE_SET)}",
                )
            )
        else:
            facts["source_ip_provenance"] = ip_key

    window_raw = raw.get("release_window")
    if not _is_blank(window_raw):
        window_key = _normalize_enum(window_raw)
        if window_key is None or window_key not in RELEASE_WINDOW_SET:
            errors.append(
                FieldError(
                    "release_window",
                    "release_window must be one of " f"{sorted(RELEASE_WINDOW_SET)}",
                )
            )
        else:
            facts["release_window"] = window_key

    month_raw = raw.get("release_month")
    if not _is_blank(month_raw):
        month = coerce_int(month_raw)
        if month is None or month < RELEASE_MONTH_MIN or month > RELEASE_MONTH_MAX:
            errors.append(
                FieldError(
                    "release_month",
                    "release_month must be within the inclusive range 1..12",
                )
            )
        else:
            facts["release_month"] = month

    count_raw = raw.get("vernacular_track_count")
    if not _is_blank(count_raw):
        count = coerce_int(count_raw)
        if count is None or count < 1:
            errors.append(
                FieldError(
                    "vernacular_track_count",
                    "vernacular_track_count must be an integer greater than or equal to 1",
                )
            )
        else:
            facts["vernacular_track_count"] = count

    return facts, errors
