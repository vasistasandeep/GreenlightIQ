"""Fit and measure the first Content_Eval viewing-hours version (task 19).

The fit-and-measure step of the Content_Eval_System (content-eval-model). Unlike
``make_content_eval_dataset.py`` (which builds the labeled truth sheet), this
script runs ``Model_Fit`` to LEARN a ``content_eval`` version from the dataset's
TRAINING split, measures it on the HELD-OUT test split with the Backtest_Harness,
and writes a committed report -- WITHOUT activating anything (R4.1, R4.4-R4.7,
R6.1-R6.3; Properties 8, 10, 13).

What it does:

- **Load** the committed ``KPI_Test_Dataset`` JSON (offline, no DB, no network).
- **Fit** a viewing-hours version on the TRAINING split only (Property 11: the
  fit never reads a held-out row). The heavy-tailed ``projected_viewing_hours``
  target is fit in ``log1p`` space via :func:`app.domain.fit.fit_log_wape` over
  the NUMERIC predictive features that carry a beta (the label features
  asset_type / genre / content_format are non-numeric and carry no weight, so
  they are excluded from the design matrix). A deterministic, stdlib-only solve
  with a fixed seed -> byte-identical coefficients on every run (Property 8).
- **Assemble** a candidate ``content_eval`` block: the fitted viewing-hours
  intercept + non-negative betas, with engagement and churn left at the
  illustrative defaults for this first pass (a churn fit is explored below and
  only adopted when it is clearly beneficial -- it is not here, because the
  harness churn model stays the hand-tuned reference member of the family).
- **Measure** via :func:`app.engines.backtest_harness.compare_versions`
  (baseline = illustrative defaults, candidate = fitted) on the held-out split:
  MAPE/WAPE/Log-MAE, verdict-match, False_Greenlight_Rate / False_Pass_Rate, and
  the four Output_KPI deltas, every figure labeled by Label_Type (PROXY banner).
- **Decide** honestly: if the candidate REGRESSED (False_Greenlight_Rate rose OR
  verdict-match fell vs baseline, per the harness's Property-10 rule), the report
  flags ``REGRESSED`` and recommends NOT activating. The report is still written
  either way; this script NEVER activates a version (no seed change, no
  model_versions write) -- it only produces and measures the candidate (R4.7).

Artifacts written (committed):

- ``fitted_content_eval_v1.json`` -- the fitted candidate ``content_eval`` block
  plus its measurement (metrics, deltas, the regression decision).
- ``fit_report.md`` -- a human-readable report of the fitted-vs-baseline numbers
  and the activation recommendation.

Usage::

    python database/kpi_dataset/fit_content_eval.py            # fit + write report
    python database/kpi_dataset/fit_content_eval.py --check     # recompute, verify

``--check`` is idempotent and writes nothing: it re-fits and re-measures in
memory and exits non-zero if either committed artifact is missing or out of date,
mirroring ``make_content_eval_dataset.py`` and ``generate_seed_sql.py``.

Standard library + the existing pure domain/engine modules only. Deterministic,
offline, reproducible. No third-party dependency, no database, no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# Make ``app`` importable when run as a plain script, the way
# ``make_content_eval_dataset.py`` and ``generate_seed_sql.py`` do.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.domain import content_eval as cemod  # noqa: E402
from app.domain import features as featmod  # noqa: E402
from app.domain import fit as fitmod  # noqa: E402
from app.domain import viewing_hours as vhmod  # noqa: E402
from app.engines import backtest_harness as harness  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET_JSON = HERE / "content_eval_dataset.json"
FITTED_JSON = HERE / "fitted_content_eval_v1.json"
REPORT_MD = HERE / "fit_report.md"

# The fitted candidate's provenance label (never activated; label only).
FITTED_VERSION_LABEL = "fitted-viewing-hours-v1"
CHANGED_MODEL = "viewing_hours"

# Only NUMERIC predictive features carry a viewing-hours beta. The label features
# (asset_type / genre / content_format) are non-numeric and cannot multiply a
# string, so they are excluded from the design matrix (mirrors the illustrative
# DEFAULT_VIEWING_HOURS_BETAS, which also keys only the numeric predictors).
FIT_FEATURES = tuple(vhmod.DEFAULT_VIEWING_HOURS_BETAS.keys())

# Coefficient quantization: the fitted intercept/betas are rounded to a fixed
# number of decimal places BEFORE they go into the candidate block, so the
# committed JSON is byte-stable across runs/platforms (float noise in the last
# ULP never leaks into the artifact). 10 dp is far finer than the hour-space
# quantum needs and keeps the log-space coefficients fully expressive.
_COEFF_QUANTUM = Decimal("0.0000000001")  # 1e-10


# ---------------------------------------------------------------------------
# Feature extraction for the design matrix
# ---------------------------------------------------------------------------


def _feature_value(vector: featmod.FeatureVector, name: str) -> float:
    """Resolve the numeric feature value ``x_i`` for one predictive feature.

    Reads the resolved :class:`app.domain.features.Feature` and coerces it to a
    float the same way the pure viewing-hours model does: a boolean -> 0/1, a
    finite Decimal -> its float value. A design-matrix column is always one of
    :data:`FIT_FEATURES`, every one of which is numeric, so this never hits a
    label feature.
    """
    feature = getattr(vector, name)
    value = feature.value
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, Decimal):
        return float(value)
    # Should not happen for the numeric FIT_FEATURES; treat as a neutral 0.
    return 0.0


def _training_rows(dataset: dict) -> list[dict]:
    """Return only the TRAINING-split rows (Property 11: the fit reads no test row)."""
    return [row for row in dataset["rows"] if row.get("split") == "train"]


def _design_matrix(rows: list[dict]) -> tuple[list[list[float]], list[float]]:
    """Build the viewing-hours design matrix + target over the given rows.

    Each row's features are derived via the shared
    :func:`app.domain.features.derive_features`, then reduced to the numeric
    :data:`FIT_FEATURES` columns in fixed order. The target is the row's expected
    ``projected_viewing_hours`` (hour space; ``fit_log_wape`` takes the log1p
    internally). Rows missing the target are skipped.
    """
    x: list[list[float]] = []
    y: list[float] = []
    for row in rows:
        target_raw = row.get("expected_drivers", {}).get("projected_viewing_hours")
        if target_raw in (None, ""):
            continue
        vector = featmod.derive_features(row.get("features", {}))
        x.append([_feature_value(vector, name) for name in FIT_FEATURES])
        y.append(float(Decimal(str(target_raw))))
    return x, y


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------


def _q_coeff(value: float) -> Decimal:
    """Quantize a fitted float coefficient to a byte-stable Decimal (>= 0)."""
    dec = Decimal(str(value)).quantize(_COEFF_QUANTUM, rounding=ROUND_HALF_UP)
    # Non-negativity is guaranteed by the solver (Property 9); clamp defensively
    # so a -0E-10 quantization artifact never serializes as a negative weight.
    if dec <= 0:
        return Decimal("0")
    return dec


def fit_viewing_hours(dataset: dict) -> dict:
    """Fit the viewing-hours coefficients on the dataset's TRAINING split.

    Returns a JSON-serializable fit summary: the fitted intercept, the per-feature
    betas (quantized, non-negative), the train metrics, and the fit provenance.
    The fit is deterministic (fixed seed, stdlib only) so it is byte-identical on
    every run and platform (Property 8).
    """
    train_rows = _training_rows(dataset)
    x, y = _design_matrix(train_rows)

    result = fitmod.fit_log_wape(
        x,
        y,
        feature_names=FIT_FEATURES,
        fit_intercept=True,
        nonneg_intercept=False,
        seed=fitmod.DEFAULT_SEED,
    )

    intercept = _q_coeff(result.intercept)
    betas = {
        name: _q_coeff(coef)
        for name, coef in zip(result.feature_names, result.coefficients)
    }
    # Drop zero-weight features so the committed block mirrors the illustrative
    # block's shape (only features that actually carry signal are listed).
    nonzero_betas = {name: beta for name, beta in betas.items() if beta > 0}

    return {
        "intercept": str(intercept),
        "betas": {name: str(beta) for name, beta in nonzero_betas.items()},
        "objective": result.objective,
        "iterations": result.iterations,
        "converged": result.converged,
        "train_rows": len(x),
        "train_metrics": {
            key: round(value, 6) for key, value in sorted(result.metrics.items())
        },
    }


# ---------------------------------------------------------------------------
# Candidate assembly + measurement
# ---------------------------------------------------------------------------


def build_candidate_block(fit_summary: dict, dataset: dict) -> dict:
    """Assemble the candidate ``content_eval`` block from the fit (never activated).

    The viewing-hours intercept + betas come from the fit; engagement and churn
    are left at the illustrative defaults for this first pass. ``floor`` reuses
    the model's positive default so CPVH never divides by zero. This block is
    exactly what the harness parses via ``parse_content_eval_params`` and what the
    report commits; it is NOT written to any seed or ``model_versions`` row.
    """
    metadata = dataset.get("metadata", {})
    return {
        "version_label": FITTED_VERSION_LABEL,
        "fit_dataset_version": metadata.get("version"),
        "dominant_label_type": metadata.get("dominant_label_type", "PROXY"),
        # Keep the churn->LTV link OFF; this candidate changes viewing hours only.
        "link_churn_to_ltv": False,
        "viewing_hours": {
            "intercept": fit_summary["intercept"],
            "betas": dict(fit_summary["betas"]),
            "floor": str(vhmod.VIEWING_HOURS_FLOOR),
            "objective": fit_summary["objective"],
        },
        # engagement + churn intentionally omitted -> parsed to illustrative
        # defaults (this first pass changes only the viewing-hours model).
    }


def _driver_accuracy_json(acc: harness.DriverAccuracy) -> dict:
    """Serialize a :class:`DriverAccuracy` to a JSON-stable mapping."""
    return {
        "driver": acc.driver,
        "mape": None if acc.mape is None else str(acc.mape),
        "wape": None if acc.wape is None else str(acc.wape),
        "log_mae": None if acc.log_mae is None else str(acc.log_mae),
        "eligible": acc.eligible,
        "scored": acc.scored,
        "proxy": acc.proxy,
    }


def _verdict_json(verdict: harness.VerdictScore) -> dict:
    """Serialize a :class:`VerdictScore` to a JSON-stable mapping."""
    return {
        "false_greenlight_rate": str(verdict.false_greenlight_rate),
        "false_pass_rate": str(verdict.false_pass_rate),
        "verdict_match_rate": str(verdict.verdict_match_rate),
        "matches": verdict.matches,
        "total": verdict.total,
        "false_greenlights": verdict.false_greenlights,
        "false_passes": verdict.false_passes,
        "proxy": verdict.proxy,
    }


def _kpis_json(kpis: harness.OutputKPIs) -> dict:
    """Serialize an :class:`OutputKPIs` to a JSON-stable mapping."""
    return {
        "active_pipeline_valuation": str(kpis.active_pipeline_valuation),
        "avg_ltv_to_cost": str(kpis.avg_ltv_to_cost),
        "portfolio_risk_exposure": str(kpis.portfolio_risk_exposure),
        "model_prediction_accuracy": str(kpis.model_prediction_accuracy),
    }


def _result_json(res: harness.HarnessResult) -> dict:
    """Serialize a :class:`HarnessResult` to a JSON-stable mapping."""
    return {
        "dataset_version": res.dataset_version,
        "version_label": res.version_label,
        "fit_dataset_version": res.fit_dataset_version,
        "rows_scored": res.rows_scored,
        "temporal_cutoff_year": res.temporal_cutoff_year,
        "proxy_accuracy": res.proxy_accuracy,
        "dominant_label_type": res.dominant_label_type,
        "label_type_counts": dict(res.label_type_counts),
        "drivers": {
            driver: _driver_accuracy_json(res.drivers[driver])
            for driver in harness.DRIVER_KEYS
        },
        "verdict": _verdict_json(res.verdict),
        "output_kpis": _kpis_json(res.output_kpis),
    }


def measure(candidate_block: dict, dataset: dict) -> harness.VersionComparison:
    """Measure the fitted candidate vs the illustrative baseline on the held-out split.

    Baseline = the illustrative defaults (``parse_content_eval_params(None)``);
    candidate = the fitted block. One-change-at-a-time attribution to the
    viewing-hours model. Returns the harness's :class:`VersionComparison`, whose
    ``regressed`` / ``auto_activate`` encode the no-auto-regression rule
    (Property 10).
    """
    baseline = cemod.parse_content_eval_params(None)
    candidate = cemod.parse_content_eval_params(candidate_block)
    return harness.compare_versions(
        baseline, candidate, CHANGED_MODEL, dataset=dataset
    )


def build_report(fit_summary: dict, candidate_block: dict, dataset: dict) -> dict:
    """Build the full committed report payload (fit + candidate + measurement)."""
    comparison = measure(candidate_block, dataset)
    recommended = not comparison.regressed
    return {
        "report_version": "fit-report-v1",
        "changed_model": comparison.changed_model,
        "fit_dataset_version": dataset.get("metadata", {}).get("version"),
        "honesty_note": (
            "PROXY accuracy: every measured row is PROXY/SYNTHETIC, so all "
            "metrics below are proxy accuracy, NOT real-world accuracy."
        ),
        "proxy_accuracy": comparison.proxy_accuracy,
        "dominant_label_type": comparison.candidate.dominant_label_type,
        "fit": fit_summary,
        "candidate_content_eval": candidate_block,
        "baseline": _result_json(comparison.baseline),
        "candidate": _result_json(comparison.candidate),
        "kpi_deltas": {
            key: str(value) for key, value in sorted(comparison.kpi_deltas.items())
        },
        "false_greenlight_delta": str(comparison.false_greenlight_delta),
        "verdict_match_delta": str(comparison.verdict_match_delta),
        "regressed": comparison.regressed,
        "auto_activate": comparison.auto_activate,
        "activation_recommendation": (
            "DO NOT ACTIVATE (candidate REGRESSED vs baseline: "
            "False_Greenlight_Rate rose or Verdict_Match_Rate fell)"
            if comparison.regressed
            else "candidate did not regress; activation is an explicit manual "
            "decision (this script never auto-activates)"
        ),
        "recommended_for_activation": recommended,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_report_json(report: dict) -> str:
    """Render the committed JSON report (deterministic, pretty, sorted)."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_report_md(report: dict) -> str:
    """Render the human-readable fit report (markdown)."""
    base = report["baseline"]
    cand = report["candidate"]
    fit = report["fit"]
    verdict_flag = "**REGRESSED**" if report["regressed"] else "no regression"

    lines: list[str] = [
        "# Content_Eval fit report (viewing-hours v1)",
        "",
        f"- Changed model: `{report['changed_model']}`",
        f"- Fit dataset version: `{report['fit_dataset_version']}`",
        f"- Candidate version label: `{report['candidate_content_eval']['version_label']}`",
        f"- Dominant label type: `{report['dominant_label_type']}`",
        "",
        "> PROXY ACCURACY: every measured row is PROXY/SYNTHETIC. All numbers "
        "below are proxy accuracy, **not** real-world accuracy.",
        "",
        "## Fit (training split)",
        "",
        f"- Objective: `{fit['objective']}`  | converged: {fit['converged']} "
        f"| iterations: {fit['iterations']} | train rows: {fit['train_rows']}",
        f"- Intercept: `{fit['intercept']}`",
        "- Fitted betas (non-negative):",
    ]
    if fit["betas"]:
        for name in FIT_FEATURES:
            if name in fit["betas"]:
                lines.append(f"  - `{name}` = {fit['betas'][name]}")
    else:
        lines.append("  - (all features fit to zero weight)")
    lines += [
        "- Train metrics: "
        + ", ".join(f"{k}={v}" for k, v in sorted(fit["train_metrics"].items())),
        "",
        "## Measurement (held-out test split)",
        "",
        f"- Rows scored (test): {cand['rows_scored']}  | temporal cutoff: "
        f"{cand['temporal_cutoff_year']}  | label types: {cand['label_type_counts']}",
        "",
        "### Viewing-hours accuracy (PROXY)",
        "",
        "| metric | baseline | candidate |",
        "| --- | --- | --- |",
    ]
    bvh = base["drivers"]["projected_viewing_hours"]
    cvh = cand["drivers"]["projected_viewing_hours"]
    lines += [
        f"| MAPE % | {bvh['mape']} | {cvh['mape']} |",
        f"| WAPE | {bvh['wape']} | {cvh['wape']} |",
        f"| Log-MAE | {bvh['log_mae']} | {cvh['log_mae']} |",
        f"| eligible/scored | {bvh['eligible']}/{bvh['scored']} | "
        f"{cvh['eligible']}/{cvh['scored']} |",
        "",
        "### Verdict scoring (PROXY; False_Greenlight_Rate is the primary risk metric)",
        "",
        "| metric | baseline | candidate | delta |",
        "| --- | --- | --- | --- |",
        f"| False_Greenlight_Rate | {base['verdict']['false_greenlight_rate']} | "
        f"{cand['verdict']['false_greenlight_rate']} | {report['false_greenlight_delta']} |",
        f"| False_Pass_Rate | {base['verdict']['false_pass_rate']} | "
        f"{cand['verdict']['false_pass_rate']} | - |",
        f"| Verdict_Match_Rate | {base['verdict']['verdict_match_rate']} | "
        f"{cand['verdict']['verdict_match_rate']} | {report['verdict_match_delta']} |",
        "",
        "### Output_KPI deltas (candidate - baseline; PROXY indices)",
        "",
        "| KPI | delta |",
        "| --- | --- |",
    ]
    for key, value in sorted(report["kpi_deltas"].items()):
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Decision",
        "",
        f"- Regression check: {verdict_flag}",
        f"- `auto_activate`: {report['auto_activate']}",
        f"- Recommendation: {report['activation_recommendation']}",
        "",
        "This script measures only; it never changes the seed or writes a "
        "`model_versions` row. Activating the fitted version is a separate, "
        "explicit governance decision.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_dataset() -> dict:
    """Load the committed KPI_Test_Dataset JSON (offline)."""
    return json.loads(DATASET_JSON.read_text(encoding="utf-8"))


def _artifacts() -> dict[Path, str]:
    """Build every committed artifact's path -> content mapping (in memory)."""
    dataset = _load_dataset()
    fit_summary = fit_viewing_hours(dataset)
    candidate_block = build_candidate_block(fit_summary, dataset)
    report = build_report(fit_summary, candidate_block, dataset)
    return {
        FITTED_JSON: render_report_json(report),
        REPORT_MD: render_report_md(report),
    }


def write_artifacts() -> int:
    """Fit, measure, and write the committed report artifacts. Prints a banner."""
    dataset = _load_dataset()
    fit_summary = fit_viewing_hours(dataset)
    candidate_block = build_candidate_block(fit_summary, dataset)
    report = build_report(fit_summary, candidate_block, dataset)

    FITTED_JSON.write_text(render_report_json(report), encoding="utf-8")
    REPORT_MD.write_text(render_report_md(report), encoding="utf-8")

    _print_console_summary(report)
    print(f"\nwrote {FITTED_JSON}")
    print(f"wrote {REPORT_MD}")
    return 0


def _print_console_summary(report: dict) -> None:
    """Print the measured numbers with the PROXY banner (CLI visibility)."""
    base = report["baseline"]
    cand = report["candidate"]
    bvh = base["drivers"]["projected_viewing_hours"]
    cvh = cand["drivers"]["projected_viewing_hours"]
    print("=" * 72)
    print("Content_Eval fit + measure (viewing-hours v1)")
    print("PROXY ACCURACY -- measured rows are PROXY/SYNTHETIC; NOT real-world.")
    print("=" * 72)
    print(f"  fit dataset version : {report['fit_dataset_version']}")
    print(f"  candidate label     : {report['candidate_content_eval']['version_label']}")
    print(f"  rows scored (test)  : {cand['rows_scored']}")
    print(f"  fit converged       : {report['fit']['converged']} "
          f"(iterations {report['fit']['iterations']})")
    print("  viewing-hours accuracy (baseline -> candidate):")
    print(f"    MAPE %  : {bvh['mape']} -> {cvh['mape']}")
    print(f"    WAPE    : {bvh['wape']} -> {cvh['wape']}")
    print(f"    Log-MAE : {bvh['log_mae']} -> {cvh['log_mae']}")
    print("  verdict scoring (baseline -> candidate):")
    print(f"    False_Greenlight_Rate : {base['verdict']['false_greenlight_rate']} "
          f"-> {cand['verdict']['false_greenlight_rate']} "
          f"(delta {report['false_greenlight_delta']})")
    print(f"    False_Pass_Rate       : {base['verdict']['false_pass_rate']} "
          f"-> {cand['verdict']['false_pass_rate']}")
    print(f"    Verdict_Match_Rate    : {base['verdict']['verdict_match_rate']} "
          f"-> {cand['verdict']['verdict_match_rate']} "
          f"(delta {report['verdict_match_delta']})")
    print("  Output_KPI deltas (candidate - baseline):")
    for key, value in sorted(report["kpi_deltas"].items()):
        print(f"    {key:<26}: {value}")
    print(f"  regressed            : {report['regressed']}")
    print(f"  auto_activate        : {report['auto_activate']}")
    print(f"  recommendation       : {report['activation_recommendation']}")


def check_artifacts() -> int:
    """Verify committed artifacts match a fresh re-fit + re-measure (no write).

    Returns 0 when both artifacts are present and byte-identical to the freshly
    recomputed content, else 1 -- the idempotent, no-write ``--check`` contract.
    """
    ok = True
    for path, content in _artifacts().items():
        if not path.exists():
            print(f"MISSING {path} (run the fit to create it)")
            ok = False
            continue
        current = path.read_text(encoding="utf-8")
        if current == content:
            print(f"ok   {path.name} is up to date")
        else:
            cur_sum = hashlib.sha256(current.encode("utf-8")).hexdigest()[:12]
            new_sum = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
            print(f"STALE {path.name} (committed {cur_sum} != expected {new_sum})")
            ok = False
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="recompute the fit + measurement and verify the committed report "
        "is up to date (idempotent, no write)",
    )
    args = parser.parse_args(argv)
    if args.check:
        return check_artifacts()
    return write_artifacts()


if __name__ == "__main__":
    raise SystemExit(main())
