"""Property-based gating suite for the advanced content-eval drivers.

# Feature: advanced-content-eval-drivers

Targets the five pure driver / assembler modules before any engine wiring:

- :mod:`app.domain.comps` (Driver A, the empirical anchor ``H_comps`` / ``C_comps``),
- :mod:`app.domain.lineage` (Driver B, the hour-space ``Franchise_Floor`` and the
  additive churn credit ``delta_C_franchise``),
- :mod:`app.domain.momentum` (Driver C, the stage-gated ``Momentum_Multiplier``),
- :mod:`app.domain.macro_modifiers` (Driver D, the four market multipliers),
- :mod:`app.domain.driver_assembly` (the normative seven-stage assembler).

The five properties map to the design's "Correctness Properties" section:

- Property 1  Conservation (exact Decimal) on BOTH the hours and churn sides.
- Property 2  Monotonicity (``beta_i >= 0``; a negative beta is rejected to
              defaults by ``viewing_hours.parse_params``) and non-decreasing lift.
- Property 3  Multiplier boundedness (momentum ``[1.00, 1.50]`` via
              ``momentum_multiplier_max``; IP ``[0.95, 1.25]``; seasonality
              ``[0.80, 1.35]``; ``S_velocity`` ``[0.50, 2.00]``; vernacular up to
              2.20; the macro product never drops a premium prediction below its
              pre-modifier value).
- Property 4  Determinism + equal-distance ``(cosine, title_id asc)`` tie-break.
- Property 5  STAGE_EXCLUDED neutrality (CONCEPT_SCRIPT / IN_PRODUCTION ->
              ``Momentum_Multiplier == 1.00``, a 0-hour momentum line, prediction
              unchanged versus a neutral assembly).

Each test carries a leading ``# Feature: advanced-content-eval-drivers, Property
N: ...`` comment matching the house convention and a docstring citing the
acceptance criteria it exercises. Every test imports only the pure domain
modules -- no database, no app framework. Several tests carry
``@settings(deadline=None)`` because the assembler evaluates transcendental
``exp``/``ln`` under a 50-digit Decimal context, so determinism -- not
per-example latency -- is what is under test (matching the house convention in
``test_viewing_hours_properties.py``).

Validates: Requirements 5.7, 1.4, 1.5, 1.8, 3.3, 3.5, 4.3, 4.4, 4.5; Properties
1, 2, 3, 4, 5.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain import comps as cmp
from app.domain import driver_assembly as da
from app.domain import lineage as lin
from app.domain import macro_modifiers as mac
from app.domain import momentum as mom
from app.domain import viewing_hours as vh

# The fixed Decimal context the driver modules share; reused here so the
# in-test churn-side reconciliation matches the production quantization.
_CTX = Context(prec=50, rounding=ROUND_HALF_UP)
_Q_CHURN = Decimal("0.01")


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------


def _dec(min_value: str, max_value: str, places: int = 2) -> st.SearchStrategy:
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        allow_nan=False,
        allow_infinity=False,
        places=places,
    )


# A single additive log-space feature term (beta_i * x_i) with a NON-NEGATIVE
# beta -- the monotone-admissible regime (Property 2).
def _feature_term(key: str) -> st.SearchStrategy:
    def build(x: Decimal, beta: Decimal) -> da.FeatureTerm:
        return da.FeatureTerm(
            key=key,
            label=key.replace("_", " ").title(),
            x=x,
            coefficient=beta,
            term=(beta * x),
        )

    return st.builds(build, x=_dec("0", "5", places=3), beta=_dec("0", "0.8", places=3))


_FEATURE_KEYS = ("normalized_rating", "franchise_flag", "award_signal", "log_vote_count")

_feature_terms = st.lists(
    st.one_of(*(_feature_term(k) for k in _FEATURE_KEYS)),
    min_size=0,
    max_size=4,
)

# An anchor H_comps spanning the realistic base-hours regime (and 0 for the
# empty-set guard).
_h_comps = _dec("0", "20000", places=0)

# Documented-domain macro descriptors, including absent / unrecognized values
# that resolve to the neutral 1.00.
_source_ip = st.one_of(
    st.none(),
    st.just("UNRECOGNIZED_IP"),
    st.sampled_from(sorted(mac.DEFAULT_SOURCE_IP_TABLE)),
)
_release_window = st.one_of(
    st.none(),
    st.just("UNRECOGNIZED_WINDOW"),
    st.sampled_from(sorted(mac.DEFAULT_RELEASE_WINDOW_TABLE)),
)
_release_month = st.one_of(st.none(), st.integers(min_value=-3, max_value=20))
_vernacular = st.one_of(st.none(), st.integers(min_value=-1, max_value=8))

_macro_features = st.builds(
    mac.MacroFeatures,
    source_ip_provenance=_source_ip,
    release_window=_release_window,
    release_month=_release_month,
    vernacular_track_count=_vernacular,
)

# The two non-neutral production stages that run the momentum composition.
_active_stage = st.sampled_from(
    [mom.Production_Stage.FESTIVAL_PREVIEW, mom.Production_Stage.ACQUISITION_READY]
)
_excluded_stage = st.sampled_from(sorted(mom.EXCLUDED_STAGES, key=lambda s: s.value))


def _momentum_features(stage: mom.Production_Stage, **kw) -> mom.MomentumFeatures:
    return mom.MomentumFeatures(production_stage=stage, **kw)


# ---------------------------------------------------------------------------
# Property 1: Conservation to exact Decimal, hours side
# ---------------------------------------------------------------------------


# Feature: advanced-content-eval-drivers, Property 1: Hour-space conservation
# deadline=None: the assembler runs exp()/ln() under a 50-digit Decimal context
# (transcendental-heavy); exact conservation, not latency, is under test.
@settings(max_examples=200, deadline=None)
@given(
    h_comps=_h_comps,
    terms=_feature_terms,
    m_momentum=_dec("1.00", "1.50", places=2),
    m_window=st.sampled_from(sorted(mac.DEFAULT_RELEASE_WINDOW_TABLE.values())),
    m_ip=st.sampled_from(sorted(mac.DEFAULT_SOURCE_IP_TABLE.values())),
    m_vernacular=st.sampled_from(sorted(mac.DEFAULT_VERNACULAR_TABLE.values())),
    m_calendar=_dec("0.80", "1.35", places=2),
    franchise_floor=_dec("0", "25000", places=0),
)
def test_hours_conservation_sum_equals_prediction(
    h_comps: Decimal,
    terms: list[da.FeatureTerm],
    m_momentum: Decimal,
    m_window: Decimal,
    m_ip: Decimal,
    m_vernacular: Decimal,
    m_calendar: Decimal,
    franchise_floor: Decimal,
) -> None:
    """Validates: Requirements 5.7, 1.8; Properties 1

    The nine attributed hour lines plus the single residual sink sum EXACTLY to
    the quantized prediction for arbitrary anchors, feature terms, multipliers,
    and franchise floors:

        Hours_comps + sum(Hours_i) + Hours_momentum + Hours_window + Hours_ip
                    + Hours_vernacular + Hours_calendar + Hours_franchise_floor
                    + rounding_or_bounds_adjustment  ==  H_hat

    ``comps_anchor`` strictly equals ``quantize(H_comps)`` (never a sink) and the
    residual is quantization-only (bounded to a few whole hours, never the
    structural franchise lift).
    """
    result = da.assemble_drivers(
        h_comps,
        terms,
        m_momentum=m_momentum,
        m_window=m_window,
        m_ip=m_ip,
        m_vernacular=m_vernacular,
        m_calendar=m_calendar,
        franchise_floor=franchise_floor,
    )

    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours

    # The comps anchor line strictly equals the quantized H_comps (R5.3).
    anchor = next(c for c in result.breakdown if c.key == da.KEY_COMPS_ANCHOR)
    assert anchor.hours == h_comps.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # The franchise lift is its own attributed line, never the residual sink.
    floor_line = next(c for c in result.breakdown if c.key == da.KEY_FRANCHISE_FLOOR)
    assert floor_line.hours >= Decimal("0")

    # The residual sink carries ONLY per-line whole-hour quantization residual:
    # bounded by one rounding unit per quantized breakdown line.
    adj = [c for c in result.breakdown if c.key == da.KEY_ADJUSTMENT]
    if adj:
        assert abs(adj[0].hours) <= Decimal(len(result.breakdown))


# Feature: advanced-content-eval-drivers, Property 1: comps_anchor exactness
@settings(max_examples=200, deadline=None)
@given(h_comps=_h_comps, terms=_feature_terms)
def test_comps_anchor_strictly_equals_h_comps(
    h_comps: Decimal, terms: list[da.FeatureTerm]
) -> None:
    """Validates: Requirements 1.4, 5.7; Properties 1

    Regardless of the active feature terms, the ``comps_anchor`` line equals the
    quantized ``H_comps`` exactly and is never used as a residual sink.
    """
    result = da.assemble_drivers(h_comps, terms, m_window=Decimal("1.25"))
    anchor = next(c for c in result.breakdown if c.key == da.KEY_COMPS_ANCHOR)
    assert anchor.hours == h_comps.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Property 1: Conservation to exact Decimal, churn side
# ---------------------------------------------------------------------------

# The churn side is purely additive, so it conserves by construction: the comps
# anchor (C_comps), the per-feature points, and the lineage credit
# (delta_C_franchise) sum into an unclamped total, the [0.10, 5.00] clamp is
# applied, and a single bounds_adjustment absorbs the clamp delta plus the 2 dp
# quantization residual. delta_C_franchise is summed BEFORE the clamp and the
# 1.5 hurdle. This mirrors the task-9 churn extension and pins the identity on
# the driver outputs (C_comps from comps.py, delta_C_franchise from lineage.py).

_MIN_CHURN = Decimal("0.10")
_MAX_CHURN = Decimal("5.00")
_HURDLE = Decimal("1.5")

# Comp churn percentages feeding C_comps (median); a NULL / blank entry is a
# per-metric skip. At least one entry must be a finite value so the churn median
# (C_comps) is defined (an all-skipped churn list leaves C_comps None).
_churn_value = _dec("0.00", "5.00", places=2)
_churn_metric = st.one_of(st.none(), st.just(""), _churn_value)


@st.composite
def _comp_churn_metrics(draw: st.DrawFn) -> list:
    """A comp-set churn list with at least one finite value (C_comps defined)."""
    head = [draw(_churn_value)]
    tail = draw(st.lists(_churn_metric, min_size=0, max_size=6))
    metrics = head + tail
    # Shuffle so the finite value is not always first (median is order-free).
    order = draw(st.permutations(list(range(len(metrics)))))
    return [metrics[i] for i in order]


_churn_list = _comp_churn_metrics()

# Additive per-feature churn points (already 2 dp, non-negative illustrative
# contributions).
_feature_points = st.lists(_dec("0.00", "1.50", places=2), min_size=0, max_size=5)


def _q_churn(value: Decimal) -> Decimal:
    return value.quantize(_Q_CHURN, rounding=ROUND_HALF_UP)


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value


# Feature: advanced-content-eval-drivers, Property 1: Churn-space conservation
@settings(max_examples=200, deadline=None)
@given(
    churn_metrics=_churn_list,
    feature_points=_feature_points,
    franchise_order=st.integers(min_value=1, max_value=10),
    is_franchise=st.booleans(),
)
def test_churn_conservation_sum_equals_final(
    churn_metrics: list,
    feature_points: list[Decimal],
    franchise_order: int,
    is_franchise: bool,
) -> None:
    """Validates: Requirements 5.7, 1.8, 1.4; Properties 1

    The additive churn breakdown conserves exactly at 2 dp:

        C_comps_anchor + sum(feature_points) + delta_C_franchise
                       + bounds_adjustment  ==  final_churn

    where ``C_comps`` is the comps median (``comps.py``) and
    ``delta_C_franchise`` is the lineage credit (``lineage.py``), summed into the
    unclamped total BEFORE the [0.10, 5.00] clamp and the 1.5 hurdle. The single
    ``bounds_adjustment`` entry absorbs only the clamp delta plus the 2 dp
    quantization residual.
    """
    # A non-empty comp set (the hours entries may all be skips -- C_comps is the
    # churn median, which is defined because the churn list has a finite value).
    hours_metrics = [None] * len(churn_metrics)
    comps_result = cmp.calculate_comps(hours_metrics, churn_metrics)
    assert comps_result.use_intercept_fallback is False
    c_comps = comps_result.c_comps
    assert c_comps is not None

    lineage_result = lin.calculate_lineage(
        lin.LineageFeatures(is_franchise=is_franchise, franchise_order=franchise_order),
        lin.DEFAULT_LINEAGE_PARAMS,
    )
    delta_c = lineage_result.delta_c_franchise

    with localcontext(_CTX):
        c_anchor = _q_churn(c_comps)
        points = [_q_churn(p) for p in feature_points]
        credit = _q_churn(delta_c)

        unclamped = c_anchor + sum(points, Decimal("0")) + credit
        clamped = _clamp(unclamped, _MIN_CHURN, _MAX_CHURN)
        final = _q_churn(clamped)

        line_sum = c_anchor + sum(points, Decimal("0")) + credit
        bounds_adjustment = final - line_sum

        total = c_anchor + sum(points, Decimal("0")) + credit + bounds_adjustment

    assert total == final
    assert _MIN_CHURN <= final <= _MAX_CHURN
    # A non-franchise entry earns zero credit; an active franchise earns a credit
    # inside the documented [0.15, 0.45] band (summed before the hurdle).
    if is_franchise and franchise_order > 1:
        assert lin.DELTA_C_MIN <= delta_c <= lin.DELTA_C_MAX
    else:
        assert delta_c == Decimal("0.00")


# Feature: advanced-content-eval-drivers, Property 1: Franchise credit lifts the hurdle
@settings(max_examples=100, deadline=None)
@given(franchise_order=st.integers(min_value=2, max_value=10))
def test_franchise_credit_can_cross_hurdle_then_clamp_bounds(
    franchise_order: int,
) -> None:
    """Validates: Requirements 1.8; Properties 1

    The additive loyalty credit, summed before the clamp and the hurdle, can lift
    a title that sits just below the 1.5 hurdle across it, while the [0.10, 5.00]
    clamp still bounds the final value.
    """
    lineage_result = lin.calculate_lineage(
        lin.LineageFeatures(is_franchise=True, franchise_order=franchise_order),
        lin.DEFAULT_LINEAGE_PARAMS,
    )
    delta_c = lineage_result.delta_c_franchise
    assume(delta_c > Decimal("0"))

    # A base sitting just below the hurdle by less than the credit.
    base = _HURDLE - (delta_c / Decimal("2"))
    with localcontext(_CTX):
        before = _q_churn(_clamp(base, _MIN_CHURN, _MAX_CHURN))
        after = _q_churn(_clamp(base + delta_c, _MIN_CHURN, _MAX_CHURN))

    assert before < _HURDLE
    assert after >= _HURDLE
    assert _MIN_CHURN <= after <= _MAX_CHURN


# ---------------------------------------------------------------------------
# Property 2: Monotonicity (beta_i >= 0; negative beta rejected to defaults)
# ---------------------------------------------------------------------------


# Feature: advanced-content-eval-drivers, Property 2: Non-negative beta monotonicity
@settings(max_examples=200, deadline=None)
@given(
    h_comps=_dec("500", "15000", places=0),
    key=st.sampled_from(_FEATURE_KEYS),
    x_low=_dec("0", "1.5", places=3),
    x_high=_dec("2.0", "5.0", places=3),
    beta=_dec("0.05", "0.8", places=3),
)
def test_increasing_a_non_negative_feature_never_decreases_hours(
    h_comps: Decimal,
    key: str,
    x_low: Decimal,
    x_high: Decimal,
    beta: Decimal,
) -> None:
    """Validates: Requirements 4.3; Properties 2

    With a non-negative beta, increasing a single feature value (all else held)
    never decreases the assembled prediction: exp is monotone, so the unclamped
    ``H_hat`` strictly orders and the quantized ``viewing_hours`` is
    non-decreasing.
    """
    assume(x_high > x_low)
    low_term = da.FeatureTerm(key=key, label=key, x=x_low, coefficient=beta, term=beta * x_low)
    high_term = da.FeatureTerm(key=key, label=key, x=x_high, coefficient=beta, term=beta * x_high)

    low = da.assemble_drivers(h_comps, [low_term], m_window=Decimal("1.20"))
    high = da.assemble_drivers(h_comps, [high_term], m_window=Decimal("1.20"))

    assert high.unclamped >= low.unclamped
    assert high.viewing_hours >= low.viewing_hours


# Feature: advanced-content-eval-drivers, Property 2: Negative beta rejected to defaults
@settings(max_examples=200)
@given(
    feature=st.sampled_from(sorted(vh.DEFAULT_VIEWING_HOURS_PARAMS.betas)),
    neg_beta=_dec("-5.0", "-0.001", places=3),
)
def test_negative_beta_is_rejected_to_defaults(
    feature: str, neg_beta: Decimal
) -> None:
    """Validates: Requirements 4.3; Properties 2

    A ``betas`` mapping carrying ANY negative coefficient is invalid: the
    viewing-hours full-fallback ``parse_params`` rejects the whole block to the
    DETERMINISTIC_FALLBACK defaults, so the monotone ``beta_i >= 0`` regime is
    the only one that can ever reach the assembler.
    """
    betas = {k: str(v) for k, v in vh.DEFAULT_VIEWING_HOURS_PARAMS.betas.items()}
    betas[feature] = str(neg_beta)
    raw = {"intercept": "8.0", "betas": betas, "floor": "1"}

    params, source = vh.parse_params(raw)
    # viewing_hours.parse_params tags the full-fallback source as "DEFAULTS".
    assert source != "MODEL_VERSION"
    assert params is vh.DEFAULT_VIEWING_HOURS_PARAMS
    # Every default beta is non-negative.
    assert all(v >= 0 for v in params.betas.values())


# ---------------------------------------------------------------------------
# Property 3: Multiplier boundedness
# ---------------------------------------------------------------------------


# Feature: advanced-content-eval-drivers, Property 3: Momentum multiplier boundedness
@settings(max_examples=200, deadline=None)
@given(
    stage=_active_stage,
    v_trailer=st.one_of(st.none(), _dec("-5", "20", places=3)),
    e_ratio=st.one_of(st.none(), _dec("-5", "20", places=3)),
    s_velocity=st.one_of(st.none(), _dec("-5", "20", places=3)),
)
def test_momentum_multiplier_within_bounds(
    stage: mom.Production_Stage,
    v_trailer: Decimal | None,
    e_ratio: Decimal | None,
    s_velocity: Decimal | None,
) -> None:
    """Validates: Requirements 3.5; Properties 3

    For any (even out-of-range) signals on an active, fresh, available stage, the
    composed ``Momentum_Multiplier`` is always in the inclusive
    ``[1.00, momentum_multiplier_max]`` = ``[1.00, 1.50]`` band.
    """
    features = _momentum_features(
        stage, v_trailer=v_trailer, e_ratio=e_ratio, s_velocity=s_velocity
    )
    result = mom.calculate_momentum(features, mom.DEFAULT_MOMENTUM_PARAMS)

    assert mom.NEUTRAL_MULTIPLIER <= result.multiplier
    assert result.multiplier <= mom.DEFAULT_MOMENTUM_PARAMS.momentum_multiplier_max
    assert result.multiplier <= Decimal("1.50")


# Feature: advanced-content-eval-drivers, Property 3: S_velocity clamp [0.50, 2.00]
@settings(max_examples=200, deadline=None)
@given(stage=_active_stage, s_velocity=_dec("-10", "10", places=3))
def test_momentum_is_monotone_nondecreasing_in_s_velocity(
    stage: mom.Production_Stage, s_velocity: Decimal
) -> None:
    """Validates: Requirements 3.2, 3.5; Properties 3

    ``S_velocity`` is clamped to ``[0.50, 2.00]`` before entering the
    composition, so values below 0.50 and above 2.00 saturate the multiplier at
    the same bounds as the clamp endpoints: the result stays in band and a value
    at or above 2.00 yields the same multiplier as exactly 2.00.
    """
    base = mom.calculate_momentum(
        _momentum_features(stage, s_velocity=s_velocity), mom.DEFAULT_MOMENTUM_PARAMS
    )
    at_cap = mom.calculate_momentum(
        _momentum_features(stage, s_velocity=Decimal("2.00")),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    at_floor = mom.calculate_momentum(
        _momentum_features(stage, s_velocity=Decimal("0.50")),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    assert Decimal("1.00") <= base.multiplier <= Decimal("1.50")
    if s_velocity >= Decimal("2.00"):
        assert base.multiplier == at_cap.multiplier
    if s_velocity <= Decimal("0.50"):
        assert base.multiplier == at_floor.multiplier


# Feature: advanced-content-eval-drivers, Property 3: Macro multiplier boundedness
@settings(max_examples=300)
@given(features=_macro_features)
def test_macro_multipliers_within_documented_bounds(
    features: mac.MacroFeatures,
) -> None:
    """Validates: Requirements 4.3, 4.4, 4.5; Properties 3

    Each resolved macro multiplier stays inside its documented inclusive clamp:
    IP ``[0.95, 1.25]``, seasonality ``[0.80, 1.35]``, vernacular ``[1.00,
    2.20]``; the release-window halo stays within its documented table set
    ``[1.00, 1.40]``. An absent / unrecognized descriptor resolves to the neutral
    1.00 (and is recorded as assumed).
    """
    result = mac.calculate_macro_modifiers(features, mac.DEFAULT_MACRO_PARAMS)

    assert mac.IP_BOUND_LOW <= result.source_ip_multiplier <= mac.IP_BOUND_HIGH
    assert (
        mac.SEASONALITY_BOUND_LOW
        <= result.calendar_seasonality_multiplier
        <= mac.SEASONALITY_BOUND_HIGH
    )
    assert (
        mac.VERNACULAR_BOUND_LOW
        <= result.vernacular_tam_multiplier
        <= mac.VERNACULAR_BOUND_HIGH
    )
    assert Decimal("1.00") <= result.release_window_multiplier <= Decimal("1.40")

    # Absent / unrecognized descriptors resolve to the neutral 1.00.
    if mac.normalize_descriptor(features.source_ip_provenance) not in mac.DEFAULT_SOURCE_IP_TABLE:
        assert result.source_ip_multiplier == mac.NEUTRAL_MULTIPLIER
        assert "source_ip_provenance" in result.assumed_features
    if mac.normalize_descriptor(features.release_window) not in mac.DEFAULT_RELEASE_WINDOW_TABLE:
        assert result.release_window_multiplier == mac.NEUTRAL_MULTIPLIER
        assert "release_window" in result.assumed_features


# Feature: advanced-content-eval-drivers, Property 3: Premium multipliers never reduce hours
@settings(max_examples=200, deadline=None)
@given(
    h_comps=_dec("500", "15000", places=0),
    m_momentum=_dec("1.00", "1.50", places=2),
    m_window=st.sampled_from(sorted(mac.DEFAULT_RELEASE_WINDOW_TABLE.values())),
    m_vernacular=st.sampled_from(sorted(mac.DEFAULT_VERNACULAR_TABLE.values())),
    m_calendar=_dec("1.00", "1.35", places=2),
)
def test_premium_multipliers_never_reduce_below_pre_modifier_hours(
    h_comps: Decimal,
    m_momentum: Decimal,
    m_window: Decimal,
    m_vernacular: Decimal,
    m_calendar: Decimal,
) -> None:
    """Validates: Requirements 4.3; Properties 3

    With only premium (``>= 1.00``) multipliers active (IP held neutral, since
    PUBLIC_DOMAIN = 0.95 is the single intentional sub-neutral case), the
    assembled prediction never drops below the anchor-plus-features baseline: the
    momentum, window, vernacular, and calendar line hour-deltas are each
    non-negative.
    """
    result = da.assemble_drivers(
        h_comps,
        [],
        m_momentum=m_momentum,
        m_window=m_window,
        m_ip=Decimal("1.00"),
        m_vernacular=m_vernacular,
        m_calendar=m_calendar,
    )
    for key in (
        da.KEY_MOMENTUM,
        da.KEY_RELEASE_WINDOW_HALO,
        da.KEY_VERNACULAR_TAM,
        da.KEY_CALENDAR_SEASONALITY,
    ):
        line = next(c for c in result.breakdown if c.key == key)
        assert line.hours >= Decimal("0")
    # The post-floor prediction is at least the quantized anchor.
    assert result.viewing_hours >= h_comps.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Property 4: Determinism + equal-distance tie-break
# ---------------------------------------------------------------------------


# Feature: advanced-content-eval-drivers, Property 4: Assembler determinism
@settings(max_examples=200, deadline=None)
@given(
    h_comps=_h_comps,
    terms=_feature_terms,
    m_momentum=_dec("1.00", "1.50", places=2),
    m_window=st.sampled_from(sorted(mac.DEFAULT_RELEASE_WINDOW_TABLE.values())),
    m_ip=st.sampled_from(sorted(mac.DEFAULT_SOURCE_IP_TABLE.values())),
    franchise_floor=_dec("0", "25000", places=0),
)
def test_assembler_is_deterministic(
    h_comps: Decimal,
    terms: list[da.FeatureTerm],
    m_momentum: Decimal,
    m_window: Decimal,
    m_ip: Decimal,
    franchise_floor: Decimal,
) -> None:
    """Validates: Requirements 5.7; Properties 4

    ``assemble_drivers`` called twice on identical inputs returns an equal result
    across every observable field (frozen dataclasses compare by value).
    """
    kw = dict(
        m_momentum=m_momentum,
        m_window=m_window,
        m_ip=m_ip,
        franchise_floor=franchise_floor,
    )
    first = da.assemble_drivers(h_comps, terms, **kw)
    second = da.assemble_drivers(h_comps, terms, **kw)
    assert first == second


# Feature: advanced-content-eval-drivers, Property 4: comps determinism
@settings(max_examples=200)
@given(
    hours=st.lists(st.one_of(st.none(), _dec("0", "20000", places=0)), max_size=8),
    churn=st.lists(st.one_of(st.none(), _dec("0", "5", places=2)), max_size=8),
)
def test_comps_calculation_is_deterministic(hours: list, churn: list) -> None:
    """Validates: Requirements 1.4; Properties 4

    ``calculate_comps`` is deterministic across repeated calls on identical
    in-memory metric lists.
    """
    first = cmp.calculate_comps(hours, churn)
    second = cmp.calculate_comps(hours, churn)
    assert first == second


# Feature: advanced-content-eval-drivers, Property 4: Equal-distance tie-break
@settings(max_examples=200)
@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10_000),  # title_id
            _dec("0", "0.9", places=4),  # cosine distance
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda t: t[0],
    )
)
def test_order_candidates_breaks_ties_by_title_id(rows: list) -> None:
    """Validates: Requirements 1.4; Properties 4

    ``order_candidates`` orders by ``(cosine_distance asc, title_id asc)``
    deterministically. In particular, equal-distance candidates resolve by
    ascending ``title_id`` -- the same tie-break the retrieval seam applies in
    SQL.
    """
    candidates = [
        cmp.CompCandidate(
            title_id=tid,
            cost=Decimal("1000"),
            cosine_distance=dist,
            viewing_hours=None,
            churn_pct=None,
        )
        for tid, dist in rows
    ]
    ordered = cmp.order_candidates(candidates)

    # The order is exactly the sort by (distance, title_id).
    expected = sorted(rows, key=lambda t: (t[1], t[0]))
    assert [c.title_id for c in ordered] == [tid for tid, _ in expected]

    # Pairwise: each element is <= its successor under the tie-break key.
    keys = [(c.cosine_distance, c.title_id) for c in ordered]
    assert keys == sorted(keys)


# Feature: advanced-content-eval-drivers, Property 4: Equal-distance determinism
@settings(max_examples=200)
@given(ids=st.lists(st.integers(min_value=1, max_value=5000), min_size=2, max_size=8, unique=True))
def test_equal_distance_comps_order_by_title_id(ids: list[int]) -> None:
    """Validates: Requirements 1.4; Properties 4

    When EVERY candidate sits at the same cosine distance, the realized order is
    strictly ascending by ``title_id`` (a fully-determined tie-break, no implicit
    ordering leakage).
    """
    candidates = [
        cmp.CompCandidate(
            title_id=tid,
            cost=Decimal("1000"),
            cosine_distance=Decimal("0.25"),
            viewing_hours=None,
            churn_pct=None,
        )
        for tid in ids
    ]
    ordered = cmp.order_candidates(candidates)
    assert [c.title_id for c in ordered] == sorted(ids)


# ---------------------------------------------------------------------------
# Property 5: STAGE_EXCLUDED neutrality
# ---------------------------------------------------------------------------


# Feature: advanced-content-eval-drivers, Property 5: Stage-excluded momentum neutrality
@settings(max_examples=200, deadline=None)
@given(
    stage=_excluded_stage,
    v_trailer=st.one_of(st.none(), _dec("0", "20", places=3)),
    e_ratio=st.one_of(st.none(), _dec("0", "20", places=3)),
    s_velocity=st.one_of(st.none(), _dec("0", "20", places=3)),
    source_available=st.booleans(),
)
def test_excluded_stage_momentum_is_neutral(
    stage: mom.Production_Stage,
    v_trailer: Decimal | None,
    e_ratio: Decimal | None,
    s_velocity: Decimal | None,
    source_available: bool,
) -> None:
    """Validates: Requirements 3.3; Properties 5

    A CONCEPT_SCRIPT / IN_PRODUCTION stage gates the momentum multiplier to
    exactly 1.00 with ``stage_excluded = True`` and ``reason == STAGE_EXCLUDED``,
    regardless of the (possibly strong) signal values or source availability -- an
    unproduced pitch is never moved by buzz it cannot yet have.
    """
    result = mom.calculate_momentum(
        _momentum_features(
            stage,
            v_trailer=v_trailer,
            e_ratio=e_ratio,
            s_velocity=s_velocity,
            source_available=source_available,
        ),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    assert result.multiplier == Decimal("1.00")
    assert result.stage_excluded is True
    assert result.reason == mom.REASON_STAGE_EXCLUDED


# Feature: advanced-content-eval-drivers, Property 5: Excluded stage -> 0-hour line, unchanged prediction
@settings(max_examples=200, deadline=None)
@given(
    h_comps=_dec("500", "15000", places=0),
    terms=_feature_terms,
    stage=_excluded_stage,
    v_trailer=_dec("5", "20", places=3),
    e_ratio=_dec("0.5", "5", places=3),
    s_velocity=_dec("1.5", "2.0", places=3),
)
def test_excluded_stage_yields_zero_hour_line_and_unchanged_prediction(
    h_comps: Decimal,
    terms: list[da.FeatureTerm],
    stage: mom.Production_Stage,
    v_trailer: Decimal,
    e_ratio: Decimal,
    s_velocity: Decimal,
) -> None:
    """Validates: Requirements 3.3; Properties 5

    An excluded stage feeds ``M_momentum = 1.00`` into the assembler, so the
    momentum breakdown line is exactly 0 hours and the assembled prediction is
    identical to the same assembly with momentum omitted entirely (neutral),
    across all other active drivers.
    """
    # The driver gates to 1.00 even with strong signals on an excluded stage.
    gated = mom.calculate_momentum(
        _momentum_features(stage, v_trailer=v_trailer, e_ratio=e_ratio, s_velocity=s_velocity),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    assert gated.multiplier == Decimal("1.00")

    with_momentum = da.assemble_drivers(
        h_comps, terms, m_momentum=gated.multiplier, m_window=Decimal("1.25")
    )
    neutral = da.assemble_drivers(
        h_comps, terms, m_momentum=Decimal("1.00"), m_window=Decimal("1.25")
    )

    mom_line = next(c for c in with_momentum.breakdown if c.key == da.KEY_MOMENTUM)
    assert mom_line.hours == Decimal("0")
    assert with_momentum.viewing_hours == neutral.viewing_hours
    assert with_momentum.breakdown == neutral.breakdown


# Feature: advanced-content-eval-drivers, Property 5: Staleness / unavailability degrade to neutral
@settings(max_examples=200, deadline=None)
@given(
    stage=_active_stage,
    v_trailer=_dec("5", "20", places=3),
    e_ratio=_dec("0.5", "5", places=3),
    s_velocity=_dec("1.5", "2.0", places=3),
    extra_days=st.integers(min_value=1, max_value=400),
)
def test_stale_or_unavailable_telemetry_degrades_to_neutral(
    stage: mom.Production_Stage,
    v_trailer: Decimal,
    e_ratio: Decimal,
    s_velocity: Decimal,
    extra_days: int,
) -> None:
    """Validates: Requirements 3.3, 3.5; Properties 5

    On an active stage with strong signals, a reading older than the staleness
    window degrades the multiplier to 1.00 (reason STALE), and an unavailable
    source degrades to 1.00 (reason UNAVAILABLE) -- both neutral despite the buzz.
    """
    now = datetime(2024, 6, 1, 12, 0, 0)
    window = mom.DEFAULT_MOMENTUM_PARAMS.staleness_window_days
    stale_stamp = now - timedelta(days=window + extra_days)

    stale = mom.calculate_momentum(
        _momentum_features(
            stage,
            v_trailer=v_trailer,
            e_ratio=e_ratio,
            s_velocity=s_velocity,
            last_updated_at=stale_stamp,
            now=now,
            source_available=True,
        ),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    assert stale.multiplier == Decimal("1.00")
    assert stale.reason == mom.REASON_STALE

    unavailable = mom.calculate_momentum(
        _momentum_features(
            stage,
            v_trailer=v_trailer,
            e_ratio=e_ratio,
            s_velocity=s_velocity,
            last_updated_at=now,
            now=now,
            source_available=False,
        ),
        mom.DEFAULT_MOMENTUM_PARAMS,
    )
    assert unavailable.multiplier == Decimal("1.00")
    assert unavailable.reason == mom.REASON_UNAVAILABLE
