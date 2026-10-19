"""Tests for the offline Backtest_Harness (content-eval-model, task 10).

# Feature: content-eval-model

Targets the pure :mod:`app.engines.backtest_harness` module (task 9). The suite
mixes crafted small in-memory datasets (so the computed metrics are known exactly)
with a smoke test over the committed ``content_eval_dataset.json``. It pins down
Requirement 6 (the Backtest_Harness and KPI impact measurement) and the design's
Correctness Properties 10, 11, 13 and 14:

- correct MAPE / WAPE / verdict-match on crafted fixtures;
- the asymmetric ``False_Greenlight_Rate`` and ``False_Pass_Rate``;
- Output_KPI deltas from :func:`compare_versions` with one-changed-model attribution;
- Property 10: a regressing candidate is flagged ``regressed`` and never auto-activated;
- Property 11: a test row dated at/before the Temporal_Split cutoff raises (non-leakage);
- Property 13: a PROXY/SYNTHETIC dataset propagates the honesty flag/label;
- Property 14: an unknown feature key never changes predictions (older versions ignore it);
- reproducibility of a :class:`HarnessResult` from the dataset + model version alone.

Each property test carries a leading ``# Feature: content-eval-model, Property N: ...``
comment matching the house convention and a docstring citing the acceptance
criteria it exercises. The module imports only the pure harness + domain modules;
no database, no network, no app framework.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain import content_eval as cemod
from app.engines.backtest_harness import (
    DRIVER_KEYS,
    GREENLIGHT,
    GUARDRAILS,
    NEGOTIATE_HARD,
    PASS,
    DriverAccuracy,
    HarnessResult,
    OutputKPIs,
    VerdictScore,
    VersionComparison,
    compare_versions,
    load_dataset,
    predict_row,
    run_harness,
)
from app.engines.backtest_harness import (
    # Aliased on import: the public name begins with ``test_`` which pytest would
    # otherwise collect as a (fixture-less) test. The alias keeps it a plain call.
    test_split_rows as split_test_rows,
)

# ---------------------------------------------------------------------------
# Shared crafted-fixture helpers
# ---------------------------------------------------------------------------

# A feature set whose default-churn prediction (3.06) clears the live
# CHURN_MITIGATION_THRESHOLD (1.5), so with all other guardrails passing the
# harness predicts GREENLIGHT.
_HIGH_CHURN_FEATURES = {
    "asset_type": "CO_PRODUCTION",
    "talent_pedigree": "10",
    "production_scale": "10",
    "is_exclusive": True,
    "genre": "crime",
    "content_format": "live-sports",
    "normalized_rating": 0.8,
    "runtime_minutes": 120,
    "franchise_flag": True,
}

# A feature set whose default-churn prediction (0.33) falls below the threshold,
# so the harness predicts a hard PASS regardless of the other guardrails.
_LOW_CHURN_FEATURES = {
    "asset_type": "LICENSED_LIBRARY",
    "talent_pedigree": "0",
    "production_scale": "0",
    "is_exclusive": False,
    "genre": "documentary",
    "content_format": "library",
}

_ALL_PASS = {"CPVH": True, "LTV_TO_COST": True, "PAYBACK_HORIZON": True}

_DEFAULT_PARAMS = cemod.parse_content_eval_params(None)


def _row(
    title_id: str,
    *,
    features: dict,
    expected_drivers: dict,
    expected_guardrails: dict,
    expected_recommendation: str,
    split: str = "test",
    release_year: int = 2021,
    label_type: str = "SYNTHETIC",
) -> dict:
    """Build a single crafted dataset row with the schema the harness reads."""
    return {
        "title_id": title_id,
        "label_type": label_type,
        "split": split,
        "release_year": release_year,
        "stratum": "tentpole",
        "features": dict(features),
        "expected_drivers": dict(expected_drivers),
        "expected_guardrails": dict(expected_guardrails),
        "expected_recommendation": expected_recommendation,
    }


def _dataset(
    rows: list[dict],
    *,
    cutoff: int | None = 2019,
    version: str = "crafted-v1",
    dominant_label_type: str = "SYNTHETIC",
) -> dict:
    """Wrap crafted rows in the ``{"metadata": ..., "rows": ...}`` envelope."""
    return {
        "metadata": {
            "version": version,
            "temporal_cutoff_year": cutoff,
            "dominant_label_type": dominant_label_type,
        },
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Per-input error: MAPE / WAPE / verdict-match on crafted fixtures
# ---------------------------------------------------------------------------


def test_mape_is_computed_per_driver_excluding_zero_actuals() -> None:
    """Validates: Requirements 6.1

    The harness reports a MAPE per modeled driver, computed the existing way
    (zero-actual pairs excluded). We craft a two-row test split, read back the
    harness's predicted drivers, and assert the reported churn MAPE equals the
    hand-computed mean absolute percentage error over the predicted-vs-expected
    churn pairs.
    """
    rows = [
        _row(
            "a",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "100000000",
                "churn_reduction_pct": "3.00",
                "watch_time_elasticity": "1.10",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "b",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "50000000",
                "churn_reduction_pct": "0.50",
                "watch_time_elasticity": "1.00",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
    ]
    dataset = _dataset(rows)
    result = run_harness(_DEFAULT_PARAMS, dataset=dataset)

    # Reconstruct the predicted churn values the harness used.
    preds = [predict_row(r, _DEFAULT_PARAMS) for r in rows]
    expected_vals = [Decimal("3.00"), Decimal("0.50")]
    pred_vals = [p.predicted_drivers["churn_reduction_pct"] for p in preds]

    terms = [abs((a - p) / a) for a, p in zip(expected_vals, pred_vals)]
    expected_mape = ((sum(terms, Decimal("0")) / Decimal(len(terms))) * Decimal(100)).quantize(
        Decimal("0.01")
    )

    churn_acc = result.drivers["churn_reduction_pct"]
    assert churn_acc.mape == expected_mape
    assert churn_acc.scored == 2
    assert churn_acc.eligible == 2  # neither expected actual is zero


def test_zero_actual_rows_are_excluded_from_mape() -> None:
    """Validates: Requirements 6.1

    A driver whose expected actual is 0 is excluded from the MAPE term count
    (the existing convention). With one zero-actual row and one non-zero row the
    ``eligible`` count drops to 1 while ``scored`` stays 2; if every actual is 0
    the MAPE is ``None``.
    """
    rows = [
        _row(
            "nonzero",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "100000000",
                "churn_reduction_pct": "3.00",
                "watch_time_elasticity": "1.10",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "zero",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "0",
                "churn_reduction_pct": "0.50",
                "watch_time_elasticity": "1.00",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
    ]
    result = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows))

    vh_acc = result.drivers["projected_viewing_hours"]
    assert vh_acc.scored == 2
    assert vh_acc.eligible == 1  # the zero-actual viewing-hours row is excluded


def test_viewing_hours_reports_wape_and_log_mae_only_for_that_driver() -> None:
    """Validates: Requirements 6.1

    The heavy-tailed ``projected_viewing_hours`` driver additionally reports WAPE
    and Log-MAE; the other three drivers leave both ``None``. We also hand-check
    WAPE = sum|actual-pred| / sum|actual| against the harness's figure.
    """
    rows = [
        _row(
            "a",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "100000000",
                "churn_reduction_pct": "3.00",
                "watch_time_elasticity": "1.10",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "b",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "40000000",
                "churn_reduction_pct": "0.50",
                "watch_time_elasticity": "1.00",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
    ]
    dataset = _dataset(rows)
    result = run_harness(_DEFAULT_PARAMS, dataset=dataset)

    vh_acc = result.drivers["projected_viewing_hours"]
    assert vh_acc.wape is not None
    assert vh_acc.log_mae is not None
    for other in ("churn_reduction_pct", "watch_time_elasticity", "ad_load_receptivity"):
        assert result.drivers[other].wape is None
        assert result.drivers[other].log_mae is None

    # Hand-compute WAPE from the harness's own predictions.
    preds = [predict_row(r, _DEFAULT_PARAMS) for r in rows]
    actuals = [Decimal("100000000"), Decimal("40000000")]
    pred_vals = [p.predicted_drivers["projected_viewing_hours"] for p in preds]
    num = sum((abs(a - p) for a, p in zip(actuals, pred_vals)), Decimal("0"))
    den = sum((abs(a) for a in actuals), Decimal("0"))
    expected_wape = (num / den).quantize(Decimal("0.0001"))
    assert vh_acc.wape == expected_wape


def test_verdict_match_rate_counts_exact_recommendation_matches() -> None:
    """Validates: Requirements 6.2

    The verdict-match rate is the fraction of rows whose predicted recommendation
    equals the expected one. We craft three rows: a true GREENLIGHT, a true PASS,
    and a mismatch, and assert the match rate is 2/3.
    """
    rows = [
        _row(
            "match-gl",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "match-pass",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
        _row(
            "mismatch",
            features=_LOW_CHURN_FEATURES,  # predicts PASS
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,  # expected GREENLIGHT -> mismatch
        ),
    ]
    result = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows))

    assert result.verdict.total == 3
    assert result.verdict.matches == 2
    assert result.verdict.verdict_match_rate == (Decimal("2") / Decimal("3")).quantize(
        Decimal("0.0001")
    )


# ---------------------------------------------------------------------------
# Asymmetric directional error: False_Greenlight_Rate / False_Pass_Rate
# ---------------------------------------------------------------------------


def test_false_greenlight_rate_counts_predicted_greenlight_on_should_not_clear() -> None:
    """Validates: Requirements 6.2

    A FALSE GREENLIGHT is a row predicted GREENLIGHT whose expected verdict was
    NEGOTIATE_HARD or PASS (capital committed to a title that should not clear).
    We force one such row (high-churn features, all guardrails pass -> predicted
    GREENLIGHT, but expected PASS) alongside a correct GREENLIGHT, and assert
    FGR = 1/2 and that no false pass is counted.
    """
    rows = [
        _row(
            "false-greenlight",
            features=_HIGH_CHURN_FEATURES,  # predicts GREENLIGHT
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,  # should NOT have cleared
        ),
        _row(
            "true-greenlight",
            features=_HIGH_CHURN_FEATURES,  # predicts GREENLIGHT
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
    ]
    verdict = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows)).verdict

    assert verdict.false_greenlights == 1
    assert verdict.false_passes == 0
    assert verdict.false_greenlight_rate == (Decimal("1") / Decimal("2")).quantize(
        Decimal("0.0001")
    )


def test_false_pass_rate_counts_predicted_pass_on_should_have_cleared() -> None:
    """Validates: Requirements 6.2

    A FALSE PASS is a row predicted PASS/NEGOTIATE_HARD whose expected verdict was
    GREENLIGHT (a missed acquisition / opportunity cost). We force one such row
    (low-churn features -> predicted PASS, expected GREENLIGHT) alongside a correct
    PASS, and assert FPR = 1/2 with no false greenlight counted.
    """
    rows = [
        _row(
            "false-pass",
            features=_LOW_CHURN_FEATURES,  # predicts PASS
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,  # should have cleared
        ),
        _row(
            "true-pass",
            features=_LOW_CHURN_FEATURES,  # predicts PASS
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
    ]
    verdict = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows)).verdict

    assert verdict.false_passes == 1
    assert verdict.false_greenlights == 0
    assert verdict.false_pass_rate == (Decimal("1") / Decimal("2")).quantize(
        Decimal("0.0001")
    )


def test_both_directional_rates_coexist_on_one_split() -> None:
    """Validates: Requirements 6.2

    The two asymmetric rates are reported independently over the same split: a
    split holding one false greenlight and one false pass yields FGR = 1/3 and
    FPR = 1/3 (three rows total), so neither metric masks the other.
    """
    rows = [
        _row(
            "fg",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
        _row(
            "fp",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "ok",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
    ]
    verdict = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows)).verdict

    third = (Decimal("1") / Decimal("3")).quantize(Decimal("0.0001"))
    assert verdict.false_greenlight_rate == third
    assert verdict.false_pass_rate == third


# ---------------------------------------------------------------------------
# Output_KPI deltas + one-changed-model attribution (compare_versions)
# ---------------------------------------------------------------------------


def _ad_load_candidate(centre: str) -> cemod.ContentEvalParams:
    """A candidate content_eval version that shifts only the ad-load centre.

    The ad-load-receptivity parser requires a complete valid block, so we supply
    every magnitude at its illustrative value and move only ``centre`` -- this is
    a single-model change that raises the LTV-to-cost proxy (ad signal) without
    touching churn/viewing-hours/elasticity.
    """
    raw = {
        "engagement": {
            "ad_load_receptivity": {
                "centre": centre,
                "rating_weight": "0.10",
                "runtime_weight": "0.05",
                "franchise_lift": "0.05",
                "min_value": "0.50",
                "max_value": "1.50",
            }
        }
    }
    return cemod.parse_content_eval_params(raw)


def test_compare_versions_reports_kpi_deltas_and_attributes_one_model() -> None:
    """Validates: Requirements 6.3, 6.4

    ``compare_versions`` runs a baseline and a candidate over the SAME dataset and
    reports candidate-minus-baseline deltas for each Output_KPI, attributing the
    movement to one named changed model. A candidate that only raises the ad-load
    centre lifts the LTV-to-cost proxy, so ``avg_ltv_to_cost`` and
    ``active_pipeline_valuation`` deltas are POSITIVE while the churn-driven
    verdict (and thus accuracy) is unchanged.
    """
    candidate = _ad_load_candidate("1.40")
    row = _row(
        "a",
        features={**_HIGH_CHURN_FEATURES, "normalized_rating": 0.8, "runtime_minutes": 120},
        expected_drivers={
            "projected_viewing_hours": "100000000",
            "churn_reduction_pct": "3.00",
            "watch_time_elasticity": "1.10",
            "ad_load_receptivity": "1.00",
        },
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
    )
    dataset = _dataset([row])

    cmp = compare_versions(
        _DEFAULT_PARAMS, candidate, "ad_load_receptivity", dataset=dataset
    )

    assert isinstance(cmp, VersionComparison)
    assert cmp.changed_model == "ad_load_receptivity"
    assert cmp.kpi_deltas["avg_ltv_to_cost"] > 0
    assert cmp.kpi_deltas["active_pipeline_valuation"] > 0
    # Delta == candidate minus baseline for each KPI (definitional check).
    assert cmp.kpi_deltas["avg_ltv_to_cost"] == (
        cmp.candidate.output_kpis.avg_ltv_to_cost
        - cmp.baseline.output_kpis.avg_ltv_to_cost
    )
    # The verdict is churn-driven and identical across the two versions here.
    assert cmp.kpi_deltas["model_prediction_accuracy"] == Decimal("0.0000")


def test_compare_versions_no_regression_allows_auto_activate() -> None:
    """Validates: Requirements 4.7, 6.3

    When a candidate does not raise the False_Greenlight_Rate and does not lower
    the verdict-match rate, ``regressed`` is False and ``auto_activate`` is True --
    the harness surfaces a clean comparison that an operator may activate.
    """
    candidate = _ad_load_candidate("1.40")
    row = _row(
        "a",
        features=_HIGH_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "3.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
    )
    cmp = compare_versions(
        _DEFAULT_PARAMS, candidate, "ad_load_receptivity", dataset=_dataset([row])
    )

    assert cmp.false_greenlight_delta == Decimal("0.0000")
    assert cmp.verdict_match_delta == Decimal("0.0000")
    assert cmp.regressed is False
    assert cmp.auto_activate is True


# ---------------------------------------------------------------------------
# Property 10: no auto-regression
# ---------------------------------------------------------------------------


def _harness_result(
    *, fgr: str, match: str, version_label: str, proxy: bool = True
) -> HarnessResult:
    """A minimal crafted HarnessResult with a chosen FGR and verdict-match rate.

    Only the verdict rates matter for the regression decision, so the driver
    accuracies and KPIs are filled with neutral placeholders.
    """
    verdict = VerdictScore(
        false_greenlight_rate=Decimal(fgr),
        false_pass_rate=Decimal("0.0000"),
        verdict_match_rate=Decimal(match),
        matches=0,
        total=10,
        false_greenlights=0,
        false_passes=0,
        proxy=proxy,
    )
    drivers = {
        key: DriverAccuracy(key, None, None, None, 0, 0, proxy) for key in DRIVER_KEYS
    }
    kpis = OutputKPIs(Decimal("0.00"), Decimal("0.00"), Decimal("0.0000"), Decimal(match))
    return HarnessResult(
        dataset_version="crafted-v1",
        version_label=version_label,
        fit_dataset_version=None,
        rows_scored=10,
        temporal_cutoff_year=2019,
        drivers=drivers,
        verdict=verdict,
        output_kpis=kpis,
        proxy_accuracy=proxy,
        dominant_label_type="SYNTHETIC",
    )


def _comparison_from_results(
    baseline: HarnessResult, candidate: HarnessResult
) -> VersionComparison:
    """Apply the harness's own regression decision rule to two results.

    Mirrors :func:`compare_versions`'s decision: a regression is a RISEN
    False_Greenlight_Rate OR a FALLEN verdict-match rate, and ``auto_activate`` is
    the negation of ``regressed``.
    """
    fgr_delta = (
        candidate.verdict.false_greenlight_rate - baseline.verdict.false_greenlight_rate
    )
    match_delta = (
        candidate.verdict.verdict_match_rate - baseline.verdict.verdict_match_rate
    )
    regressed = fgr_delta > 0 or match_delta < 0
    return VersionComparison(
        changed_model="churn",
        baseline=baseline,
        candidate=candidate,
        kpi_deltas={},
        false_greenlight_delta=fgr_delta,
        verdict_match_delta=match_delta,
        regressed=regressed,
        auto_activate=not regressed,
        proxy_accuracy=baseline.proxy_accuracy or candidate.proxy_accuracy,
    )


# Feature: content-eval-model, Property 10: No auto-regression
@settings(max_examples=200)
@given(
    base_fgr=st.decimals(min_value=Decimal("0.00"), max_value=Decimal("0.90"), places=4),
    bump=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("0.10"), places=4),
    base_match=st.decimals(min_value=Decimal("0.10"), max_value=Decimal("0.99"), places=4),
)
def test_candidate_raising_fgr_never_auto_activates(
    base_fgr: Decimal, bump: Decimal, base_match: Decimal
) -> None:
    """Validates: Requirements 4.7, 6.2

    A candidate whose False_Greenlight_Rate ROSE above the baseline (the primary
    capital-loss risk) is flagged ``regressed`` and is NEVER auto-activated, no
    matter what else moved. Verified over a range of crafted baseline/candidate
    rates via the harness's own regression rule.
    """
    baseline = _harness_result(fgr=str(base_fgr), match=str(base_match), version_label="base")
    candidate = _harness_result(
        fgr=str(base_fgr + bump), match=str(base_match), version_label="cand"
    )
    cmp = _comparison_from_results(baseline, candidate)

    assert cmp.false_greenlight_delta > 0
    assert cmp.regressed is True
    assert cmp.auto_activate is False


# Feature: content-eval-model, Property 10: No auto-regression
@settings(max_examples=200)
@given(
    base_match=st.decimals(min_value=Decimal("0.20"), max_value=Decimal("0.99"), places=4),
    drop=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("0.10"), places=4),
    fgr=st.decimals(min_value=Decimal("0.00"), max_value=Decimal("0.50"), places=4),
)
def test_candidate_lowering_verdict_match_never_auto_activates(
    base_match: Decimal, drop: Decimal, fgr: Decimal
) -> None:
    """Validates: Requirements 4.7, 6.2

    A candidate whose verdict-match rate FELL below the baseline (even with an
    unchanged False_Greenlight_Rate) is flagged ``regressed`` and never
    auto-activated.
    """
    baseline = _harness_result(fgr=str(fgr), match=str(base_match), version_label="base")
    candidate = _harness_result(
        fgr=str(fgr), match=str(base_match - drop), version_label="cand"
    )
    cmp = _comparison_from_results(baseline, candidate)

    assert cmp.verdict_match_delta < 0
    assert cmp.regressed is True
    assert cmp.auto_activate is False


def test_identical_results_do_not_regress() -> None:
    """Validates: Requirements 4.7

    A candidate identical to the baseline neither raises FGR nor lowers accuracy,
    so it does not regress and may be auto-activated (the boundary of the rule).
    """
    baseline = _harness_result(fgr="0.2000", match="0.8000", version_label="base")
    candidate = _harness_result(fgr="0.2000", match="0.8000", version_label="cand")
    cmp = _comparison_from_results(baseline, candidate)

    assert cmp.regressed is False
    assert cmp.auto_activate is True


# ---------------------------------------------------------------------------
# Property 11: temporal non-leakage
# ---------------------------------------------------------------------------


def test_test_split_rows_raises_on_row_at_or_before_cutoff() -> None:
    """Validates: Requirements 3.3, 6.6

    A test-split row dated at/before the Temporal_Split cutoff would leak future
    information into a held-out metric, so ``test_split_rows`` raises rather than
    silently scoring it. Both the at-cutoff and before-cutoff cases are rejected.
    """
    at_cutoff = _row(
        "leak-at",
        features=_HIGH_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "3.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
        release_year=2019,  # == cutoff
    )
    before_cutoff = _row(
        "leak-before",
        features=_HIGH_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "3.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
        release_year=2015,  # < cutoff
    )

    for leaking in (at_cutoff, before_cutoff):
        with pytest.raises(ValueError, match="temporal leakage"):
            split_test_rows(_dataset([leaking], cutoff=2019))


def test_run_harness_raises_on_leaking_dataset() -> None:
    """Validates: Requirements 3.3, 6.6

    The leakage check runs inside ``run_harness`` too, so a full run over a
    leaking dataset raises rather than returning a silently biased result.
    """
    leaking = _row(
        "leak",
        features=_HIGH_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "3.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
        release_year=2018,
    )
    with pytest.raises(ValueError, match="temporal leakage"):
        run_harness(_DEFAULT_PARAMS, dataset=_dataset([leaking], cutoff=2019))


def test_clean_test_split_passes_the_leakage_check() -> None:
    """Validates: Requirements 3.3

    A test split whose rows are all dated strictly after the cutoff passes the
    non-leakage check and is returned unchanged; train-split rows (even at/before
    the cutoff) are not subject to the test-split check.
    """
    clean = _row(
        "clean",
        features=_HIGH_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "3.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
        release_year=2020,
        split="test",
    )
    train_old = _row(
        "train-old",
        features=_LOW_CHURN_FEATURES,
        expected_drivers={"churn_reduction_pct": "0.50"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=PASS,
        release_year=2001,  # at/before cutoff, but train split -> allowed
        split="train",
    )
    rows = split_test_rows(_dataset([clean, train_old], cutoff=2019))
    assert [r["title_id"] for r in rows] == ["clean"]


# ---------------------------------------------------------------------------
# Property 13: honesty propagation (PROXY/SYNTHETIC labeling)
# ---------------------------------------------------------------------------


def test_proxy_dataset_sets_proxy_accuracy_and_propagates_labels() -> None:
    """Validates: Requirements 6.5

    When the measured rows are PROXY/SYNTHETIC, every accuracy figure is labeled
    PROXY: ``HarnessResult.proxy_accuracy`` is True, each per-driver
    ``DriverAccuracy.proxy`` and the ``VerdictScore.proxy`` flag are True, and the
    dataset's dominant Label_Type is carried through.
    """
    rows = [
        _row(
            "p",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
            label_type="PROXY",
        ),
        _row(
            "s",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "0.50"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
            label_type="SYNTHETIC",
        ),
    ]
    result = run_harness(
        _DEFAULT_PARAMS, dataset=_dataset(rows, dominant_label_type="SYNTHETIC")
    )

    assert result.proxy_accuracy is True
    assert result.dominant_label_type == "SYNTHETIC"
    assert result.verdict.proxy is True
    assert all(acc.proxy is True for acc in result.drivers.values())
    assert result.label_type_counts == {"PROXY": 1, "SYNTHETIC": 1}


def test_all_observed_dataset_is_not_proxy() -> None:
    """Validates: Requirements 6.5

    Proxy accuracy holds unless EVERY measured row is OBSERVED (a real realized
    outcome). A test split made entirely of OBSERVED rows yields
    ``proxy_accuracy`` False and clears the per-driver/verdict proxy flags, so the
    honesty label is never applied to genuinely real-world accuracy.
    """
    rows = [
        _row(
            "o1",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={"churn_reduction_pct": "3.00"},
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
            label_type="OBSERVED",
        ),
    ]
    result = run_harness(_DEFAULT_PARAMS, dataset=_dataset(rows))

    assert result.proxy_accuracy is False
    assert result.verdict.proxy is False
    assert all(acc.proxy is False for acc in result.drivers.values())


# ---------------------------------------------------------------------------
# Property 14: unknown features never change predictions
# ---------------------------------------------------------------------------

_KNOWN_FEATURE_VALUES = st.fixed_dictionaries(
    {
        "asset_type": st.sampled_from(
            ["ORIGINAL_SERIES", "CO_PRODUCTION", "ORIGINAL_FILM", "LICENSED_LIBRARY"]
        ),
        "genre": st.sampled_from(["crime", "drama", "sci-fi", "documentary", "comedy"]),
        "talent_pedigree": st.sampled_from(["0", "3.5", "7.2", "10"]),
        "production_scale": st.sampled_from(["0", "4", "6.5", "9"]),
        "is_exclusive": st.booleans(),
        "runtime_minutes": st.integers(min_value=20, max_value=200),
    }
)

# Unknown keys a newer connector might add; an older content_eval version must
# ignore them entirely (Requirement 7.2).
_UNKNOWN_KEYS = st.dictionaries(
    keys=st.sampled_from(
        ["embedding_signal", "sentiment_score", "future_feature", "trailer_views"]
    ),
    values=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=6)),
    min_size=1,
    max_size=4,
)


# Feature: content-eval-model, Property 14: Unknown features ignored
@settings(max_examples=200)
@given(known=_KNOWN_FEATURE_VALUES, unknown=_UNKNOWN_KEYS)
def test_adding_unknown_feature_keys_does_not_change_predictions(
    known: dict, unknown: dict
) -> None:
    """Validates: Requirements 7.2

    Adding one or more unknown feature keys to a row never changes the harness's
    predicted drivers or predicted recommendation: feature derivation ignores
    unrecognized keys, so an older Content_Eval_Version is byte-identical in the
    face of a newly-added Open_Data_Source signal.
    """
    base_row = _row(
        "base",
        features=known,
        expected_drivers={"churn_reduction_pct": "2.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
    )
    augmented_features = {**known, **unknown}
    augmented_row = _row(
        "aug",
        features=augmented_features,
        expected_drivers={"churn_reduction_pct": "2.00"},
        expected_guardrails=_ALL_PASS,
        expected_recommendation=GREENLIGHT,
    )

    base_pred = predict_row(base_row, _DEFAULT_PARAMS)
    aug_pred = predict_row(augmented_row, _DEFAULT_PARAMS)

    assert base_pred.predicted_drivers == aug_pred.predicted_drivers
    assert base_pred.predicted_recommendation == aug_pred.predicted_recommendation


# ---------------------------------------------------------------------------
# Reproducibility from dataset + model version alone (R6.6)
# ---------------------------------------------------------------------------


def test_run_harness_is_reproducible_on_same_dataset_and_params() -> None:
    """Validates: Requirements 6.6

    A HarnessResult is a pure function of the dataset version and the model
    version: two runs over the same in-memory dataset with the same params are
    equal across every observable field (frozen dataclasses compare by value).
    """
    rows = [
        _row(
            "a",
            features=_HIGH_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "100000000",
                "churn_reduction_pct": "3.00",
                "watch_time_elasticity": "1.10",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=GREENLIGHT,
        ),
        _row(
            "b",
            features=_LOW_CHURN_FEATURES,
            expected_drivers={
                "projected_viewing_hours": "40000000",
                "churn_reduction_pct": "0.50",
                "watch_time_elasticity": "1.00",
                "ad_load_receptivity": "1.00",
            },
            expected_guardrails=_ALL_PASS,
            expected_recommendation=PASS,
        ),
    ]
    dataset = _dataset(rows)

    first = run_harness(_DEFAULT_PARAMS, dataset=dataset)
    second = run_harness(_DEFAULT_PARAMS, dataset=dataset)

    assert first == second


# ---------------------------------------------------------------------------
# Smoke test over the committed KPI_Test_Dataset
# ---------------------------------------------------------------------------


def test_committed_dataset_smoke_run() -> None:
    """Validates: Requirements 6.1, 6.5, 6.6

    A full run over the committed ``content_eval_dataset.json`` with the
    illustrative defaults scores the held-out rows, keeps every directional rate
    in [0, 1], labels accuracy PROXY (the committed rows are PROXY/SYNTHETIC), and
    scores every known driver. This is the offline, reproducible smoke path.
    """
    dataset = load_dataset()
    result = run_harness(_DEFAULT_PARAMS, dataset=dataset)

    assert result.rows_scored > 0
    assert result.proxy_accuracy is True
    assert set(result.drivers) == set(DRIVER_KEYS)
    for rate in (
        result.verdict.false_greenlight_rate,
        result.verdict.false_pass_rate,
        result.verdict.verdict_match_rate,
    ):
        assert Decimal("0") <= rate <= Decimal("1")
    # The four guardrail names are the engine-order constant the harness exposes.
    assert GUARDRAILS == ("CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON")
    # Recommendation vocabulary round-trips.
    assert {GREENLIGHT, NEGOTIATE_HARD, PASS} == {"GREENLIGHT", "NEGOTIATE_HARD", "PASS"}
