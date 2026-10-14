"""Pure domain module for the Churn_Mitigation_Model (calculable-churn-model).

Replaces the former hard-coded churn-reduction input with a transparent,
deterministic, additive, versioned model. The calculated churn-reduction
percentage is the additive sum of per-feature contributions:

    intercept
  + asset-type offset
  + pedigree_weight  * pedigree score      (score clamped to [0, 10])
  + scale_weight     * production scale     (score clamped to [0, 10])
  + exclusivity_lift  (when the title is exclusive, else 0)
  + telemetry_weight * Telemetry_Heat       (heat clamped to [0, 100])
  + genre weight      (per-genre, else a neutral default)

Every point of a calculated result is traceable to a feature via the ordered
:class:`ChurnContribution` breakdown; a single ``bounds_adjustment`` entry
absorbs the clamp delta and any quantization residual so the breakdown always
conserves to the final value at 2 dp. An explicitly supplied finite value
overrides the calculation exactly (SUPPLIED), and values within +/- 0.05 of the
1.5 percent hurdle are flagged borderline.

Two features degrade gracefully rather than scoring zero (which would penalize a
data gap): a missing Telemetry_Heat uses a neutral mid-value, and an unknown or
absent genre uses a neutral default weight. Both are reported in
``assumed_features`` (distinct from ``missing_features``, which is reserved for
pedigree / production scale / asset type that genuinely contribute 0 when absent).

The coefficients in :data:`DEFAULT_CHURN_MODEL_PARAMS` are Illustrative_Coefficients:
tuned to the five demo titles, not fitted to real subscriber-outcome data.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic is performed with :class:`decimal.Decimal` precision and
it imports only the Python standard library, so it is importable without the
application framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = [
    "CHURN_MITIGATION_THRESHOLD",
    "BORDERLINE_BAND",
    "MIN_CHURN",
    "MAX_CHURN",
    "DEFAULT_GENRE_OFFSETS",
    "DEFAULT_GENRE_WEIGHT",
    "DEFAULT_TELEMETRY_NEUTRAL",
    "DEFAULT_FORMAT_OFFSETS",
    "DEFAULT_FORMAT_WEIGHT",
    "DEFAULT_CHURN_MODEL_PARAMS",
    "ChurnModelParams",
    "ChurnFeatures",
    "ChurnContribution",
    "ChurnResult",
    "normalize_genre",
    "is_borderline",
    "coerce_supplied",
    "parse_params",
    "calculate_churn_mitigation",
    "resolve_churn",
]

CHURN_MITIGATION_THRESHOLD = Decimal("1.5")  # mirror of the engine hurdle
BORDERLINE_BAND = Decimal("0.05")  # inclusive band [1.45, 1.55]
MIN_CHURN = Decimal("0.10")
MAX_CHURN = Decimal("5.00")
_Q = Decimal("0.01")  # 2 dp, ROUND_HALF_UP

# Feature-domain clamp bounds.
_PEDIGREE_MIN = Decimal("0")
_PEDIGREE_MAX = Decimal("10")
_SCALE_MIN = Decimal("0")
_SCALE_MAX = Decimal("10")
_HEAT_MIN = Decimal("0")
_HEAT_MAX = Decimal("100")

# The four known asset types (used only for defaults; unknown types -> 0 offset).
_ASSET_TYPES = (
    "ORIGINAL_SERIES",
    "CO_PRODUCTION",
    "ORIGINAL_FILM",
    "LICENSED_LIBRARY",
)

# Canonical per-genre churn weights (retention propensity, pct points). Keys are
# normalized (lowercased, spaces/underscores -> hyphen). Serialized / returning
# formats (crime, drama, thriller, reality) retain subscribers more than
# one-and-done formats (documentary, kids, musical), so they weigh more. These
# are Illustrative_Coefficients tuned to the demo, not fitted to real data.
DEFAULT_GENRE_OFFSETS: Mapping[str, Decimal] = {
    "crime": Decimal("0.18"),
    "crime-biopic": Decimal("0.17"),
    "drama": Decimal("0.15"),
    "thriller": Decimal("0.15"),
    "reality": Decimal("0.15"),
    "mystery": Decimal("0.14"),
    "sci-fi": Decimal("0.12"),
    "fantasy": Decimal("0.12"),
    "biopic": Decimal("0.11"),
    "romance": Decimal("0.10"),
    "action": Decimal("0.10"),
    "adventure": Decimal("0.09"),
    "historical": Decimal("0.09"),
    "war": Decimal("0.09"),
    "horror": Decimal("0.08"),
    "sports": Decimal("0.08"),
    "family": Decimal("0.07"),
    "animation": Decimal("0.07"),
    "anthology": Decimal("0.07"),
    "comedy": Decimal("0.05"),
    "documentary": Decimal("0.05"),
    "kids": Decimal("0.05"),
    "musical": Decimal("0.05"),
    "western": Decimal("0.05"),
}

# Neutral genre weight for an unknown / absent genre (mid of the range, not 0 and
# not the max), so a title in an unseeded genre still gets a rational score.
DEFAULT_GENRE_WEIGHT = Decimal("0.10")

# Neutral Telemetry_Heat (0-100 scale) used when no cached reading exists, so a
# data gap does not score as zero buzz.
DEFAULT_TELEMETRY_NEUTRAL = Decimal("50")

# Canonical content-format lifts (calculable-churn-model Addendum B, R17). An
# ADDITIVE lift on top of the asset-type offset: 0 for formats the asset type
# already captures (scripted series, films, library), positive only for the
# OTT-native appointment formats the four asset types cannot express (live
# sports, live events, reality). Keys are normalized like genres.
DEFAULT_FORMAT_OFFSETS: Mapping[str, Decimal] = {
    "live-sports": Decimal("0.70"),
    "live-event": Decimal("0.50"),
    "reality-competition": Decimal("0.45"),
    "scripted-series": Decimal("0.00"),
    "limited-series": Decimal("0.00"),
    "original-film": Decimal("0.00"),
    "licensed-film": Decimal("0.00"),
    "documentary": Decimal("0.00"),
    "kids-animation": Decimal("0.00"),
    "library": Decimal("0.00"),
}

# Neutral content-format lift for an unknown/absent format. Default 0 preserves
# the pre-format behavior (asset_cadence still applies); a non-zero value would
# mark an unknown format as assumed.
DEFAULT_FORMAT_WEIGHT = Decimal("0.00")

_SOURCE_MODEL_VERSION = "MODEL_VERSION"
_SOURCE_DEFAULTS = "DEFAULTS"

_METHOD_CALCULATED = "CALCULATED"
_METHOD_SUPPLIED = "SUPPLIED"


def normalize_genre(genre: str | None) -> str | None:
    """Normalize a genre label to its lookup key (lowercased, trimmed, hyphenated).

    Spaces and underscores collapse to a single hyphen so "Crime Biopic",
    "crime_biopic", and "crime-biopic" all map to the same key. Returns ``None``
    for a blank/absent genre.
    """
    if genre is None:
        return None
    text = genre.strip().lower()
    if not text:
        return None
    for sep in (" ", "_"):
        text = text.replace(sep, "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text or None


@dataclass(frozen=True)
class ChurnModelParams:
    """Parameters for the additive churn model. All feature weights/offsets are
    non-negative; ``min_churn <= max_churn``."""

    intercept: Decimal
    asset_offsets: Mapping[str, Decimal]
    pedigree_weight: Decimal
    scale_weight: Decimal
    exclusivity_lift: Decimal
    telemetry_weight: Decimal
    min_churn: Decimal
    max_churn: Decimal
    genre_offsets: Mapping[str, Decimal] = field(default_factory=dict)
    genre_default: Decimal = DEFAULT_GENRE_WEIGHT
    telemetry_neutral: Decimal = DEFAULT_TELEMETRY_NEUTRAL
    format_offsets: Mapping[str, Decimal] = field(default_factory=dict)
    format_default: Decimal = DEFAULT_FORMAT_WEIGHT


@dataclass(frozen=True)
class ChurnFeatures:
    """A title's observable features fed to the model.

    A ``None`` numeric feature (pedigree / production scale) is treated as
    missing (contributes 0). An unknown or ``None`` ``asset_type`` yields a zero
    asset offset. ``is_exclusive`` is a plain bool. ``telemetry_heat`` of ``None``
    uses the neutral default (not 0). ``genre`` of ``None`` / unknown uses the
    neutral genre default.
    """

    asset_type: str | None
    pedigree: Decimal | None
    production_scale: Decimal | None
    is_exclusive: bool
    telemetry_heat: Decimal | None  # 0-100 scale; None -> neutral default
    genre: str | None = None  # unknown/absent -> neutral genre default
    content_format: str | None = None  # unknown/absent -> neutral format lift


@dataclass(frozen=True)
class ChurnContribution:
    """A single per-feature contribution within the breakdown."""

    key: str
    label: str
    input: Decimal | None  # feature value used (None when missing/NA)
    coefficient: Decimal | None  # per-unit weight (None for intercept/offset/adj)
    points: Decimal  # quantized contribution in pct points


@dataclass(frozen=True)
class ChurnResult:
    """The resolved churn-reduction percentage plus explanation metadata."""

    churn_reduction_pct: Decimal
    method: str  # "CALCULATED" | "SUPPLIED"
    is_borderline: bool
    breakdown: tuple[ChurnContribution, ...] | None  # None when SUPPLIED
    missing_features: tuple[str, ...]
    params_source: str  # "MODEL_VERSION" | "DEFAULTS"
    unclamped: Decimal | None  # pre-clamp calculated value (None when SUPPLIED)
    assumed_features: tuple[str, ...] = ()  # used a neutral default (not a real reading)


DEFAULT_CHURN_MODEL_PARAMS = ChurnModelParams(
    intercept=Decimal("0.03"),
    asset_offsets={
        "ORIGINAL_SERIES": Decimal("0.35"),
        "CO_PRODUCTION": Decimal("0.45"),
        "ORIGINAL_FILM": Decimal("0.15"),
        "LICENSED_LIBRARY": Decimal("0.00"),
    },
    pedigree_weight=Decimal("0.09"),
    scale_weight=Decimal("0.03"),
    exclusivity_lift=Decimal("0.25"),
    telemetry_weight=Decimal("0.005"),
    min_churn=MIN_CHURN,
    max_churn=MAX_CHURN,
    genre_offsets=DEFAULT_GENRE_OFFSETS,
    genre_default=DEFAULT_GENRE_WEIGHT,
    telemetry_neutral=DEFAULT_TELEMETRY_NEUTRAL,
    format_offsets=DEFAULT_FORMAT_OFFSETS,
    format_default=DEFAULT_FORMAT_WEIGHT,
)


def is_borderline(value: Decimal) -> bool:
    """True when ``value`` lies within +/- ``BORDERLINE_BAND`` of the 1.5 hurdle,
    i.e. in the inclusive band [1.45, 1.55] (R5.1, R5.2)."""
    return abs(value - CHURN_MITIGATION_THRESHOLD) <= BORDERLINE_BAND


def coerce_supplied(raw: object) -> Decimal | None:
    """Coerce a raw supplied churn value to a finite :class:`Decimal`, or ``None``.

    Blank, ``None``, non-numeric, non-finite, or boolean inputs yield ``None``
    (treated as "not supplied", R4.3). A finite numeric value (including 0, a
    pass-through ``Decimal``, an ``int``, a numeric string, or a finite float)
    yields a ``Decimal`` (R4.4). ``bool`` is rejected to match the codebase
    convention that a boolean is not a number. Never raises.
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


def _parse_genre_offsets(raw: object) -> Mapping[str, Decimal] | None:
    """Parse a genre_offsets mapping of non-negative Decimals, else ``None``.

    An absent mapping is tolerated by the caller (falls back to defaults). A
    present-but-malformed mapping (non-mapping, or any negative/non-numeric
    weight) is rejected so the whole param set falls back to defaults.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _REJECT  # type: ignore[return-value]
    offsets: dict[str, Decimal] = {}
    for key, value in raw.items():
        weight = _coerce_param(value)
        if weight is None:
            return _REJECT  # type: ignore[return-value]
        norm = normalize_genre(str(key))
        if norm is not None:
            offsets[norm] = weight
    return offsets


# Sentinel distinguishing "absent" (use defaults) from "present but invalid"
# (reject the whole param block) for genre_offsets.
_REJECT: Mapping[str, Decimal] = {"__reject__": Decimal("-1")}


def parse_params(raw: Mapping | None) -> tuple[ChurnModelParams, str]:
    """Parse a ``churn_model`` mapping into (:class:`ChurnModelParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_CHURN_MODEL_PARAMS, "DEFAULTS")`` (R3.2). A valid parse requires
    the intercept, all four asset offsets, and every scalar weight to coerce to
    finite non-negative Decimals, and the bounds to be finite with
    ``min_churn <= max_churn``. The genre fields and telemetry_neutral are
    optional: when absent they fall back to the built-in defaults; when present
    they must be valid (non-negative), else the whole block falls back. Never
    raises.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS

    intercept = _coerce_param(raw.get("intercept"))
    pedigree_weight = _coerce_param(raw.get("pedigree_weight"))
    scale_weight = _coerce_param(raw.get("scale_weight"))
    exclusivity_lift = _coerce_param(raw.get("exclusivity_lift"))
    telemetry_weight = _coerce_param(raw.get("telemetry_weight"))
    min_churn = _coerce_param(raw.get("min_churn"))
    max_churn = _coerce_param(raw.get("max_churn"))

    if any(
        v is None
        for v in (
            intercept,
            pedigree_weight,
            scale_weight,
            exclusivity_lift,
            telemetry_weight,
            min_churn,
            max_churn,
        )
    ):
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS

    if min_churn > max_churn:  # type: ignore[operator]
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS

    raw_offsets = raw.get("asset_offsets")
    if not isinstance(raw_offsets, Mapping):
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS

    offsets: dict[str, Decimal] = {}
    for asset_type in _ASSET_TYPES:
        offset = _coerce_param(raw_offsets.get(asset_type))
        if offset is None:
            return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
        offsets[asset_type] = offset

    # Optional genre offsets: absent -> defaults; present-invalid -> reject.
    genre_offsets = _parse_genre_offsets(raw.get("genre_offsets"))
    if genre_offsets is _REJECT:
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
    if genre_offsets is None:
        genre_offsets = DEFAULT_GENRE_OFFSETS

    # Optional neutral defaults: absent -> built-in; present must be valid.
    if "genre_default" in raw:
        genre_default = _coerce_param(raw.get("genre_default"))
        if genre_default is None:
            return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
    else:
        genre_default = DEFAULT_GENRE_WEIGHT

    if "telemetry_neutral" in raw:
        telemetry_neutral = _coerce_param(raw.get("telemetry_neutral"))
        if telemetry_neutral is None:
            return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
    else:
        telemetry_neutral = DEFAULT_TELEMETRY_NEUTRAL

    # Optional content-format lifts: absent -> defaults; present-invalid -> reject.
    format_offsets = _parse_genre_offsets(raw.get("format_offsets"))
    if format_offsets is _REJECT:
        return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
    if format_offsets is None:
        format_offsets = DEFAULT_FORMAT_OFFSETS

    if "format_default" in raw:
        format_default = _coerce_param(raw.get("format_default"))
        if format_default is None:
            return DEFAULT_CHURN_MODEL_PARAMS, _SOURCE_DEFAULTS
    else:
        format_default = DEFAULT_FORMAT_WEIGHT

    params = ChurnModelParams(
        intercept=intercept,  # type: ignore[arg-type]
        asset_offsets=offsets,
        pedigree_weight=pedigree_weight,  # type: ignore[arg-type]
        scale_weight=scale_weight,  # type: ignore[arg-type]
        exclusivity_lift=exclusivity_lift,  # type: ignore[arg-type]
        telemetry_weight=telemetry_weight,  # type: ignore[arg-type]
        min_churn=min_churn,  # type: ignore[arg-type]
        max_churn=max_churn,  # type: ignore[arg-type]
        genre_offsets=genre_offsets,
        genre_default=genre_default,  # type: ignore[arg-type]
        telemetry_neutral=telemetry_neutral,  # type: ignore[arg-type]
        format_offsets=format_offsets,
        format_default=format_default,  # type: ignore[arg-type]
    )
    return params, _SOURCE_MODEL_VERSION


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _quantize(value: Decimal) -> Decimal:
    """Quantize to 2 dp using half-up rounding."""
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def calculate_churn_mitigation(
    features: ChurnFeatures,
    params: ChurnModelParams,
    params_source: str = _SOURCE_DEFAULTS,
) -> ChurnResult:
    """Compute the additive churn-reduction percentage from ``features`` (R1, R2, R14, R15).

    Numeric feature domains are clamped before use (pedigree/scale to [0, 10],
    heat to [0, 100]). A ``None`` pedigree/production-scale contributes 0 and is
    recorded in ``missing_features``; an unknown/``None`` asset type yields a
    zero offset and adds ``"asset_type"`` to ``missing_features``. A ``None``
    telemetry heat uses ``params.telemetry_neutral`` (R15) and an unknown/absent
    genre uses ``params.genre_default`` (R14.3); both are recorded in
    ``assumed_features`` (they still contribute, just from a neutral default).
    Each contribution is computed at full precision then quantized to 2 dp
    half-up. The result is clamped to the parameter bounds and rounded; a
    ``bounds_adjustment`` entry (only when nonzero) absorbs the clamp delta and
    quantization residual so the breakdown sums exactly to the final value (R1.8).
    """
    missing: list[str] = []
    assumed: list[str] = []

    # Base platform rate (intercept).
    base_full = params.intercept
    base_points = _quantize(base_full)

    # Asset cadence (asset-type offset).
    asset_type = features.asset_type
    if asset_type is None or asset_type not in params.asset_offsets:
        offset_full = Decimal("0")
        asset_input: Decimal | None = None
        missing.append("asset_type")
    else:
        offset_full = params.asset_offsets[asset_type]
        asset_input = offset_full
    asset_points = _quantize(offset_full)

    # Talent pedigree contribution.
    if features.pedigree is None or not features.pedigree.is_finite():
        pedigree_input: Decimal | None = None
        pedigree_full = Decimal("0")
        missing.append("pedigree")
    else:
        pedigree_input = _clamp(features.pedigree, _PEDIGREE_MIN, _PEDIGREE_MAX)
        pedigree_full = params.pedigree_weight * pedigree_input
    pedigree_points = _quantize(pedigree_full)

    # Production scale contribution.
    if features.production_scale is None or not features.production_scale.is_finite():
        scale_input: Decimal | None = None
        scale_full = Decimal("0")
        missing.append("production_scale")
    else:
        scale_input = _clamp(features.production_scale, _SCALE_MIN, _SCALE_MAX)
        scale_full = params.scale_weight * scale_input
    scale_points = _quantize(scale_full)

    # Exclusivity lift.
    if features.is_exclusive:
        excl_full = params.exclusivity_lift
        excl_input: Decimal | None = Decimal("1")
    else:
        excl_full = Decimal("0")
        excl_input = Decimal("0")
    excl_points = _quantize(excl_full)

    # Market telemetry heat: a missing reading uses the neutral default (R15).
    if features.telemetry_heat is None or not features.telemetry_heat.is_finite():
        heat_input = _clamp(params.telemetry_neutral, _HEAT_MIN, _HEAT_MAX)
        heat_full = params.telemetry_weight * heat_input
        assumed.append("telemetry_heat")
    else:
        heat_input = _clamp(features.telemetry_heat, _HEAT_MIN, _HEAT_MAX)
        heat_full = params.telemetry_weight * heat_input
    heat_points = _quantize(heat_full)

    # Genre affinity: unknown/absent genre uses the neutral default (R14.3).
    norm_genre = normalize_genre(features.genre)
    if norm_genre is not None and norm_genre in params.genre_offsets:
        genre_full = params.genre_offsets[norm_genre]
        genre_input: Decimal | None = genre_full
    else:
        genre_full = params.genre_default
        genre_input = genre_full
        assumed.append("genre")
    genre_points = _quantize(genre_full)

    # Content format: an additive lift for OTT-native appointment formats (live
    # sports / events / reality) the asset type cannot express; 0 for formats the
    # asset offset already covers (R17.1, R17.3). An unknown/absent format uses
    # the neutral default (0 by default); it is only recorded as assumed when the
    # configured default is non-zero (a 0 default is simply "no extra signal").
    norm_format = normalize_genre(features.content_format)
    if norm_format is not None and norm_format in params.format_offsets:
        format_full = params.format_offsets[norm_format]
        format_input: Decimal | None = format_full
    else:
        format_full = params.format_default
        format_input = format_full
        if params.format_default != 0:
            assumed.append("content_format")
    format_points = _quantize(format_full)

    unclamped = (
        base_full
        + offset_full
        + pedigree_full
        + scale_full
        + excl_full
        + heat_full
        + genre_full
        + format_full
    )
    clamped = _clamp(unclamped, params.min_churn, params.max_churn)
    final = _quantize(clamped)

    feature_points_sum = (
        base_points
        + asset_points
        + pedigree_points
        + scale_points
        + excl_points
        + heat_points
        + genre_points
        + format_points
    )
    bounds_adjustment = final - feature_points_sum

    contributions = [
        ChurnContribution(
            key="base_platform_rate",
            label="Base Platform Rate",
            input=None,
            coefficient=None,
            points=base_points,
        ),
        ChurnContribution(
            key="asset_cadence",
            label="Asset Cadence",
            input=asset_input,
            coefficient=None,
            points=asset_points,
        ),
        ChurnContribution(
            key="talent_pedigree_contribution",
            label="Talent Pedigree Contribution",
            input=pedigree_input,
            coefficient=params.pedigree_weight,
            points=pedigree_points,
        ),
        ChurnContribution(
            key="production_scale_contribution",
            label="Production Scale Contribution",
            input=scale_input,
            coefficient=params.scale_weight,
            points=scale_points,
        ),
        ChurnContribution(
            key="exclusivity_lift",
            label="Exclusivity Lift",
            input=excl_input,
            coefficient=params.exclusivity_lift,
            points=excl_points,
        ),
        ChurnContribution(
            key="market_telemetry_heat",
            label="Market Telemetry Heat",
            input=heat_input,
            coefficient=params.telemetry_weight,
            points=heat_points,
        ),
        ChurnContribution(
            key="genre_affinity",
            label="Genre Affinity",
            input=genre_input,
            coefficient=None,
            points=genre_points,
        ),
        ChurnContribution(
            key="content_format",
            label="Content Format",
            input=format_input,
            coefficient=None,
            points=format_points,
        ),
    ]

    if bounds_adjustment != 0:
        contributions.append(
            ChurnContribution(
                key="bounds_adjustment",
                label="Bounds Adjustment",
                input=None,
                coefficient=None,
                points=bounds_adjustment,
            )
        )

    return ChurnResult(
        churn_reduction_pct=final,
        method=_METHOD_CALCULATED,
        is_borderline=is_borderline(final),
        breakdown=tuple(contributions),
        missing_features=tuple(missing),
        params_source=params_source,
        unclamped=unclamped,
        assumed_features=tuple(assumed),
    )


def resolve_churn(
    supplied: object,
    features: ChurnFeatures,
    params: ChurnModelParams,
    params_source: str,
) -> ChurnResult:
    """Resolve the churn-reduction percentage, supplied value winning (R4).

    When ``supplied`` coerces to a finite numeric (including 0), it is returned
    exactly with method SUPPLIED, no clamp, no re-round, no breakdown, and the
    borderline flag computed on the supplied value. Otherwise the model is
    computed via :func:`calculate_churn_mitigation` with ``params_source``
    attached.
    """
    value = coerce_supplied(supplied)
    if value is not None:
        return ChurnResult(
            churn_reduction_pct=value,
            method=_METHOD_SUPPLIED,
            is_borderline=is_borderline(value),
            breakdown=None,
            missing_features=(),
            params_source=params_source,
            unclamped=None,
            assumed_features=(),
        )
    return calculate_churn_mitigation(features, params, params_source)