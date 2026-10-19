"""Offline Backtest_Harness for the Content_Eval_System (content-eval-model).

Component 7 of the design and Requirement 6. This is the measurement substrate:
it loads a committed ``KPI_Test_Dataset`` version and a ``content_eval`` model
version, runs each pure ``Content_Eval_Model`` over the HELD-OUT (test-split)
rows, and reports per-input error, verdict-match rate, the asymmetric directional
error rates (``False_Greenlight_Rate`` first, as capital-loss risk), and the
change in the four ``Output_KPIs`` between a baseline and a candidate version.

What it does (R6.1-R6.6; Properties 10, 11, 13):

- **Load** a dataset by file path (the committed
  ``database/kpi_dataset/content_eval_dataset.json``) and a ``content_eval``
  version parsed via :func:`app.domain.content_eval.parse_content_eval_params`
  from a ``guardrail_params['content_eval']`` mapping. The dataset is read
  directly as JSON; no DB, no network (R6.6).
- **Predict** per input over the test-split rows via
  :func:`app.domain.features.derive_features` plus the pure models: viewing hours
  (:mod:`app.domain.viewing_hours`), watch-time elasticity and ad-load
  receptivity (:mod:`app.domain.engagement`), and churn-reduction percentage
  (:mod:`app.domain.churn`).
- **Per-input error**: MAPE via :func:`app.domain.mape.compute_mape`, which
  EXCLUDES zero-actual metrics (the existing convention). For the heavy-tailed
  ``projected_viewing_hours`` target the harness additionally reports WAPE and
  Log-MAE, reusing the :mod:`app.domain.fit` helper logic.
- **Verdict scoring**: the verdict-match rate plus the two directional error
  rates. ``False_Greenlight_Rate`` (predicted GREENLIGHT where expected was
  NEGOTIATE_HARD/PASS) is the PRIMARY risk metric and is reported first;
  ``False_Pass_Rate`` (predicted PASS/NEGOTIATE_HARD where expected was
  GREENLIGHT) is the opportunity-cost metric. The predicted recommendation is
  derived the SAME deterministic way the dataset generator does
  (``_recommendation_from_guardrails``): a non-correctable churn breach is a hard
  PASS, any other breach downgrades to NEGOTIATE_HARD, all-pass is GREENLIGHT.
  The churn guardrail is recomputed from the predicted churn percentage against
  the live ``CHURN_MITIGATION_THRESHOLD`` (1.5); the other three guardrails,
  which depend on cost/payback inputs the dataset does not carry, are taken from
  the row's own expected outcomes so the rule stays consistent with the dataset's
  recommendation rule while the churn model genuinely moves the verdict.
- **Output_KPI deltas**: the four portfolio metrics (active pipeline valuation,
  average LTV-to-Cost, portfolio risk-exposure index, model prediction-accuracy
  rate) recomputed over the same dataset for a baseline vs a candidate version,
  reported as deltas and attributed to the single changed model (one-change-at-a-
  time, R6.3, R6.4).
- **Honesty (Property 13)**: every accuracy figure is labeled PROXY whenever the
  measured rows are PROXY/SYNTHETIC (they always are in the committed dataset);
  ``proxy_accuracy`` is True and ``dominant_label_type`` is carried through.
- **No auto-regression (Property 10)**: :func:`compare_versions` reports whether
  the candidate regressed against the baseline and sets ``auto_activate`` False
  on a regression; it never activates anything itself.
- **Reproducibility (R6.6, Property 11)**: results are a pure function of the
  dataset version and the model version. Only the test-split rows are scored, and
  the harness asserts the Temporal_Split invariant (no test row at/before the
  cutoff) so a leaking dataset is caught rather than silently measured.

The harness is both a CLI (``python -m app.engines.backtest_harness``) and an
importable library returning a frozen :class:`HarnessResult` dataclass so the
task-10 tests can assert on it (it does NOT print-only).

Standard library + the existing pure domain modules only. No new third-party
dependency. Pure/offline: no DB, no network.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from app.domain import content_eval as cemod
from app.domain import engagement as engmod
from app.domain import features as featmod
from app.domain import fit as fitmod
from app.domain import viewing_hours as vhmod
from app.domain.churn import (
    CHURN_MITIGATION_THRESHOLD,
    ChurnFeatures,
    calculate_churn_mitigation,
)
from app.domain.mape import compute_mape
from app.engines.backtesting import PREDICTED_METRIC_FIELDS

__all__ = [
    "DEFAULT_DATASET_PATH",
    "GREENLIGHT",
    "NEGOTIATE_HARD",
    "PASS",
    "GUARDRAILS",
    "DRIVER_KEYS",
    "DRIVER_AUDIT_METRICS",
    "RISK_WEIGHTS",
    "DriverAccuracy",
    "VerdictScore",
    "OutputKPIs",
    "HarnessResult",
    "VersionComparison",
    "load_dataset",
    "test_split_rows",
    "predict_row",
    "run_harness",
    "compare_versions",
    "audit_metric_name_for_driver",
    "audit_metrics_for_row",
    "main",
]

# The committed dataset lives outside the backend package root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_PATH = _REPO_ROOT / "database" / "kpi_dataset" / "content_eval_dataset.json"

# Recommendation vocabulary (matches the Guardrails_Engine and the dataset).
GREENLIGHT = "GREENLIGHT"
NEGOTIATE_HARD = "NEGOTIATE_HARD"
PASS = "PASS"

# The four guardrail check names, engine order (mirrors the dataset generator).
GUARDRAILS = ("CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON")

# The modeled drivers the harness scores per input.
DRIVER_KEYS = (
    "projected_viewing_hours",
    "churn_reduction_pct",
    "watch_time_elasticity",
    "ad_load_receptivity",
)

# --------------------------------------------------------------------------- #
# Audit-contract bridge (R6.7)
# --------------------------------------------------------------------------- #
#
# Each content-eval modeled driver is expressed in terms of an EXISTING
# ``PREDICTED_METRIC_FIELDS`` audit metric name, so a harness prediction can be
# scored through the very ``POST /api/v1/backtest/audit`` path the Backtest Studio
# already uses for CPVH and LTV-to-Cost. This is a thin, declarative mapping only:
# it does NOT re-home or fork the MAPE arithmetic (the audit endpoint and
# ``app.domain.mape`` own that, excluding zero-actual metrics), and it does not
# change CPVH/LTV/churn semantics.
#
#   churn_reduction_pct      -> "churn_reduction" (churn_reduction_pct column)
#   projected_viewing_hours  -> "cpvh"            (calculated_cpvh column; CPVH is
#                               Cost / Projected Viewing Hours, so viewing hours is
#                               the modeled driver behind the audited CPVH metric)
#   watch_time_elasticity    -> "ltv_to_cost"     (ltv_to_cost_multiple column; an
#   ad_load_receptivity      -> "ltv_to_cost"      LTV-numerator advertising driver)
#
# Only driver keys with a comparable audited metric appear here; a driver whose
# actual is not audited through the shared contract is simply absent (and the
# bridge yields no audit metric for it), exactly as the audit endpoint already
# skips a metric name it has no predicted field for.
DRIVER_AUDIT_METRICS: Mapping[str, str] = {
    "churn_reduction_pct": "churn_reduction",
    "projected_viewing_hours": "cpvh",
    "watch_time_elasticity": "ltv_to_cost",
    "ad_load_receptivity": "ltv_to_cost",
}

# Sanity gate: every audit metric name the bridge emits MUST be a metric name the
# existing contract already knows how to score (i.e. it has a predicted column in
# ``PREDICTED_METRIC_FIELDS``). This keeps the bridge honest if either side drifts.
assert set(DRIVER_AUDIT_METRICS.values()) <= set(PREDICTED_METRIC_FIELDS), (
    "DRIVER_AUDIT_METRICS references an audit metric name absent from "
    "PREDICTED_METRIC_FIELDS; the bridge must reuse the existing contract."
)

# Portfolio risk-exposure index weights by recommendation: a GREENLIGHT title
# carries the most committed-capital risk, a NEGOTIATE_HARD some, a PASS none.
# Used only to compute the relative Output_KPI; it is a proxy index, not dollars.
RISK_WEIGHTS: Mapping[str, Decimal] = {
    GREENLIGHT: Decimal("1.0"),
    NEGOTIATE_HARD: Decimal("0.5"),
    PASS: Decimal("0.0"),
}

_PCT_QUANTUM = Decimal("0.01")
_RATE_QUANTUM = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Result dataclasses (frozen; the task-10 tests assert on these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriverAccuracy:
    """Per-input accuracy for one modeled driver over the scored rows.

    ``mape`` is the Mean Absolute Percentage Error over the eligible pairs
    (zero-actual rows excluded, per the existing convention); it is ``None`` when
    no pair is eligible. ``wape`` and ``log_mae`` are populated only for the
    heavy-tailed ``projected_viewing_hours`` driver (``None`` otherwise).
    ``eligible`` / ``scored`` count the MAPE-eligible pairs and the total scored
    pairs. ``proxy`` is True when the measured rows are PROXY/SYNTHETIC.
    """

    driver: str
    mape: Decimal | None
    wape: Decimal | None
    log_mae: Decimal | None
    eligible: int
    scored: int
    proxy: bool


@dataclass(frozen=True)
class VerdictScore:
    """Verdict-match plus the asymmetric directional error rates.

    ``false_greenlight_rate`` is reported FIRST as the primary capital-loss risk
    metric: the fraction of titles predicted GREENLIGHT whose expected verdict was
    NEGOTIATE_HARD or PASS. ``false_pass_rate`` is the opportunity-cost metric: the
    fraction predicted PASS/NEGOTIATE_HARD whose expected verdict was GREENLIGHT.
    All rates are in [0, 1] rounded to 4 dp.
    """

    false_greenlight_rate: Decimal
    false_pass_rate: Decimal
    verdict_match_rate: Decimal
    matches: int
    total: int
    false_greenlights: int
    false_passes: int
    proxy: bool


@dataclass(frozen=True)
class OutputKPIs:
    """The four portfolio-level Output_KPIs recomputed over the scored rows.

    - ``active_pipeline_valuation`` -- a relative pipeline valuation index: the
      sum of each title's predicted LTV-to-cost proxy weighted by whether it
      would clear (GREENLIGHT full, NEGOTIATE_HARD half, PASS zero).
    - ``avg_ltv_to_cost`` -- the average predicted LTV-to-cost proxy across rows.
    - ``portfolio_risk_exposure`` -- the committed-capital risk index: the mean
      :data:`RISK_WEIGHTS` over the predicted recommendations.
    - ``model_prediction_accuracy`` -- the verdict-match rate (the share of rows
      whose predicted recommendation equals the expected one).

    All four are PROXY indices over a PROXY/SYNTHETIC dataset, never real-world
    figures (Property 13).
    """

    active_pipeline_valuation: Decimal
    avg_ltv_to_cost: Decimal
    portfolio_risk_exposure: Decimal
    model_prediction_accuracy: Decimal


@dataclass(frozen=True)
class HarnessResult:
    """The full structured result of one harness run over a dataset + version.

    Reproducible from ``dataset_version`` + ``version_label`` alone. ``drivers``
    maps each driver key to its :class:`DriverAccuracy`. ``proxy_accuracy`` is
    True whenever the measured rows are PROXY/SYNTHETIC, and
    ``dominant_label_type`` carries the dataset's honesty tag through (Property
    13).
    """

    dataset_version: str
    version_label: str
    fit_dataset_version: str | None
    rows_scored: int
    temporal_cutoff_year: int | None
    drivers: Mapping[str, DriverAccuracy]
    verdict: VerdictScore
    output_kpis: OutputKPIs
    proxy_accuracy: bool
    dominant_label_type: str
    label_type_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionComparison:
    """The baseline-vs-candidate comparison with KPI deltas (R6.3, R6.4).

    ``changed_model`` names the single model the candidate changed (one-change-at-
    a-time attribution). ``kpi_deltas`` is candidate minus baseline for each
    Output_KPI. ``regressed`` is True when the candidate's primary risk metric
    (False_Greenlight_Rate) rose OR its model prediction accuracy fell; on a
    regression ``auto_activate`` is False -- the harness surfaces the regression
    and never auto-activates (Property 10).
    """

    changed_model: str
    baseline: HarnessResult
    candidate: HarnessResult
    kpi_deltas: Mapping[str, Decimal]
    false_greenlight_delta: Decimal
    verdict_match_delta: Decimal
    regressed: bool
    auto_activate: bool
    proxy_accuracy: bool


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> dict:
    """Load the committed KPI_Test_Dataset JSON by file path (pure, offline).

    Reads ``{"metadata": {...}, "rows": [...]}`` from ``path``. No DB and no
    network -- the committed bytes are the single source of truth so a run is
    reproducible from the dataset version alone (R6.6).
    """
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict) or "rows" not in data:
        raise ValueError(f"malformed dataset at {path}: missing 'rows'")
    return data


def test_split_rows(dataset: Mapping) -> list[dict]:
    """Return only the held-out (test-split) rows, enforcing temporal non-leakage.

    Property 11 / R3.3: no test-split row may be dated at or before the recorded
    Temporal_Split cutoff. A violation is a dataset defect that would leak future
    information into a held-out metric, so it raises rather than being silently
    scored.
    """
    metadata = dataset.get("metadata", {}) if isinstance(dataset, Mapping) else {}
    cutoff = metadata.get("temporal_cutoff_year")
    rows = [row for row in dataset["rows"] if row.get("split") == "test"]
    if cutoff is not None:
        leaks = [
            row.get("title_id")
            for row in rows
            if row.get("release_year") is not None
            and int(row["release_year"]) <= int(cutoff)
        ]
        if leaks:
            raise ValueError(
                f"temporal leakage: test rows at/before cutoff {cutoff}: {leaks}"
            )
    return rows


# ---------------------------------------------------------------------------
# Prediction over a single row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RowPrediction:
    """The four predicted drivers plus the derived verdict for one row."""

    title_id: str
    label_type: str
    predicted_drivers: Mapping[str, Decimal]
    predicted_recommendation: str
    expected_recommendation: str


def _churn_features_from_raw(raw: Mapping) -> ChurnFeatures:
    """Build :class:`ChurnFeatures` from a dataset row's raw feature mapping.

    The churn model consumes its own feature struct (it predates the shared
    FeatureVector). Telemetry_Heat is not carried in the dataset, so it is left
    ``None`` and the churn model applies its neutral default -- deterministic and
    consistent for every row.
    """
    return ChurnFeatures(
        asset_type=featmod.normalize_asset_type(raw.get("asset_type")),
        pedigree=featmod._coerce_decimal(raw.get("talent_pedigree")),
        production_scale=featmod._coerce_decimal(raw.get("production_scale")),
        is_exclusive=bool(featmod._coerce_bool(raw.get("is_exclusive")) or False),
        telemetry_heat=None,
        genre=raw.get("genre"),
        content_format=raw.get("content_format"),
    )


def predict_row(row: Mapping, params: cemod.ContentEvalParams) -> RowPrediction:
    """Predict the four modeled drivers and the verdict for one dataset row.

    Runs the pure models over the row's features with the given ``content_eval``
    params. No Supplied_Value is consulted (the harness measures the MODEL, so it
    always calculates). The predicted recommendation is derived the same way the
    dataset generator does, with the churn guardrail recomputed from the predicted
    churn percentage against the live threshold.
    """
    raw = dict(row.get("features", {}))
    vector = featmod.derive_features(raw)

    vh = vhmod.calculate_viewing_hours(
        vector, params.viewing_hours, params.viewing_hours_source
    )
    wte = engmod.calculate_watch_time_elasticity(
        vector, params.watch_time_elasticity, params.watch_time_elasticity_source
    )
    alr = engmod.calculate_ad_load_receptivity(
        vector, params.ad_load_receptivity, params.ad_load_receptivity_source
    )
    churn = _calculate_churn(raw, params)

    predicted_drivers = {
        "projected_viewing_hours": vh.viewing_hours,
        "churn_reduction_pct": churn,
        "watch_time_elasticity": wte.watch_time_elasticity,
        "ad_load_receptivity": alr.ad_load_receptivity,
    }

    expected_guardrails = dict(row.get("expected_guardrails", {}))
    predicted_recommendation = _recommendation_from_predicted(
        churn, expected_guardrails
    )
    return RowPrediction(
        title_id=str(row.get("title_id", "")),
        label_type=str(row.get("label_type", "")),
        predicted_drivers=predicted_drivers,
        predicted_recommendation=predicted_recommendation,
        expected_recommendation=str(row.get("expected_recommendation", "")),
    )


def _calculate_churn(raw: Mapping, params: cemod.ContentEvalParams) -> Decimal:
    """Calculate the predicted churn-reduction percentage for a row.

    Uses the hand-tuned churn model defaults (the Churn_Mitigation_Model is its
    own deterministic fallback and reference member of the family); the
    ``content_eval`` block does not re-home the churn params, which stay under
    ``guardrail_params['churn_model']`` in the engine. For the harness the
    illustrative churn defaults are the measured churn model.
    """
    from app.domain.churn import DEFAULT_CHURN_MODEL_PARAMS

    result = calculate_churn_mitigation(
        _churn_features_from_raw(raw),
        DEFAULT_CHURN_MODEL_PARAMS,
        params.source,
    )
    return result.churn_reduction_pct


def _recommendation_from_predicted(
    predicted_churn_pct: Decimal, expected_guardrails: Mapping
) -> str:
    """Derive the predicted recommendation, consistent with the dataset's rule.

    Mirrors ``make_content_eval_dataset._recommendation_from_guardrails``: a
    non-correctable CHURN_MITIGATION breach is a hard PASS, any other breach
    downgrades a GREENLIGHT to NEGOTIATE_HARD, all-pass is a GREENLIGHT. The churn
    guardrail is RECOMPUTED from the predicted churn percentage against the live
    :data:`CHURN_MITIGATION_THRESHOLD` (so the churn model genuinely moves the
    verdict); the other three guardrails depend on cost/payback inputs the dataset
    does not carry, so they are taken from the row's own expected outcomes.
    """
    churn_ok = predicted_churn_pct >= CHURN_MITIGATION_THRESHOLD
    if not churn_ok:
        return PASS
    breaches = [
        name
        for name in GUARDRAILS
        if name != "CHURN_MITIGATION" and not bool(expected_guardrails.get(name, True))
    ]
    if not breaches:
        return GREENLIGHT
    return NEGOTIATE_HARD


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _to_decimal(raw: object) -> Decimal | None:
    """Coerce an expected/predicted value to a finite Decimal, else ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _score_driver(
    driver: str,
    rows: Sequence[Mapping],
    predictions: Sequence[RowPrediction],
    proxy: bool,
) -> DriverAccuracy:
    """Compute MAPE (+ WAPE/Log-MAE for viewing hours) for one driver."""
    pairs: list[tuple[Decimal, Decimal]] = []
    actuals: list[float] = []
    preds: list[float] = []
    for row, pred in zip(rows, predictions):
        actual = _to_decimal(row.get("expected_drivers", {}).get(driver))
        predicted = pred.predicted_drivers.get(driver)
        if actual is None or predicted is None:
            continue
        pairs.append((actual, predicted))
        actuals.append(float(actual))
        preds.append(float(predicted))

    mape = compute_mape(pairs)
    eligible = sum(1 for actual, _ in pairs if actual != 0)

    wape: Decimal | None = None
    log_mae: Decimal | None = None
    if driver == "projected_viewing_hours" and pairs:
        wape = Decimal(str(fitmod._wape(actuals, preds))).quantize(
            _RATE_QUANTUM, rounding=ROUND_HALF_UP
        )
        log_mae = Decimal(str(fitmod._log_mae(actuals, preds))).quantize(
            _RATE_QUANTUM, rounding=ROUND_HALF_UP
        )

    return DriverAccuracy(
        driver=driver,
        mape=mape,
        wape=wape,
        log_mae=log_mae,
        eligible=eligible,
        scored=len(pairs),
        proxy=proxy,
    )


def _score_verdicts(predictions: Sequence[RowPrediction], proxy: bool) -> VerdictScore:
    """Compute verdict-match and the asymmetric directional error rates."""
    total = len(predictions)
    matches = 0
    false_greenlights = 0
    false_passes = 0
    for pred in predictions:
        if pred.predicted_recommendation == pred.expected_recommendation:
            matches += 1
        # False greenlight: predicted GREENLIGHT, expected NEGOTIATE_HARD/PASS.
        if pred.predicted_recommendation == GREENLIGHT and pred.expected_recommendation in (
            NEGOTIATE_HARD,
            PASS,
        ):
            false_greenlights += 1
        # False pass: predicted PASS/NEGOTIATE_HARD, expected GREENLIGHT.
        if pred.predicted_recommendation in (PASS, NEGOTIATE_HARD) and (
            pred.expected_recommendation == GREENLIGHT
        ):
            false_passes += 1

    def _rate(num: int) -> Decimal:
        if total == 0:
            return Decimal("0").quantize(_RATE_QUANTUM)
        return (Decimal(num) / Decimal(total)).quantize(
            _RATE_QUANTUM, rounding=ROUND_HALF_UP
        )

    return VerdictScore(
        false_greenlight_rate=_rate(false_greenlights),
        false_pass_rate=_rate(false_passes),
        verdict_match_rate=_rate(matches),
        matches=matches,
        total=total,
        false_greenlights=false_greenlights,
        false_passes=false_passes,
        proxy=proxy,
    )


def _ltv_to_cost_proxy(pred: RowPrediction) -> Decimal:
    """A relative LTV-to-cost proxy from a row's predicted drivers.

    The dataset carries no acquisition cost, so this is a scale-free proxy index
    (NOT the dollar LTV-to-cost multiple): it blends the subscription signal
    (churn reduction) with the advertising signal (watch-time elasticity x ad-load
    receptivity). Used only to drive the relative Output_KPI deltas between two
    versions over the same rows, so the constant basis cancels.
    """
    churn = pred.predicted_drivers["churn_reduction_pct"]
    wte = pred.predicted_drivers["watch_time_elasticity"]
    alr = pred.predicted_drivers["ad_load_receptivity"]
    return churn + (wte * alr)


def _compute_output_kpis(
    predictions: Sequence[RowPrediction], verdict: VerdictScore
) -> OutputKPIs:
    """Recompute the four portfolio Output_KPIs over the scored predictions."""
    n = len(predictions)
    if n == 0:
        zero = Decimal("0").quantize(_PCT_QUANTUM)
        return OutputKPIs(zero, zero, zero, zero)

    ltv_proxies = [_ltv_to_cost_proxy(p) for p in predictions]
    valuation = Decimal("0")
    risk = Decimal("0")
    for pred, proxy_value in zip(predictions, ltv_proxies):
        weight = RISK_WEIGHTS.get(pred.predicted_recommendation, Decimal("0"))
        valuation += proxy_value * weight
        risk += weight

    avg_ltv = (sum(ltv_proxies, Decimal("0")) / Decimal(n)).quantize(
        _PCT_QUANTUM, rounding=ROUND_HALF_UP
    )
    risk_exposure = (risk / Decimal(n)).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)
    valuation_q = valuation.quantize(_PCT_QUANTUM, rounding=ROUND_HALF_UP)

    return OutputKPIs(
        active_pipeline_valuation=valuation_q,
        avg_ltv_to_cost=avg_ltv,
        portfolio_risk_exposure=risk_exposure,
        model_prediction_accuracy=verdict.verdict_match_rate,
    )


# ---------------------------------------------------------------------------
# Top-level run + comparison
# ---------------------------------------------------------------------------


def run_harness(
    params: cemod.ContentEvalParams,
    dataset: Mapping | None = None,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> HarnessResult:
    """Run the harness for one ``content_eval`` version over a dataset's test split.

    Loads the committed dataset (by path when ``dataset`` is not supplied), scores
    only the held-out test-split rows (enforcing temporal non-leakage), and
    returns a frozen :class:`HarnessResult`. Reproducible from the dataset version
    and the model version alone (R6.6). All accuracy is labeled PROXY when the
    measured rows are PROXY/SYNTHETIC (Property 13).
    """
    if dataset is None:
        dataset = load_dataset(dataset_path)
    metadata = dataset.get("metadata", {}) if isinstance(dataset, Mapping) else {}

    rows = test_split_rows(dataset)
    predictions = [predict_row(row, params) for row in rows]

    # The committed dataset is entirely PROXY/SYNTHETIC: any OBSERVED row would be
    # a real realized outcome, so proxy accuracy holds unless EVERY row is OBSERVED.
    label_types = {str(row.get("label_type", "")) for row in rows}
    proxy = bool(label_types - {"OBSERVED"}) or not label_types

    drivers = {
        driver: _score_driver(driver, rows, predictions, proxy) for driver in DRIVER_KEYS
    }
    verdict = _score_verdicts(predictions, proxy)
    output_kpis = _compute_output_kpis(predictions, verdict)

    label_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("label_type", ""))
        label_counts[key] = label_counts.get(key, 0) + 1

    cutoff = metadata.get("temporal_cutoff_year")
    return HarnessResult(
        dataset_version=str(metadata.get("version", "unknown")),
        version_label=params.version_label,
        fit_dataset_version=params.fit_dataset_version,
        rows_scored=len(rows),
        temporal_cutoff_year=int(cutoff) if cutoff is not None else None,
        drivers=drivers,
        verdict=verdict,
        output_kpis=output_kpis,
        proxy_accuracy=proxy,
        dominant_label_type=str(metadata.get("dominant_label_type", params.dominant_label_type)),
        label_type_counts=dict(sorted(label_counts.items())),
    )


def compare_versions(
    baseline: cemod.ContentEvalParams,
    candidate: cemod.ContentEvalParams,
    changed_model: str,
    dataset: Mapping | None = None,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> VersionComparison:
    """Run baseline and candidate over the same dataset and report KPI deltas.

    Attributes impact to a single ``changed_model`` (one-change-at-a-time, R6.4).
    Reports candidate-minus-baseline deltas for each Output_KPI. Flags a
    regression (Property 10) when the candidate's primary risk metric
    (False_Greenlight_Rate) ROSE or its model prediction accuracy FELL, and sets
    ``auto_activate`` False on a regression -- the harness never auto-activates a
    regressing version; it only surfaces the comparison for an explicit decision.
    """
    if dataset is None:
        dataset = load_dataset(dataset_path)

    base = run_harness(baseline, dataset=dataset)
    cand = run_harness(candidate, dataset=dataset)

    kpi_deltas = {
        "active_pipeline_valuation": (
            cand.output_kpis.active_pipeline_valuation
            - base.output_kpis.active_pipeline_valuation
        ),
        "avg_ltv_to_cost": (
            cand.output_kpis.avg_ltv_to_cost - base.output_kpis.avg_ltv_to_cost
        ),
        "portfolio_risk_exposure": (
            cand.output_kpis.portfolio_risk_exposure
            - base.output_kpis.portfolio_risk_exposure
        ),
        "model_prediction_accuracy": (
            cand.output_kpis.model_prediction_accuracy
            - base.output_kpis.model_prediction_accuracy
        ),
    }

    fgr_delta = (
        cand.verdict.false_greenlight_rate - base.verdict.false_greenlight_rate
    )
    match_delta = cand.verdict.verdict_match_rate - base.verdict.verdict_match_rate

    regressed = fgr_delta > 0 or match_delta < 0
    return VersionComparison(
        changed_model=changed_model,
        baseline=base,
        candidate=cand,
        kpi_deltas=kpi_deltas,
        false_greenlight_delta=fgr_delta,
        verdict_match_delta=match_delta,
        regressed=regressed,
        auto_activate=not regressed,
        proxy_accuracy=base.proxy_accuracy or cand.proxy_accuracy,
    )


# ---------------------------------------------------------------------------
# Audit-contract bridge helpers (R6.7)
# ---------------------------------------------------------------------------


def audit_metric_name_for_driver(driver: str) -> str | None:
    """Return the existing audit metric name a modeled driver scores through.

    Looks ``driver`` up in :data:`DRIVER_AUDIT_METRICS` to find the
    ``PREDICTED_METRIC_FIELDS`` metric name the Backtest Studio already audits it
    under (e.g. ``"churn_reduction_pct"`` -> ``"churn_reduction"``,
    ``"projected_viewing_hours"`` -> ``"cpvh"``). Returns ``None`` for a driver
    that is not scored through the shared contract, so callers can skip it the
    same way the audit endpoint skips an unknown metric name (R6.7).
    """
    return DRIVER_AUDIT_METRICS.get(driver)


def audit_metrics_for_row(row: Mapping) -> list[dict[str, object]]:
    """Express a dataset row's expected drivers as audit-contract metrics (R6.7).

    Translates each ``expected_drivers`` value into a
    ``{"metric_name", "actual_value"}`` entry keyed by the EXISTING audit metric
    name (:data:`DRIVER_AUDIT_METRICS`), i.e. the exact shape
    ``POST /api/v1/backtest/audit`` accepts in its ``metrics`` list. This lets a
    committed dataset row be scored through the same audit path the Backtest
    Studio uses for CPVH and LTV-to-Cost, reusing the MAPE-excludes-zero
    convention owned by that endpoint -- no MAPE logic is duplicated here.

    A driver without an expected value, or one not mapped to an audited metric,
    is omitted. When two drivers map to the same audit metric name (the two LTV
    drivers both map to ``"ltv_to_cost"``) the first in :data:`DRIVER_KEYS` order
    wins, mirroring the audit module's one-value-per-metric collapse, so the
    emitted list carries at most one entry per metric name.
    """
    expected = row.get("expected_drivers", {}) if isinstance(row, Mapping) else {}
    metrics: list[dict[str, object]] = []
    seen: set[str] = set()
    for driver in DRIVER_KEYS:
        metric_name = DRIVER_AUDIT_METRICS.get(driver)
        if metric_name is None or metric_name in seen:
            continue
        actual = _to_decimal(expected.get(driver))
        if actual is None:
            continue
        seen.add(metric_name)
        metrics.append({"metric_name": metric_name, "actual_value": actual})
    return metrics


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------


def _render_decimal(value: Decimal | None) -> str:
    return "n/a" if value is None else str(value)


def render_report(result: HarnessResult) -> str:
    """Render a human-readable, reproducible harness report (CLI output)."""
    proxy_banner = (
        "PROXY ACCURACY (measured rows are PROXY/SYNTHETIC; "
        "NOT real-world accuracy)"
        if result.proxy_accuracy
        else "accuracy"
    )
    lines = [
        "Content_Eval Backtest_Harness report",
        f"  dataset version    : {result.dataset_version}",
        f"  model version      : {result.version_label}",
        f"  fit dataset version: {result.fit_dataset_version}",
        f"  rows scored (test) : {result.rows_scored}",
        f"  temporal cutoff    : {result.temporal_cutoff_year}",
        f"  label type counts  : {dict(result.label_type_counts)}",
        f"  dominant label type: {result.dominant_label_type}",
        f"  honesty            : {proxy_banner}",
        "",
        "Verdict scoring (asymmetric; False_Greenlight_Rate is the primary risk metric):",
        f"  False_Greenlight_Rate : {result.verdict.false_greenlight_rate} "
        f"({result.verdict.false_greenlights}/{result.verdict.total})",
        f"  False_Pass_Rate       : {result.verdict.false_pass_rate} "
        f"({result.verdict.false_passes}/{result.verdict.total})",
        f"  Verdict_Match_Rate    : {result.verdict.verdict_match_rate} "
        f"({result.verdict.matches}/{result.verdict.total})",
        "",
        "Per-input error (MAPE excludes zero-actual rows):",
    ]
    for driver in DRIVER_KEYS:
        acc = result.drivers[driver]
        extra = ""
        if acc.wape is not None:
            extra = f"  WAPE={_render_decimal(acc.wape)}  Log-MAE={_render_decimal(acc.log_mae)}"
        lines.append(
            f"  {driver:<26} MAPE={_render_decimal(acc.mape)}%  "
            f"(eligible {acc.eligible}/{acc.scored}){extra}"
        )
    lines += [
        "",
        "Output_KPIs (PROXY indices over a PROXY/SYNTHETIC dataset):",
        f"  active_pipeline_valuation : {result.output_kpis.active_pipeline_valuation}",
        f"  avg_ltv_to_cost           : {result.output_kpis.avg_ltv_to_cost}",
        f"  portfolio_risk_exposure   : {result.output_kpis.portfolio_risk_exposure}",
        f"  model_prediction_accuracy : {result.output_kpis.model_prediction_accuracy}",
    ]
    return "\n".join(lines)


def _load_params_from_file(path: str | None) -> cemod.ContentEvalParams:
    """Load a ``content_eval`` params mapping from a JSON file, or the defaults.

    The file may be either a bare ``content_eval`` mapping or a full
    ``guardrail_params`` object carrying a ``content_eval`` key. Absent path ->
    the illustrative defaults.
    """
    if not path:
        return cemod.parse_content_eval_params(None)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, Mapping) and "content_eval" in data:
        data = data["content_eval"]
    return cemod.parse_content_eval_params(data if isinstance(data, Mapping) else None)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run the harness over the committed dataset and print a report.

    With no ``--params`` the illustrative (default) ``content_eval`` version is
    measured. With ``--baseline`` and ``--params`` a baseline-vs-candidate
    comparison is reported, including the Output_KPI deltas and the no-auto-
    regression decision.
    """
    parser = argparse.ArgumentParser(description="Content_Eval Backtest_Harness")
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET_PATH),
        help="path to the KPI_Test_Dataset JSON (defaults to the committed dataset)",
    )
    parser.add_argument(
        "--params",
        default=None,
        help="path to a JSON content_eval params file (candidate); defaults to illustrative",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="path to a JSON content_eval params file to compare against (baseline)",
    )
    parser.add_argument(
        "--changed-model",
        default="content_eval",
        help="name of the single changed model for one-change-at-a-time attribution",
    )
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    candidate = _load_params_from_file(args.params)

    if args.baseline is not None:
        baseline = _load_params_from_file(args.baseline)
        comparison = compare_versions(
            baseline, candidate, args.changed_model, dataset=dataset
        )
        print(render_report(comparison.baseline))
        print("\n--- candidate ---\n")
        print(render_report(comparison.candidate))
        print("\n--- comparison ---")
        print(f"  changed model          : {comparison.changed_model}")
        for key, delta in comparison.kpi_deltas.items():
            print(f"  delta {key:<24}: {delta}")
        print(f"  delta False_Greenlight_Rate: {comparison.false_greenlight_delta}")
        print(f"  delta Verdict_Match_Rate   : {comparison.verdict_match_delta}")
        print(f"  regressed              : {comparison.regressed}")
        print(f"  auto_activate          : {comparison.auto_activate}")
        return 0

    result = run_harness(candidate, dataset=dataset)
    print(render_report(result))
    return 0


# ---------------------------------------------------------------------------
# Inline sanity check (tiny; the full test suite is task 10)
# ---------------------------------------------------------------------------


def _sanity_check() -> HarnessResult:
    """Run the harness over the committed dataset with the illustrative defaults.

    A tiny importable self-check (the full property/unit suite is task 10): asserts
    the harness scores the held-out rows, labels accuracy PROXY, and keeps every
    directional rate in [0, 1]. Returns the :class:`HarnessResult` so a caller can
    inspect it.
    """
    params = cemod.parse_content_eval_params(None)
    result = run_harness(params)
    assert result.rows_scored > 0, "no test-split rows scored"
    assert result.proxy_accuracy is True, "proxy accuracy must hold on the dataset"
    for rate in (
        result.verdict.false_greenlight_rate,
        result.verdict.false_pass_rate,
        result.verdict.verdict_match_rate,
    ):
        assert Decimal("0") <= rate <= Decimal("1"), f"rate out of [0,1]: {rate}"
    return result


if __name__ == "__main__":
    raise SystemExit(main())
