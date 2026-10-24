"""Unit tests for the Lineage_Decay pure math (Driver B, task 2).

# Feature: advanced-content-eval-drivers

Targets :mod:`app.domain.lineage`: the Franchise_Floor formula, the
``delta_C_franchise`` clamp and monotonicity, the sequel-with-missing-parent
0.70-retention fallback, the non-franchise zero path, and the full-fallback
params parse. Pure domain only.

Validates: Requirements 2.1-2.6, 9.3; Properties 1, 2.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import lineage as lin


def _features(**overrides) -> lin.LineageFeatures:
    base = dict(
        is_franchise=True,
        franchise_order=2,
        parent_title_viewing_hours=Decimal("5000"),
        parent_completion_rate=Decimal("0.80"),
        genre_baseline_viewing_hours=Decimal("3000"),
    )
    base.update(overrides)
    return lin.LineageFeatures(**base)


class TestFranchiseFloor:
    def test_floor_formula(self) -> None:
        # 5000 * (0.55 + 0.35 * 0.80) = 5000 * 0.83 = 4150.
        result = lin.calculate_lineage(_features(), lin.DEFAULT_LINEAGE_PARAMS)
        assert result.is_active is True
        assert result.franchise_floor == Decimal("4150.00")

    def test_completion_rate_clamped_to_unit_interval(self) -> None:
        # rate > 1 clamps to 1.0: 5000 * (0.55 + 0.35*1.0) = 5000*0.90 = 4500.
        result = lin.calculate_lineage(
            _features(parent_completion_rate=Decimal("1.5")),
            lin.DEFAULT_LINEAGE_PARAMS,
        )
        assert result.franchise_floor == Decimal("4500.00")

    def test_inputs_not_mutated(self) -> None:
        feats = _features()
        hours_before = feats.parent_title_viewing_hours
        lin.calculate_lineage(feats, lin.DEFAULT_LINEAGE_PARAMS)
        assert feats.parent_title_viewing_hours == hours_before


class TestDeltaCFranchise:
    def test_second_entry_credit(self) -> None:
        # clamp(0.15 + 0.05*min(2-1,6)) = 0.20.
        result = lin.calculate_lineage(
            _features(franchise_order=2), lin.DEFAULT_LINEAGE_PARAMS
        )
        assert result.delta_c_franchise == Decimal("0.20")

    def test_clamp_floor_is_min(self) -> None:
        # order=1 is non-franchise path (handled below); the minimum active
        # credit for order=2 is already 0.20, but the band floor is 0.15.
        assert lin.DELTA_C_MIN == Decimal("0.15")

    def test_saturates_at_band_ceiling(self) -> None:
        # order >= 7 -> loyalty signal capped at 6 -> 0.15 + 0.05*6 = 0.45.
        for order in (7, 8, 20):
            result = lin.calculate_lineage(
                _features(franchise_order=order), lin.DEFAULT_LINEAGE_PARAMS
            )
            assert result.delta_c_franchise == Decimal("0.45")

    def test_monotonic_non_decreasing(self) -> None:
        prev = Decimal("-1")
        for order in range(2, 12):
            result = lin.calculate_lineage(
                _features(franchise_order=order), lin.DEFAULT_LINEAGE_PARAMS
            )
            assert result.delta_c_franchise >= prev
            assert lin.DELTA_C_MIN <= result.delta_c_franchise <= lin.DELTA_C_MAX
            prev = result.delta_c_franchise


class TestMissingParentFallback:
    def test_missing_rate_uses_070(self) -> None:
        # No parent completion rate -> assumed 0.70. 5000*(0.55+0.35*0.70)=3975.
        result = lin.calculate_lineage(
            _features(parent_completion_rate=None), lin.DEFAULT_LINEAGE_PARAMS
        )
        assert "parent_completion_rate" in result.assumed_features
        assert result.franchise_floor == Decimal("3975.00")

    def test_missing_hours_uses_genre_baseline_and_070(self) -> None:
        # No parent hours -> genre baseline 3000; no rate -> 0.70.
        # 3000*(0.55+0.35*0.70)=3000*0.795=2385.
        result = lin.calculate_lineage(
            _features(parent_title_viewing_hours=None, parent_completion_rate=None),
            lin.DEFAULT_LINEAGE_PARAMS,
        )
        assert "parent_completion_rate" in result.assumed_features
        assert result.franchise_floor == Decimal("2385.00")

    def test_missing_hours_and_no_baseline_yields_zero_floor(self) -> None:
        result = lin.calculate_lineage(
            _features(
                parent_title_viewing_hours=None,
                parent_completion_rate=None,
                genre_baseline_viewing_hours=None,
            ),
            lin.DEFAULT_LINEAGE_PARAMS,
        )
        assert result.franchise_floor == Decimal("0")
        # Credit is independent of the floor and still earned.
        assert result.delta_c_franchise == Decimal("0.20")


class TestNonFranchise:
    def test_not_franchise_is_zero(self) -> None:
        result = lin.calculate_lineage(
            _features(is_franchise=False), lin.DEFAULT_LINEAGE_PARAMS
        )
        assert result.is_active is False
        assert result.franchise_floor == Decimal("0")
        assert result.delta_c_franchise == Decimal("0.00")

    def test_original_order_one_is_zero(self) -> None:
        result = lin.calculate_lineage(
            _features(franchise_order=1), lin.DEFAULT_LINEAGE_PARAMS
        )
        assert result.is_active is False
        assert result.franchise_floor == Decimal("0")
        assert result.delta_c_franchise == Decimal("0.00")


class TestParseParams:
    def test_full_fallback_on_invalid(self) -> None:
        for bad in (
            None,
            "not-a-mapping",
            {},
            {"alpha_base_decay": "-0.1", "beta_comp": "0.35",
             "gamma_base": "0.15", "delta_order": "0.05"},
            {"alpha_base_decay": "x", "beta_comp": "0.35",
             "gamma_base": "0.15", "delta_order": "0.05"},
            {"alpha_base_decay": "0.55", "beta_comp": "0.35",
             "gamma_base": "0.15", "delta_order": "0.05", "loyalty_cap": 0},
        ):
            params, source = lin.parse_params(bad)
            assert source == lin.SOURCE_DETERMINISTIC_FALLBACK
            assert params is lin.DEFAULT_LINEAGE_PARAMS

    def test_valid_parse_is_model_version(self) -> None:
        params, source = lin.parse_params(
            {
                "alpha_base_decay": "0.60",
                "beta_comp": "0.30",
                "gamma_base": "0.10",
                "delta_order": "0.04",
                "loyalty_cap": 8,
            }
        )
        assert source == lin.SOURCE_MODEL_VERSION
        assert params.alpha_base_decay == Decimal("0.60")
        assert params.loyalty_cap == 8
