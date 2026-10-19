"""Tests for the committed KPI_Test_Dataset and its generator (task 8).

# Feature: content-eval-model

Covers the behaviors the task calls out for the labeled truth sheet
(``database/kpi_dataset/content_eval_dataset.{csv,json}`` + the sidecar
``DATASET_META.json``) and its stdlib-only generator
(``make_content_eval_dataset.py``):

- **``--check`` is idempotent and writes nothing** -- the committed artifacts are
  byte-identical to a fresh in-memory build; running ``--check`` leaves every
  file untouched and exits 0 (R3.1).
- **Schema + size bound** -- every row carries a stable id, the full
  Feature_Vector inputs ``derive_features`` consumes, an expected value for each
  modeled driver, an expected per-guardrail outcome, an expected recommendation,
  a Label_Type, a release_year, and a split; the benchmark holds 50-100 titles
  spanning all five strata (R3.1, R3.2).
- **Temporal non-leakage (Property 11)** -- no test-split row has
  ``release_year <= cutoff`` and no train-split row has
  ``release_year > cutoff``; the cutoff is recorded in the metadata (R3.3).
- **The five seeded demo titles are present with their verdicts pinned** --
  Aurora Protocol / Echoes of 2019 / Monsoon Lanes -> GREENLIGHT, The Ledger ->
  NEGOTIATE_HARD, Vintage Reruns Vol. 7 -> PASS (R3.4).
- **Honest labeling** -- every row carries a Label_Type and NONE is OBSERVED, so
  no measurement over this dataset can overstate real-world accuracy (R2.6,
  R3.6).

Pure/stdlib tests: no database, no app framework beyond the pure feature module,
no network. The generator module lives under ``database/kpi_dataset`` (outside
the backend package root), so it is loaded by file path with ``importlib``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.domain.features import PREDICTIVE_FEATURES, derive_features

# ---------------------------------------------------------------------------
# Load the committed generator module by file path (it sits outside the backend
# package root, under database/kpi_dataset/).
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KPI_DIR = _REPO_ROOT / "database" / "kpi_dataset"
_GEN_PATH = _KPI_DIR / "make_content_eval_dataset.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_content_eval_dataset", _GEN_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


CSV_PATH = _KPI_DIR / "content_eval_dataset.csv"
JSON_PATH = _KPI_DIR / "content_eval_dataset.json"
META_PATH = _KPI_DIR / "DATASET_META.json"
PROVENANCE_PATH = _KPI_DIR / "PROVENANCE.md"


# ---------------------------------------------------------------------------
# Fixtures: the committed artifacts, loaded once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dataset() -> dict:
    """The committed JSON dataset (metadata + rows)."""
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(dataset) -> list[dict]:
    return dataset["rows"]


@pytest.fixture(scope="module")
def metadata(dataset) -> dict:
    return dataset["metadata"]


# ---------------------------------------------------------------------------
# --check is idempotent and writes nothing (R3.1).
# ---------------------------------------------------------------------------


def test_committed_artifacts_exist() -> None:
    """The committed CSV/JSON/metadata/provenance artifacts are all present."""
    for path in (CSV_PATH, JSON_PATH, META_PATH, PROVENANCE_PATH):
        assert path.exists(), f"missing committed artifact: {path}"


def test_check_mode_reports_up_to_date() -> None:
    """``--check`` exits 0 when the committed artifacts match a fresh build (R3.1)."""
    assert gen.main(["--check"]) == 0


def test_check_mode_writes_nothing() -> None:
    """``--check`` is no-write: the bytes of every artifact are untouched (R3.1)."""
    before = {
        path: path.read_bytes()
        for path in (CSV_PATH, JSON_PATH, META_PATH)
    }
    rc = gen.main(["--check"])
    assert rc == 0
    after = {path: path.read_bytes() for path in before}
    assert after == before


def test_committed_artifacts_match_fresh_build() -> None:
    """Every committed artifact is byte-identical to a fresh in-memory build.

    This is the determinism/idempotence contract behind ``--check``: rebuilding
    the artifacts in memory reproduces exactly the committed bytes.
    """
    artifacts = gen._artifacts()
    for path, content in artifacts.items():
        assert path.read_text(encoding="utf-8") == content, f"stale artifact: {path}"


def test_rebuild_is_deterministic() -> None:
    """Two independent in-memory builds are byte-identical (no RNG/wall-clock)."""
    first = gen._artifacts()
    second = gen._artifacts()
    assert {p.name: c for p, c in first.items()} == {
        p.name: c for p, c in second.items()
    }


# ---------------------------------------------------------------------------
# Schema + size bound (R3.1, R3.2).
# ---------------------------------------------------------------------------


def test_size_bound_is_50_to_100_titles(rows) -> None:
    """The committed benchmark holds 50-100 titles (R3.1)."""
    assert 50 <= len(rows) <= 100


def test_every_stratum_is_represented(rows) -> None:
    """All five content strata appear in the benchmark (R3.1)."""
    strata = {row["stratum"] for row in rows}
    assert strata == set(gen.STRATA)


def test_row_count_matches_metadata(rows, metadata) -> None:
    """The metadata row_count agrees with the actual number of rows."""
    assert metadata["row_count"] == len(rows)


def test_title_ids_are_stable_and_unique(rows) -> None:
    """Each row carries a stable, unique title id (R3.2)."""
    ids = [row["title_id"] for row in rows]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(ids) == len(set(ids))


REQUIRED_ROW_KEYS = {
    "title_id",
    "features",
    "expected_drivers",
    "expected_guardrails",
    "expected_recommendation",
    "label_type",
    "release_year",
    "split",
    "provenance",
}


def test_each_row_has_the_required_schema(rows) -> None:
    """Every row carries the full documented schema (R3.2)."""
    for row in rows:
        missing = REQUIRED_ROW_KEYS - set(row)
        assert not missing, f"{row.get('title_id')} missing keys: {missing}"


def test_each_row_carries_the_full_feature_vector(rows) -> None:
    """Every row's features cover exactly the FeatureVector input keys (R3.2)."""
    expected_keys = set(gen.FEATURE_KEYS)
    for row in rows:
        assert set(row["features"]) == expected_keys, row["title_id"]


def test_feature_keys_match_the_predictive_feature_contract() -> None:
    """The dataset's feature keys match the pure model's predictor contract.

    ``release_year`` is split-only and must NOT appear as a feature key, matching
    ``features.PREDICTIVE_FEATURES`` which deliberately omits it.
    """
    assert set(gen.FEATURE_KEYS) == set(PREDICTIVE_FEATURES)
    assert "release_year" not in gen.FEATURE_KEYS


def test_features_are_consumable_by_derive_features(rows) -> None:
    """Each row's features derive a FeatureVector without raising (R2.1, R3.2).

    The dataset is the shared feature contract: feeding a row's features into the
    pure ``derive_features`` must succeed and never fall back to defaults for a
    key the row actually provides.
    """
    for row in rows:
        vector = derive_features(row["features"])
        # A row provides every predictive feature, so nothing should be assumed.
        assert vector.assumed_features == (), row["title_id"]


def test_each_row_has_an_expected_value_for_every_driver(rows) -> None:
    """Every row carries an expected value for all four modeled drivers (R3.2)."""
    expected = set(gen.DRIVER_KEYS)
    for row in rows:
        assert set(row["expected_drivers"]) == expected, row["title_id"]
        for key in expected:
            assert row["expected_drivers"][key] not in (None, ""), row["title_id"]


def test_each_row_has_a_per_guardrail_outcome(rows) -> None:
    """Every row records a boolean outcome for each of the four guardrails (R3.2)."""
    expected = set(gen.GUARDRAILS)
    for row in rows:
        assert set(row["expected_guardrails"]) == expected, row["title_id"]
        for value in row["expected_guardrails"].values():
            assert isinstance(value, bool), row["title_id"]


def test_each_row_has_a_valid_recommendation(rows) -> None:
    """Every row carries a recommendation from the engine vocabulary (R3.2)."""
    valid = {gen.GREENLIGHT, gen.NEGOTIATE_HARD, gen.PASS}
    for row in rows:
        assert row["expected_recommendation"] in valid, row["title_id"]


def test_recommendation_is_consistent_with_guardrail_outcomes(rows) -> None:
    """A row's recommendation follows from its own per-guardrail outcomes (R3.2).

    A non-correctable churn breach is a hard PASS; any other breach downgrades to
    NEGOTIATE_HARD; all-pass is a GREENLIGHT.
    """
    for row in rows:
        derived = gen._recommendation_from_guardrails(row["expected_guardrails"])
        assert derived == row["expected_recommendation"], row["title_id"]


def test_csv_and_json_describe_the_same_rows(rows) -> None:
    """The CSV and JSON artifacts carry the same title ids in the same order."""
    csv_lines = CSV_PATH.read_text(encoding="utf-8").strip().splitlines()
    header = csv_lines[0].split(",")
    id_index = header.index("title_id")
    csv_ids = [line.split(",")[id_index] for line in csv_lines[1:]]
    assert csv_ids == [row["title_id"] for row in rows]


# ---------------------------------------------------------------------------
# Temporal non-leakage (Property 11, R3.3).
# ---------------------------------------------------------------------------


def test_metadata_records_the_temporal_cutoff(metadata) -> None:
    """The release-year cutoff is recorded in the dataset metadata (R3.3)."""
    assert metadata["temporal_cutoff_year"] == gen.TEMPORAL_CUTOFF_YEAR
    assert "k-fold" not in metadata["split_rule"] or "no random k-fold" in metadata[
        "split_rule"
    ]


def test_sidecar_metadata_matches_embedded_metadata(metadata) -> None:
    """DATASET_META.json is byte-consistent with the embedded metadata block (R3.5)."""
    sidecar = json.loads(META_PATH.read_text(encoding="utf-8"))
    assert sidecar == metadata


def test_no_test_row_is_on_or_before_cutoff(rows) -> None:
    """# Property 11: no held-out (test) row has release_year <= cutoff (R3.3).

    This is the temporal non-leakage invariant: the fit reads only training-split
    rows, so no title at or before the cutoff may appear in the held-out split.
    """
    cutoff = gen.TEMPORAL_CUTOFF_YEAR
    leaks = [
        row["title_id"]
        for row in rows
        if row["split"] == "test" and row["release_year"] is not None
        and int(row["release_year"]) <= cutoff
    ]
    assert not leaks, f"test rows leaking at/before cutoff {cutoff}: {leaks}"


def test_every_train_row_is_on_or_before_cutoff(rows) -> None:
    """A train row is dated on/before the cutoff (R3.3).

    A row with a known release year is partitioned strictly by the cutoff; only a
    row with no recorded year may be conservatively assigned to the train split.
    """
    cutoff = gen.TEMPORAL_CUTOFF_YEAR
    for row in rows:
        if row["split"] != "train":
            continue
        year = row["release_year"]
        assert year is None or int(year) <= cutoff, row["title_id"]


def test_both_splits_are_non_trivial(rows, metadata) -> None:
    """Both the train and held-out test splits are meaningfully populated (R3.3)."""
    split_counts = metadata["split_counts"]
    assert split_counts.get("train", 0) > 0
    assert split_counts.get("test", 0) > 1  # not a trivial 0-1 held-out rows
    actual = {"train": 0, "test": 0}
    for row in rows:
        actual[row["split"]] += 1
    assert actual == {k: split_counts[k] for k in actual}


# ---------------------------------------------------------------------------
# The five seeded demo titles are present with their verdicts pinned (R3.4).
# ---------------------------------------------------------------------------

PINNED_DEMO_VERDICTS = {
    "demo-aurora-protocol": "GREENLIGHT",
    "demo-echoes-of-2019": "GREENLIGHT",
    "demo-monsoon-lanes": "GREENLIGHT",
    "demo-the-ledger": "NEGOTIATE_HARD",
    "demo-vintage-reruns-vol-7": "PASS",
}


def test_all_five_demo_titles_are_present(rows) -> None:
    """The five seeded demo titles are included in the benchmark (R3.4)."""
    ids = {row["title_id"] for row in rows}
    assert set(PINNED_DEMO_VERDICTS).issubset(ids)


def test_demo_titles_have_pinned_verdicts(rows) -> None:
    """Each demo title's expected recommendation is pinned to the seeded demo (R3.4)."""
    by_id = {row["title_id"]: row for row in rows}
    for title_id, verdict in PINNED_DEMO_VERDICTS.items():
        assert by_id[title_id]["expected_recommendation"] == verdict, title_id


def test_demo_title_names_are_the_seeded_ones(rows) -> None:
    """The demo titles keep their recognizable seeded names."""
    by_id = {row["title_id"]: row for row in rows}
    assert by_id["demo-aurora-protocol"]["title_name"] == "Aurora Protocol"
    assert by_id["demo-echoes-of-2019"]["title_name"] == "Echoes of 2019"
    assert by_id["demo-monsoon-lanes"]["title_name"] == "Monsoon Lanes"
    assert by_id["demo-the-ledger"]["title_name"] == "The Ledger"
    assert by_id["demo-vintage-reruns-vol-7"]["title_name"] == "Vintage Reruns Vol. 7"


# ---------------------------------------------------------------------------
# Honest labeling: every row carries a Label_Type, none overstates OBSERVED
# (R2.6, R3.6).
# ---------------------------------------------------------------------------

VALID_LABEL_TYPES = {"PROXY", "SYNTHETIC"}


def test_every_row_has_a_label_type(rows) -> None:
    """Every row carries a Label_Type (R3.2)."""
    for row in rows:
        assert row["label_type"] in VALID_LABEL_TYPES, row["title_id"]


def test_no_row_is_labeled_observed(rows) -> None:
    """No row claims an OBSERVED (real realized) outcome (R2.6, R3.6).

    The dataset is proxy/synthetic only; labeling a row OBSERVED would overstate
    real-world accuracy, which the honesty posture forbids.
    """
    for row in rows:
        assert row["label_type"] != gen.LABEL_OBSERVED, row["title_id"]


def test_demo_rows_are_proxy(rows) -> None:
    """The five demo rows are PROXY (open-data-correlate backed), never OBSERVED."""
    by_id = {row["title_id"]: row for row in rows}
    for title_id in PINNED_DEMO_VERDICTS:
        assert by_id[title_id]["label_type"] == gen.LABEL_PROXY, title_id


def test_dominant_label_type_is_recorded_and_honest(metadata, rows) -> None:
    """The metadata records the dominant Label_Type and it is the actual majority (R3.5)."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["label_type"]] = counts.get(row["label_type"], 0) + 1
    dominant = max(counts, key=counts.get)
    assert metadata["dominant_label_type"] == dominant
    assert metadata["label_type_counts"] == dict(sorted(counts.items()))


def test_metadata_records_sources_with_license_and_imdb_flagged(metadata) -> None:
    """The metadata embeds each source's license; IMDb is flagged non-commercial (R2.2)."""
    sources = {s["name"]: s for s in metadata["sources"]}
    assert sources  # at least one source recorded
    for source in sources.values():
        assert source["license"]
        assert source["url"]
        assert source["access_date"]
    imdb = sources["IMDb-NonCommercial"]
    assert imdb["noncommercial"] is True


def test_provenance_doc_flags_imdb_non_commercial() -> None:
    """The committed PROVENANCE.md flags IMDb as non-commercial (R2.2)."""
    text = PROVENANCE_PATH.read_text(encoding="utf-8")
    assert "IMDb" in text
    assert "non-commercial" in text.lower()
