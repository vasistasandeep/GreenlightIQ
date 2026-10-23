"""Unit tests for the Macro_Modifiers pure math (Driver D, task 4).

# Feature: advanced-content-eval-drivers

Targets :mod:`app.domain.macro_modifiers`: each of the four lookup tables, their
inclusive clamps, the unknown-descriptor -> neutral 1.00 (recorded as assumed)
path, the intentional PUBLIC_DOMAIN sub-neutral IP value, and the full-fallback
params parse. Pure domain only.

Validates: Requirements 4.1-4.6, 9.3; Properties 3.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import macro_modifiers as mac


class TestSourceIpProvenance:
    def test_each_documented_value(self) -> None:
        cases = {
            "ORIGINAL_SCREENPLAY": Decimal("1.00"),
            "BESTSELLER_BOOK": Decimal("1.20"),
            "TRUE_CRIME_IP": Decimal("1.25"),
            "WEBTOON_MANGA": Decimal("1.15"),
            "PUBLIC_DOMAIN": Decimal("0.95"),
        }
        for descriptor, expected in cases.items():
            result = mac.calculate_macro_modifiers(
                mac.MacroFeatures(source_ip_provenance=descriptor),
                mac.DEFAULT_MACRO_PARAMS,
            )
            assert result.source_ip_multiplier == expected

    def test_public_domain_is_the_only_sub_neutral(self) -> None:
        sub_neutral = [
            k for k, v in mac.DEFAULT_SOURCE_IP_TABLE.items() if v < Decimal("1.00")
        ]
        assert sub_neutral == ["PUBLIC_DOMAIN"]

    def test_unknown_ip_is_neutral_assumed(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(source_ip_provenance="MYSTERY_SOURCE"),
            mac.DEFAULT_MACRO_PARAMS,
        )
        assert result.source_ip_multiplier == Decimal("1.00")
        assert "source_ip_provenance" in result.assumed_features

    def test_ip_values_within_bound(self) -> None:
        for v in mac.DEFAULT_SOURCE_IP_TABLE.values():
            assert mac.IP_BOUND_LOW <= v <= mac.IP_BOUND_HIGH


class TestReleaseWindowHalo:
    def test_each_documented_value(self) -> None:
        cases = {
            "DIRECT_TO_STREAMING": Decimal("1.00"),
            "DAY_AND_DATE": Decimal("1.10"),
            "THEATRICAL_30D": Decimal("1.25"),
            "THEATRICAL_60D_PLUS": Decimal("1.40"),
        }
        for descriptor, expected in cases.items():
            result = mac.calculate_macro_modifiers(
                mac.MacroFeatures(release_window=descriptor),
                mac.DEFAULT_MACRO_PARAMS,
            )
            assert result.release_window_multiplier == expected

    def test_descriptor_normalization(self) -> None:
        # Mixed case / hyphens normalize to the same key.
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(release_window="theatrical-30d"),
            mac.DEFAULT_MACRO_PARAMS,
        )
        assert result.release_window_multiplier == Decimal("1.25")

    def test_unknown_window_is_neutral_assumed(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(release_window="LIMITED_DRIVE_IN"),
            mac.DEFAULT_MACRO_PARAMS,
        )
        assert result.release_window_multiplier == Decimal("1.00")
        assert "release_window" in result.assumed_features


class TestCalendarSeasonality:
    def test_each_month_lookup_within_clamp(self) -> None:
        for month in range(1, 13):
            result = mac.calculate_macro_modifiers(
                mac.MacroFeatures(release_month=month), mac.DEFAULT_MACRO_PARAMS
            )
            m = result.calendar_seasonality_multiplier
            assert mac.SEASONALITY_BOUND_LOW <= m <= mac.SEASONALITY_BOUND_HIGH
            assert m == mac.DEFAULT_SEASONALITY_TABLE[month]

    def test_null_month_is_neutral_assumed(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(release_month=None), mac.DEFAULT_MACRO_PARAMS
        )
        assert result.calendar_seasonality_multiplier == Decimal("1.00")
        assert "release_month" in result.assumed_features

    def test_out_of_range_month_is_neutral(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(release_month=13), mac.DEFAULT_MACRO_PARAMS
        )
        assert result.calendar_seasonality_multiplier == Decimal("1.00")

    def test_seasonality_table_clamped_when_out_of_bound(self) -> None:
        # A custom table with an out-of-bound value is clamped at lookup.
        params = mac.MacroParams(
            source_ip_table=mac.DEFAULT_SOURCE_IP_TABLE,
            release_window_table=mac.DEFAULT_RELEASE_WINDOW_TABLE,
            seasonality_table={6: Decimal("2.00")},  # above 1.35
            vernacular_table=mac.DEFAULT_VERNACULAR_TABLE,
        )
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(release_month=6), params
        )
        assert result.calendar_seasonality_multiplier == mac.SEASONALITY_BOUND_HIGH


class TestVernacularTam:
    def test_each_documented_count(self) -> None:
        cases = {
            1: Decimal("1.00"),
            2: Decimal("1.40"),
            3: Decimal("1.80"),
            4: Decimal("2.20"),
        }
        for count, expected in cases.items():
            result = mac.calculate_macro_modifiers(
                mac.MacroFeatures(vernacular_track_count=count),
                mac.DEFAULT_MACRO_PARAMS,
            )
            assert result.vernacular_tam_multiplier == expected

    def test_count_above_max_saturates_at_bound(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(vernacular_track_count=10), mac.DEFAULT_MACRO_PARAMS
        )
        assert result.vernacular_tam_multiplier == mac.VERNACULAR_BOUND_HIGH

    def test_none_count_is_neutral_assumed(self) -> None:
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(vernacular_track_count=None), mac.DEFAULT_MACRO_PARAMS
        )
        assert result.vernacular_tam_multiplier == Decimal("1.00")
        assert "vernacular_track_count" in result.assumed_features

    def test_values_within_bound(self) -> None:
        for v in mac.DEFAULT_VERNACULAR_TABLE.values():
            assert mac.VERNACULAR_BOUND_LOW <= v <= mac.VERNACULAR_BOUND_HIGH


class TestProductAndNeutrality:
    def test_all_neutral_product_is_one(self) -> None:
        # Fully-absent features -> every modifier neutral -> product 1.00.
        result = mac.calculate_macro_modifiers(
            mac.MacroFeatures(), mac.DEFAULT_MACRO_PARAMS
        )
        assert result.product == Decimal("1.00")
        assert set(result.assumed_features) == {
            "source_ip_provenance",
            "release_window",
            "release_month",
            "vernacular_track_count",
        }

    def test_product_is_multiplier_of_parts(self) -> None:
        feats = mac.MacroFeatures(
            source_ip_provenance="BESTSELLER_BOOK",  # 1.20
            release_window="THEATRICAL_30D",  # 1.25
            release_month=12,  # 1.30
            vernacular_track_count=1,  # 1.00
        )
        result = mac.calculate_macro_modifiers(feats, mac.DEFAULT_MACRO_PARAMS)
        expected = Decimal("1.20") * Decimal("1.25") * Decimal("1.30") * Decimal("1.00")
        assert result.product == expected

    def test_inputs_not_mutated(self) -> None:
        feats = mac.MacroFeatures(release_window="DAY_AND_DATE", release_month=7)
        mac.calculate_macro_modifiers(feats, mac.DEFAULT_MACRO_PARAMS)
        assert feats.release_window == "DAY_AND_DATE"
        assert feats.release_month == 7


class TestParseParams:
    def test_full_fallback_on_invalid(self) -> None:
        for bad in (
            None,
            "not-a-mapping",
            {"source_ip_table": "not-a-mapping"},
            {"source_ip_table": {"X": "-1"}},  # negative multiplier
            {"seasonality_table": {"notint": "1.0"}},
            {"ip_bound_low": "1.5", "ip_bound_high": "1.0"},  # low > high
        ):
            params, source = mac.parse_params(bad)
            assert source == mac.SOURCE_DETERMINISTIC_FALLBACK
            assert params is mac.DEFAULT_MACRO_PARAMS

    def test_empty_mapping_uses_default_tables(self) -> None:
        params, source = mac.parse_params({})
        assert source == mac.SOURCE_MODEL_VERSION
        assert params.source_ip_table is mac.DEFAULT_SOURCE_IP_TABLE
        assert params.release_window_table is mac.DEFAULT_RELEASE_WINDOW_TABLE

    def test_valid_custom_tables_parse(self) -> None:
        params, source = mac.parse_params(
            {
                "source_ip_table": {"original_screenplay": "1.00", "remake": "1.05"},
                "vernacular_table": {1: "1.00", 2: "1.50"},
            }
        )
        assert source == mac.SOURCE_MODEL_VERSION
        assert params.source_ip_table["REMAKE"] == Decimal("1.05")
        assert params.vernacular_table[2] == Decimal("1.50")
