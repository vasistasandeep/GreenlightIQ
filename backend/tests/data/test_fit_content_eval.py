"""Tests for the fit-and-measure step (task 19).

# Feature: content-eval-model

Covers the behaviors the task calls out for
``database/kpi_dataset/fit_content_eval.py`` -- the script that fits a
viewing-hours ``content_eval`` version from the TRAINING split, measures it on
the HELD-OUT test split via the Backtest_Harness, and writes a committed report
WITHOUT activating anything:

- **Reproducible fit (Property 8)** -- re-fitting on the fixed dataset yields
  byte-identical coefficients (intercept + betas) every run; the fit reads only
  the training split (Property 11: never a held-out row).
- **``--check`` is idempotent and no-write** -- the committed report artifacts
  (``fitted_content_eval_v1.json`` + ``fit_report.md``) are byte-identical to a
  fresh recompute; ``--check`` exits 0 and leaves the files untouched.
- **Regression decision consistency (Property 10)** -- the ``regressed`` /
  ``auto_activate`` / ``recommended_for_activation`` fields in the committed
  report agree with the harness's own ``compare_versions`` result recomputed
  here; a regressed candidate would be flagged DO-NOT-ACTIVATE and never
  auto-activated.
- **Honest labeling (Property 13)** -- every reported metric is labeled PROXY
  because the measured rows are PROXY/SYNTHETIC; no metric is presented as
  real-world accuracy, and the script never changes the seed or writes a
  ``model_versions`` row.

Pure/stdlib tests: no database, no app framework beyond the pure domain/engine
modules, no network. The fit script lives under ``database/kpi_dataset`` (outside
the backend package root), so it is loaded by file path with ``importlib``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.domain import content_eval as cemod
from app.engines import backtest_harness as harness

# ---------------------------------------------------------------------------
# Load the committed fit script by file path (it sits outside the backend
# package root, under database/kpi_dataset/).
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KPI_DIR = _REPO_ROOT / "database" / "kpi_dataset"
_FIT_PATH = _KPI_DIR / "fit_content_eval.py"

FITTED_JSON = _KPI_DIR / "fitted_content_eval_v1.json"
REPORT_MD = _KPI_DIR / "fit_report.md"


def _load_fit_module():
    spec = importlib.util.spec_from_file_location("fit_content_eval", _FIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fit = _load_fit_module()


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dataset() -> dict:
    return fit._load_dataset()


@pytest.fixture(scope="module")
def report() -> dict:
    """The committed JSON report payload."""
    return json.loads(FITTED_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Committed artifacts exist.
# ---------------------------------------------------------------------------


def test_committed_report_artifacts_exist() -> None:
    """The committed fit script and both report artifacts are present."""
    assert _FIT_PATH.exists(), f"missing fit script: {_FIT_PATH}"
    assert FITTED_JSON.exists(), f"missing committed report: {FITTED_JSON}"
    assert REPORT_MD.exists(), f"missing committed report: {REPORT_MD}"


# ---------------------------------------------------------------------------
# Reproducible fit (Property 8).
# ---------------------------------------------------------------------------


def test_fit_is_byte_identical_across_runs(dataset) -> None:
    """# Property 8: re-fitting on the fixed dataset is byte-identical.

    The fit is deterministic (fixed seed, stdlib only), so two independent runs
    produce exactly the same intercept + betas.
    """
    first = fit.fit_viewing_hours(dataset)
    second = fit.fit_viewing_hours(dataset)
    assert first["intercept"] == second["intercept"]
    assert first["betas"] == second["betas"]
    assert first == second


def test_fit_reads_only_the_training_split(dataset) -> None:
    """# Property 11: the fit's design matrix comes only from training rows.

    No held-out (test-split) row may feed the fit; the training-row count the fit
    records equals the number of train-split rows carrying the target.
    """
    train_rows = [r for r in dataset["rows"] if r.get("split") == "train"]
    with_target = [
        r
        for r in train_rows
        if r.get("expected_drivers", {}).get("projected_viewing_hours")
        not in (None, "")
    ]
    summary = fit.fit_viewing_hours(dataset)
    assert summary["train_rows"] == len(with_target)
    # And no test row leaks in: the matrix size never exceeds the train rows.
    assert summary["train_rows"] <= len(train_rows)


def test_fitted_betas_are_nonnegative(report) -> None:
    """# Property 9 (carried through): every fitted beta is non-negative."""
    from decimal import Decimal

    for name, value in report["fit"]["betas"].items():
        assert Decimal(value) >= 0, name
    assert Decimal(report["fit"]["intercept"]).is_finite()


def test_committed_report_matches_a_fresh_fit(dataset, report) -> None:
    """The committed report's fit block equals a fresh in-memory fit."""
    fresh = fit.fit_viewing_hours(dataset)
    assert report["fit"]["intercept"] == fresh["intercept"]
    assert report["fit"]["betas"] == fresh["betas"]


# ---------------------------------------------------------------------------
# --check is idempotent and writes nothing.
# ---------------------------------------------------------------------------


def test_check_mode_returns_zero() -> None:
    """``--check`` exits 0 when the committed report matches a fresh recompute."""
    assert fit.main(["--check"]) == 0


def test_check_mode_writes_nothing() -> None:
    """``--check`` is no-write: the bytes of both artifacts are untouched."""
    before = {path: path.read_bytes() for path in (FITTED_JSON, REPORT_MD)}
    rc = fit.main(["--check"])
    assert rc == 0
    after = {path: path.read_bytes() for path in before}
    assert after == before


def test_committed_artifacts_match_fresh_build() -> None:
    """Both committed artifacts are byte-identical to a fresh recompute."""
    artifacts = fit._artifacts()
    for path, content in artifacts.items():
        assert path.read_text(encoding="utf-8") == content, f"stale artifact: {path}"


def test_rebuild_is_deterministic() -> None:
    """Two independent in-memory recomputes are byte-identical (no RNG/wall-clock)."""
    first = fit._artifacts()
    second = fit._artifacts()
    assert {p.name: c for p, c in first.items()} == {
        p.name: c for p, c in second.items()
    }


# ---------------------------------------------------------------------------
# Regression decision consistency (Property 10).
# ---------------------------------------------------------------------------


def test_report_regression_decision_matches_harness(dataset, report) -> None:
    """# Property 10: the report's regression decision matches compare_versions.

    Re-running the harness's ``compare_versions`` with the committed candidate
    block reproduces the ``regressed`` / ``auto_activate`` flags recorded in the
    report, and the candidate is only recommended for activation when it did not
    regress.
    """
    candidate_block = report["candidate_content_eval"]
    comparison = fit.measure(candidate_block, dataset)

    assert report["regressed"] == comparison.regressed
    assert report["auto_activate"] == comparison.auto_activate
    # No-auto-regression: a regressed candidate is never auto-activated.
    if comparison.regressed:
        assert comparison.auto_activate is False
        assert report["recommended_for_activation"] is False
        assert "DO NOT ACTIVATE" in report["activation_recommendation"]
    else:
        assert report["recommended_for_activation"] is True


def test_report_fgr_and_match_deltas_match_harness(dataset, report) -> None:
    """The report's FGR / verdict-match deltas equal the harness's deltas."""
    candidate_block = report["candidate_content_eval"]
    comparison = fit.measure(candidate_block, dataset)
    assert report["false_greenlight_delta"] == str(comparison.false_greenlight_delta)
    assert report["verdict_match_delta"] == str(comparison.verdict_match_delta)
    # The harness's Property-10 rule: regressed iff FGR rose or match fell.
    expected_regressed = (
        comparison.false_greenlight_delta > 0 or comparison.verdict_match_delta < 0
    )
    assert comparison.regressed == expected_regressed


def test_candidate_changes_only_viewing_hours(report) -> None:
    """One-change-at-a-time: the candidate changes the viewing-hours model only.

    The engagement + churn blocks are left at the illustrative defaults (the
    candidate block omits them), and the churn->LTV link stays OFF.
    """
    block = report["candidate_content_eval"]
    assert report["changed_model"] == "viewing_hours"
    assert "viewing_hours" in block
    assert "engagement" not in block
    assert block["link_churn_to_ltv"] is False
    # Parsing the block defaults engagement to the illustrative params.
    params = cemod.parse_content_eval_params(block)
    assert params.watch_time_elasticity_source == "DEFAULTS"
    assert params.ad_load_receptivity_source == "DEFAULTS"
    assert params.viewing_hours_source == "MODEL_VERSION"


# ---------------------------------------------------------------------------
# Honest labeling (Property 13).
# ---------------------------------------------------------------------------


def test_every_reported_metric_is_labeled_proxy(report) -> None:
    """# Property 13: every reported accuracy figure is labeled PROXY.

    The measured rows are PROXY/SYNTHETIC, so the report flags proxy accuracy at
    the top level and on every per-driver accuracy block of both versions.
    """
    assert report["proxy_accuracy"] is True
    assert "PROXY" in report["honesty_note"]
    for side in ("baseline", "candidate"):
        assert report[side]["proxy_accuracy"] is True
        for driver in harness.DRIVER_KEYS:
            assert report[side]["drivers"][driver]["proxy"] is True
        assert report[side]["verdict"]["proxy"] is True


def test_viewing_hours_accuracy_improves_or_holds(report) -> None:
    """The fitted candidate does not worsen viewing-hours WAPE vs baseline.

    A sanity check that the fit actually learned signal: the candidate's WAPE is
    at least as good (<=) as the illustrative baseline's on the held-out split.
    """
    from decimal import Decimal

    base_wape = Decimal(report["baseline"]["drivers"]["projected_viewing_hours"]["wape"])
    cand_wape = Decimal(report["candidate"]["drivers"]["projected_viewing_hours"]["wape"])
    assert cand_wape <= base_wape


def test_report_does_not_activate_anything(report) -> None:
    """The report is a measurement only: no seed change, no model_versions write.

    The committed fit script produces and measures a candidate; it must not claim
    any activation. The ``recommended_for_activation`` flag is advisory only and
    the markdown report states activation is a separate explicit decision.
    """
    md = REPORT_MD.read_text(encoding="utf-8")
    assert "never" in md.lower()
    assert "model_versions" in md
    # The report carries a label, never an active flag.
    assert report["candidate_content_eval"]["version_label"] == "fitted-viewing-hours-v1"
