"""Pure domain module for the Projected_Viewing_Hours Content_Eval_Model.

The second member of the Content_Eval_Model family (after
:mod:`app.domain.churn`). Unlike the additive churn model, projected viewing
hours are heavy-tailed / power-law distributed (a tentpole can be orders of
magnitude above a library title), so the model is **linear in log space** and
**reported, conserved, and clamped in hour space** (design Component 2, R4.4):

    y_log = intercept + sum_i(beta_i * x_i)          # linear in log space
    H_hat = exp(y_log) - 1                            # inverse of log(1 + H)

The per-feature breakdown is built in HOURS with the **base-plus-marginal-lift
(Option B)** allocation, never a naive per-term log share (which would
double-count the intercept and force a large negative adjustment):

    H0  = exp(intercept) - 1                          # base platform hours
    L   = sum_i(beta_i * x_i)                          # total non-intercept log lift
    dH  = H_hat - H0                                   # total feature lift in hours
    hours_i = (beta_i * x_i / L) * dH    when L > 0
    hours_i = 0                          when L == 0   # base-only, every lift 0

By construction ``H0 + sum_i(hours_i) == H_hat`` BEFORE quantization, so the
single trailing ``rounding_or_bounds_adjustment`` entry (exactly like
``churn.bounds_adjustment``) only ever carries a tiny +/- rounding or
floor-clamp residual, NEVER a large structural offset. ``L`` is NEVER used as
the denominator for an intercept term -- the intercept lives entirely in ``H0``.

The output is clamped to a positive ``floor`` so CPVH (``cost / viewing_hours``)
never hits its null/zero path (see :mod:`app.domain.cpvh`); the clamp delta
flows into the adjustment entry so the breakdown still conserves exactly.

Feature values are read from the shared :class:`app.domain.features.FeatureVector`
contract; only the names in :data:`app.domain.features.PREDICTIVE_FEATURES` are
consulted (``release_year`` is split-only and never predictive). ``betas`` is a
mapping ``feature_name -> non-negative weight``; a beta for a non-numeric label
feature (asset_type / genre / content_format) cannot multiply a string value and
so contributes 0, with the feature recorded as missing.

``parse_params`` mirrors the churn model's full-fallback parse: any
invalid/missing field (or a negative beta, or a non-positive floor) yields
:data:`DEFAULT_VIEWING_HOURS_PARAMS` with source ``"DEFAULTS"`` and never raises.
``resolve_viewing_hours`` implements the SUPPLIED-wins contract: a finite
supplied value (including 0) is returned exactly with method SUPPLIED and no
breakdown; otherwise the model is calculated.

This module is pure: no I/O, no database access, no async, no global mutable
state. All arithmetic uses :class:`decimal.Decimal` under a fixed
:class:`decimal.Context` (so ``exp``/``ln`` are deterministic across platforms)
and it imports only the Python standard library plus the sibling pure
``features`` module, so it is importable without the application framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

from app.domain import features as featmod

__all__ = [
    "VIEWING_HOURS_FLOOR",
    "VIEWING_HOURS_QUANTUM",
    "DECIMAL_CONTEXT_PRECISION",
    "DEFAULT_VIEWING_HOURS_BETAS",
    "DEFAULT_VIEWING_HOURS_PARAMS",
    "ViewingHoursParams",
    "ViewingHoursContribution",
    "ViewingHoursResult",
    "coerce_supplied",
    "parse_params",
    "calculate_viewing_hours",
    "resolve_viewing_hours",
]

# A fixed, generous precision for the Decimal exp()/ln() transcendental math so
# predictions are byte-identical across platforms (no float, no BLAS, no env
# dependence). 50 digits is far more than the hour-space quantum needs.
DECIMAL_CONTEXT_PRECISION = 50
_CTX = Context(prec=DECIMAL_CONTEXT_PRECISION, rounding=ROUND_HALF_UP)

# Viewing hours quantize to whole hours (0 dp): CPVH divides cost by hours, so a
# whole-hour resolution is ample and keeps the breakdown human-readable. The
# adjustment entry absorbs the residual so sum(breakdown) == final exactly.
VIEWING_HOURS_QUANTUM = Decimal("1")

# A small positive floor keeps projected viewing hours strictly above the CPVH
# null/zero path (cpvh.compute_cpvh raises on hours <= 0). One whole hour is the
# smallest value that survives whole-hour quantization while staying positive.
VIEWING_HOURS_FLOOR = Decimal("1")

_SOURCE_MODEL_VERSION = "MODEL_VERSION"
_SOURCE_DEFAULTS = "DEFAULTS"

_METHOD_CALCULATED = "CALCULATED"
_METHOD_SUPPLIED = "SUPPLIED"

_OBJECTIVE_WAPE_LOG = "wape_log"

# The feature-domain clamp bounds for every numeric predictive feature, mirrored
# from the features module's documented domains. A feature absent from this map
# (a label feature) is non-numeric and contributes 0. ``franchise_flag`` and
# ``is_exclusive`` are 0/1 indicators; ``log_vote_count`` has only a lower bound.
_FEATURE_DOMAINS: Mapping[str, tuple[Decimal, Decimal | None]] = {
    "runtime_minutes": (Decimal("0"), None),
    "is_exclusive": (Decimal("0"), Decimal("1")),
    "production_scale": (featmod.SCALE_MIN, featmod.SCALE_MAX),
    "talent_pedigree": (featmod.PEDIGREE_MIN, featmod.PEDIGREE_MAX),
    "normalized_rating": (featmod.RATING_MIN, featmod.RATING_MAX),
    "log_vote_count": (featmod.VOTE_COUNT_MIN, None),
    "franchise_flag": (Decimal("0"), Decimal("1")),
    "award_signal": (featmod.AWARD_MIN, featmod.AWARD_MAX),
}


@dataclass(frozen=True)
class ViewingHoursParams:
    """Parameters for the log-space viewing-hours model.

    ``intercept`` is the log-space intercept (may be any finite value; the base
    hours ``exp(intercept) - 1`` are clamped non-negative downstream). ``betas``
    maps a predictive feature name to its NON-NEGATIVE log-space weight; a
    missing beta is treated as 0. ``floor`` is a STRICTLY POSITIVE hour floor so
    CPVH never divides by zero. ``objective`` is a provenance tag naming the fit
    objective (``"wape_log"`` for the log-scale WAPE used at fit time).
    """

    intercept: Decimal
    betas: Mapping[str, Decimal]
    floor: Decimal
    objective: str = _OBJECTIVE_WAPE_LOG


@dataclass(frozen=True)
class ViewingHoursContribution:
    """A single per-feature contribution within the hour-space breakdown."""

    key: str
    label: str
    input: Decimal | None  # feature value used (None for base / adjustment)
    coefficient: Decimal | None  # log-space beta (None for base / adjustment)
    hours: Decimal  # quantized contribution in whole viewing hours


@dataclass(frozen=True)
class ViewingHoursResult:
    """The resolved projected viewing hours plus explanation metadata."""

    viewing_hours: Decimal
    method: str  # "CALCULATED" | "SUPPLIED"
    breakdown: tuple[ViewingHoursContribution, ...] | None  # None when SUPPLIED
    missing_features: tuple[str, ...]
    assumed_features: tuple[str, ...]
    params_source: str  # "MODEL_VERSION" | "DEFAULTS"
    unclamped: Decimal | None  # pre-floor-clamp H_hat (None when SUPPLIED)


# Illustrative_Coefficients: log-space weights tuned for the demo, NOT fitted to
# real viewing data. Only numeric predictive features carry a beta; the label
# features (asset_type / genre / content_format) are non-numeric here and so are
# intentionally absent (weight 0). intercept exp(intercept)-1 gives the base
# platform hours a featureless title would project.
DEFAULT_VIEWING_HOURS_BETAS: Mapping[str, Decimal] = {
    "runtime_minutes": Decimal("0.004"),
    "is_exclusive": Decimal("0.20"),
    "production_scale": Decimal("0.15"),
    "talent_pedigree": Decimal("0.12"),
    "normalized_rating": Decimal("0.60"),
    "log_vote_count": Decimal("0.35"),
    "franchise_flag": Decimal("0.40"),
    "award_signal": Decimal("0.30"),
}

DEFAULT_VIEWING_HOURS_PARAMS = ViewingHoursParams(
    intercept=Decimal("8.0"),  # exp(8) - 1 ~= 2980 base platform hours
    betas=DEFAULT_VIEWING_HOURS_BETAS,
    floor=VIEWING_HOURS_FLOOR,
    objective=_OBJECTIVE_WAPE_LOG,
)


def coerce_supplied(raw: object) -> Decimal | None:
    """Coerce a raw supplied viewing-hours value to a finite Decimal, or ``None``.

    Mirrors :func:`app.domain.churn.coerce_supplied`: blank / ``None`` /
    non-numeric / non-finite / boolean inputs yield ``None`` ("not supplied");
    a finite numeric (including 0, a pass-through ``Decimal``, an ``int``, a
    numeric string, or a finite float) yields a ``Decimal``. Never raises.
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


def _coerce_finite(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite Decimal (any sign), else ``None``."""
    return coerce_supplied(raw)


def _coerce_nonneg(raw: object) -> Decimal | None:
    """Coerce a raw param to a finite NON-NEGATIVE Decimal, else ``None``."""
    value = coerce_supplied(raw)
    if value is None or value < 0:
        return None
    return value


def _parse_betas(raw: object) -> Mapping[str, Decimal] | None:
    """Parse a betas mapping of non-negative Decimals keyed by predictive feature.

    ``None`` / absent is rejected by the caller via ``None`` return only when the
    whole param block is malformed; here an absent/non-mapping input returns
    ``None`` (caller falls back). A present mapping with any negative/non-numeric
    weight, or a key outside :data:`PREDICTIVE_FEATURES`, is rejected (``None``)
    so the whole param set falls back to defaults rather than silently dropping a
    misconfigured weight.
    """
    if not isinstance(raw, Mapping):
        return None
    betas: dict[str, Decimal] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in featmod.PREDICTIVE_FEATURES:
            return None
        weight = _coerce_nonneg(value)
        if weight is None:
            return None
        betas[name] = weight
    return betas


def parse_params(raw: Mapping | None) -> tuple[ViewingHoursParams, str]:
    """Parse a ``viewing_hours`` mapping into (:class:`ViewingHoursParams`, source).

    Returns ``(params, "MODEL_VERSION")`` on a valid parse, else
    ``(DEFAULT_VIEWING_HOURS_PARAMS, "DEFAULTS")``. A valid parse requires a
    finite ``intercept``, a valid ``betas`` mapping (all keys in
    :data:`PREDICTIVE_FEATURES`, all weights finite non-negative), and a STRICTLY
    POSITIVE ``floor``. ``objective`` is optional and defaults to ``"wape_log"``.
    Mirrors the churn model's full-fallback contract: never raises; any invalid
    or missing field collapses the entire block to the illustrative defaults.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_VIEWING_HOURS_PARAMS, _SOURCE_DEFAULTS

    intercept = _coerce_finite(raw.get("intercept"))
    if intercept is None:
        return DEFAULT_VIEWING_HOURS_PARAMS, _SOURCE_DEFAULTS

    betas = _parse_betas(raw.get("betas"))
    if betas is None:
        return DEFAULT_VIEWING_HOURS_PARAMS, _SOURCE_DEFAULTS

    floor = _coerce_nonneg(raw.get("floor"))
    if floor is None or floor <= 0:
        return DEFAULT_VIEWING_HOURS_PARAMS, _SOURCE_DEFAULTS

    objective_raw = raw.get("objective")
    objective = objective_raw if isinstance(objective_raw, str) and objective_raw else _OBJECTIVE_WAPE_LOG

    params = ViewingHoursParams(
        intercept=intercept,
        betas=betas,
        floor=floor,
        objective=objective,
    )
    return params, _SOURCE_MODEL_VERSION


def _clamp(value: Decimal, low: Decimal, high: Decimal | None) -> Decimal:
    """Clamp ``value`` to [``low``, ``high``]; ``high`` ``None`` means unbounded."""
    if value < low:
        return low
    if high is not None and value > high:
        return high
    return value


def _quantize(value: Decimal) -> Decimal:
    """Quantize to whole viewing hours using half-up rounding."""
    return value.quantize(VIEWING_HOURS_QUANTUM, rounding=ROUND_HALF_UP)


def _feature_x(name: str, vector: featmod.FeatureVector) -> tuple[Decimal | None, bool]:
    """Resolve the numeric feature value ``x_i`` for predictive feature ``name``.

    Returns ``(x, assumed)`` where ``x`` is the clamped numeric value or ``None``
    when the feature is non-numeric / unusable (a label feature, or a numeric
    feature whose resolved value is missing). ``assumed`` mirrors the feature's
    own ``assumed`` flag so a neutral-default (data-gap) value is reported.
    """
    feature = getattr(vector, name, None)
    if feature is None:
        return None, False
    value = feature.value
    assumed = bool(feature.assumed)

    if isinstance(value, bool):
        return (Decimal("1") if value else Decimal("0")), assumed
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None, assumed
        low, high = _FEATURE_DOMAINS.get(name, (None, None))  # type: ignore[assignment]
        if low is not None:
            value = _clamp(value, low, high)
        return value, assumed
    # A string (label feature) or None value is non-numeric here.
    return None, assumed


def calculate_viewing_hours(
    features: featmod.FeatureVector,
    params: ViewingHoursParams,
    params_source: str = _SOURCE_DEFAULTS,
) -> ViewingHoursResult:
    """Compute projected viewing hours in log space with Option-B hour conservation.

    Predicts ``H_hat = exp(intercept + L) - 1`` where ``L = sum_i(beta_i * x_i)``
    over the numeric predictive features. The hour-space breakdown is base hours
    ``H0 = exp(intercept) - 1`` plus the marginal lift ``dH = H_hat - H0``
    allocated across features by their log-lift share ``beta_i * x_i / L`` (every
    ``hours_i == 0`` when ``L == 0``). The output is clamped to ``params.floor``
    (keeping CPVH out of its null/zero path); the single
    ``rounding_or_bounds_adjustment`` entry absorbs the floor-clamp delta and the
    whole-hour quantization residual so ``sum(breakdown.hours) == viewing_hours``
    exactly. All transcendental math runs under the fixed Decimal context for
    determinism.
    """
    missing: list[str] = []
    assumed: list[str] = []

    with localcontext(_CTX):
        intercept = +params.intercept  # normalize to the fixed context

        # Base platform hours: H0 = exp(intercept) - 1, floored at 0 (hours can
        # never be negative; the intercept lives ENTIRELY here, never over L).
        h0_raw = intercept.exp() - Decimal(1)
        h0 = h0_raw if h0_raw > 0 else Decimal(0)

        # Per-feature log lift terms beta_i * x_i, accumulated into L.
        terms: list[tuple[str, Decimal, Decimal, Decimal]] = []  # (name, x, beta, term)
        total_l = Decimal(0)
        for name in featmod.PREDICTIVE_FEATURES:
            beta = params.betas.get(name)
            x, is_assumed = _feature_x(name, features)
            if x is None:
                # A feature with a configured beta but no usable numeric value is
                # a genuine gap (label features simply have no beta, so skip).
                if beta is not None and beta != 0:
                    missing.append(name)
                continue
            if is_assumed and name not in assumed:
                assumed.append(name)
            if beta is None or beta == 0:
                continue
            term = beta * x
            terms.append((name, x, beta, term))
            total_l += term

        # H_hat = exp(intercept + L) - 1, floored at 0 before clamping.
        h_hat_raw = (intercept + total_l).exp() - Decimal(1)
        h_hat = h_hat_raw if h_hat_raw > 0 else Decimal(0)
        d_h = h_hat - h0

        # Option B allocation: hours_i = (term / L) * dH when L > 0, else 0.
        allocations: list[tuple[str, Decimal, Decimal, Decimal]] = []
        for name, x, beta, term in terms:
            if total_l > 0:
                hours_full = (term / total_l) * d_h
            else:
                hours_full = Decimal(0)
            allocations.append((name, x, beta, hours_full))

    # Clamp the prediction to the positive floor so CPVH never divides by zero.
    clamped = h_hat if h_hat >= params.floor else params.floor
    final = _quantize(clamped)

    # Quantize the base and per-feature hours; the adjustment entry carries the
    # floor-clamp delta plus every quantization residual so the sum is exact.
    base_hours = _quantize(h0)
    contributions: list[ViewingHoursContribution] = [
        ViewingHoursContribution(
            key="base_platform_hours",
            label="Base Platform Hours",
            input=None,
            coefficient=None,
            hours=base_hours,
        )
    ]
    feature_hours_sum = base_hours
    for name, x, beta, hours_full in allocations:
        hours_q = _quantize(hours_full)
        feature_hours_sum += hours_q
        contributions.append(
            ViewingHoursContribution(
                key=name,
                label=_feature_label(name),
                input=x,
                coefficient=beta,
                hours=hours_q,
            )
        )

    adjustment = final - feature_hours_sum
    if adjustment != 0:
        contributions.append(
            ViewingHoursContribution(
                key="rounding_or_bounds_adjustment",
                label="Rounding or Bounds Adjustment",
                input=None,
                coefficient=None,
                hours=adjustment,
            )
        )

    return ViewingHoursResult(
        viewing_hours=final,
        method=_METHOD_CALCULATED,
        breakdown=tuple(contributions),
        missing_features=tuple(missing),
        assumed_features=tuple(assumed),
        params_source=params_source,
        unclamped=h_hat,
    )


def _feature_label(name: str) -> str:
    """Human-readable label for a predictive feature key."""
    return name.replace("_", " ").title()


def resolve_viewing_hours(
    supplied: object,
    features: featmod.FeatureVector,
    params: ViewingHoursParams,
    params_source: str,
) -> ViewingHoursResult:
    """Resolve projected viewing hours, a supplied value winning (SUPPLIED-wins).

    When ``supplied`` coerces to a finite numeric (including 0), it is returned
    exactly with method SUPPLIED -- no floor clamp, no re-round, no breakdown --
    mirroring :func:`app.domain.churn.resolve_churn`. Otherwise the model is
    computed via :func:`calculate_viewing_hours` with ``params_source`` attached.
    """
    value = coerce_supplied(supplied)
    if value is not None:
        return ViewingHoursResult(
            viewing_hours=value,
            method=_METHOD_SUPPLIED,
            breakdown=None,
            missing_features=(),
            assumed_features=(),
            params_source=params_source,
            unclamped=None,
        )
    return calculate_viewing_hours(features, params, params_source)
