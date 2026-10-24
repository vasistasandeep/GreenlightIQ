"""Inline sanity tests for the combined log-space assembler (Task 5).

These are minimal example-based checks that pin the normative seven-stage
Attribution_Order, the Option-B hour-space conservation, the exact
``comps_anchor == H_comps`` guarantee, the isolated Stage-7 franchise floor, and
the neutral-multiplier inertness. The exhaustive Hypothesis gating suite
(Properties 1-5) lives in ``test_advanced_drivers_properties.py`` (Task 6).
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import driver_assembly as da


def _term(key: str, x: str, beta: str) -> da.FeatureTerm:
    xd = Decimal(x)
    bd = Decimal(beta)
    return da.FeatureTerm(
        key=key, label=key.replace("_", " ").title(), x=xd, coefficient=bd, term=bd * xd
    )


def _line(result: da.AssemblyResult, key: str) -> da.AssemblyLine:
    return next(c for c in result.breakdown if c.key == key)


def test_design_worked_example_aurora_protocol() -> None:
    """Reproduces the design's Aurora Protocol worked example to the whole hour."""
    terms = [
        _term("normalized_rating", "0.80", "0.12"),
        _term("franchise_flag", "1", "0.08"),
        _term("award_signal", "0.30", "0.10"),
    ]
    result = da.assemble_drivers(
        Decimal("3100"),
        terms,
        m_momentum=Decimal("1.00"),
        m_window=Decimal("1.25"),
        m_ip=Decimal("1.20"),
        m_vernacular=Decimal("1.00"),
        m_calendar=Decimal("1.15"),
        franchise_floor=Decimal("0"),
    )
    # H_hat quantizes to 6572 per the design example.
    assert result.viewing_hours == Decimal("6572")
    assert _line(result, "comps_anchor").hours == Decimal("3100")
    assert _line(result, "normalized_rating").hours == Decimal("331")
    assert _line(result, "franchise_flag").hours == Decimal("275")
    assert _line(result, "award_signal").hours == Decimal("103")
    assert _line(result, "momentum").hours == Decimal("0")
    assert _line(result, "release_window_halo").hours == Decimal("953")
    assert _line(result, "source_ip_provenance").hours == Decimal("953")
    assert _line(result, "vernacular_tam").hours == Decimal("0")
    assert _line(result, "calendar_seasonality").hours == Decimal("857")
    assert _line(result, "franchise_floor").hours == Decimal("0")
    # Residual is exactly 0 for this example (no adjustment line emitted).
    assert all(c.key != "rounding_or_bounds_adjustment" for c in result.breakdown)


def test_conservation_sum_equals_prediction() -> None:
    """sum(breakdown.hours) == viewing_hours exactly across all stages."""
    terms = [
        _term("normalized_rating", "0.82", "0.60"),
        _term("log_vote_count", "7.5", "0.35"),
        _term("award_signal", "0.6", "0.30"),
    ]
    result = da.assemble_drivers(
        Decimal("2980"),
        terms,
        m_momentum=Decimal("1.30"),
        m_window=Decimal("1.40"),
        m_ip=Decimal("1.25"),
        m_vernacular=Decimal("1.80"),
        m_calendar=Decimal("1.35"),
        franchise_floor=Decimal("9000"),
    )
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours
    # H7 == H_hat (post-floor) and the prediction is the quantized H7.
    assert result.running_hours[-1] == result.unclamped


def test_comps_anchor_strictly_equals_h_comps() -> None:
    """The comps_anchor line equals quantize(H_comps), never a residual sink."""
    result = da.assemble_drivers(Decimal("4123"), [], m_window=Decimal("1.25"))
    assert _line(result, "comps_anchor").hours == Decimal("4123")


def test_franchise_floor_isolated_lift() -> None:
    """A floor above H6 lifts the prediction via the franchise_floor line only."""
    # No features, all neutral multipliers -> H6 == H0 == 3000.
    result = da.assemble_drivers(Decimal("3000"), [], franchise_floor=Decimal("5000"))
    assert _line(result, "comps_anchor").hours == Decimal("3000")
    assert _line(result, "franchise_floor").hours == Decimal("2000")
    assert result.viewing_hours == Decimal("5000")
    # The residual sink never carries the structural floor lift.
    adj = [c for c in result.breakdown if c.key == "rounding_or_bounds_adjustment"]
    assert adj == [] or abs(adj[0].hours) <= Decimal(len(result.breakdown))


def test_inactive_floor_is_noop() -> None:
    """A floor at/below H6 contributes a 0-hour franchise_floor line (d_floor == 0)."""
    result = da.assemble_drivers(Decimal("3000"), [], franchise_floor=Decimal("1000"))
    assert _line(result, "franchise_floor").hours == Decimal("0")
    assert result.viewing_hours == Decimal("3000")


def test_neutral_multipliers_emit_zero_hour_lines() -> None:
    """All-neutral multipliers (1.00) contribute 0-hour lines (inertness)."""
    result = da.assemble_drivers(
        Decimal("2980"),
        [_term("normalized_rating", "0.5", "0.6")],
        m_momentum=Decimal("1.00"),
        m_window=Decimal("1.00"),
        m_ip=Decimal("1.00"),
        m_vernacular=Decimal("1.00"),
        m_calendar=Decimal("1.00"),
    )
    for key in (
        "momentum",
        "release_window_halo",
        "source_ip_provenance",
        "vernacular_tam",
        "calendar_seasonality",
    ):
        assert _line(result, key).hours == Decimal("0")
    assert sum((c.hours for c in result.breakdown), Decimal(0)) == result.viewing_hours


def test_l_equals_zero_allocates_no_feature_hours() -> None:
    """When every beta*x is zero, each feature line is 0 and H1 == H0."""
    result = da.assemble_drivers(
        Decimal("2980"),
        [_term("normalized_rating", "0", "0.6")],
        m_window=Decimal("1.25"),
    )
    assert _line(result, "normalized_rating").hours == Decimal("0")
    # H1 round-trips exp(ln(1 + H0)); it equals H0 to the whole hour (the only
    # resolution that matters for the breakdown), modulo transcendental noise.
    h0, h1 = result.running_hours[0], result.running_hours[1]
    assert h0.quantize(Decimal("1")) == h1.quantize(Decimal("1"))
    assert sum((c.hours for c in result.breakdown), Decimal(0)) == result.viewing_hours
