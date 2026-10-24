"""Pure domain module for the Comps_Engine (Driver A of advanced-content-eval-drivers).

Driver A replaces the blunt platform-wide viewing-hours intercept
(``exp(8) - 1 ~= 2980`` base hours) with an empirical Bayesian prior anchored to
the median of a title's nearest historical comps. This module is the **pure
set-math** half of the driver: it receives the already-retrieved comps as
in-memory ``Decimal`` vectors and computes the anchor statistics. The pgvector
retrieval (budget-band + asset-type + historical-only + SUCCESS-only
cosine-nearest ranking) lives in the repository seam (task 12), **not** here.

Given a comp set it computes:

- ``H_comps`` -- the median of the non-skipped projected-viewing-hours values
  (for an even realized ``k`` the mean of the two central values).
- ``C_comps`` -- the median of the non-skipped churn-mitigation percentages
  (a NULL / non-finite entry is skipped **per metric** and recorded; the two
  medians can therefore have different effective counts).
- ``Comps_Dispersion`` -- the inter-quartile range (IQR) of the viewing-hours
  values by the averaged-halves method, surfaced for UI confidence.
- the realized ``k`` (the post-dedup count of eligible comps) and a
  ``Source_Tier`` tag.

``<k`` fallback: when fewer than ``k`` eligible comps exist, ``k`` shrinks to the
eligible count and the medians are computed over that smaller, honestly-labeled
set -- the band is **never** widened (widening would silently change the
comparability contract shown to the buyer). When **zero** eligible comps exist,
``Source_Tier`` is ``DETERMINISTIC_FALLBACK`` and ``use_intercept_fallback`` is
set so the caller falls back to the ``viewing_hours.py`` constant intercept.

In-memory band-membership and ``(cosine, title_id asc)`` tie-break ordering are
provided so the math is exercisable with in-memory candidate vectors.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (``prec=50``, ``ROUND_HALF_UP``) so results are
byte-identical across platforms, and it imports only the Python standard
library, so it is importable without the application framework. Inputs are never
mutated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

__all__ = [
    "DEFAULT_K",
    "DECIMAL_CONTEXT_PRECISION",
    "SOURCE_DETERMINISTIC_FALLBACK",
    "SOURCE_MODEL_VERSION",
    "DEFAULT_COMPS_PARAMS",
    "CompsParams",
    "CompCandidate",
    "CompSet",
    "CompsResult",
    "coerce_metric",
    "parse_params",
    "select_band_members",
    "order_candidates",
    "calculate_comps",
]

# The anchor comp-set size (post-dedup truncation count over eligible rows).
DEFAULT_K = 5

# Fixed, generous precision so the median / IQR Decimal math is byte-identical
# across platforms, mirroring viewing_hours.py's context.
DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

_TWO = Decimal("2")

# Source-tier tags. Every driver in this feature ships its coefficients as
# DETERMINISTIC_FALLBACK Illustrative_Coefficients; the comps anchor VALUE is
# empirical, but the tier labels the coefficient provenance and the zero-comp
# fallback path.
SOURCE_DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
SOURCE_MODEL_VERSION = "MODEL_VERSION"


@dataclass(frozen=True)
class CompsParams:
    """Parameters for the Comps_Engine set math.

    ``k`` is the target comp-set size (strictly positive). ``band_low_factor`` /
    ``band_high_factor`` are the normalized-USD Budget_Band multipliers applied
    to a query cost (``low < high``, both strictly positive). The band is used
    only by :func:`select_band_members`; the retrieval seam applies the same band
    in SQL before the query.
    """

    k: int
    band_low_factor: Decimal
    band_high_factor: Decimal


@dataclass(frozen=True)
class CompCandidate:
    """A single in-memory comp candidate used for band membership / ordering.

    ``cost`` is the candidate's normalized-USD cost (for band membership);
    ``cosine_distance`` is the pgvector cosine distance to the query vector (for
    the deterministic ``(cosine, title_id asc)`` tie-break); ``viewing_hours`` /
    ``churn_pct`` are the metrics fed into the medians (either may be ``None`` /
    non-finite, which is skipped per metric).
    """

    title_id: int
    cost: Decimal
    cosine_distance: Decimal
    viewing_hours: Decimal | None
    churn_pct: Decimal | None


@dataclass(frozen=True)
class CompSet:
    """The ordered, truncated comp set the medians are computed over."""

    title_ids: tuple[int, ...]
    viewing_hours: tuple[Decimal | None, ...]
    churn_pct: tuple[Decimal | None, ...]


@dataclass(frozen=True)
class CompsResult:
    """The resolved comps anchor statistics plus provenance metadata.

    ``h_comps`` / ``c_comps`` / ``dispersion_iqr`` are ``None`` when their metric
    has no non-skipped values. ``use_intercept_fallback`` is ``True`` only when
    **zero** eligible comps exist (the caller must then use the viewing-hours
    constant intercept). ``skipped_hours`` / ``skipped_churn`` count the
    per-metric NULL / non-finite skips. ``comp_title_ids`` preserves the
    deterministic order of the realized set.
    """

    h_comps: Decimal | None
    c_comps: Decimal | None
    dispersion_iqr: Decimal | None
    realized_k: int
    requested_k: int
    source_tier: str
    use_intercept_fallback: bool
    comp_title_ids: tuple[int, ...]
    skipped_hours: int = 0
    skipped_churn: int = 0


DEFAULT_COMPS_PARAMS = CompsParams(
    k=DEFAULT_K,
    band_low_factor=Decimal("0.65"),
    band_high_factor=Decimal("1.35"),
)


def coerce_metric(raw: object) -> Decimal | None:
    """Coerce a raw comp metric to a finite :class:`Decimal`, else ``None``.

    Mirrors :func:`app.domain.churn.coerce_supplied`: ``None`` / non-numeric /
    non-finite / boolean inputs yield ``None`` (a skip marker); a finite numeric
    (including a pass-through ``Decimal``, an ``int``, a numeric string, or a
    finite float) yields a ``Decimal``. Never raises.
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


def _coerce_positive(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite STRICTLY POSITIVE Decimal, else ``None``."""
    value = coerce_metric(raw)
    if value is None or value <= 0:
        return None
    return value


def _coerce_positive_int(raw: object) -> int | None:
    """Coerce a raw param to a strictly positive ``int``, else ``None``.

    A ``bool`` is rejected (a boolean is not a number); a finite whole-valued
    numeric is accepted.
    """
    if isinstance(raw, bool):
        return None
    value = coerce_metric(raw)
    if value is None:
        return None
    if value != value.to_integral_value():
        return None
    as_int = int(value)
    return as_int if as_int > 0 else None


def parse_params(raw: Mapping | None) -> tuple[CompsParams, str]:
    """Parse a ``comps`` mapping into (:class:`CompsParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_COMPS_PARAMS, "DETERMINISTIC_FALLBACK")``. A valid parse requires a
    strictly positive integer ``k`` and strictly positive band factors with
    ``band_low_factor < band_high_factor``. Mirrors the churn / viewing-hours
    full-fallback contract: never raises; any invalid / missing field collapses
    the entire block to the illustrative defaults.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_COMPS_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    k = _coerce_positive_int(raw.get("k"))
    band_low = _coerce_positive(raw.get("band_low_factor"))
    band_high = _coerce_positive(raw.get("band_high_factor"))

    if k is None or band_low is None or band_high is None:
        return DEFAULT_COMPS_PARAMS, SOURCE_DETERMINISTIC_FALLBACK
    if band_low >= band_high:
        return DEFAULT_COMPS_PARAMS, SOURCE_DETERMINISTIC_FALLBACK

    params = CompsParams(k=k, band_low_factor=band_low, band_high_factor=band_high)
    return params, SOURCE_MODEL_VERSION


def _median(values: Sequence[Decimal]) -> Decimal:
    """Median of a non-empty, already-sorted sequence (even -> mean of centers)."""
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / _TWO


def _iqr(values: Sequence[Decimal]) -> Decimal | None:
    """Inter-quartile range (Q3 - Q1) by the averaged-halves method.

    The sorted list is split into a lower and an upper half about the median;
    for an odd count the central value is excluded from both halves. Q1 / Q3 are
    the medians of those halves. Returns ``None`` when a half is empty (fewer
    than two values), where an IQR is undefined.
    """
    n = len(values)
    if n < 2:
        return None
    mid = n // 2
    lower = values[:mid]
    upper = values[mid:] if n % 2 == 0 else values[mid + 1:]
    if not lower or not upper:
        return None
    return _median(upper) - _median(lower)


def select_band_members(
    candidates: Sequence[CompCandidate],
    query_cost: Decimal,
    params: CompsParams,
) -> list[CompCandidate]:
    """Return the candidates whose ``cost`` is inside the normalized-USD band.

    The inclusive Budget_Band is ``[band_low_factor * query_cost,
    band_high_factor * query_cost]``. A candidate with a non-finite ``cost`` is
    excluded. The band is **never** widened. The input sequence is not mutated.
    """
    with localcontext(_CTX):
        low = params.band_low_factor * query_cost
        high = params.band_high_factor * query_cost
    members: list[CompCandidate] = []
    for cand in candidates:
        if cand.cost is None or not cand.cost.is_finite():
            continue
        if low <= cand.cost <= high:
            members.append(cand)
    return members


def order_candidates(candidates: Sequence[CompCandidate]) -> list[CompCandidate]:
    """Order candidates by ``(cosine_distance asc, title_id asc)`` deterministically.

    Equal-distance comps resolve reproducibly by ascending ``title_id`` -- the
    same tie-break the retrieval seam applies in SQL (``ORDER BY cos_dist ASC,
    title_id ASC``). The input sequence is not mutated.
    """
    return sorted(candidates, key=lambda c: (c.cosine_distance, c.title_id))


def build_comp_set(
    candidates: Sequence[CompCandidate],
    query_cost: Decimal,
    params: CompsParams,
) -> CompSet:
    """Resolve the ordered, truncated :class:`CompSet` from in-memory candidates.

    Applies band membership, the deterministic tie-break order, and truncation to
    the target ``k`` (shrinking naturally when fewer eligible comps exist). Pure;
    inputs unmodified.
    """
    members = select_band_members(candidates, query_cost, params)
    ordered = order_candidates(members)[: params.k]
    return CompSet(
        title_ids=tuple(c.title_id for c in ordered),
        viewing_hours=tuple(c.viewing_hours for c in ordered),
        churn_pct=tuple(c.churn_pct for c in ordered),
    )


def calculate_comps(
    viewing_hours_list: Sequence[object],
    churn_pct_list: Sequence[object],
    k: int = DEFAULT_K,
    *,
    title_ids: Sequence[int] | None = None,
    params: CompsParams | None = None,
    params_source: str = SOURCE_DETERMINISTIC_FALLBACK,
) -> CompsResult:
    """Compute the comps anchor statistics from in-memory metric lists (R1.3-R1.5).

    ``viewing_hours_list`` / ``churn_pct_list`` are the retrieved comps' metrics
    (NULL / non-finite entries are coerced to a per-metric skip). ``H_comps`` is
    the median of the non-skipped viewing hours (even realized ``k`` -> mean of
    the two central values); ``C_comps`` is the median of the non-skipped churn
    percentages. ``Comps_Dispersion`` is the IQR of the viewing-hours values by
    the averaged-halves method.

    The realized ``k`` is the count of supplied comps (after any upstream
    band/dedup truncation) and shrinks naturally to the eligible count -- the
    band is never widened here. When **zero** comps are supplied,
    ``use_intercept_fallback`` is ``True`` and ``source_tier`` is
    ``DETERMINISTIC_FALLBACK`` so the caller uses the viewing-hours constant
    intercept. Never raises; inputs are not mutated.
    """
    if params is not None:
        requested_k = params.k
    else:
        requested_k = k

    hours_raw = list(viewing_hours_list)
    churn_raw = list(churn_pct_list)
    realized_k = len(hours_raw)

    ids = tuple(title_ids) if title_ids is not None else ()

    # Zero eligible comps -> intercept fallback (R1.5 zero-comp path).
    if realized_k == 0:
        return CompsResult(
            h_comps=None,
            c_comps=None,
            dispersion_iqr=None,
            realized_k=0,
            requested_k=requested_k,
            source_tier=SOURCE_DETERMINISTIC_FALLBACK,
            use_intercept_fallback=True,
            comp_title_ids=ids,
            skipped_hours=0,
            skipped_churn=0,
        )

    hours_vals: list[Decimal] = []
    skipped_hours = 0
    for raw in hours_raw:
        value = coerce_metric(raw)
        if value is None:
            skipped_hours += 1
        else:
            hours_vals.append(value)

    churn_vals: list[Decimal] = []
    skipped_churn = 0
    for raw in churn_raw:
        value = coerce_metric(raw)
        if value is None:
            skipped_churn += 1
        else:
            churn_vals.append(value)

    with localcontext(_CTX):
        hours_sorted = sorted(hours_vals)
        churn_sorted = sorted(churn_vals)
        h_comps = _median(hours_sorted) if hours_sorted else None
        c_comps = _median(churn_sorted) if churn_sorted else None
        dispersion = _iqr(hours_sorted) if hours_sorted else None

    return CompsResult(
        h_comps=h_comps,
        c_comps=c_comps,
        dispersion_iqr=dispersion,
        realized_k=realized_k,
        requested_k=requested_k,
        source_tier=params_source,
        use_intercept_fallback=False,
        comp_title_ids=ids,
        skipped_hours=skipped_hours,
        skipped_churn=skipped_churn,
    )
