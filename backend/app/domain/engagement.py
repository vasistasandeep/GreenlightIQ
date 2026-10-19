"""Pure domain module for the engagement Content_Eval_Models (content-eval-model).

Covers the two engagement-correlate Modeled_Engagement_Drivers that open data can
inform beyond churn and viewing hours:

- **Watch_Time_Elasticity** -- an ADDITIVE model, built exactly like
  :mod:`app.domain.churn`: the elasticity is the additive sum of per-feature
  contributions

      intercept
    + runtime_weight    * runtime score        (minutes clamped, scaled)
    + serialization_lift (when the title is a serialized/returning format)
    + bingeability weight (per-genre retention/bingeability, else neutral)
    + rating_weight     * normalized_rating     (clamped to [0, 1])
    + franchise_lift     (when the title is a franchise/sequel, else 0)

  quantized to 2 dp half-up per feature, clamped to a documented domain, with a
  single trailing ``bounds_adjustment`` entry (only when nonzero) so the
  breakdown conserves to the final value exactly (Property 2).

- **Ad_Load_Receptivity** -- a unit-centered MULTIPLIER (default 1.0) that SCALES
  the configured CPM Platform_Rate rather than inventing a dollar CPM. It too is
  built additively around the neutral centre 1.0: the multiplier is

      1.0 (neutral centre)
    + genre receptivity offset (per-genre ad tolerance, else neutral 0)
    + rating receptivity       (rating_weight * (rating - 0.5))
    + runtime receptivity      (longer slots -> more inventory, bounded)
    + franchise receptivity    (when franchise, else 0)

  quantized and conserving the same way, then clamped to a documented sensible
  range centred on 1.0. The model NEVER emits a dollar CPM -- the engine still
  multiplies by the configured ``cpm``; this model only supplies the receptivity
  scalar, honoring the Platform_Rate boundary (R1.1).

Both models read their inputs from the shared :class:`app.domain.features.
FeatureVector` and consume only features named in
:data:`app.domain.features.PREDICTIVE_FEATURES` (``release_year`` is split-only
and never consulted). Both expose a ``resolve_*`` implementing the SUPPLIED-wins
contract: a finite supplied value (including 0) is returned exactly with method
SUPPLIED; otherwise the model is calculated (Property 6). Missing/absent features
degrade to neutral defaults flagged ``assumed`` and never raise (Property 7).

The coefficients in :data:`DEFAULT_WATCH_TIME_ELASTICITY_PARAMS` and
:data:`DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS` are Illustrative_Coefficients: chosen
to be sensible defaults, NOT fitted to real engagement or ad-revenue data.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic is performed with :class:`decimal.Decimal` precision and it
imports only the Python standard library (plus the sibling pure ``features``
module), so it is importable without the application framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.domain.features import (
    FeatureVector,
    normalize_genre,
    normalize_label,
)

__all__ = [
    "WTE_MIN",
    "WTE_MAX",
    "RECEPTIVITY_MIN",
    "RECEPTIVITY_MAX",
    "RECEPTIVITY_CENTRE",
    "RUNTIME_REF_MINUTES",
    "RATING_CENTRE",
    "DEFAULT_WTE_GENRE_OFFSETS",
    "DEFAULT_WTE_GENRE_WEIGHT",
    "DEFAULT_WTE_FORMAT_LIFTS",
    "DEFAULT_WTE_FORMAT_WEIGHT",
    "DEFAULT_RECEPTIVITY_GENRE_OFFSETS",
    "DEFAULT_RECEPTIVITY_GENRE_WEIGHT",
    "DEFAULT_WATCH_TIME_ELASTICITY_PARAMS",
    "DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS",
    "WatchTimeElasticityParams",
    "AdLoadReceptivityParams",
    "EngagementContribution",
    "WatchTimeElasticityResult",
    "AdLoadReceptivityResult",
    "coerce_supplied",
    "parse_watch_time_elasticity_params",
    "parse_ad_load_receptivity_params",
    "calculate_watch_time_elasticity",
    "calculate_ad_load_receptivity",
    "resolve_watch_time_elasticity",
    "resolve_ad_load_receptivity",
]

# ---------------------------------------------------------------------------
# Documented output domains and reference points
# ---------------------------------------------------------------------------

# Watch_Time_Elasticity output domain. Elasticity is a non-negative demand
# multiplier used in the LTV numerator; it stays in a sensible bounded band so a
# single feature can never drive the LTV contribution to an absurd value.
WTE_MIN = Decimal("0.00")
WTE_MAX = Decimal("3.00")

# Ad_Load_Receptivity output domain. A unit-centred multiplier on the configured
# CPM basis: 1.0 is neutral, and the model may only nudge within a documented
# sensible band (never negative, never more than +/-50%).
RECEPTIVITY_CENTRE = Decimal("1.00")
RECEPTIVITY_MIN = Decimal("0.50")
RECEPTIVITY_MAX = Decimal("1.50")

# Reference runtime used to scale the runtime feature into a bounded [0, ~2]
# contributor (minutes / RUNTIME_REF_MINUTES). 60 mirrors features.RUNTIME_NEUTRAL.
RUNTIME_REF_MINUTES = Decimal("60")

# Rating centre: normalized_rating lives in [0, 1]; the neutral/mid rating is 0.5,
# so a rating feature contributes 0 at the centre and a signed lift either side.
RATING_CENTRE = Decimal("0.5")

_Q = Decimal("0.01")  # 2 dp, ROUND_HALF_UP (mirror of churn._Q)

# Feature-domain clamp bounds (mirror features.py / churn.py conventions).
_RATING_MIN = Decimal("0")
_RATING_MAX = Decimal("1")
_RUNTIME_MIN = Decimal("0")
# Runtime is scaled by RUNTIME_REF_MINUTES then capped so an outlier runtime
# cannot dominate; the cap is documented as a 3x-reference bound.
_RUNTIME_SCORE_MAX = Decimal("3")

_SOURCE_MODEL_VERSION = "MODEL_VERSION"
_SOURCE_DEFAULTS = "DEFAULTS"

_METHOD_CALCULATED = "CALCULATED"
_METHOD_SUPPLIED = "SUPPLIED"

# ---------------------------------------------------------------------------
# Illustrative coefficients (NOT fitted to real data)
# ---------------------------------------------------------------------------

# Per-genre watch-time elasticity / bingeability offsets. Serialized, returning
# formats (crime, drama, thriller, mystery) hold attention and binge longer than
# one-and-done formats (documentary, kids, musical), so they weigh more. Keys are
# normalized (lowercased, spaces/underscores -> hyphen). Illustrative_Coefficients.
DEFAULT_WTE_GENRE_OFFSETS: Mapping[str, Decimal] = {
    "crime": Decimal("0.20"),
    "crime-biopic": Decimal("0.19"),
    "drama": Decimal("0.18"),
    "thriller": Decimal("0.18"),
    "mystery": Decimal("0.17"),
    "sci-fi": Decimal("0.16"),
    "fantasy": Decimal("0.16"),
    "reality": Decimal("0.15"),
    "action": Decimal("0.13"),
    "adventure": Decimal("0.12"),
    "romance": Decimal("0.11"),
    "biopic": Decimal("0.11"),
    "historical": Decimal("0.10"),
    "war": Decimal("0.10"),
    "horror": Decimal("0.10"),
    "anthology": Decimal("0.09"),
    "animation": Decimal("0.08"),
    "family": Decimal("0.08"),
    "sports": Decimal("0.08"),
    "comedy": Decimal("0.07"),
    "western": Decimal("0.06"),
    "documentary": Decimal("0.05"),
    "kids": Decimal("0.05"),
    "musical": Decimal("0.05"),
}

# Neutral genre bingeability for an unknown/absent genre (mid of the range, not 0
# and not the max), so a title in an unseeded genre still scores rationally.
DEFAULT_WTE_GENRE_WEIGHT = Decimal("0.12")

# Content-format serialization lift. ADDITIVE on top of the genre bingeability:
# positive for serialized/returning formats that drive repeat watch-time, 0 for
# one-and-done formats. Keys normalized like genres. Illustrative_Coefficients.
DEFAULT_WTE_FORMAT_LIFTS: Mapping[str, Decimal] = {
    "scripted-series": Decimal("0.25"),
    "limited-series": Decimal("0.18"),
    "reality-competition": Decimal("0.20"),
    "live-sports": Decimal("0.15"),
    "live-event": Decimal("0.08"),
    "original-film": Decimal("0.00"),
    "licensed-film": Decimal("0.00"),
    "documentary": Decimal("0.00"),
    "kids-animation": Decimal("0.05"),
    "library": Decimal("0.00"),
}

# Neutral format lift for an unknown/absent format. Default 0 preserves the
# genre-only behavior; a non-zero value would flag an unknown format as assumed.
DEFAULT_WTE_FORMAT_WEIGHT = Decimal("0.00")

# Per-genre ad-load receptivity offsets (signed, centred on 0 around the neutral
# 1.0 multiplier). Lean-back, long-session genres (sports, reality, comedy)
# tolerate heavier ad loads; prestige/binge drama is more ad-sensitive (slightly
# negative). Keys normalized. Illustrative_Coefficients.
DEFAULT_RECEPTIVITY_GENRE_OFFSETS: Mapping[str, Decimal] = {
    "live-sports": Decimal("0.15"),
    "sports": Decimal("0.12"),
    "reality": Decimal("0.10"),
    "comedy": Decimal("0.08"),
    "family": Decimal("0.06"),
    "kids": Decimal("0.05"),
    "game-show": Decimal("0.08"),
    "talk": Decimal("0.07"),
    "action": Decimal("0.03"),
    "adventure": Decimal("0.02"),
    "documentary": Decimal("0.00"),
    "historical": Decimal("0.00"),
    "romance": Decimal("-0.02"),
    "horror": Decimal("-0.03"),
    "thriller": Decimal("-0.04"),
    "mystery": Decimal("-0.04"),
    "sci-fi": Decimal("-0.03"),
    "crime": Decimal("-0.05"),
    "drama": Decimal("-0.06"),
}

# Neutral receptivity offset for an unknown/absent genre: 0 (purely neutral, no
# ad-tolerance signal either way). Only flagged assumed when non-zero.
DEFAULT_RECEPTIVITY_GENRE_WEIGHT = Decimal("0.00")


# ---------------------------------------------------------------------------
# Parameter dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchTimeElasticityParams:
    """Parameters for the additive Watch_Time_Elasticity model.

    All scalar weights/lifts are non-negative so the model is monotone in each
    feature (Property 4); ``min_value <= max_value`` bounds the output domain.
    """

    intercept: Decimal
    runtime_weight: Decimal
    serialization_lift: Decimal
    rating_weight: Decimal
    franchise_lift: Decimal
    min_value: Decimal
    max_value: Decimal
    genre_offsets: Mapping[str, Decimal] = field(default_factory=dict)
    genre_default: Decimal = DEFAULT_WTE_GENRE_WEIGHT
    format_lifts: Mapping[str, Decimal] = field(default_factory=dict)
    format_default: Decimal = DEFAULT_WTE_FORMAT_WEIGHT


@dataclass(frozen=True)
class AdLoadReceptivityParams:
    """Parameters for the unit-centred Ad_Load_Receptivity multiplier model.

    The receptivity is built additively around ``centre`` (1.0): per-genre
    offsets are signed, and the rating/runtime/franchise weights are non-negative
    magnitudes applied to signed, centred feature deltas. ``min_value <=
    max_value`` bounds the output multiplier domain centred on ``centre``.
    """

    centre: Decimal
    rating_weight: Decimal
    runtime_weight: Decimal
    franchise_lift: Decimal
    min_value: Decimal
    max_value: Decimal
    genre_offsets: Mapping[str, Decimal] = field(default_factory=dict)
    genre_default: Decimal = DEFAULT_RECEPTIVITY_GENRE_WEIGHT


# ---------------------------------------------------------------------------
# Result dataclasses (mirror churn.ChurnContribution / ChurnResult)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngagementContribution:
    """A single per-feature contribution within an engagement breakdown."""

    key: str
    label: str
    input: Decimal | None  # feature value used (None when missing/NA)
    coefficient: Decimal | None  # per-unit weight (None for intercept/offset/adj)
    points: Decimal  # quantized contribution in the model's output unit


@dataclass(frozen=True)
class WatchTimeElasticityResult:
    """The resolved Watch_Time_Elasticity plus explanation metadata."""

    watch_time_elasticity: Decimal
    method: str  # "CALCULATED" | "SUPPLIED"
    breakdown: tuple[EngagementContribution, ...] | None  # None when SUPPLIED
    missing_features: tuple[str, ...]
    params_source: str  # "MODEL_VERSION" | "DEFAULTS"
    unclamped: Decimal | None  # pre-clamp calculated value (None when SUPPLIED)
    assumed_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdLoadReceptivityResult:
    """The resolved Ad_Load_Receptivity multiplier plus explanation metadata.

    ``ad_load_receptivity`` is a unit-centred multiplier (default 1.0) that scales
    the configured CPM basis; it is NEVER a dollar CPM.
    """

    ad_load_receptivity: Decimal
    method: str  # "CALCULATED" | "SUPPLIED"
    breakdown: tuple[EngagementContribution, ...] | None  # None when SUPPLIED
    missing_features: tuple[str, ...]
    params_source: str  # "MODEL_VERSION" | "DEFAULTS"
    unclamped: Decimal | None  # pre-clamp calculated value (None when SUPPLIED)
    assumed_features: tuple[str, ...] = ()


DEFAULT_WATCH_TIME_ELASTICITY_PARAMS = WatchTimeElasticityParams(
    intercept=Decimal("0.80"),
    runtime_weight=Decimal("0.10"),
    serialization_lift=Decimal("0.15"),
    rating_weight=Decimal("0.30"),
    franchise_lift=Decimal("0.12"),
    min_value=WTE_MIN,
    max_value=WTE_MAX,
    genre_offsets=DEFAULT_WTE_GENRE_OFFSETS,
    genre_default=DEFAULT_WTE_GENRE_WEIGHT,
    format_lifts=DEFAULT_WTE_FORMAT_LIFTS,
    format_default=DEFAULT_WTE_FORMAT_WEIGHT,
)

DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS = AdLoadReceptivityParams(
    centre=RECEPTIVITY_CENTRE,
    rating_weight=Decimal("0.10"),
    runtime_weight=Decimal("0.05"),
    franchise_lift=Decimal("0.03"),
    min_value=RECEPTIVITY_MIN,
    max_value=RECEPTIVITY_MAX,
    genre_offsets=DEFAULT_RECEPTIVITY_GENRE_OFFSETS,
    genre_default=DEFAULT_RECEPTIVITY_GENRE_WEIGHT,
)


# ---------------------------------------------------------------------------
# Coercion + parsing helpers (mirror churn.coerce_supplied / parse_params)
# ---------------------------------------------------------------------------


def coerce_supplied(raw: object) -> Decimal | None:
    """Coerce a raw supplied value to a finite :class:`Decimal`, or ``None``.

    Blank, ``None``, non-numeric, non-finite, or boolean inputs yield ``None``
    (treated as "not supplied"). A finite numeric value (including 0, a
    pass-through ``Decimal``, an ``int``, a numeric string, or a finite float)
    yields a ``Decimal``. ``bool`` is rejected to match the codebase convention
    that a boolean is not a number. Never raises.
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


def _coerce_param(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite non-negative Decimal, else ``None``."""
    value = coerce_supplied(raw)
    if value is None or value < 0:
        return None
    return value


def _coerce_signed_param(raw: object) -> Decimal | None:
    """Coerce a raw param to any finite Decimal (signed), else ``None``.

    Used for the signed receptivity genre offsets, which may be negative (an
    ad-sensitive genre reduces the multiplier below 1.0).
    """
    return coerce_supplied(raw)


# Sentinel distinguishing "absent" (use defaults) from "present but invalid"
# (reject the whole param block) for an optional offsets mapping.
_REJECT: Mapping[str, Decimal] = {"__reject__": Decimal("-1")}


def _parse_offsets(raw: object, *, signed: bool) -> Mapping[str, Decimal] | None:
    """Parse an optional label->weight mapping, else a sentinel/``None``.

    Returns ``None`` when the mapping is absent (caller falls back to defaults),
    ``_REJECT`` when it is present but malformed (non-mapping, or any invalid
    weight), else the normalized mapping. ``signed`` allows negative weights
    (receptivity genre offsets); otherwise weights must be non-negative.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _REJECT
    offsets: dict[str, Decimal] = {}
    for key, value in raw.items():
        weight = _coerce_signed_param(value) if signed else _coerce_param(value)
        if weight is None:
            return _REJECT
        norm = normalize_label(str(key))
        if norm is not None:
            offsets[norm] = weight
    return offsets


def parse_watch_time_elasticity_params(
    raw: Mapping | None,
) -> tuple[WatchTimeElasticityParams, str]:
    """Parse a ``watch_time_elasticity`` mapping into (params, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, "DEFAULTS")``. A valid parse requires
    the intercept and every scalar weight/lift to coerce to finite non-negative
    Decimals and the bounds to be finite with ``min_value <= max_value``. The
    genre/format mappings and their neutral defaults are optional: absent -> the
    built-in defaults; present-but-invalid -> the whole block falls back. Never
    raises (mirrors :func:`app.domain.churn.parse_params`).
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS

    intercept = _coerce_param(raw.get("intercept"))
    runtime_weight = _coerce_param(raw.get("runtime_weight"))
    serialization_lift = _coerce_param(raw.get("serialization_lift"))
    rating_weight = _coerce_param(raw.get("rating_weight"))
    franchise_lift = _coerce_param(raw.get("franchise_lift"))
    min_value = _coerce_param(raw.get("min_value"))
    max_value = _coerce_param(raw.get("max_value"))

    if any(
        v is None
        for v in (
            intercept,
            runtime_weight,
            serialization_lift,
            rating_weight,
            franchise_lift,
            min_value,
            max_value,
        )
    ):
        return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS

    if min_value > max_value:  # type: ignore[operator]
        return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS

    genre_offsets = _parse_offsets(raw.get("genre_offsets"), signed=False)
    if genre_offsets is _REJECT:
        return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS
    if genre_offsets is None:
        genre_offsets = DEFAULT_WTE_GENRE_OFFSETS

    if "genre_default" in raw:
        genre_default = _coerce_param(raw.get("genre_default"))
        if genre_default is None:
            return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS
    else:
        genre_default = DEFAULT_WTE_GENRE_WEIGHT

    format_lifts = _parse_offsets(raw.get("format_lifts"), signed=False)
    if format_lifts is _REJECT:
        return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS
    if format_lifts is None:
        format_lifts = DEFAULT_WTE_FORMAT_LIFTS

    if "format_default" in raw:
        format_default = _coerce_param(raw.get("format_default"))
        if format_default is None:
            return DEFAULT_WATCH_TIME_ELASTICITY_PARAMS, _SOURCE_DEFAULTS
    else:
        format_default = DEFAULT_WTE_FORMAT_WEIGHT

    params = WatchTimeElasticityParams(
        intercept=intercept,  # type: ignore[arg-type]
        runtime_weight=runtime_weight,  # type: ignore[arg-type]
        serialization_lift=serialization_lift,  # type: ignore[arg-type]
        rating_weight=rating_weight,  # type: ignore[arg-type]
        franchise_lift=franchise_lift,  # type: ignore[arg-type]
        min_value=min_value,  # type: ignore[arg-type]
        max_value=max_value,  # type: ignore[arg-type]
        genre_offsets=genre_offsets,
        genre_default=genre_default,  # type: ignore[arg-type]
        format_lifts=format_lifts,
        format_default=format_default,  # type: ignore[arg-type]
    )
    return params, _SOURCE_MODEL_VERSION


def parse_ad_load_receptivity_params(
    raw: Mapping | None,
) -> tuple[AdLoadReceptivityParams, str]:
    """Parse an ``ad_load_receptivity`` mapping into (params, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, "DEFAULTS")``. A valid parse requires
    the centre and the non-negative rating/runtime/franchise magnitudes to coerce
    to finite non-negative Decimals and the bounds to be finite with ``min_value
    <= max_value``. The signed genre offsets and the neutral genre default are
    optional: absent -> defaults; present-but-invalid -> the block falls back.
    Never raises.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, _SOURCE_DEFAULTS

    centre = _coerce_param(raw.get("centre"))
    rating_weight = _coerce_param(raw.get("rating_weight"))
    runtime_weight = _coerce_param(raw.get("runtime_weight"))
    franchise_lift = _coerce_param(raw.get("franchise_lift"))
    min_value = _coerce_param(raw.get("min_value"))
    max_value = _coerce_param(raw.get("max_value"))

    if any(
        v is None
        for v in (
            centre,
            rating_weight,
            runtime_weight,
            franchise_lift,
            min_value,
            max_value,
        )
    ):
        return DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, _SOURCE_DEFAULTS

    if min_value > max_value:  # type: ignore[operator]
        return DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, _SOURCE_DEFAULTS

    # Signed genre offsets (an ad-sensitive genre may be negative).
    genre_offsets = _parse_offsets(raw.get("genre_offsets"), signed=True)
    if genre_offsets is _REJECT:
        return DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, _SOURCE_DEFAULTS
    if genre_offsets is None:
        genre_offsets = DEFAULT_RECEPTIVITY_GENRE_OFFSETS

    if "genre_default" in raw:
        genre_default = _coerce_signed_param(raw.get("genre_default"))
        if genre_default is None:
            return DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS, _SOURCE_DEFAULTS
    else:
        genre_default = DEFAULT_RECEPTIVITY_GENRE_WEIGHT

    params = AdLoadReceptivityParams(
        centre=centre,  # type: ignore[arg-type]
        rating_weight=rating_weight,  # type: ignore[arg-type]
        runtime_weight=runtime_weight,  # type: ignore[arg-type]
        franchise_lift=franchise_lift,  # type: ignore[arg-type]
        min_value=min_value,  # type: ignore[arg-type]
        max_value=max_value,  # type: ignore[arg-type]
        genre_offsets=genre_offsets,
        genre_default=genre_default,  # type: ignore[arg-type]
    )
    return params, _SOURCE_MODEL_VERSION


# ---------------------------------------------------------------------------
# Shared numeric helpers (mirror churn._clamp / _quantize)
# ---------------------------------------------------------------------------


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _quantize(value: Decimal) -> Decimal:
    """Quantize to 2 dp using half-up rounding (mirror of churn._quantize)."""
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def _feature_decimal(feature) -> Decimal | None:
    """Return a feature's value as a finite Decimal, else ``None``.

    Reads from an :class:`app.domain.features.Feature`. A non-Decimal or
    non-finite value (e.g. a None label) returns ``None`` so the caller can treat
    it as missing.
    """
    value = getattr(feature, "value", None)
    if isinstance(value, Decimal) and value.is_finite():
        return value
    return None


def _feature_label(feature) -> str | None:
    """Return a feature's value as a label string, else ``None``."""
    value = getattr(feature, "value", None)
    if isinstance(value, str):
        return value
    return None


# ---------------------------------------------------------------------------
# Watch_Time_Elasticity (additive, like churn)
# ---------------------------------------------------------------------------


def calculate_watch_time_elasticity(
    features: FeatureVector,
    params: WatchTimeElasticityParams,
    params_source: str = _SOURCE_DEFAULTS,
) -> WatchTimeElasticityResult:
    """Compute the additive Watch_Time_Elasticity from ``features``.

    Reads only features in :data:`app.domain.features.PREDICTIVE_FEATURES`
    (``runtime_minutes``, ``content_format``, ``genre``, ``normalized_rating``,
    ``franchise_flag``). Each contribution is computed at full precision then
    quantized to 2 dp half-up; the sum is clamped to the parameter output domain
    and a single ``bounds_adjustment`` entry (only when nonzero) absorbs the clamp
    delta and quantization residual so ``sum(breakdown) == final`` exactly
    (Property 2). A feature that fell back to a neutral default in ``features`` is
    reported in ``assumed_features``; a feature with no usable value contributes 0
    and is reported in ``missing_features``.
    """
    missing: list[str] = []
    assumed: list[str] = []

    # Base elasticity (intercept).
    base_full = params.intercept
    base_points = _quantize(base_full)

    # Runtime score: minutes / reference, capped. A missing runtime contributes 0.
    runtime_val = _feature_decimal(features.runtime_minutes)
    if runtime_val is None:
        runtime_input: Decimal | None = None
        runtime_full = Decimal("0")
        missing.append("runtime_minutes")
    else:
        runtime_clamped = _clamp(runtime_val, _RUNTIME_MIN, _RUNTIME_MIN + Decimal("1e9"))
        runtime_score = _clamp(
            runtime_clamped / RUNTIME_REF_MINUTES, Decimal("0"), _RUNTIME_SCORE_MAX
        )
        runtime_input = runtime_score
        runtime_full = params.runtime_weight * runtime_score
        if getattr(features.runtime_minutes, "assumed", False):
            assumed.append("runtime_minutes")
    runtime_points = _quantize(runtime_full)

    # Serialization lift (content-format): an additive lift for serialized /
    # returning formats; 0 for one-and-done formats or an unknown format.
    norm_format = normalize_label(_feature_label(features.content_format))
    if norm_format is not None and norm_format in params.format_lifts:
        serialization_full = params.format_lifts[norm_format]
        serialization_input: Decimal | None = serialization_full
    else:
        serialization_full = params.format_default
        serialization_input = serialization_full
        if norm_format is None:
            missing.append("content_format")
        elif params.format_default != 0:
            assumed.append("content_format")
    serialization_points = _quantize(serialization_full)

    # Genre bingeability: unknown/absent genre uses the neutral default.
    norm_genre = normalize_genre(_feature_label(features.genre))
    if norm_genre is not None and norm_genre in params.genre_offsets:
        genre_full = params.genre_offsets[norm_genre]
        genre_input: Decimal | None = genre_full
    else:
        genre_full = params.genre_default
        genre_input = genre_full
        assumed.append("genre")
    genre_points = _quantize(genre_full)

    # Rating contribution: rating_weight * normalized_rating (clamped [0, 1]).
    rating_val = _feature_decimal(features.normalized_rating)
    if rating_val is None:
        rating_input: Decimal | None = None
        rating_full = Decimal("0")
        missing.append("normalized_rating")
    else:
        rating_input = _clamp(rating_val, _RATING_MIN, _RATING_MAX)
        rating_full = params.rating_weight * rating_input
        if getattr(features.normalized_rating, "assumed", False):
            assumed.append("normalized_rating")
    rating_points = _quantize(rating_full)

    # Franchise lift: additive when the franchise indicator is truthy.
    franchise_val = _feature_decimal(features.franchise_flag)
    if franchise_val is None:
        franchise_input: Decimal | None = None
        franchise_full = Decimal("0")
        missing.append("franchise_flag")
    else:
        is_franchise = franchise_val > 0
        franchise_input = Decimal("1") if is_franchise else Decimal("0")
        franchise_full = params.franchise_lift if is_franchise else Decimal("0")
        if getattr(features.franchise_flag, "assumed", False):
            assumed.append("franchise_flag")
    franchise_points = _quantize(franchise_full)

    unclamped = (
        base_full
        + runtime_full
        + serialization_full
        + genre_full
        + rating_full
        + franchise_full
    )
    clamped = _clamp(unclamped, params.min_value, params.max_value)
    final = _quantize(clamped)

    feature_points_sum = (
        base_points
        + runtime_points
        + serialization_points
        + genre_points
        + rating_points
        + franchise_points
    )
    bounds_adjustment = final - feature_points_sum

    contributions = [
        EngagementContribution(
            key="base_elasticity",
            label="Base Elasticity",
            input=None,
            coefficient=None,
            points=base_points,
        ),
        EngagementContribution(
            key="runtime_contribution",
            label="Runtime Contribution",
            input=runtime_input,
            coefficient=params.runtime_weight,
            points=runtime_points,
        ),
        EngagementContribution(
            key="serialization_lift",
            label="Serialization Lift",
            input=serialization_input,
            coefficient=None,
            points=serialization_points,
        ),
        EngagementContribution(
            key="genre_bingeability",
            label="Genre Bingeability",
            input=genre_input,
            coefficient=None,
            points=genre_points,
        ),
        EngagementContribution(
            key="rating_contribution",
            label="Rating Contribution",
            input=rating_input,
            coefficient=params.rating_weight,
            points=rating_points,
        ),
        EngagementContribution(
            key="franchise_lift",
            label="Franchise Lift",
            input=franchise_input,
            coefficient=params.franchise_lift,
            points=franchise_points,
        ),
    ]

    if bounds_adjustment != 0:
        contributions.append(
            EngagementContribution(
                key="bounds_adjustment",
                label="Bounds Adjustment",
                input=None,
                coefficient=None,
                points=bounds_adjustment,
            )
        )

    return WatchTimeElasticityResult(
        watch_time_elasticity=final,
        method=_METHOD_CALCULATED,
        breakdown=tuple(contributions),
        missing_features=tuple(missing),
        params_source=params_source,
        unclamped=unclamped,
        assumed_features=tuple(assumed),
    )


def resolve_watch_time_elasticity(
    supplied: object,
    features: FeatureVector,
    params: WatchTimeElasticityParams,
    params_source: str,
) -> WatchTimeElasticityResult:
    """Resolve Watch_Time_Elasticity, supplied value winning (Property 6).

    When ``supplied`` coerces to a finite numeric (including 0), it is returned
    exactly with method SUPPLIED -- no clamp, no re-round, no breakdown.
    Otherwise the model is computed via :func:`calculate_watch_time_elasticity`.
    """
    value = coerce_supplied(supplied)
    if value is not None:
        return WatchTimeElasticityResult(
            watch_time_elasticity=value,
            method=_METHOD_SUPPLIED,
            breakdown=None,
            missing_features=(),
            params_source=params_source,
            unclamped=None,
            assumed_features=(),
        )
    return calculate_watch_time_elasticity(features, params, params_source)


# ---------------------------------------------------------------------------
# Ad_Load_Receptivity (unit-centred multiplier; scales the CPM basis)
# ---------------------------------------------------------------------------


def calculate_ad_load_receptivity(
    features: FeatureVector,
    params: AdLoadReceptivityParams,
    params_source: str = _SOURCE_DEFAULTS,
) -> AdLoadReceptivityResult:
    """Compute the unit-centred Ad_Load_Receptivity multiplier from ``features``.

    The result is a multiplier centred on ``params.centre`` (1.0 by default) that
    SCALES the configured CPM Platform_Rate; it is NEVER a dollar CPM (honors the
    Platform_Rate boundary, R1.1). It is built additively from a neutral centre
    plus signed per-genre / rating / runtime / franchise offsets, quantized per
    feature, clamped to the documented sensible band, with a single conserving
    ``bounds_adjustment`` entry so ``sum(breakdown) == final`` exactly (Property
    2). Reads only PREDICTIVE_FEATURES (``genre``, ``normalized_rating``,
    ``runtime_minutes``, ``franchise_flag``).
    """
    missing: list[str] = []
    assumed: list[str] = []

    # Neutral centre (1.0).
    centre_full = params.centre
    centre_points = _quantize(centre_full)

    # Genre ad-tolerance offset (signed).
    norm_genre = normalize_genre(_feature_label(features.genre))
    if norm_genre is not None and norm_genre in params.genre_offsets:
        genre_full = params.genre_offsets[norm_genre]
        genre_input: Decimal | None = genre_full
    else:
        genre_full = params.genre_default
        genre_input = genre_full
        if norm_genre is None:
            missing.append("genre")
        elif params.genre_default != 0:
            assumed.append("genre")
    genre_points = _quantize(genre_full)

    # Rating receptivity: rating_weight * (rating - centre), signed around 0.5.
    rating_val = _feature_decimal(features.normalized_rating)
    if rating_val is None:
        rating_input: Decimal | None = None
        rating_full = Decimal("0")
        missing.append("normalized_rating")
    else:
        rating_input = _clamp(rating_val, _RATING_MIN, _RATING_MAX)
        rating_full = params.rating_weight * (rating_input - RATING_CENTRE)
        if getattr(features.normalized_rating, "assumed", False):
            assumed.append("normalized_rating")
    rating_points = _quantize(rating_full)

    # Runtime receptivity: longer slots -> more inventory. runtime_weight *
    # (runtime_score - 1), where score = minutes / reference (1.0 at reference),
    # so a reference-length title is neutral and a longer title is positive.
    runtime_val = _feature_decimal(features.runtime_minutes)
    if runtime_val is None:
        runtime_input: Decimal | None = None
        runtime_full = Decimal("0")
        missing.append("runtime_minutes")
    else:
        runtime_clamped = _clamp(runtime_val, _RUNTIME_MIN, _RUNTIME_MIN + Decimal("1e9"))
        runtime_score = _clamp(
            runtime_clamped / RUNTIME_REF_MINUTES, Decimal("0"), _RUNTIME_SCORE_MAX
        )
        runtime_input = runtime_score
        runtime_full = params.runtime_weight * (runtime_score - Decimal("1"))
        if getattr(features.runtime_minutes, "assumed", False):
            assumed.append("runtime_minutes")
    runtime_points = _quantize(runtime_full)

    # Franchise receptivity: franchises carry a known, ad-tolerant audience.
    franchise_val = _feature_decimal(features.franchise_flag)
    if franchise_val is None:
        franchise_input: Decimal | None = None
        franchise_full = Decimal("0")
        missing.append("franchise_flag")
    else:
        is_franchise = franchise_val > 0
        franchise_input = Decimal("1") if is_franchise else Decimal("0")
        franchise_full = params.franchise_lift if is_franchise else Decimal("0")
        if getattr(features.franchise_flag, "assumed", False):
            assumed.append("franchise_flag")
    franchise_points = _quantize(franchise_full)

    unclamped = (
        centre_full + genre_full + rating_full + runtime_full + franchise_full
    )
    clamped = _clamp(unclamped, params.min_value, params.max_value)
    final = _quantize(clamped)

    feature_points_sum = (
        centre_points
        + genre_points
        + rating_points
        + runtime_points
        + franchise_points
    )
    bounds_adjustment = final - feature_points_sum

    contributions = [
        EngagementContribution(
            key="neutral_centre",
            label="Neutral Centre",
            input=None,
            coefficient=None,
            points=centre_points,
        ),
        EngagementContribution(
            key="genre_receptivity",
            label="Genre Receptivity",
            input=genre_input,
            coefficient=None,
            points=genre_points,
        ),
        EngagementContribution(
            key="rating_receptivity",
            label="Rating Receptivity",
            input=rating_input,
            coefficient=params.rating_weight,
            points=rating_points,
        ),
        EngagementContribution(
            key="runtime_receptivity",
            label="Runtime Receptivity",
            input=runtime_input,
            coefficient=params.runtime_weight,
            points=runtime_points,
        ),
        EngagementContribution(
            key="franchise_receptivity",
            label="Franchise Receptivity",
            input=franchise_input,
            coefficient=params.franchise_lift,
            points=franchise_points,
        ),
    ]

    if bounds_adjustment != 0:
        contributions.append(
            EngagementContribution(
                key="bounds_adjustment",
                label="Bounds Adjustment",
                input=None,
                coefficient=None,
                points=bounds_adjustment,
            )
        )

    return AdLoadReceptivityResult(
        ad_load_receptivity=final,
        method=_METHOD_CALCULATED,
        breakdown=tuple(contributions),
        missing_features=tuple(missing),
        params_source=params_source,
        unclamped=unclamped,
        assumed_features=tuple(assumed),
    )


def resolve_ad_load_receptivity(
    supplied: object,
    features: FeatureVector,
    params: AdLoadReceptivityParams,
    params_source: str,
) -> AdLoadReceptivityResult:
    """Resolve Ad_Load_Receptivity, supplied value winning (Property 6).

    When ``supplied`` coerces to a finite numeric (including 0), it is returned
    exactly with method SUPPLIED -- no clamp, no re-round, no breakdown.
    Otherwise the model is computed via :func:`calculate_ad_load_receptivity`.
    The resolved value is always a multiplier, never a dollar CPM.
    """
    value = coerce_supplied(supplied)
    if value is not None:
        return AdLoadReceptivityResult(
            ad_load_receptivity=value,
            method=_METHOD_SUPPLIED,
            breakdown=None,
            missing_features=(),
            params_source=params_source,
            unclamped=None,
            assumed_features=(),
        )
    return calculate_ad_load_receptivity(features, params, params_source)
