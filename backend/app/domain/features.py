"""Pure feature-derivation module for the Content_Eval_System (content-eval-model).

Turns raw, already-fetched title attributes plus licensed open-data correlates
into a typed, explainable :class:`FeatureVector` -- the single feature contract
shared by the engine path, the KPI_Test_Dataset generator, and the
Backtest_Harness, so every consumer derives features the same way (R2.1).

The vector is organized into three feature groups (all title-level, zero PII,
R2.3):

- **Intrinsic** -- attributes carried on the title itself: ``asset_type``,
  ``genre``, ``content_format``, ``runtime_minutes``, ``is_exclusive``,
  ``production_scale``, ``talent_pedigree``. These reuse the fields the churn
  model and the metadata radar already consume.
- **Open-data popularity/quality correlates** -- signals sourced from a named
  Open_Data_Source: ``normalized_rating`` (e.g. a TMDB/IMDb vote average scaled
  to [0, 1]), ``log_vote_count`` (log-normalized vote/popularity volume),
  ``franchise_flag`` (a 0/1 sequel/franchise indicator from Wikidata), and
  ``award_signal`` (a [0, 1] award correlate). Every correlate has a neutral
  default and an ``assumed`` flag when absent, so a data gap never contributes a
  penalizing zero (R2.4).
- **Temporal** -- ``release_year``, which drives the Temporal_Split only and is
  NEVER used as a predictive feature (modeling on release year would leak the
  very trend the split exists to guard against).

Each feature is wrapped in a frozen :class:`Feature` carrying ``(value, source,
assumed)`` metadata so the downstream breakdown can report provenance and flag
assumed values exactly as the churn model's ``assumed_features`` does.

``normalize_*`` helpers mirror :func:`app.domain.churn.normalize_genre`. The
module exposes :func:`derive_features`, a pure function that receives an
already-fetched raw mapping (open-data access and caching happen in the offline
generator / connector layer, never here, consistent with how ``churn.py``
receives ``Telemetry_Heat`` rather than querying for it). Unknown raw keys are
ignored so a new Open_Data_Source never breaks an older fitted Content_Eval_
Version, which resolves using only the features it was fitted on (R7.2, R9.7).

This module is pure: no I/O, no database access, no async, no network, no global
mutable state. All numeric work uses :class:`decimal.Decimal` precision and it
imports only the Python standard library, so it is importable without the
application framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

__all__ = [
    "SOURCE_TITLE",
    "SOURCE_DEFAULT",
    "RATING_MIN",
    "RATING_MAX",
    "RATING_NEUTRAL",
    "VOTE_COUNT_MIN",
    "LOG_VOTE_COUNT_NEUTRAL",
    "FRANCHISE_NEUTRAL",
    "AWARD_MIN",
    "AWARD_MAX",
    "AWARD_NEUTRAL",
    "RUNTIME_NEUTRAL",
    "PEDIGREE_MIN",
    "PEDIGREE_MAX",
    "SCALE_MIN",
    "SCALE_MAX",
    "PREDICTIVE_FEATURES",
    "Feature",
    "FeatureVector",
    "normalize_label",
    "normalize_genre",
    "normalize_asset_type",
    "derive_features",
]

# ---------------------------------------------------------------------------
# Provenance tags and feature domains
# ---------------------------------------------------------------------------

# Where a resolved feature value came from. A feature resolved from the raw
# title/open-data input is tagged with its concrete source; a feature that fell
# back to its neutral default (a data gap) is tagged DEFAULTS and flagged
# assumed, mirroring churn's DEFAULTS source + assumed_features distinction.
SOURCE_TITLE = "TITLE"
SOURCE_DEFAULT = "DEFAULTS"

# normalized_rating domain: a [0, 1] scaled rating. A missing rating uses the
# neutral mid-point 0.5 (not 0, which would read as "universally panned").
RATING_MIN = Decimal("0")
RATING_MAX = Decimal("1")
RATING_NEUTRAL = Decimal("0.5")

# log_vote_count domain: log(1 + votes) is always >= 0. A missing vote count
# uses a neutral low-but-nonzero prior rather than 0 (0 would read as "no
# audience signal whatsoever" and over-penalize an unmeasured title).
VOTE_COUNT_MIN = Decimal("0")
LOG_VOTE_COUNT_NEUTRAL = Decimal("2.0")

# franchise_flag domain: a 0/1 indicator. Absent franchise data is neutral at 0
# (standalone is the common, non-penalizing default), and is still flagged
# assumed so the gap is visible.
FRANCHISE_NEUTRAL = Decimal("0")

# award_signal domain: a [0, 1] award correlate. A missing award signal uses a
# small neutral prior rather than 0.
AWARD_MIN = Decimal("0")
AWARD_MAX = Decimal("1")
AWARD_NEUTRAL = Decimal("0.1")

# runtime_minutes: a missing runtime uses a neutral typical runtime rather than
# 0 (a 0-minute title would distort any runtime-sensitive model).
RUNTIME_NEUTRAL = Decimal("60")

# Intrinsic numeric domains reused from the churn model's conventions.
PEDIGREE_MIN = Decimal("0")
PEDIGREE_MAX = Decimal("10")
SCALE_MIN = Decimal("0")
SCALE_MAX = Decimal("10")

# The ordered set of features a Content_Eval_Model may consume as predictors.
# release_year is deliberately excluded: it is split-only and never predictive.
PREDICTIVE_FEATURES = (
    "asset_type",
    "genre",
    "content_format",
    "runtime_minutes",
    "is_exclusive",
    "production_scale",
    "talent_pedigree",
    "normalized_rating",
    "log_vote_count",
    "franchise_flag",
    "award_signal",
)

# ---------------------------------------------------------------------------
# Normalization helpers (mirror churn.normalize_genre)
# ---------------------------------------------------------------------------


def normalize_label(label: str | None) -> str | None:
    """Normalize a free-text label to a lookup key (lowercased, trimmed, hyphenated).

    Spaces and underscores collapse to a single hyphen so "Crime Biopic",
    "crime_biopic", and "crime-biopic" all map to the same key. Returns ``None``
    for a blank/absent label. This is the generalized form of
    :func:`app.domain.churn.normalize_genre`, shared by every label feature.
    """
    if label is None:
        return None
    text = label.strip().lower()
    if not text:
        return None
    for sep in (" ", "_"):
        text = text.replace(sep, "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text or None


def normalize_genre(genre: str | None) -> str | None:
    """Normalize a genre label to its lookup key (see :func:`normalize_label`)."""
    return normalize_label(genre)


def normalize_asset_type(asset_type: str | None) -> str | None:
    """Normalize an asset-type label to an UPPER_SNAKE_CASE key.

    Mirrors the churn model's asset-type keys (e.g. ``ORIGINAL_SERIES``):
    trimmed, uppercased, with spaces/hyphens collapsed to single underscores.
    Returns ``None`` for a blank/absent value.
    """
    if asset_type is None:
        return None
    text = asset_type.strip().upper()
    if not text:
        return None
    for sep in (" ", "-"):
        text = text.replace(sep, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or None


# ---------------------------------------------------------------------------
# Coercion helpers (pure, never raise)
# ---------------------------------------------------------------------------


def _coerce_decimal(raw: object) -> Decimal | None:
    """Coerce a raw value to a finite :class:`Decimal`, else ``None``.

    Accepts ``Decimal``, ``int``, finite ``float`` (via ``str`` to avoid binary
    float noise), and numeric strings. ``bool`` is rejected (a boolean is not a
    number, matching the codebase convention). Blank/``None``/non-numeric/
    non-finite inputs yield ``None``. Never raises.
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


def _coerce_bool(raw: object) -> bool | None:
    """Coerce a raw value to a bool, else ``None`` (absent -> caller default).

    Accepts a real ``bool``, a 0/1 integer, and the common truthy/falsey string
    spellings ("true"/"false", "yes"/"no", "1"/"0"). Anything else -> ``None``.
    Never raises.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        if raw == 0:
            return False
        if raw == 1:
            return True
        return None
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("true", "yes", "y", "1"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
        return None
    return None


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# Feature + FeatureVector dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Feature:
    """A single resolved feature plus its provenance metadata.

    ``value`` is the resolved value (``None`` only for a genuinely optional
    label such as an unknown genre, never for a numeric correlate, which always
    falls back to its neutral default). ``source`` names where the value came
    from (:data:`SOURCE_TITLE` when derived from the raw input, or
    :data:`SOURCE_DEFAULT` when it fell back to a neutral default). ``assumed``
    is ``True`` exactly when the feature used a neutral default because the raw
    input was absent/invalid -- the direct analogue of churn's
    ``assumed_features``.
    """

    value: Decimal | str | bool | None
    source: str
    assumed: bool


@dataclass(frozen=True)
class FeatureVector:
    """A title's derived, explainable feature set (the shared feature contract).

    Every field is a :class:`Feature` carrying ``(value, source, assumed)``.
    Fields are grouped as intrinsic, open-data correlate, and temporal.
    ``release_year`` is split-only metadata and MUST NOT be read as a predictive
    feature; :data:`PREDICTIVE_FEATURES` is the authoritative predictor list and
    deliberately omits it.

    ``assumed_features`` is a convenience tuple (computed at construction) of the
    names of every field that fell back to a neutral default, so a consumer can
    surface a title's data gaps the same way the churn result exposes them.
    """

    # Intrinsic.
    asset_type: Feature
    genre: Feature
    content_format: Feature
    runtime_minutes: Feature
    is_exclusive: Feature
    production_scale: Feature
    talent_pedigree: Feature
    # Open-data popularity/quality correlates.
    normalized_rating: Feature
    log_vote_count: Feature
    franchise_flag: Feature
    award_signal: Feature
    # Temporal (split-only; never a predictive feature).
    release_year: Feature

    assumed_features: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        assumed = tuple(
            name
            for name in (
                "asset_type",
                "genre",
                "content_format",
                "runtime_minutes",
                "is_exclusive",
                "production_scale",
                "talent_pedigree",
                "normalized_rating",
                "log_vote_count",
                "franchise_flag",
                "award_signal",
            )
            if getattr(self, name).assumed
        )
        # Frozen dataclass: set the derived field via object.__setattr__.
        object.__setattr__(self, "assumed_features", assumed)


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _label_feature(raw: object, normalizer) -> Feature:
    """Resolve a label feature (genre / asset_type / content_format).

    A present, non-blank label normalizes to its key with source
    :data:`SOURCE_TITLE`; an absent/blank label resolves to ``None`` with source
    :data:`SOURCE_DEFAULT` and ``assumed=True`` (an unknown label is a data gap,
    reported but never penalizing -- the consuming model applies its own neutral
    default weight, exactly as churn does for an unknown genre).
    """
    key = normalizer(raw) if isinstance(raw, str) else None
    if key is None:
        return Feature(value=None, source=SOURCE_DEFAULT, assumed=True)
    return Feature(value=key, source=SOURCE_TITLE, assumed=False)


def _numeric_feature(
    raw: object,
    neutral: Decimal,
    low: Decimal | None = None,
    high: Decimal | None = None,
) -> Feature:
    """Resolve a numeric feature, clamping to [low, high] and defaulting neutrally.

    A finite numeric input is clamped to its documented domain (when bounds are
    given) with source :data:`SOURCE_TITLE`; an absent/invalid input uses the
    neutral default with source :data:`SOURCE_DEFAULT` and ``assumed=True``. The
    neutral default is never a penalizing zero (R2.4).
    """
    value = _coerce_decimal(raw)
    if value is None:
        return Feature(value=neutral, source=SOURCE_DEFAULT, assumed=True)
    if low is not None and high is not None:
        value = _clamp(value, low, high)
    elif low is not None and value < low:
        value = low
    return Feature(value=value, source=SOURCE_TITLE, assumed=False)


def derive_features(raw: Mapping | None) -> FeatureVector:
    """Derive a :class:`FeatureVector` from an already-fetched raw mapping (pure).

    This is a pure function of ``raw``: no I/O, no fetching, no global state. It
    reads only known keys and IGNORES any unknown key, so a newly onboarded
    Open_Data_Source feature never disturbs an older fitted Content_Eval_Version
    (R7.2, R9.7). A ``None`` / non-mapping ``raw`` yields an all-defaults vector
    (every feature assumed) rather than raising, matching the graceful-
    degradation posture of the churn model (R2.4).

    Recognized intrinsic keys: ``asset_type``, ``genre``, ``content_format``,
    ``runtime_minutes``, ``is_exclusive``, ``production_scale``,
    ``talent_pedigree``. Recognized open-data correlate keys:
    ``normalized_rating``, ``log_vote_count``, ``franchise_flag``,
    ``award_signal``. Recognized temporal key: ``release_year`` (split-only).

    Every absent open-data correlate falls back to its neutral default (never a
    penalizing zero) and is flagged ``assumed`` in the returned vector.
    """
    data: Mapping = raw if isinstance(raw, Mapping) else {}

    # Intrinsic labels.
    asset_type = _label_feature(data.get("asset_type"), normalize_asset_type)
    genre = _label_feature(data.get("genre"), normalize_genre)
    content_format = _label_feature(data.get("content_format"), normalize_label)

    # Intrinsic numerics.
    runtime_minutes = _numeric_feature(
        data.get("runtime_minutes"), RUNTIME_NEUTRAL, low=Decimal("0")
    )
    production_scale = _numeric_feature(
        data.get("production_scale"),
        # No real reading -> neutral midpoint of the 0-10 scale, not 0.
        (SCALE_MIN + SCALE_MAX) / Decimal("2"),
        low=SCALE_MIN,
        high=SCALE_MAX,
    )
    talent_pedigree = _numeric_feature(
        data.get("talent_pedigree"),
        (PEDIGREE_MIN + PEDIGREE_MAX) / Decimal("2"),
        low=PEDIGREE_MIN,
        high=PEDIGREE_MAX,
    )

    # Intrinsic bool: absent -> neutral False (standalone is the common,
    # non-penalizing default), flagged assumed so the gap stays visible.
    excl_bool = _coerce_bool(data.get("is_exclusive"))
    if excl_bool is None:
        is_exclusive = Feature(value=False, source=SOURCE_DEFAULT, assumed=True)
    else:
        is_exclusive = Feature(value=excl_bool, source=SOURCE_TITLE, assumed=False)

    # Open-data popularity/quality correlates (neutral defaults, never 0-penalty).
    normalized_rating = _numeric_feature(
        data.get("normalized_rating"), RATING_NEUTRAL, low=RATING_MIN, high=RATING_MAX
    )
    log_vote_count = _numeric_feature(
        data.get("log_vote_count"), LOG_VOTE_COUNT_NEUTRAL, low=VOTE_COUNT_MIN
    )
    award_signal = _numeric_feature(
        data.get("award_signal"), AWARD_NEUTRAL, low=AWARD_MIN, high=AWARD_MAX
    )

    # Franchise flag is an indicator: coerce to 0/1; absent -> neutral 0 assumed.
    franchise_bool = _coerce_bool(data.get("franchise_flag"))
    if franchise_bool is None:
        franchise_flag = Feature(
            value=FRANCHISE_NEUTRAL, source=SOURCE_DEFAULT, assumed=True
        )
    else:
        franchise_flag = Feature(
            value=Decimal("1") if franchise_bool else Decimal("0"),
            source=SOURCE_TITLE,
            assumed=False,
        )

    # Temporal split field: NEVER a predictive feature. Absent -> None/assumed.
    year = _coerce_decimal(data.get("release_year"))
    if year is None:
        release_year = Feature(value=None, source=SOURCE_DEFAULT, assumed=True)
    else:
        release_year = Feature(
            value=year.to_integral_value(), source=SOURCE_TITLE, assumed=False
        )

    return FeatureVector(
        asset_type=asset_type,
        genre=genre,
        content_format=content_format,
        runtime_minutes=runtime_minutes,
        is_exclusive=is_exclusive,
        production_scale=production_scale,
        talent_pedigree=talent_pedigree,
        normalized_rating=normalized_rating,
        log_vote_count=log_vote_count,
        franchise_flag=franchise_flag,
        award_signal=award_signal,
        release_year=release_year,
    )
