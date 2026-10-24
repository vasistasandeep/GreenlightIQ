"""Unit tests for the Comps_Engine pure set math (Driver A, task 1).

# Feature: advanced-content-eval-drivers

Targets :mod:`app.domain.comps`: median / IQR for even and odd realized ``k``,
the ``<k`` shrink path, the zero-comps intercept-fallback signal, in-memory band
membership, and the deterministic ``(cosine, title_id asc)`` tie-break. All tests
import only the pure domain module -- no database, no app framework.

Validates: Requirements 1.3, 1.4, 1.5, 1.7, 1.8, 9.3; Properties 1, 4.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import comps as cmp


def _cand(title_id, cost, cosine, hours=None, churn=None):
    return cmp.CompCandidate(
        title_id=title_id,
        cost=Decimal(str(cost)),
        cosine_distance=Decimal(str(cosine)),
        viewing_hours=None if hours is None else Decimal(str(hours)),
        churn_pct=None if churn is None else Decimal(str(churn)),
    )


class TestMedianAndIqr:
    def test_odd_k_median_is_central_value(self) -> None:
        # The design worked example: five comps -> median is the 3rd value.
        result = cmp.calculate_comps(
            ["2600", "2900", "3100", "3400", "4200"],
            ["1.60", "1.80", "1.90", "2.10", "2.30"],
        )
        assert result.h_comps == Decimal("3100")
        assert result.c_comps == Decimal("1.90")
        assert result.realized_k == 5
        assert result.use_intercept_fallback is False

    def test_odd_k_iqr_averaged_halves(self) -> None:
        # Q3 = (3400+4200)/2 = 3800; Q1 = (2600+2900)/2 = 2750; IQR = 1050.
        result = cmp.calculate_comps(
            ["2600", "2900", "3100", "3400", "4200"], []
        )
        assert result.dispersion_iqr == Decimal("1050")

    def test_even_k_median_is_mean_of_two_centers(self) -> None:
        result = cmp.calculate_comps(
            ["2600", "2900", "3100", "3400"], ["1.60", "1.80", "2.00", "2.40"]
        )
        assert result.h_comps == (Decimal("2900") + Decimal("3100")) / Decimal("2")
        assert result.h_comps == Decimal("3000")
        assert result.c_comps == (Decimal("1.80") + Decimal("2.00")) / Decimal("2")

    def test_even_k_iqr_averaged_halves(self) -> None:
        # n=4 -> lower=[2600,2900] Q1=2750; upper=[3100,3400] Q3=3250; IQR=500.
        result = cmp.calculate_comps(["2600", "2900", "3100", "3400"], [])
        assert result.dispersion_iqr == Decimal("500")

    def test_single_comp_iqr_is_none(self) -> None:
        result = cmp.calculate_comps(["3000"], ["1.50"])
        assert result.h_comps == Decimal("3000")
        assert result.dispersion_iqr is None


class TestSkipAndShrink:
    def test_per_metric_skip_null_and_non_finite(self) -> None:
        # One NULL hours entry, one NULL churn entry -> each skipped per metric.
        result = cmp.calculate_comps(
            ["3000", None, "3200"],
            ["1.50", "1.70", None],
        )
        # Hours median over [3000, 3200]; churn median over [1.50, 1.70].
        assert result.realized_k == 3
        assert result.skipped_hours == 1
        assert result.skipped_churn == 1
        assert result.h_comps == Decimal("3100")
        assert result.c_comps == Decimal("1.60")

    def test_shrink_k_below_target(self) -> None:
        # Fewer than k=5 comps -> realized k shrinks to the eligible count.
        result = cmp.calculate_comps(["3000", "3400", "3800"], ["1.5", "1.7", "1.9"])
        assert result.realized_k == 3
        assert result.requested_k == cmp.DEFAULT_K
        assert result.use_intercept_fallback is False
        assert result.h_comps == Decimal("3400")

    def test_zero_comps_signals_intercept_fallback(self) -> None:
        result = cmp.calculate_comps([], [])
        assert result.realized_k == 0
        assert result.use_intercept_fallback is True
        assert result.source_tier == cmp.SOURCE_DETERMINISTIC_FALLBACK
        assert result.h_comps is None
        assert result.c_comps is None
        assert result.dispersion_iqr is None

    def test_all_hours_skipped_still_not_intercept_fallback(self) -> None:
        # Comps exist but every hours value is NULL: H_comps is None, yet the set
        # is non-empty so the intercept fallback is NOT triggered.
        result = cmp.calculate_comps([None, None], ["1.5", "1.7"])
        assert result.realized_k == 2
        assert result.use_intercept_fallback is False
        assert result.h_comps is None
        assert result.c_comps == Decimal("1.60")


class TestBandMembershipAndOrdering:
    def test_band_membership_excludes_out_of_band(self) -> None:
        params = cmp.DEFAULT_COMPS_PARAMS  # band [0.65x, 1.35x]
        query_cost = Decimal("1000")
        candidates = [
            _cand(1, 640, 0.1),   # below 650 -> out
            _cand(2, 650, 0.2),   # exactly low bound -> in
            _cand(3, 1000, 0.3),  # in
            _cand(4, 1350, 0.4),  # exactly high bound -> in
            _cand(5, 1360, 0.5),  # above 1350 -> out
        ]
        members = cmp.select_band_members(candidates, query_cost, params)
        assert [c.title_id for c in members] == [2, 3, 4]

    def test_band_never_widens_leaves_input_unmodified(self) -> None:
        params = cmp.DEFAULT_COMPS_PARAMS
        candidates = [_cand(1, 2000, 0.1), _cand(2, 900, 0.2)]
        before = list(candidates)
        cmp.select_band_members(candidates, Decimal("1000"), params)
        assert candidates == before

    def test_tie_break_cosine_then_title_id(self) -> None:
        candidates = [
            _cand(30, 1000, "0.20"),
            _cand(10, 1000, "0.10"),
            _cand(20, 1000, "0.10"),  # equal distance to id 10 -> title_id asc
            _cand(5, 1000, "0.30"),
        ]
        ordered = cmp.order_candidates(candidates)
        assert [c.title_id for c in ordered] == [10, 20, 30, 5]

    def test_build_comp_set_truncates_to_k(self) -> None:
        params = cmp.CompsParams(
            k=2, band_low_factor=Decimal("0.65"), band_high_factor=Decimal("1.35")
        )
        candidates = [
            _cand(1, 1000, "0.3", hours="3100", churn="1.9"),
            _cand(2, 1000, "0.1", hours="3000", churn="1.8"),
            _cand(3, 1000, "0.2", hours="3200", churn="2.0"),
        ]
        comp_set = cmp.build_comp_set(candidates, Decimal("1000"), params)
        assert comp_set.title_ids == (2, 3)  # closest two, deterministic order
        assert comp_set.viewing_hours == (Decimal("3000"), Decimal("3200"))

    def test_determinism_repeated_calls(self) -> None:
        args = (["3000", "3400", "3800"], ["1.5", "1.7", "1.9"])
        assert cmp.calculate_comps(*args) == cmp.calculate_comps(*args)


class TestParseParams:
    def test_full_fallback_on_invalid(self) -> None:
        for bad in (
            None,
            "not-a-mapping",
            {},
            {"k": 0, "band_low_factor": "0.65", "band_high_factor": "1.35"},
            {"k": 5, "band_low_factor": "-0.1", "band_high_factor": "1.35"},
            {"k": 5, "band_low_factor": "1.35", "band_high_factor": "0.65"},  # low>=high
            {"k": "x", "band_low_factor": "0.65", "band_high_factor": "1.35"},
        ):
            params, source = cmp.parse_params(bad)
            assert source == cmp.SOURCE_DETERMINISTIC_FALLBACK
            assert params is cmp.DEFAULT_COMPS_PARAMS

    def test_valid_parse_is_model_version(self) -> None:
        params, source = cmp.parse_params(
            {"k": 7, "band_low_factor": "0.70", "band_high_factor": "1.30"}
        )
        assert source == cmp.SOURCE_MODEL_VERSION
        assert params.k == 7
        assert params.band_low_factor == Decimal("0.70")
        assert params.band_high_factor == Decimal("1.30")
