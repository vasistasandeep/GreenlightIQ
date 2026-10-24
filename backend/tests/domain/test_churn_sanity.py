"""Inline sanity tests for the Driver A churn anchor and Driver B loyalty credit.

These are minimal example-based checks pinning the churn-space analogue of the
hour-space ``base_hours_override`` work (task 9):

- ``base_churn_override`` seeds a ``comps_anchor`` line equal to ``C_comps`` in
  place of the ``base_platform_rate`` intercept line, and that anchor line
  strictly equals the override (it never carries any residual).
- Driver B's ``franchise_loyalty_credit`` (``delta_C_franchise``) is summed into
  the UNCLAMPED total BEFORE the ``[0.10, 5.00]`` clamp and the 1.5 hurdle /
  borderline classification, so it can lift a title across the hurdle while the
  clamp still bounds the final value.
- The churn conservation identity holds at 2 dp with the single
  ``bounds_adjustment`` line as the sole residual sink, and ``None`` / zero
  credit reproduces today's identity byte-for-byte.

The exhaustive Hypothesis conservation property lives in
``test_advanced_drivers_properties.py`` (task 6).
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.churn import (
    DEFAULT_CHURN_MODEL_PARAMS,
    MAX_CHURN,
    MIN_CHURN,
    ChurnFeatures,
    calculate_churn_mitigation,
    resolve_churn,
)

_Q = Decimal("0.01")


def _features(**overrides) -> ChurnFeatures:
    base = dict(
        asset_type="ORIGINAL_SERIES",
        pedigree=Decimal("8"),
        production_scale=Decimal("7"),
        is_exclusive=True,
        telemetry_heat=Decimal("60"),
        genre="drama",
        content_format=None,
    )
    base.update(overrides)
    return ChurnFeatures(**base)  # type: ignore[arg-type]


def _sum(result) -> Decimal:
    assert result.breakdown is not None
    return sum((c.points for c in result.breakdown), Decimal(0))


def test_defaults_are_byte_identical_to_today() -> None:
    """No override and no credit reproduces the pre-feature result exactly."""
    features = _features()
    baseline = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)
    with_none = calculate_churn_mitigation(
        features,
        DEFAULT_CHURN_MODEL_PARAMS,
        base_churn_override=None,
        franchise_loyalty_credit=None,
    )
    assert with_none == baseline
    # The base line is still the intercept-derived platform-rate line.
    assert with_none.breakdown is not None
    assert with_none.breakdown[0].key == "base_platform_rate"
    # And there is no franchise credit line when no credit is supplied.
    assert not any(c.key == "franchise_loyalty_credit" for c in with_none.breakdown)


def test_zero_credit_reproduces_today_identity() -> None:
    """An explicit zero credit is a no-op: no extra line, result unchanged."""
    features = _features()
    baseline = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)
    with_zero = calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS, franchise_loyalty_credit=Decimal("0")
    )
    assert with_zero == baseline
    assert with_zero.breakdown is not None
    assert not any(c.key == "franchise_loyalty_credit" for c in with_zero.breakdown)


def test_comps_anchor_replaces_intercept_and_equals_override() -> None:
    """base_churn_override seeds a comps_anchor line strictly equal to C_comps."""
    features = _features()
    c_comps = Decimal("1.90")
    result = calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS, base_churn_override=c_comps
    )
    assert result.breakdown is not None
    anchor = result.breakdown[0]
    assert anchor.key == "comps_anchor"
    assert anchor.label == "Comps Anchor"
    # Strictly equals the anchor value; never carries any residual.
    assert anchor.points == c_comps
    # The intercept line is gone.
    assert not any(c.key == "base_platform_rate" for c in result.breakdown)


def test_conservation_with_anchor_and_credit() -> None:
    """Breakdown sums exactly to the final value at 2 dp with anchor + credit."""
    features = _features()
    result = calculate_churn_mitigation(
        features,
        DEFAULT_CHURN_MODEL_PARAMS,
        base_churn_override=Decimal("1.90"),
        franchise_loyalty_credit=Decimal("0.25"),
    )
    assert result.breakdown is not None
    # The credit line is present and equals delta_C_franchise.
    credit = next(c for c in result.breakdown if c.key == "franchise_loyalty_credit")
    assert credit.points == Decimal("0.25")
    # Exactly one bounds_adjustment residual sink at most.
    sinks = [c for c in result.breakdown if c.key == "bounds_adjustment"]
    assert len(sinks) <= 1
    # Conservation: sum of all lines == final churn, at 2 dp.
    assert _sum(result) == result.churn_reduction_pct
    assert result.churn_reduction_pct == result.churn_reduction_pct.quantize(_Q)


def test_credit_lifts_across_the_1_5_hurdle() -> None:
    """delta_C_franchise summed BEFORE the hurdle can push a title across 1.5."""
    # Build a title that lands just under the 1.5 hurdle without the credit.
    features = _features(
        asset_type="ORIGINAL_FILM",
        pedigree=Decimal("5"),
        production_scale=Decimal("3"),
        is_exclusive=False,
        telemetry_heat=Decimal("40"),
        genre="comedy",
    )
    without = calculate_churn_mitigation(features, DEFAULT_CHURN_MODEL_PARAMS)
    assert without.churn_reduction_pct < Decimal("1.5")

    # A credit large enough to clear the gap lifts the resolved value across 1.5
    # (the credit enters the UNCLAMPED total before the hurdle classification).
    gap = Decimal("1.5") - without.churn_reduction_pct
    credit = (gap + Decimal("0.10")).quantize(_Q)
    with_credit = calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS, franchise_loyalty_credit=credit
    )
    assert with_credit.churn_reduction_pct >= Decimal("1.5")
    assert _sum(with_credit) == with_credit.churn_reduction_pct


def test_clamp_still_bounds_final_value_with_large_credit() -> None:
    """Even a huge credit cannot push the final value past MAX_CHURN."""
    features = _features()
    result = calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS, franchise_loyalty_credit=Decimal("99")
    )
    assert result.churn_reduction_pct == MAX_CHURN
    # The unclamped total reflects the pre-clamp sum (> MAX_CHURN).
    assert result.unclamped is not None and result.unclamped > MAX_CHURN
    # bounds_adjustment absorbs the clamp delta; the sum still conserves.
    assert _sum(result) == result.churn_reduction_pct
    assert MIN_CHURN <= result.churn_reduction_pct <= MAX_CHURN


def test_resolve_churn_threads_anchor_and_credit_when_not_supplied() -> None:
    """resolve_churn forwards the anchor/credit on the CALCULATED path."""
    features = _features()
    result = resolve_churn(
        None,
        features,
        DEFAULT_CHURN_MODEL_PARAMS,
        "MODEL_VERSION",
        base_churn_override=Decimal("1.90"),
        franchise_loyalty_credit=Decimal("0.25"),
    )
    assert result.method == "CALCULATED"
    assert result.breakdown is not None
    assert result.breakdown[0].key == "comps_anchor"
    assert any(c.key == "franchise_loyalty_credit" for c in result.breakdown)


def test_supplied_value_wins_over_anchor_and_credit() -> None:
    """A finite SUPPLIED value ignores the driver anchor/credit (precedence)."""
    features = _features()
    result = resolve_churn(
        Decimal("2.10"),
        features,
        DEFAULT_CHURN_MODEL_PARAMS,
        "MODEL_VERSION",
        base_churn_override=Decimal("1.90"),
        franchise_loyalty_credit=Decimal("0.25"),
    )
    assert result.method == "SUPPLIED"
    assert result.breakdown is None
    assert result.churn_reduction_pct == Decimal("2.10")
