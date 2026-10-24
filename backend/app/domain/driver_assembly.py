"""Combined log-space assembler for the advanced content-eval drivers.

This module is the single composition point for the normative seven-stage
Attribution_Order (R5.1, R5.2, R5.4, as amended by the R5 erratum). The four
pure driver modules compute their pieces in isolation:

- :mod:`app.domain.comps` (Driver A) -> the empirical anchor ``H_comps``,
- :mod:`app.domain.viewing_hours` betas (the additive log-space feature terms),
- :mod:`app.domain.momentum` (Driver C) -> ``M_momentum``,
- :mod:`app.domain.macro_modifiers` (Driver D) -> ``M_window`` / ``M_ip`` /
  ``M_vernacular`` / ``M_calendar``,
- :mod:`app.domain.lineage` (Driver B) -> the hour-space ``Franchise_Floor``.

``assemble_drivers`` threads them through the one normative order. Stages 0-6
are log-space (``y_log``); Stage 7 is a one-sided hour-space ``max`` applied
after re-exponentiation::

    Stage 0  anchor      : H0  = H_comps
    Stage 1  additive bi : H1  = exp(ln(1 + H0) + L) - 1,  L = sum_i(beta_i * x_i)
                           per-feature hours_i = (beta_i*x_i / L) * (H1 - H0)   # Option B, L > 0
    Stage 2  M_momentum  : H2  = exp(ln(1 + H1) + ln(M_momentum)) - 1 ; d_mom  = H2 - H1
    Stage 3  M_window    : H3  = exp(ln(1 + H2) + ln(M_window)) - 1    ; d_win  = H3 - H2
    Stage 4  M_ip        : H4  = exp(ln(1 + H3) + ln(M_ip)) - 1        ; d_ip   = H4 - H3
    Stage 5  M_vernacular: H5  = exp(ln(1 + H4) + ln(M_vern)) - 1      ; d_vern = H5 - H4
    Stage 6  M_calendar  : H6  = exp(ln(1 + H5) + ln(M_cal)) - 1       ; d_cal  = H6 - H5
    Stage 7  franchise   : H7  = max(H6, Franchise_Floor)              ; d_floor = H7 - H6 >= 0

``H7 == H_hat`` by construction (the final prediction is post-floor). Because
``Decimal`` ``exp``/``ln`` do not commute bitwise under reordering, the
multiplicative order is fixed; Stage 7 is a one-sided clamp that can only raise
the prediction, applied last so the floor is enforced against the fully
assembled hours.

Each stage's hour-delta is attributed by sequential re-exponentiation
(``exp(partial_y) - 1``), quantized to whole hours, and emitted as its own
breakdown line (``comps_anchor``, one line per active feature, ``momentum``,
``release_window_halo``, ``source_ip_provenance``, ``vernacular_tam``,
``calendar_seasonality``, ``franchise_floor``). The ``comps_anchor`` line
strictly equals ``H_comps`` (R5.3) and the Stage-7 floor lift is isolated in
its own ``franchise_floor`` line -- neither is ever the residual sink. The
single trailing ``rounding_or_bounds_adjustment`` line is computed last as
``H_hat_quantized - sum(all prior quantized lines)`` so it carries only the
whole-hour quantization residual, exactly as the standalone
:mod:`app.domain.viewing_hours` model does.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under the same fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``) the sibling modules
use, so results are byte-identical across platforms, and it imports only the
Python standard library. Inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

__all__ = [
    "DECIMAL_CONTEXT_PRECISION",
    "VIEWING_HOURS_QUANTUM",
    "KEY_COMPS_ANCHOR",
    "KEY_MOMENTUM",
    "KEY_RELEASE_WINDOW_HALO",
    "KEY_SOURCE_IP_PROVENANCE",
    "KEY_VERNACULAR_TAM",
    "KEY_CALENDAR_SEASONALITY",
    "KEY_FRANCHISE_FLOOR",
    "KEY_ADJUSTMENT",
    "NEUTRAL_MULTIPLIER",
    "FeatureTerm",
    "AssemblyLine",
    "AssemblyResult",
    "assemble_drivers",
]

# Mirror the sibling modules' fixed Decimal context so exp()/ln() are
# deterministic across platforms (no float, no BLAS, no env dependence).
DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

# Viewing hours quantize to whole hours, exactly as viewing_hours.py does; the
# single adjustment line absorbs the per-line quantization residual so the sum
# is exact.
VIEWING_HOURS_QUANTUM = Decimal("1")

_ONE = Decimal("1")
_ZERO = Decimal("0")

# The neutral (no-lift) multiplier. A multiplier at 1.00 contributes ln(1) = 0
# to y_log and so a 0-hour line, keeping the flag-off / excluded path inert.
NEUTRAL_MULTIPLIER = Decimal("1.00")

# Canonical breakdown-line keys for the normative order.
KEY_COMPS_ANCHOR = "comps_anchor"
KEY_MOMENTUM = "momentum"
KEY_RELEASE_WINDOW_HALO = "release_window_halo"
KEY_SOURCE_IP_PROVENANCE = "source_ip_provenance"
KEY_VERNACULAR_TAM = "vernacular_tam"
KEY_CALENDAR_SEASONALITY = "calendar_seasonality"
KEY_FRANCHISE_FLOOR = "franchise_floor"
KEY_ADJUSTMENT = "rounding_or_bounds_adjustment"


@dataclass(frozen=True)
class FeatureTerm:
    """A single additive log-space feature term ``beta_i * x_i`` (Stage 1).

    ``key`` / ``label`` identify the feature on the breakdown; ``x`` is the
    (clamped) numeric feature value and ``coefficient`` the non-negative
    log-space ``beta_i``. ``term`` is ``beta_i * x_i`` (the log-lift contribution
    that goes into ``L``). A term with a zero (or negative) coefficient or value
    contributes nothing to ``L`` and allocates 0 hours.
    """

    key: str
    label: str
    x: Decimal
    coefficient: Decimal
    term: Decimal


@dataclass(frozen=True)
class AssemblyLine:
    """A single quantized line in the combined hour-space breakdown.

    ``hours`` is the whole-hour contribution. ``input`` / ``coefficient`` carry
    the per-feature value / beta for Stage-1 lines (``None`` for the anchor, the
    multiplicative stages, the floor, and the residual). ``multiplier`` carries
    the stage multiplier for the Stage 2-6 lines (``None`` otherwise).
    """

    key: str
    label: str
    hours: Decimal
    input: Decimal | None = None
    coefficient: Decimal | None = None
    multiplier: Decimal | None = None


@dataclass(frozen=True)
class AssemblyResult:
    """The assembled prediction plus the conserving hour-space breakdown.

    ``viewing_hours`` is the quantized post-floor prediction ``H7 == H_hat``.
    ``breakdown`` is the ordered tuple of lines (anchor, features, the five
    multiplicative stages, franchise floor, then the single residual line when
    non-zero). ``unclamped`` is the pre-quantization ``H7``. ``running_hours``
    exposes the intermediate ``H0..H7`` for auditability / tests.
    """

    viewing_hours: Decimal
    breakdown: tuple[AssemblyLine, ...]
    unclamped: Decimal
    running_hours: tuple[Decimal, ...]


def _quantize(value: Decimal) -> Decimal:
    """Quantize to whole viewing hours using half-up rounding."""
    return value.quantize(VIEWING_HOURS_QUANTUM, rounding=ROUND_HALF_UP)


def _clamp_floor_zero(value: Decimal) -> Decimal:
    """Floor a raw hour value at 0 (hours can never be negative)."""
    return value if value > _ZERO else _ZERO


def _hours_from_logsum(log_sum: Decimal) -> Decimal:
    """``exp(log_sum) - 1`` floored at 0, under the fixed context."""
    return _clamp_floor_zero(log_sum.exp() - _ONE)


def _ln_multiplier(multiplier: Decimal | None) -> Decimal:
    """``ln(multiplier)`` under the fixed context; a neutral / non-positive multiplier -> 0."""
    if multiplier is None or not multiplier.is_finite() or multiplier <= _ZERO:
        return _ZERO
    if multiplier == NEUTRAL_MULTIPLIER or multiplier == _ONE:
        return _ZERO
    return multiplier.ln()


def assemble_drivers(
    h_comps: Decimal,
    feature_terms: Sequence[FeatureTerm],
    *,
    m_momentum: Decimal = NEUTRAL_MULTIPLIER,
    m_window: Decimal = NEUTRAL_MULTIPLIER,
    m_ip: Decimal = NEUTRAL_MULTIPLIER,
    m_vernacular: Decimal = NEUTRAL_MULTIPLIER,
    m_calendar: Decimal = NEUTRAL_MULTIPLIER,
    franchise_floor: Decimal = _ZERO,
) -> AssemblyResult:
    """Assemble the combined prediction over the normative seven-stage order.

    ``h_comps`` is the Stage-0 anchor (``H0``); when Driver A is off the caller
    passes the ``viewing_hours.py`` intercept base (``exp(intercept) - 1``) here
    instead. ``feature_terms`` are the Stage-1 additive log-space terms (Option-B
    allocated). ``m_momentum`` / ``m_window`` / ``m_ip`` / ``m_vernacular`` /
    ``m_calendar`` are the Stage 2-6 multipliers (each ``1.00`` when its driver
    is off / neutral, contributing a 0-hour line). ``franchise_floor`` is the
    Stage-7 hour-space floor (``0`` when Driver B is inactive, a no-op ``max``).

    Every stage's whole-hour delta is emitted as its own breakdown line; the
    ``comps_anchor`` line strictly equals ``quantize(H_comps)`` and the Stage-7
    lift is isolated in ``franchise_floor``. The single trailing
    ``rounding_or_bounds_adjustment`` line carries only the whole-hour
    quantization residual so ``sum(breakdown.hours) == viewing_hours`` exactly.
    Pure ``Decimal``; inputs are never mutated; never raises on finite inputs.
    """
    with localcontext(_CTX):
        h0 = _clamp_floor_zero(+h_comps)

        # Stage 1: additive log lift L = sum_i(beta_i * x_i).
        active_terms: list[FeatureTerm] = []
        total_l = _ZERO
        for ft in feature_terms:
            term = ft.term
            if not term.is_finite() or term == _ZERO:
                # A zero / non-finite term contributes nothing to L but is still
                # shown (its allocated hours will be 0).
                active_terms.append(ft)
                continue
            active_terms.append(ft)
            total_l += term

        ln_1_h0 = (_ONE + h0).ln()
        h1 = _hours_from_logsum(ln_1_h0 + total_l)
        d_feature_total = h1 - h0

        # Option-B per-feature allocation: hours_i = (term / L) * (H1 - H0).
        feature_alloc: list[tuple[FeatureTerm, Decimal]] = []
        for ft in active_terms:
            if total_l > _ZERO and ft.term.is_finite() and ft.term != _ZERO:
                hours_full = (ft.term / total_l) * d_feature_total
            else:
                hours_full = _ZERO
            feature_alloc.append((ft, hours_full))

        # Stages 2-6: sequential re-exponentiation of each multiplicative stage.
        partial = ln_1_h0 + total_l  # ln(1 + H1)
        h_prev = h1

        partial += _ln_multiplier(m_momentum)
        h2 = _hours_from_logsum(partial)
        d_mom = h2 - h_prev
        h_prev = h2

        partial += _ln_multiplier(m_window)
        h3 = _hours_from_logsum(partial)
        d_win = h3 - h_prev
        h_prev = h3

        partial += _ln_multiplier(m_ip)
        h4 = _hours_from_logsum(partial)
        d_ip = h4 - h_prev
        h_prev = h4

        partial += _ln_multiplier(m_vernacular)
        h5 = _hours_from_logsum(partial)
        d_vern = h5 - h_prev
        h_prev = h5

        partial += _ln_multiplier(m_calendar)
        h6 = _hours_from_logsum(partial)
        d_cal = h6 - h_prev

        # Stage 7: one-sided hour-space franchise floor (d_floor >= 0).
        floor = franchise_floor if franchise_floor.is_finite() else _ZERO
        h7 = h6 if h6 >= floor else floor
        d_floor = h7 - h6
        if d_floor < _ZERO:
            d_floor = _ZERO

        h_hat = h7

    # Quantize the prediction and each line; the adjustment line absorbs the
    # per-line whole-hour quantization residual so the sum is exact.
    final = _quantize(h_hat)

    lines: list[AssemblyLine] = [
        AssemblyLine(
            key=KEY_COMPS_ANCHOR,
            label="Comps Anchor",
            hours=_quantize(h0),
        )
    ]
    running_sum = lines[0].hours

    for ft, hours_full in feature_alloc:
        hours_q = _quantize(hours_full)
        running_sum += hours_q
        lines.append(
            AssemblyLine(
                key=ft.key,
                label=ft.label,
                hours=hours_q,
                input=ft.x,
                coefficient=ft.coefficient,
            )
        )

    for key, label, delta, mult in (
        (KEY_MOMENTUM, "Momentum", d_mom, m_momentum),
        (KEY_RELEASE_WINDOW_HALO, "Release Window Halo", d_win, m_window),
        (KEY_SOURCE_IP_PROVENANCE, "Source IP Provenance", d_ip, m_ip),
        (KEY_VERNACULAR_TAM, "Vernacular TAM", d_vern, m_vernacular),
        (KEY_CALENDAR_SEASONALITY, "Calendar Seasonality", d_cal, m_calendar),
    ):
        hours_q = _quantize(delta)
        running_sum += hours_q
        lines.append(
            AssemblyLine(key=key, label=label, hours=hours_q, multiplier=mult)
        )

    floor_q = _quantize(d_floor)
    running_sum += floor_q
    lines.append(
        AssemblyLine(key=KEY_FRANCHISE_FLOOR, label="Franchise Floor", hours=floor_q)
    )

    adjustment = final - running_sum
    if adjustment != _ZERO:
        lines.append(
            AssemblyLine(
                key=KEY_ADJUSTMENT,
                label="Rounding or Bounds Adjustment",
                hours=adjustment,
            )
        )

    return AssemblyResult(
        viewing_hours=final,
        breakdown=tuple(lines),
        unclamped=h_hat,
        running_hours=(h0, h1, h2, h3, h4, h5, h6, h7),
    )
