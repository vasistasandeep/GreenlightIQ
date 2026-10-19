"""Inline sanity tests for the viewing-hours model (full property suite is Task 4).

These are minimal example-based checks that pin the Option-B hour-space
conservation, the L == 0 base-only case, the positive-floor clamp, and the
SUPPLIED-wins precedence. The exhaustive Hypothesis properties live in
``test_viewing_hours_properties.py`` (Task 4).
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import features as featmod
from app.domain import viewing_hours as vh


def _vector(**raw) -> featmod.FeatureVector:
    return featmod.derive_features(raw)


def test_conservation_full_feature_title() -> None:
    """sum(breakdown.hours) == viewing_hours exactly for a rich feature title."""
    vector = _vector(
        asset_type="ORIGINAL_SERIES",
        genre="drama",
        runtime_minutes=55,
        is_exclusive=True,
        production_scale=8,
        talent_pedigree=9,
        normalized_rating="0.82",
        log_vote_count="7.5",
        franchise_flag=True,
        award_signal="0.6",
    )
    result = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)
    assert result.method == "CALCULATED"
    assert result.breakdown is not None
    total = sum((c.hours for c in result.breakdown), Decimal(0))
    assert total == result.viewing_hours
    # The adjustment entry must only carry a tiny residual, never a structural
    # offset: |adjustment| is at most a couple of whole-hour rounding units.
    adj = [c for c in result.breakdown if c.key == "rounding_or_bounds_adjustment"]
    if adj:
        assert abs(adj[0].hours) <= Decimal(len(result.breakdown))


def test_l_equals_zero_is_base_only() -> None:
    """When every beta*x is zero, all hours_i == 0 and hours == base (H0)."""
    params = vh.ViewingHoursParams(
        intercept=Decimal("8.0"),
        betas={"normalized_rating": Decimal("0.6")},
        floor=vh.VIEWING_HOURS_FLOOR,
    )
    # normalized_rating == 0 -> term 0 -> L == 0.
    vector = _vector(normalized_rating="0")
    result = vh.calculate_viewing_hours(vector, params)
    assert result.breakdown is not None
    base = next(c for c in result.breakdown if c.key == "base_platform_hours")
    lifts = [c for c in result.breakdown if c.key not in ("base_platform_hours", "rounding_or_bounds_adjustment")]
    assert all(c.hours == Decimal(0) for c in lifts)
    # H0 = exp(8) - 1 ~= 2980; final should equal the base (no lift) at whole hrs.
    assert result.viewing_hours == base.hours
    assert sum((c.hours for c in result.breakdown), Decimal(0)) == result.viewing_hours


def test_floor_clamp_keeps_hours_positive() -> None:
    """A tiny intercept would give ~0 hours; the floor keeps CPVH out of null."""
    params = vh.ViewingHoursParams(
        intercept=Decimal("-50"),  # exp(-50) - 1 < 0 -> H0 floored to 0
        betas={},
        floor=Decimal("1"),
    )
    vector = _vector()
    result = vh.calculate_viewing_hours(vector, params)
    assert result.viewing_hours >= params.floor
    assert result.viewing_hours > 0
    assert sum((c.hours for c in result.breakdown), Decimal(0)) == result.viewing_hours


def test_supplied_wins_exact_including_zero() -> None:
    """A finite supplied value (incl. 0) returns exactly, SUPPLIED, no breakdown."""
    vector = _vector(normalized_rating="0.9")
    for supplied in ("1234", 0, Decimal("42.5")):
        result = vh.resolve_viewing_hours(
            supplied, vector, vh.DEFAULT_VIEWING_HOURS_PARAMS, "MODEL_VERSION"
        )
        assert result.method == "SUPPLIED"
        assert result.breakdown is None
        assert result.viewing_hours == Decimal(str(supplied))


def test_parse_params_full_fallback() -> None:
    """Invalid / missing / negative inputs collapse to defaults with DEFAULTS."""
    for bad in (None, {}, {"intercept": "x"}, {"intercept": 8, "betas": {"bad_key": 1}, "floor": 1},
                {"intercept": 8, "betas": {"normalized_rating": -1}, "floor": 1},
                {"intercept": 8, "betas": {}, "floor": 0}):
        params, source = vh.parse_params(bad)
        assert source == "DEFAULTS"
        assert params is vh.DEFAULT_VIEWING_HOURS_PARAMS

    good = {"intercept": "7.5", "betas": {"normalized_rating": "0.5"}, "floor": "2", "objective": "wape_log"}
    params, source = vh.parse_params(good)
    assert source == "MODEL_VERSION"
    assert params.intercept == Decimal("7.5")
    assert params.betas == {"normalized_rating": Decimal("0.5")}
    assert params.floor == Decimal("2")


def test_determinism() -> None:
    """Identical inputs yield an identical result on repeated calls (Property 1)."""
    vector = _vector(normalized_rating="0.7", log_vote_count="6", is_exclusive=True)
    a = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)
    b = vh.calculate_viewing_hours(vector, vh.DEFAULT_VIEWING_HOURS_PARAMS)
    assert a == b


def test_monotonicity_in_rating() -> None:
    """Raising a non-negative-beta feature never decreases predicted hours (P4)."""
    low = vh.calculate_viewing_hours(_vector(normalized_rating="0.2"), vh.DEFAULT_VIEWING_HOURS_PARAMS)
    high = vh.calculate_viewing_hours(_vector(normalized_rating="0.9"), vh.DEFAULT_VIEWING_HOURS_PARAMS)
    assert high.unclamped >= low.unclamped
    assert high.viewing_hours >= low.viewing_hours
