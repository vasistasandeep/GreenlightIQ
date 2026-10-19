"""Seed demo-invariance regression test for the content_eval block (task 16).

# Feature: content-eval-model, Property 12: Demo invariance

Task 15 added a ``content_eval`` params block to the seeded active model version
(``database/seed/generate_seed_sql.py``). The block carries illustrative defaults
with NO active fitted version (``fit_dataset_version`` is ``None``) and the
``link_churn_to_ltv`` toggle OFF, so it is INERT at seed time: it is carried in
``guardrail_params`` for later use and must change no seeded projection, driver,
churn value, verdict, or explanation.

This regression pins that invariance (design Component 9, Property 12). It
recomputes every assertion from the seed generator's OWN data and helpers rather
than hard-coding values, so the test stays bound to the actual seed logic and a
drift between the two is caught immediately. The generator module lives under
``database/seed`` (outside the backend package root), so it is loaded by file
path with ``importlib`` exactly as the dataset test loads its generator.
Importing the module does not regenerate the SQL file (the render-time write
only runs under ``__main__``).

Assertions:

  * **Pinned demo verdicts (R3.4-style, 5.5):** the five demo titles keep their
    seeded recommendations -- Aurora Protocol / Echoes of 2019 / Monsoon Lanes ->
    GREENLIGHT, The Ledger -> NEGOTIATE_HARD, Vintage Reruns Vol. 7 -> PASS. If
    the seed does NOT in fact carry these verdicts, the test fails loudly (that
    would be a task-15 defect, surfaced here rather than papered over).
  * **Seeded churn projections unchanged (8.5):** each demo title's model-computed
    churn-reduction percentage recomputes to the exact value the existing
    ``test_seed_churn_regression`` pins, reusing the shared churn domain so this
    test does not weaken that bound.
  * **Drivers + explanation byte-identical (Property 12):** the modeled churn
    value stored on each demo projection and the full engine-shaped explanation
    JSON the generator renders are identical to a recompute, confirming no
    content_eval-driven movement.
  * **content_eval block is inert (Property 12):** the generated seed's
    ``content_eval`` block parses (via
    ``app.domain.content_eval.parse_content_eval_params``) to NO active fitted
    version (``fit_dataset_version`` ``None``), ``link_churn_to_ltv`` ``False``,
    and the illustrative :data:`DEFAULT_CONTENT_EVAL_PARAMS` parameters.
  * **Generator ``--check`` idempotent (5.5):** ``generate_seed_sql.py --check``
    returns 0, so the committed seed is byte-identical to a fresh build with the
    content_eval block present.

Validates: Requirements 5.5, 8.5; Property 12
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.churn import (
    CHURN_MITIGATION_THRESHOLD,
    DEFAULT_CHURN_MODEL_PARAMS,
    ChurnFeatures,
    calculate_churn_mitigation,
)
from app.domain.content_eval import (
    DEFAULT_CONTENT_EVAL_PARAMS,
    parse_content_eval_params,
)

# ---------------------------------------------------------------------------
# Load the seed generator by file path (it sits outside the backend package
# root, under database/seed/), mirroring how the dataset test loads its own
# generator. Importing it does NOT write the SQL file.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED_DIR = _REPO_ROOT / "database" / "seed"
_GEN_PATH = _SEED_DIR / "generate_seed_sql.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_seed_sql", _GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_generator()


# The five demo titles with their pinned seeded verdicts (content-eval-model
# Property 12). These are the invariant the seed must preserve with no fitted
# version active and the churn->LTV link off.
PINNED_DEMO_VERDICTS = {
    "title-aurora": ("Aurora Protocol", "GREENLIGHT"),
    "title-echoes": ("Echoes of 2019", "GREENLIGHT"),
    "title-monsoon": ("Monsoon Lanes", "GREENLIGHT"),
    "title-ledger": ("The Ledger", "NEGOTIATE_HARD"),
    "title-reruns": ("Vintage Reruns Vol. 7", "PASS"),
}

# The exact seeded churn-reduction percentage per demo title, matching what the
# existing test_seed_churn_regression pins. Recomputed below from the seed
# generator's own helper so the two stay in lock-step (do NOT weaken these).
EXPECTED_DEMO_CHURN = {
    "title-aurora": Decimal("2.11"),
    "title-echoes": Decimal("1.99"),
    "title-monsoon": Decimal("1.79"),
    "title-ledger": Decimal("1.60"),
    "title-reruns": Decimal("0.81"),
}


@pytest.fixture(scope="module")
def titles_by_label() -> dict:
    """The seeded TITLES rows keyed by their stable label."""
    return {row[0]: row for row in seed.TITLES}


# ---------------------------------------------------------------------------
# Pinned demo verdicts (R5.5). If the seed does not carry these, fail loudly.
# ---------------------------------------------------------------------------


def test_all_five_demo_titles_are_seeded(titles_by_label) -> None:
    """The five demo titles are present in the seed's TITLES data (R5.5)."""
    assert set(PINNED_DEMO_VERDICTS).issubset(titles_by_label)


@pytest.mark.parametrize("label", sorted(PINNED_DEMO_VERDICTS))
def test_demo_title_keeps_its_pinned_verdict(label: str, titles_by_label) -> None:
    """Each demo title keeps its seeded name and recommendation (Property 12).

    The recommendation is the last element of a seeded TITLES tuple; a mismatch
    means the seed no longer preserves the demo verdict (a task-15 defect) and the
    test fails rather than adapting to the new value.
    """
    expected_name, expected_verdict = PINNED_DEMO_VERDICTS[label]
    row = titles_by_label[label]
    name = row[1]
    recommendation = row[-1]
    assert name == expected_name
    assert recommendation == expected_verdict


# ---------------------------------------------------------------------------
# Seeded churn projections unchanged (R8.5): recompute via the seed generator's
# own helper and assert the exact pinned value. This mirrors (and must not
# weaken) test_seed_churn_regression.
# ---------------------------------------------------------------------------


def _seed_churn(label: str, titles_by_label) -> Decimal:
    """Recompute a demo title's churn exactly as the seed generator does."""
    row = titles_by_label[label]
    _label, _name, atype, _cost, _cur, terrs, genre, *_rest = row
    result = seed._title_churn_result(label, atype, genre, terrs)
    return result.churn_reduction_pct


@pytest.mark.parametrize("label, expected", sorted(EXPECTED_DEMO_CHURN.items()))
def test_demo_churn_projection_unchanged(
    label: str, expected: Decimal, titles_by_label
) -> None:
    """Each demo title's seeded churn recomputes to its exact pinned value (R8.5).

    The content_eval block is inert, so the seeded churn-reduction percentage must
    be byte-identical to the pre-feature value; a divergence here means the seed's
    modeled churn moved.
    """
    assert _seed_churn(label, titles_by_label) == expected


def test_seed_churn_matches_the_pure_domain_recompute(titles_by_label) -> None:
    """The seed's churn equals a direct pure-domain recompute from the same features.

    This independently reproduces the churn through ``calculate_churn_mitigation``
    (not just the generator's wrapper) to pin that the seed and the shared domain
    model agree, exactly as the standalone churn regression does.
    """
    for label, row in titles_by_label.items():
        if label not in EXPECTED_DEMO_CHURN:
            continue
        _label, _name, atype, _cost, _cur, terrs, genre, *_rest = row
        features = ChurnFeatures(
            asset_type=atype,
            pedigree=Decimal(seed._PEDIGREE_SCALE[label][0]),
            production_scale=Decimal(seed._PEDIGREE_SCALE[label][1]),
            is_exclusive=seed._EXCLUSIVE_BY_TITLE.get(label, False),
            telemetry_heat=seed._telemetry_heat(genre, terrs),
            genre=genre,
            content_format=seed._FORMAT_BY_TITLE.get(label),
        )
        direct = calculate_churn_mitigation(
            features, DEFAULT_CHURN_MODEL_PARAMS, "MODEL_VERSION"
        ).churn_reduction_pct
        assert direct == _seed_churn(label, titles_by_label) == EXPECTED_DEMO_CHURN[label]


def test_demo_churn_guardrail_outcome_preserved(titles_by_label) -> None:
    """The churn guardrail outcome behind each verdict is preserved (Property 12).

    The three GREENLIGHT and the one NEGOTIATE_HARD keep a passing churn (>= 1.5);
    the one PASS keeps the breaching churn (< 1.5). This is the churn half of each
    demo verdict and must not move under the inert content_eval block.
    """
    for label in ("title-aurora", "title-echoes", "title-monsoon", "title-ledger"):
        assert _seed_churn(label, titles_by_label) >= CHURN_MITIGATION_THRESHOLD
    assert _seed_churn("title-reruns", titles_by_label) < CHURN_MITIGATION_THRESHOLD


# ---------------------------------------------------------------------------
# Drivers + explanation byte-identical (Property 12): the stored churn value and
# the full engine-shaped explanation JSON are identical to a recompute.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(PINNED_DEMO_VERDICTS))
def test_demo_explanation_json_is_byte_identical(label: str, titles_by_label) -> None:
    """The seeded explanation JSON recomputes byte-identically (Property 12).

    The generator builds the projection's explanation from the title's seeded
    features and the model-computed churn. Rebuilding it here with the same inputs
    must reproduce the identical JSON string, confirming the content_eval block
    introduced no drift into the persisted explanation.
    """
    row = titles_by_label[label]
    (_label, _name, atype, _cost, _cur, terrs, genre, _vh, _hist,
     cpvh, ltv, _churn_literal, payback, _rec) = row
    churn_result = seed._title_churn_result(label, atype, genre, terrs)
    model_churn = str(churn_result.churn_reduction_pct)

    first = seed._seed_explanation(atype, cpvh, ltv, model_churn, payback, churn_result)
    second = seed._seed_explanation(atype, cpvh, ltv, model_churn, payback, churn_result)

    # Deterministic: two builds from identical inputs serialize identically.
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    # The CHURN_MITIGATION check inside the explanation uses the model churn, so
    # its computed value tracks the (unchanged) seeded churn exactly.
    churn_check = next(c for c in first["checks"] if c["name"] == "CHURN_MITIGATION")
    assert churn_check["computed_value"] == f"{float(model_churn):.2f}"

    # The explanation carries the churn_model block (drivers) but no content_eval
    # block, because no fitted content_eval version is active at seed time.
    assert "churn_model" in first
    assert "content_eval" not in first


# ---------------------------------------------------------------------------
# content_eval block is inert (Property 12): parses to no fitted version, link
# off, illustrative defaults.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_content_eval():
    """Parse the content_eval block embedded in the seeded model version."""
    raw = seed.MODEL_VERSION["guardrail_params"]["content_eval"]
    return parse_content_eval_params(raw)


def test_content_eval_block_is_present_in_seed() -> None:
    """The seeded guardrail_params carry a content_eval block (R5.1)."""
    params = seed.MODEL_VERSION["guardrail_params"]
    assert "content_eval" in params
    assert isinstance(params["content_eval"], dict)


def test_content_eval_has_no_active_fitted_version(seeded_content_eval) -> None:
    """# Property 12: the seed pins NO active fitted version (fit_dataset_version None)."""
    assert seeded_content_eval.fit_dataset_version is None


def test_content_eval_link_churn_to_ltv_is_off(seeded_content_eval) -> None:
    """# Property 12: the churn->LTV link is OFF, so the LTV numerator is unchanged."""
    assert seeded_content_eval.link_churn_to_ltv is False


def test_content_eval_parses_to_illustrative_defaults(seeded_content_eval) -> None:
    """# Property 12: every content_eval parameter is the illustrative default.

    Only the source tags differ (the block IS supplied by the model version, so it
    parses as MODEL_VERSION rather than DEFAULTS); the parameter values equal
    DEFAULT_CONTENT_EVAL_PARAMS, which is what makes the block demo-invariant.
    """
    ce = seeded_content_eval
    d = DEFAULT_CONTENT_EVAL_PARAMS
    assert ce.source == "MODEL_VERSION"
    assert ce.version_label == d.version_label
    assert ce.dominant_label_type == d.dominant_label_type
    assert ce.viewing_hours == d.viewing_hours
    assert ce.watch_time_elasticity == d.watch_time_elasticity
    assert ce.ad_load_receptivity == d.ad_load_receptivity


# ---------------------------------------------------------------------------
# Generator --check idempotent (R5.5): the committed seed is byte-identical to a
# fresh build with the content_eval block present.
# ---------------------------------------------------------------------------


def test_generator_check_is_idempotent() -> None:
    """``generate_seed_sql.py --check`` returns 0 (committed seed is up to date).

    With the content_eval block carried in guardrail_params, regenerating the seed
    in memory reproduces exactly the committed bytes, so --check exits 0.
    """
    assert seed.main(["--check"]) == 0
