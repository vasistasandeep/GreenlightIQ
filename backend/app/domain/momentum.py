"""Pure domain module for the Momentum_Telemetry driver (Driver C).

Driver C adds stage-gated trailer / social / search momentum that degrades to a
neutral 1.00 multiplier on stale or dead telemetry. It owns a NEW
``Production_Stage`` enum (production readiness) that is deliberately DISTINCT
from :class:`app.domain.deal_stage.DealStage` (the human acquisition pipeline);
``deal_stage.py`` and ``titles.deal_stage`` are left untouched.

Stage gating (R3.3):

- ``CONCEPT_SCRIPT`` / ``IN_PRODUCTION`` -> ``Momentum_Multiplier = 1.00`` with a
  ``STAGE_EXCLUDED`` flag (an unproduced pitch is never penalized by buzz it
  cannot yet have).
- ``FESTIVAL_PREVIEW`` / ``ACQUISITION_READY`` -> compute the multiplier.

Composition (R3.2, all DETERMINISTIC_FALLBACK Illustrative_Coefficients):

    norm(V_trailer) = clamp(V_trailer / baseline_V, 0, cap_V)
    E_norm          = clamp(E_ratio, 0, cap_E)
    S_velocity      = clamp(S_velocity, 0.50, 2.00)
    raw = 1 + w_v * norm(V_trailer) + w_e * E_norm + w_s * (S_velocity - 1)
    Momentum_Multiplier = clamp(raw, 1.00, momentum_multiplier_max)

Staleness / availability degradation (R3.4, R10.2-R10.5), computed from the
``last_updated_at`` / ``source_available`` of the governing telemetry reading
passed in as inputs (the pure function NEVER queries):

- reading age > ``Telemetry_Staleness_Window`` (14 days) -> multiplier 1.00,
  reason ``STALE``.
- ``source_available = false`` -> multiplier 1.00, reason ``UNAVAILABLE``
  (distinct from stale).

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``) and it imports only the
Python standard library. Inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from enum import Enum

__all__ = [
    "DECIMAL_CONTEXT_PRECISION",
    "SOURCE_DETERMINISTIC_FALLBACK",
    "SOURCE_MODEL_VERSION",
    "NEUTRAL_MULTIPLIER",
    "S_VELOCITY_MIN",
    "S_VELOCITY_MAX",
    "REASON_ACTIVE",
    "REASON_STAGE_EXCLUDED",
    "REASON_STALE",
    "REASON_UNAVAILABLE",
    "Production_Stage",
    "STAGE_LABELS",
    "INITIAL_STAGE",
    "EXCLUDED_STAGES",
    "DEFAULT_MOMENTUM_PARAMS",
    "MomentumParams",
    "MomentumFeatures",
    "MomentumResult",
    "coerce_stage",
    "coerce_decimal",
    "parse_params",
    "calculate_momentum",
]

DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

SOURCE_DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
SOURCE_MODEL_VERSION = "MODEL_VERSION"

# The neutral (no-lift) multiplier the driver degrades / gates to.
NEUTRAL_MULTIPLIER = Decimal("1.00")

# S_velocity is clamped to this inclusive band upstream of the composition (R3.2).
S_VELOCITY_MIN = Decimal("0.50")
S_VELOCITY_MAX = Decimal("2.00")

# Degradation / gating reasons recorded on the result for auditability (R10.5).
REASON_ACTIVE = "ACTIVE"
REASON_STAGE_EXCLUDED = "STAGE_EXCLUDED"
REASON_STALE = "STALE"
REASON_UNAVAILABLE = "UNAVAILABLE"


class Production_Stage(str, Enum):
    """A title's production-readiness stage (DISTINCT from ``DealStage``).

    The acquisition pipeline (``app.domain.deal_stage.DealStage``) is a separate,
    untouched concept. This enum gates the momentum driver: a title that is not
    yet produced cannot carry trailer / social / search buzz.
    """

    CONCEPT_SCRIPT = "CONCEPT_SCRIPT"
    IN_PRODUCTION = "IN_PRODUCTION"
    FESTIVAL_PREVIEW = "FESTIVAL_PREVIEW"
    ACQUISITION_READY = "ACQUISITION_READY"


#: The stage a title defaults to when unknown / absent (keeps momentum neutral).
INITIAL_STAGE: Production_Stage = Production_Stage.CONCEPT_SCRIPT

#: Stages that gate the momentum multiplier to the neutral baseline (R3.3).
EXCLUDED_STAGES: frozenset[Production_Stage] = frozenset(
    {Production_Stage.CONCEPT_SCRIPT, Production_Stage.IN_PRODUCTION}
)

#: Human-friendly labels for the UI (mirrors ``deal_stage.STAGE_LABELS``).
STAGE_LABELS: dict[Production_Stage, str] = {
    Production_Stage.CONCEPT_SCRIPT: "Concept / Script",
    Production_Stage.IN_PRODUCTION: "In Production",
    Production_Stage.FESTIVAL_PREVIEW: "Festival Preview",
    Production_Stage.ACQUISITION_READY: "Acquisition Ready",
}


@dataclass(frozen=True)
class MomentumParams:
    """DETERMINISTIC_FALLBACK Illustrative_Coefficients for the momentum driver.

    ``w_v`` / ``w_e`` / ``w_s`` are the three non-negative composition weights.
    ``baseline_V`` is the Trailer Velocity Index reference (strictly positive);
    ``cap_v`` caps ``norm(V_trailer)``; ``cap_e`` caps ``E_norm``.
    ``momentum_multiplier_max`` is the named upper clamp (``>= 1.00``).
    ``staleness_window_days`` is the Telemetry_Staleness_Window in whole days.
    """

    w_v: Decimal
    w_e: Decimal
    w_s: Decimal
    baseline_v: Decimal
    cap_v: Decimal
    cap_e: Decimal
    momentum_multiplier_max: Decimal
    staleness_window_days: int


@dataclass(frozen=True)
class MomentumFeatures:
    """A title's momentum signals and governing telemetry freshness inputs.

    ``production_stage`` gates the driver. ``v_trailer`` (Trailer Velocity Index),
    ``e_ratio`` (Organic Engagement Ratio), and ``s_velocity`` (search-intent
    velocity vs. genre baseline) are the signals; any may be ``None`` (treated as
    neutral / absent). ``last_updated_at`` / ``source_available`` describe the
    governing ``market_telemetry_cache`` reading and drive the staleness /
    availability degradation; ``now`` is the reference time for the age
    comparison (supplied so the pure function never reads the clock).
    """

    production_stage: Production_Stage
    v_trailer: Decimal | None = None
    e_ratio: Decimal | None = None
    s_velocity: Decimal | None = None
    last_updated_at: datetime | None = None
    source_available: bool = True
    now: datetime | None = None


@dataclass(frozen=True)
class MomentumResult:
    """The resolved ``Momentum_Multiplier`` plus provenance metadata.

    ``multiplier`` is in the inclusive ``[1.00, momentum_multiplier_max]`` band.
    ``stage_excluded`` is ``True`` for a gated stage. ``reason`` is one of
    ``ACTIVE`` / ``STAGE_EXCLUDED`` / ``STALE`` / ``UNAVAILABLE``.
    ``reading_age_days`` is the governing reading's age in whole days (``None``
    when no timestamp was supplied).
    """

    multiplier: Decimal
    production_stage: Production_Stage
    stage_excluded: bool
    reason: str
    source_available: bool
    reading_age_days: int | None
    source_tier: str


DEFAULT_MOMENTUM_PARAMS = MomentumParams(
    w_v=Decimal("0.15"),
    w_e=Decimal("0.20"),
    w_s=Decimal("0.25"),
    baseline_v=Decimal("1.0"),
    cap_v=Decimal("2.00"),
    cap_e=Decimal("1.00"),
    momentum_multiplier_max=Decimal("1.50"),
    staleness_window_days=14,
)


def coerce_stage(value: str | Production_Stage | None) -> Production_Stage:
    """Coerce a raw value to a :class:`Production_Stage`, defaulting to the initial stage.

    ``None`` (e.g. a title persisted before the column existed) maps to
    :data:`INITIAL_STAGE`; an unknown string ALSO maps to :data:`INITIAL_STAGE`
    (a gated stage), so an unrecognized descriptor keeps momentum neutral rather
    than raising (per the input-validation table: unknown -> CONCEPT_SCRIPT ->
    STAGE_EXCLUDED).
    """
    if value is None:
        return INITIAL_STAGE
    if isinstance(value, Production_Stage):
        return value
    try:
        return Production_Stage(value)
    except ValueError:
        return INITIAL_STAGE


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


def _coerce_positive(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite STRICTLY POSITIVE Decimal, else ``None``."""
    value = coerce_decimal(raw)
    if value is None or value <= 0:
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


def parse_params(raw: Mapping | None) -> tuple[MomentumParams, str]:
    """Parse a ``momentum`` mapping into (:class:`MomentumParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_MOMENTUM_PARAMS, "DETERMINISTIC_FALLBACK")``. A valid parse
    requires finite non-negative ``w_v`` / ``w_e`` / ``w_s`` / ``cap_v`` /
    ``cap_e``, a strictly positive ``baseline_v``, a ``momentum_multiplier_max``
    ``>= 1.00``, and a strictly positive integer ``staleness_window_days``.
    Mirrors the churn full-fallback contract: never raises; any invalid / missing
    field collapses the whole block to the illustrative defaults.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_MOMENTUM_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    w_v = _coerce_nonneg(raw.get("w_v"))
    w_e = _coerce_nonneg(raw.get("w_e"))
    w_s = _coerce_nonneg(raw.get("w_s"))
    baseline_v = _coerce_positive(raw.get("baseline_v"))
    cap_v = _coerce_nonneg(raw.get("cap_v"))
    cap_e = _coerce_nonneg(raw.get("cap_e"))
    mm_max = _coerce_nonneg(raw.get("momentum_multiplier_max"))
    window = _coerce_positive_int(raw.get("staleness_window_days"))

    if any(
        v is None
        for v in (w_v, w_e, w_s, baseline_v, cap_v, cap_e, mm_max, window)
    ):
        return DEFAULT_MOMENTUM_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    if mm_max < NEUTRAL_MULTIPLIER:  # type: ignore[operator]
        return DEFAULT_MOMENTUM_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    params = MomentumParams(
        w_v=w_v,  # type: ignore[arg-type]
        w_e=w_e,  # type: ignore[arg-type]
        w_s=w_s,  # type: ignore[arg-type]
        baseline_v=baseline_v,  # type: ignore[arg-type]
        cap_v=cap_v,  # type: ignore[arg-type]
        cap_e=cap_e,  # type: ignore[arg-type]
        momentum_multiplier_max=mm_max,  # type: ignore[arg-type]
        staleness_window_days=window,  # type: ignore[arg-type]
    )
    return params, SOURCE_MODEL_VERSION


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _neutral_result(
    stage: Production_Stage,
    reason: str,
    source_available: bool,
    reading_age_days: int | None,
    params_source: str,
    *,
    stage_excluded: bool,
) -> MomentumResult:
    """Build a neutral (1.00) :class:`MomentumResult` for a gated / degraded path."""
    return MomentumResult(
        multiplier=NEUTRAL_MULTIPLIER,
        production_stage=stage,
        stage_excluded=stage_excluded,
        reason=reason,
        source_available=source_available,
        reading_age_days=reading_age_days,
        source_tier=params_source,
    )


def calculate_momentum(
    features: MomentumFeatures,
    params: MomentumParams,
    params_source: str = SOURCE_DETERMINISTIC_FALLBACK,
) -> MomentumResult:
    """Compute the ``Momentum_Multiplier`` from ``features`` (R3.1-R3.6, R10.2-R10.5).

    Gating / degradation precedence: a ``CONCEPT_SCRIPT`` / ``IN_PRODUCTION``
    stage gates to 1.00 (``STAGE_EXCLUDED``); otherwise an unavailable source
    degrades to 1.00 (``UNAVAILABLE``), then a reading older than the staleness
    window degrades to 1.00 (``STALE``). On an eligible, fresh, available stage
    the multiplier is composed from the (clamped) signals and clamped to
    ``[1.00, momentum_multiplier_max]``. A missing signal contributes its neutral
    value (``norm(V)=0``, ``E_norm=0``, ``S_velocity=1``). Pure ``Decimal``; never
    queries; inputs unmodified.
    """
    stage = features.production_stage

    # Resolve the governing reading's age (in whole days) for auditability.
    reading_age_days: int | None = None
    is_stale = False
    if features.last_updated_at is not None:
        now = features.now if features.now is not None else features.last_updated_at
        delta = now - features.last_updated_at
        # Floor negative ages (future-stamped reading) to 0; it is not stale.
        reading_age_days = delta.days if delta >= timedelta(0) else 0
        is_stale = delta > timedelta(days=params.staleness_window_days)

    # Stage gating takes precedence (R3.3): an unproduced pitch is never
    # penalized and never reaches the signal composition.
    if stage in EXCLUDED_STAGES:
        return _neutral_result(
            stage,
            REASON_STAGE_EXCLUDED,
            features.source_available,
            reading_age_days,
            params_source,
            stage_excluded=True,
        )

    # Availability degradation (distinct from stale, R10.4).
    if not features.source_available:
        return _neutral_result(
            stage,
            REASON_UNAVAILABLE,
            False,
            reading_age_days,
            params_source,
            stage_excluded=False,
        )

    # Staleness degradation (R10.3).
    if is_stale:
        return _neutral_result(
            stage,
            REASON_STALE,
            features.source_available,
            reading_age_days,
            params_source,
            stage_excluded=False,
        )

    # Active composition.
    with localcontext(_CTX):
        v_raw = features.v_trailer
        if v_raw is None or not v_raw.is_finite():
            norm_v = Decimal("0")
        else:
            norm_v = _clamp(v_raw / params.baseline_v, Decimal("0"), params.cap_v)

        e_raw = features.e_ratio
        if e_raw is None or not e_raw.is_finite():
            e_norm = Decimal("0")
        else:
            e_norm = _clamp(e_raw, Decimal("0"), params.cap_e)

        s_raw = features.s_velocity
        if s_raw is None or not s_raw.is_finite():
            s_velocity = Decimal("1")
        else:
            s_velocity = _clamp(s_raw, S_VELOCITY_MIN, S_VELOCITY_MAX)

        raw = (
            Decimal("1")
            + params.w_v * norm_v
            + params.w_e * e_norm
            + params.w_s * (s_velocity - Decimal("1"))
        )
        multiplier = _clamp(
            raw, NEUTRAL_MULTIPLIER, params.momentum_multiplier_max
        )

    return MomentumResult(
        multiplier=multiplier,
        production_stage=stage,
        stage_excluded=False,
        reason=REASON_ACTIVE,
        source_available=features.source_available,
        reading_age_days=reading_age_days,
        source_tier=params_source,
    )
