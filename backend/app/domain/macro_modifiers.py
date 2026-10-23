"""Pure domain module for the Macro_Modifiers driver (Driver D).

Driver D adds four multiplicative market modifiers, each with a documented
domain table and inclusive clamp. An absent or unrecognized descriptor resolves
to the neutral ``1.00`` and is recorded as assumed (R4.1). The four modifiers
are:

- **Source_IP_Provenance** -- a lookup table bounded to ``[0.95, 1.25]``:
  ORIGINAL_SCREENPLAY 1.00, BESTSELLER_BOOK 1.20, TRUE_CRIME_IP 1.25,
  WEBTOON_MANGA 1.15, PUBLIC_DOMAIN 0.95. ``PUBLIC_DOMAIN = 0.95`` is the single
  intentional SUB-neutral IP multiplier (a discount reflecting the lack of
  exclusive source IP); the "never reduces below the pre-modifier value"
  guarantee applies to premium (``>= 1.00``) modifiers only.
- **Release_Window_Halo** -- DIRECT_TO_STREAMING 1.00, DAY_AND_DATE 1.10,
  THEATRICAL_30D 1.25, THEATRICAL_60D_PLUS 1.40. (A NEW concept;
  ``app.domain.windowing.WindowType`` is NOT re-defined.)
- **Calendar_Seasonality** -- a per-release-month factor clamped to
  ``[0.80, 1.35]`` inclusive (NULL / absent month -> neutral 1.00).
- **Vernacular_TAM_Factor** -- 1.00 (primary-language-only) up to 2.20 (four-plus
  vernacular audio tracks), clamped to its documented inclusive bound.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``) and it imports only the
Python standard library. Inputs are never mutated; ``WindowType`` and
``deal_stage.py`` are untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

__all__ = [
    "DECIMAL_CONTEXT_PRECISION",
    "SOURCE_DETERMINISTIC_FALLBACK",
    "SOURCE_MODEL_VERSION",
    "NEUTRAL_MULTIPLIER",
    "IP_BOUND_LOW",
    "IP_BOUND_HIGH",
    "SEASONALITY_BOUND_LOW",
    "SEASONALITY_BOUND_HIGH",
    "VERNACULAR_BOUND_LOW",
    "VERNACULAR_BOUND_HIGH",
    "DEFAULT_SOURCE_IP_TABLE",
    "DEFAULT_RELEASE_WINDOW_TABLE",
    "DEFAULT_SEASONALITY_TABLE",
    "DEFAULT_VERNACULAR_TABLE",
    "DEFAULT_MACRO_PARAMS",
    "MacroParams",
    "MacroFeatures",
    "MacroResult",
    "normalize_descriptor",
    "coerce_decimal",
    "parse_params",
    "calculate_macro_modifiers",
]

DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

SOURCE_DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
SOURCE_MODEL_VERSION = "MODEL_VERSION"

# The neutral (no-effect) multiplier an absent / unrecognized descriptor resolves
# to and the product baseline.
NEUTRAL_MULTIPLIER = Decimal("1.00")

# Documented inclusive clamp bounds per modifier.
IP_BOUND_LOW = Decimal("0.95")
IP_BOUND_HIGH = Decimal("1.25")
SEASONALITY_BOUND_LOW = Decimal("0.80")
SEASONALITY_BOUND_HIGH = Decimal("1.35")
VERNACULAR_BOUND_LOW = Decimal("1.00")
VERNACULAR_BOUND_HIGH = Decimal("2.20")


def normalize_descriptor(value: str | None) -> str | None:
    """Normalize an enum-text descriptor to an UPPER_SNAKE_CASE lookup key.

    Trims, uppercases, and collapses spaces / hyphens to single underscores so
    ``"theatrical 30d"``, ``"THEATRICAL-30D"``, and ``"THEATRICAL_30D"`` all map to
    the same key. Returns ``None`` for a blank / absent value.
    """
    if value is None:
        return None
    text = value.strip().upper()
    if not text:
        return None
    for sep in (" ", "-"):
        text = text.replace(sep, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or None


# ---------------------------------------------------------------------------
# Documented-domain tables (DETERMINISTIC_FALLBACK Illustrative_Coefficients).
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_IP_TABLE: Mapping[str, Decimal] = {
    "ORIGINAL_SCREENPLAY": Decimal("1.00"),
    "BESTSELLER_BOOK": Decimal("1.20"),
    "TRUE_CRIME_IP": Decimal("1.25"),
    "WEBTOON_MANGA": Decimal("1.15"),
    "PUBLIC_DOMAIN": Decimal("0.95"),  # single intentional sub-neutral multiplier
}

DEFAULT_RELEASE_WINDOW_TABLE: Mapping[str, Decimal] = {
    "DIRECT_TO_STREAMING": Decimal("1.00"),
    "DAY_AND_DATE": Decimal("1.10"),
    "THEATRICAL_30D": Decimal("1.25"),
    "THEATRICAL_60D_PLUS": Decimal("1.40"),
}

# Calendar seasonality by release month (1-12). Festive windows (Diwali /
# Christmas / Eid / summer) lift; off-peak discounts. Illustrative; every value
# is already inside the [0.80, 1.35] clamp. A NULL / absent / out-of-range month
# resolves to the neutral 1.00 (assumed).
DEFAULT_SEASONALITY_TABLE: Mapping[int, Decimal] = {
    1: Decimal("0.90"),
    2: Decimal("0.90"),
    3: Decimal("1.00"),
    4: Decimal("1.00"),
    5: Decimal("1.05"),
    6: Decimal("1.15"),
    7: Decimal("1.20"),
    8: Decimal("1.15"),
    9: Decimal("1.00"),
    10: Decimal("1.15"),
    11: Decimal("1.25"),
    12: Decimal("1.30"),
}

# Vernacular TAM factor by audio-track count. 1 track (primary-language-only) is
# neutral; each additional vernacular track widens the addressable market, up to
# the 2.20 clamp at four-plus tracks. Illustrative.
DEFAULT_VERNACULAR_TABLE: Mapping[int, Decimal] = {
    1: Decimal("1.00"),
    2: Decimal("1.40"),
    3: Decimal("1.80"),
    4: Decimal("2.20"),
}


@dataclass(frozen=True)
class MacroParams:
    """DETERMINISTIC_FALLBACK Illustrative_Coefficients for the macro driver.

    Each table maps a normalized descriptor / integer key to a ``Decimal``
    multiplier; the bounds are the inclusive clamps applied after lookup.
    """

    source_ip_table: Mapping[str, Decimal]
    release_window_table: Mapping[str, Decimal]
    seasonality_table: Mapping[int, Decimal]
    vernacular_table: Mapping[int, Decimal]
    ip_bound_low: Decimal = IP_BOUND_LOW
    ip_bound_high: Decimal = IP_BOUND_HIGH
    seasonality_bound_low: Decimal = SEASONALITY_BOUND_LOW
    seasonality_bound_high: Decimal = SEASONALITY_BOUND_HIGH
    vernacular_bound_low: Decimal = VERNACULAR_BOUND_LOW
    vernacular_bound_high: Decimal = VERNACULAR_BOUND_HIGH


@dataclass(frozen=True)
class MacroFeatures:
    """A title's macro descriptors.

    Any field may be absent (``None``) / unrecognized, which resolves to the
    neutral ``1.00`` for that modifier (recorded as assumed).
    ``vernacular_track_count`` of ``None`` / ``< 1`` is treated as the neutral
    single-track case.
    """

    source_ip_provenance: str | None = None
    release_window: str | None = None
    release_month: int | None = None
    vernacular_track_count: int | None = None


@dataclass(frozen=True)
class MacroResult:
    """The four resolved multipliers, their product, and provenance metadata.

    Each ``*_multiplier`` is the clamped per-modifier value; ``product`` is the
    combined multiplier (``m_ip * m_window * m_seasonality * m_vernacular``).
    ``assumed_features`` records every modifier that fell back to the neutral
    ``1.00`` because its descriptor was absent / unrecognized.
    """

    source_ip_multiplier: Decimal
    release_window_multiplier: Decimal
    calendar_seasonality_multiplier: Decimal
    vernacular_tam_multiplier: Decimal
    product: Decimal
    source_tier: str
    assumed_features: tuple[str, ...] = ()


DEFAULT_MACRO_PARAMS = MacroParams(
    source_ip_table=DEFAULT_SOURCE_IP_TABLE,
    release_window_table=DEFAULT_RELEASE_WINDOW_TABLE,
    seasonality_table=DEFAULT_SEASONALITY_TABLE,
    vernacular_table=DEFAULT_VERNACULAR_TABLE,
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


def _parse_str_table(raw: object) -> Mapping[str, Decimal] | object | None:
    """Parse a ``{descriptor: multiplier}`` table of non-negative Decimals.

    Returns ``None`` when absent (caller falls back to the default table) and the
    ``_REJECT`` sentinel when present-but-malformed (non-mapping, or any
    negative / non-numeric multiplier) so the whole param block falls back.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _REJECT
    table: dict[str, Decimal] = {}
    for key, value in raw.items():
        mult = _coerce_nonneg(value)
        if mult is None:
            return _REJECT
        norm = normalize_descriptor(str(key))
        if norm is not None:
            table[norm] = mult
    return table


def _parse_int_table(raw: object) -> Mapping[int, Decimal] | object | None:
    """Parse a ``{int_key: multiplier}`` table of non-negative Decimals.

    Keys must coerce to integers; multipliers to finite non-negative Decimals.
    Returns ``None`` when absent, ``_REJECT`` when present-but-malformed.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _REJECT
    table: dict[int, Decimal] = {}
    for key, value in raw.items():
        mult = _coerce_nonneg(value)
        if mult is None:
            return _REJECT
        if isinstance(key, bool):
            return _REJECT
        key_dec = coerce_decimal(key)
        if key_dec is None or key_dec != key_dec.to_integral_value():
            return _REJECT
        table[int(key_dec)] = mult
    return table


# Sentinel distinguishing "absent" (use default table) from "present but invalid"
# (reject the whole param block).
_REJECT = object()


def parse_params(raw: Mapping | None) -> tuple[MacroParams, str]:
    """Parse a ``macro_modifiers`` mapping into (:class:`MacroParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_MACRO_PARAMS, "DETERMINISTIC_FALLBACK")``. Each of the four tables
    is optional: absent -> the built-in default table; present -> every entry
    must be valid (non-negative multiplier, integer key for the int tables), else
    the whole block falls back. The optional bound overrides must be finite
    non-negative with ``low <= high``. Mirrors the churn full-fallback contract:
    never raises.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_MACRO_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    ip_table = _parse_str_table(raw.get("source_ip_table"))
    window_table = _parse_str_table(raw.get("release_window_table"))
    seasonality_table = _parse_int_table(raw.get("seasonality_table"))
    vernacular_table = _parse_int_table(raw.get("vernacular_table"))

    if _REJECT in (ip_table, window_table, seasonality_table, vernacular_table):
        return DEFAULT_MACRO_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    if ip_table is None:
        ip_table = DEFAULT_SOURCE_IP_TABLE
    if window_table is None:
        window_table = DEFAULT_RELEASE_WINDOW_TABLE
    if seasonality_table is None:
        seasonality_table = DEFAULT_SEASONALITY_TABLE
    if vernacular_table is None:
        vernacular_table = DEFAULT_VERNACULAR_TABLE

    bounds = {
        "ip_bound_low": IP_BOUND_LOW,
        "ip_bound_high": IP_BOUND_HIGH,
        "seasonality_bound_low": SEASONALITY_BOUND_LOW,
        "seasonality_bound_high": SEASONALITY_BOUND_HIGH,
        "vernacular_bound_low": VERNACULAR_BOUND_LOW,
        "vernacular_bound_high": VERNACULAR_BOUND_HIGH,
    }
    for name in list(bounds):
        if name in raw:
            value = _coerce_nonneg(raw.get(name))
            if value is None:
                return DEFAULT_MACRO_PARAMS, SOURCE_DETERMINISTIC_FALLBACK
            bounds[name] = value

    if (
        bounds["ip_bound_low"] > bounds["ip_bound_high"]
        or bounds["seasonality_bound_low"] > bounds["seasonality_bound_high"]
        or bounds["vernacular_bound_low"] > bounds["vernacular_bound_high"]
    ):
        return DEFAULT_MACRO_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    params = MacroParams(
        source_ip_table=ip_table,  # type: ignore[arg-type]
        release_window_table=window_table,  # type: ignore[arg-type]
        seasonality_table=seasonality_table,  # type: ignore[arg-type]
        vernacular_table=vernacular_table,  # type: ignore[arg-type]
        **bounds,  # type: ignore[arg-type]
    )
    return params, SOURCE_MODEL_VERSION


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` to the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def calculate_macro_modifiers(
    features: MacroFeatures,
    params: MacroParams,
    params_source: str = SOURCE_DETERMINISTIC_FALLBACK,
) -> MacroResult:
    """Resolve the four macro multipliers from ``features`` (R4.1-R4.6).

    Each modifier is a documented-domain lookup followed by its inclusive clamp;
    an absent / unrecognized descriptor resolves to the neutral ``1.00`` and is
    recorded in ``assumed_features`` (R4.1). ``PUBLIC_DOMAIN = 0.95`` is the only
    sub-neutral IP value. ``product`` is the four multipliers multiplied under the
    fixed Decimal context. Pure; inputs unmodified; never raises.
    """
    assumed: list[str] = []

    # Source IP provenance (clamped to [0.95, 1.25]).
    ip_key = normalize_descriptor(features.source_ip_provenance)
    if ip_key is not None and ip_key in params.source_ip_table:
        m_ip = _clamp(
            params.source_ip_table[ip_key], params.ip_bound_low, params.ip_bound_high
        )
    else:
        m_ip = NEUTRAL_MULTIPLIER
        assumed.append("source_ip_provenance")

    # Release-window halo (no additional clamp beyond the table's documented set).
    window_key = normalize_descriptor(features.release_window)
    if window_key is not None and window_key in params.release_window_table:
        m_window = params.release_window_table[window_key]
    else:
        m_window = NEUTRAL_MULTIPLIER
        assumed.append("release_window")

    # Calendar seasonality (clamped to [0.80, 1.35]).
    month = features.release_month
    if month is not None and month in params.seasonality_table:
        m_season = _clamp(
            params.seasonality_table[month],
            params.seasonality_bound_low,
            params.seasonality_bound_high,
        )
    else:
        m_season = NEUTRAL_MULTIPLIER
        assumed.append("release_month")

    # Vernacular TAM factor (clamped to [1.00, 2.20]). A None / < 1 count is the
    # neutral single-track case; a count above the table's max saturates at the
    # largest documented key.
    count = features.vernacular_track_count
    if count is not None and count >= 1 and params.vernacular_table:
        if count in params.vernacular_table:
            m_vern_raw = params.vernacular_table[count]
        else:
            max_key = max(params.vernacular_table)
            m_vern_raw = (
                params.vernacular_table[max_key]
                if count > max_key
                else NEUTRAL_MULTIPLIER
            )
            if count not in params.vernacular_table and count <= max_key:
                assumed.append("vernacular_track_count")
        m_vern = _clamp(
            m_vern_raw, params.vernacular_bound_low, params.vernacular_bound_high
        )
    else:
        m_vern = NEUTRAL_MULTIPLIER
        if count is None:
            assumed.append("vernacular_track_count")

    with localcontext(_CTX):
        product = m_ip * m_window * m_season * m_vern

    return MacroResult(
        source_ip_multiplier=m_ip,
        release_window_multiplier=m_window,
        calendar_seasonality_multiplier=m_season,
        vernacular_tam_multiplier=m_vern,
        product=product,
        source_tier=params_source,
        assumed_features=tuple(assumed),
    )
