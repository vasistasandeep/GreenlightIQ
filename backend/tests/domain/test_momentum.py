"""Unit tests for the Momentum_Telemetry pure math (Driver C, task 3).

# Feature: advanced-content-eval-drivers

Targets :mod:`app.domain.momentum`: the new ``Production_Stage`` enum and its
coercion, stage-gating neutrality (CONCEPT_SCRIPT / IN_PRODUCTION -> 1.00), the
composition clamp bounds, staleness / unavailable degradation, and the
full-fallback params parse. Pure domain only.

Validates: Requirements 3.1-3.6, 10.2-10.5, 9.3; Properties 3, 5.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.domain import deal_stage as ds
from app.domain import momentum as mom

_NOW = datetime(2024, 6, 1, 12, 0, 0)


def _features(stage, **overrides) -> mom.MomentumFeatures:
    base = dict(
        production_stage=stage,
        v_trailer=Decimal("1.0"),
        e_ratio=Decimal("0.5"),
        s_velocity=Decimal("1.0"),
        last_updated_at=_NOW,
        source_available=True,
        now=_NOW,
    )
    base.update(overrides)
    return mom.MomentumFeatures(**base)


class TestStageEnum:
    def test_distinct_from_deal_stage(self) -> None:
        prod_values = {s.value for s in mom.Production_Stage}
        deal_values = {s.value for s in ds.DealStage}
        assert prod_values.isdisjoint(deal_values)

    def test_coerce_known_and_unknown(self) -> None:
        assert mom.coerce_stage("ACQUISITION_READY") is mom.Production_Stage.ACQUISITION_READY
        assert mom.coerce_stage(mom.Production_Stage.IN_PRODUCTION) is mom.Production_Stage.IN_PRODUCTION
        # Unknown / None -> the initial (gated) stage, never raises.
        assert mom.coerce_stage(None) is mom.INITIAL_STAGE
        assert mom.coerce_stage("NONSENSE") is mom.INITIAL_STAGE


class TestStageGating:
    def test_concept_script_is_neutral_excluded(self) -> None:
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.CONCEPT_SCRIPT, v_trailer=Decimal("2.0"),
                      e_ratio=Decimal("1.0"), s_velocity=Decimal("2.0")),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        # Even with saturating signals, a gated stage stays at 1.00.
        assert result.multiplier == Decimal("1.00")
        assert result.stage_excluded is True
        assert result.reason == mom.REASON_STAGE_EXCLUDED

    def test_in_production_is_neutral_excluded(self) -> None:
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.IN_PRODUCTION, s_velocity=Decimal("2.0")),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.multiplier == Decimal("1.00")
        assert result.stage_excluded is True
        assert result.reason == mom.REASON_STAGE_EXCLUDED


class TestComposition:
    def test_neutral_signals_give_one(self) -> None:
        # norm(V)=1, E_norm=0.5, S=1 -> raw = 1 + 0.15*1 + 0.20*0.5 + 0 = 1.25.
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=Decimal("1.0"), e_ratio=Decimal("0.5"),
                      s_velocity=Decimal("1.0")),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.reason == mom.REASON_ACTIVE
        assert result.multiplier == Decimal("1.25")

    def test_saturating_signals_clamp_to_max(self) -> None:
        # norm(V)=2, E_norm=1, S=2 -> raw = 1+0.30+0.20+0.25 = 1.75 -> clamp 1.50.
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.FESTIVAL_PREVIEW,
                      v_trailer=Decimal("5.0"), e_ratio=Decimal("5.0"),
                      s_velocity=Decimal("5.0")),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.multiplier == mom.DEFAULT_MOMENTUM_PARAMS.momentum_multiplier_max
        assert result.multiplier == Decimal("1.50")

    def test_floor_at_one_for_weak_signal(self) -> None:
        # Low S_velocity clamped to 0.50 -> (S-1) = -0.50 contribution negative;
        # raw could dip below 1 but the multiplier floors at 1.00.
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=Decimal("0"), e_ratio=Decimal("0"),
                      s_velocity=Decimal("0.0")),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.multiplier == Decimal("1.00")
        assert mom.NEUTRAL_MULTIPLIER <= result.multiplier <= Decimal("1.50")

    def test_missing_signals_treated_as_neutral(self) -> None:
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=None, e_ratio=None, s_velocity=None),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        # norm(V)=0, E_norm=0, S=1 -> raw = 1.00.
        assert result.multiplier == Decimal("1.00")
        assert result.reason == mom.REASON_ACTIVE


class TestDegradation:
    def test_stale_reading_is_neutral(self) -> None:
        old = _NOW - timedelta(days=15)  # older than the 14-day window
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=Decimal("2.0"), last_updated_at=old),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.multiplier == Decimal("1.00")
        assert result.reason == mom.REASON_STALE
        assert result.reading_age_days == 15

    def test_exactly_window_is_not_stale(self) -> None:
        edge = _NOW - timedelta(days=14)
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=Decimal("1.0"), e_ratio=Decimal("0.5"),
                      s_velocity=Decimal("1.0"), last_updated_at=edge),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.reason == mom.REASON_ACTIVE
        assert result.multiplier == Decimal("1.25")

    def test_unavailable_source_is_neutral(self) -> None:
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.ACQUISITION_READY,
                      v_trailer=Decimal("2.0"), source_available=False),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.multiplier == Decimal("1.00")
        assert result.reason == mom.REASON_UNAVAILABLE

    def test_stage_gating_precedes_degradation(self) -> None:
        # A gated stage reports STAGE_EXCLUDED even when also stale/unavailable.
        old = _NOW - timedelta(days=30)
        result = mom.calculate_momentum(
            _features(mom.Production_Stage.CONCEPT_SCRIPT,
                      source_available=False, last_updated_at=old),
            mom.DEFAULT_MOMENTUM_PARAMS,
        )
        assert result.reason == mom.REASON_STAGE_EXCLUDED


class TestParseParams:
    def test_full_fallback_on_invalid(self) -> None:
        good = {
            "w_v": "0.15", "w_e": "0.20", "w_s": "0.25", "baseline_v": "1.0",
            "cap_v": "2.00", "cap_e": "1.00", "momentum_multiplier_max": "1.50",
            "staleness_window_days": 14,
        }
        bad_cases = [
            None,
            "not-a-mapping",
            {},
            {**good, "w_v": "-0.1"},
            {**good, "baseline_v": "0"},  # must be strictly positive
            {**good, "momentum_multiplier_max": "0.9"},  # must be >= 1.00
            {**good, "staleness_window_days": 0},
        ]
        for bad in bad_cases:
            params, source = mom.parse_params(bad)
            assert source == mom.SOURCE_DETERMINISTIC_FALLBACK
            assert params is mom.DEFAULT_MOMENTUM_PARAMS

    def test_valid_parse_is_model_version(self) -> None:
        params, source = mom.parse_params(
            {
                "w_v": "0.10", "w_e": "0.15", "w_s": "0.20", "baseline_v": "2.0",
                "cap_v": "3.00", "cap_e": "1.50", "momentum_multiplier_max": "1.75",
                "staleness_window_days": 7,
            }
        )
        assert source == mom.SOURCE_MODEL_VERSION
        assert params.w_v == Decimal("0.10")
        assert params.momentum_multiplier_max == Decimal("1.75")
        assert params.staleness_window_days == 7
