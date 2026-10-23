"""Pure domain module for the Lineage_Decay driver (Driver B).

Driver B adds a franchise floor and a churn retention credit derived from a
parent title's performance. This module is the pure-math half:

- ``Franchise_Floor`` -- a one-sided HOUR-SPACE value returned for the Stage-7
  ``max`` of the normative Attribution_Order. It is **not** applied here; the
  assembler (task 5) computes ``H7 = max(H6, Franchise_Floor)`` and attributes
  the lift to its own ``franchise_floor`` breakdown line:

      Franchise_Floor = parent_title_viewing_hours
                        * (alpha_base_decay + beta_comp * parent_completion_rate)

- ``delta_C_franchise`` -- an additive churn-retention credit in percentage
  points, clamped to the inclusive ``[0.15, 0.45]`` band:

      delta_C_franchise = clamp(gamma_base + delta_order * loyalty_signal,
                                0.15, 0.45)
      loyalty_signal    = min(franchise_order - 1, 6)

  It is non-decreasing in ``franchise_order`` (2nd entry +0.20, 3rd +0.25, ...)
  and saturates at the +0.45% ceiling by the 7th entry. The churn module (task 9)
  adds it as a ``franchise_loyalty_credit`` contribution **before** the
  ``[0.10, 5.00]`` clamp and the 1.5 hurdle classification.

- the sequel-with-missing-parent **0.70-retention fallback**: when the title is
  a franchise entry with ``franchise_order > 1`` but the parent hours or
  completion rate are absent / non-finite, a genre-baseline hours value is used
  with an assumed ``parent_completion_rate = 0.70``, recorded in
  ``assumed_features``.

- the non-franchise path: ``is_franchise = false`` or ``franchise_order = 1``
  yields a zero floor and zero credit, leaving the base prediction unchanged.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``) and it imports only the
Python standard library. Inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

__all__ = [
    "DECIMAL_CONTEXT_PRECISION",
    "SOURCE_DETERMINISTIC_FALLBACK",
    "SOURCE_MODEL_VERSION",
    "DELTA_C_MIN",
    "DELTA_C_MAX",
    "LOYALTY_SIGNAL_CAP",
    "ASSUMED_PARENT_COMPLETION_RATE",
    "DEFAULT_LINEAGE_PARAMS",
    "LineageParams",
    "LineageFeatures",
    "LineageResult",
    "coerce_decimal",
    "parse_params",
    "calculate_lineage",
]

DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

SOURCE_DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
SOURCE_MODEL_VERSION = "MODEL_VERSION"

# The inclusive churn-credit band (percentage points, R2.4).
DELTA_C_MIN = Decimal("0.15")
DELTA_C_MAX = Decimal("0.45")

# loyalty_signal = min(franchise_order - 1, cap); capped so the credit saturates.
LOYALTY_SIGNAL_CAP = 6

# Completion rate assumed for a sequel whose parent data is missing (R2.3).
ASSUMED_PARENT_COMPLETION_RATE = Decimal("0.70")

# parent_completion_rate domain [0.00, 1.00].
_RATE_MIN = Decimal("0.00")
_RATE_MAX = Decimal("1.00")


@dataclass(frozen=True)
class LineageParams:
    """DETERMINISTIC_FALLBACK Illustrative_Coefficients for the lineage driver.

    ``alpha_base_decay`` / ``beta_comp`` parameterize the Franchise_Floor; both
    are non-negative. ``gamma_base`` is the floor of the churn-credit band (the
    minimum credit any franchise entry earns) and ``delta_order`` is the credit
    per franchise position above the original; both non-negative.
    ``loyalty_cap`` caps the loyalty signal so the credit saturates.
    """

    alpha_base_decay: Decimal
    beta_comp: Decimal
    gamma_base: Decimal
    delta_order: Decimal
    loyalty_cap: int = LOYALTY_SIGNAL_CAP


@dataclass(frozen=True)
class LineageFeatures:
    """A title's franchise lineage features.

    ``franchise_order`` is 1 for the original. ``parent_title_viewing_hours`` is
    the parent's 90-day projected hours; ``parent_completion_rate`` is in
    ``[0.00, 1.00]``. Either parent field may be ``None`` (triggers the
    0.70-retention fallback on a sequel). ``genre_baseline_viewing_hours`` is the
    title's own genre-baseline hours used by that fallback when the parent hours
    are absent.
    """

    is_franchise: bool
    franchise_order: int
    parent_title_viewing_hours: Decimal | None = None
    parent_completion_rate: Decimal | None = None
    genre_baseline_viewing_hours: Decimal | None = None


@dataclass(frozen=True)
class LineageResult:
    """The resolved lineage floor and churn credit plus provenance metadata.

    ``franchise_floor`` is the one-sided hour-space value for the Stage-7 ``max``
    (``Decimal("0")`` when inactive / unresolvable). ``delta_c_franchise`` is the
    additive churn credit in pct points (``Decimal("0.00")`` when non-franchise).
    ``assumed_features`` records the 0.70-retention fallback when it fires.
    """

    franchise_floor: Decimal
    delta_c_franchise: Decimal
    is_active: bool
    source_tier: str
    assumed_features: tuple[str, ...] = ()


DEFAULT_LINEAGE_PARAMS = LineageParams(
    alpha_base_decay=Decimal("0.55"),
    beta_comp=Decimal("0.35"),
    gamma_base=Decimal("0.15"),
    delta_order=Decimal("0.05"),
    loyalty_cap=LOYALTY_SIGNAL_CAP,
)


def coerce_decimal(raw: object) -> Decimal | None:
    """Coerce a raw value to a finite :class:`Decimal`, else ``None`` (never raises)."""
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


def _coerce_nonneg(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite NON-NEGATIVE Decimal, else ``None``."""
    value = coerce_decimal(raw)
    if value is None or value < 0:
        return None
    return value


def _coerce_positive_int(raw: object) -> int | None:
    """Coerce a raw param to a strictly positive ``int``, else ``None``."""
    if isinstance(raw, bool):
        return None
    value = coerce_decimal(raw)
    if value is None or value != value.to_integral_value():
        return None
    as_int = int(value)
    return as_int if as_int > 0 else None


def parse_params(raw: Mapping | None) -> tuple[LineageParams, str]:
    """Parse a ``lineage`` mapping into (:class:`LineageParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_LINEAGE_PARAMS, "DETERMINISTIC_FALLBACK")``. A valid parse requires
    finite non-negative ``alpha_base_decay`` / ``beta_comp`` / ``gamma_base`` /
    ``delta_order``; ``loyalty_cap`` is optional (absent -> built-in cap) and when
    present must be a strictly positive integer. Mirrors the churn full-fallback
    contract: never raises; any invalid / missing field collapses the whole block
    to the illustrative defaults.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_LINEAGE_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    alpha = _coerce_nonneg(raw.get("alpha_base_decay"))
    beta = _coerce_nonneg(raw.get("beta_comp"))
    gamma = _coerce_nonneg(raw.get("gamma_base"))
    delta = _coerce_nonneg(raw.get("delta_order"))

    if any(v is None for v in (alpha, beta, gamma, delta)):
        return DEFAULT_LINEAGE_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    if "loyalty_cap" in raw:
        loyalty_cap = _coerce_positive_int(raw.get("loyalty_cap"))
        if loyalty_cap is None:
            return DEFAULT_LINEAGE_PARAMS, SOURCE_DETERMINISTIC_FALLBACK
    else:
        loyalty_cap = LOYALTY_SIGNAL_CAP

    params = LineageParams(
        alpha_base_decay=alpha,  # type: ignore[arg-type]
        beta_comp=beta,  # type: ignore[arg-type]
        gamma_base=gamma,  # type: ignore[arg-type]
        delta_order=delta,  # type: ignore[arg-type]
        loyalty_cap=loyalty_cap,
    )
    return params, SOURCE_MODEL_VERSION


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def calculate_lineage(
    features: LineageFeatures,
    params: LineageParams,
    params_source: str = SOURCE_DETERMINISTIC_FALLBACK,
) -> LineageResult:
    """Compute the Franchise_Floor and ``delta_C_franchise`` from ``features`` (R2.1-R2.6).

    A non-franchise entry (``is_franchise = false`` or ``franchise_order <= 1``)
    yields a zero floor, zero credit, and ``is_active = False`` (R2.5). For an
    active franchise entry:

    - ``delta_C_franchise = clamp(gamma_base + delta_order * min(order-1, cap),
      0.15, 0.45)`` pct points (R2.4).
    - ``Franchise_Floor = parent_hours * (alpha_base_decay + beta_comp * rate)``
      (R2.2). ``parent_completion_rate`` is clamped to ``[0, 1]``. When the parent
      hours or rate are absent / non-finite on a sequel, the genre-baseline hours
      and an assumed ``rate = 0.70`` are used and ``assumed_features`` records the
      fallback (R2.3). When no hours source is resolvable, the floor is ``0``
      (one-sided ``max`` with a zero floor is a no-op).

    Pure ``Decimal``; inputs unmodified; never raises.
    """
    if not features.is_franchise or features.franchise_order <= 1:
        return LineageResult(
            franchise_floor=Decimal("0"),
            delta_c_franchise=Decimal("0.00"),
            is_active=False,
            source_tier=params_source,
            assumed_features=(),
        )

    assumed: list[str] = []

    with localcontext(_CTX):
        loyalty_signal = min(features.franchise_order - 1, params.loyalty_cap)
        delta_c = _clamp(
            params.gamma_base + params.delta_order * Decimal(loyalty_signal),
            DELTA_C_MIN,
            DELTA_C_MAX,
        )

        # Resolve the parent hours and completion rate, with the 0.70 fallback.
        parent_hours = features.parent_title_viewing_hours
        parent_rate = features.parent_completion_rate

        hours_ok = parent_hours is not None and parent_hours.is_finite()
        rate_ok = parent_rate is not None and parent_rate.is_finite()

        if not hours_ok or not rate_ok:
            # Sequel with missing parent data -> 0.70-retention fallback (R2.3).
            if not hours_ok:
                parent_hours = features.genre_baseline_viewing_hours
            if not rate_ok:
                parent_rate = ASSUMED_PARENT_COMPLETION_RATE
            assumed.append("parent_completion_rate")

        if parent_hours is None or not parent_hours.is_finite():
            # No hours source resolvable -> zero floor (no-op one-sided max).
            franchise_floor = Decimal("0")
        else:
            rate_clamped = _clamp(parent_rate, _RATE_MIN, _RATE_MAX)  # type: ignore[arg-type]
            decay = params.alpha_base_decay + params.beta_comp * rate_clamped
            franchise_floor = parent_hours * decay
            if franchise_floor < 0:
                franchise_floor = Decimal("0")

    return LineageResult(
        franchise_floor=franchise_floor,
        delta_c_franchise=delta_c,
        is_active=True,
        source_tier=params_source,
        assumed_features=tuple(assumed),
    )
