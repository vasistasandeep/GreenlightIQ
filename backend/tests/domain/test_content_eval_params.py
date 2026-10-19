"""Tests for the Content_Eval params parser (content-eval-model, task 11).

# Feature: content-eval-model

Targets the pure :mod:`app.domain.content_eval` module: the top-level
``parse_content_eval_params`` composing the per-driver parsers into a single
validated :class:`ContentEvalParams` object that carries the overall ``source``
tag and each nested block's source, with the churn-style full-fallback contract
(never raises; invalid/missing -> defaults). Also a focused fork-forward test
asserting that a ``dict(active.guardrail_params)`` copy (the exact shape
``app.engines.calibration`` uses when forking a new immutable version) carries a
``content_eval`` sub-object forward unchanged.

All tests import only the pure domain modules -- no database, no app framework.
Validates: Requirements 5.1, 5.3.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import engagement as engmod
from app.domain import viewing_hours as vhmod
from app.domain.content_eval import (
    DEFAULT_CONTENT_EVAL_PARAMS,
    DEFAULT_DOMINANT_LABEL_TYPE,
    DEFAULT_LINK_CHURN_TO_LTV,
    DEFAULT_VERSION_LABEL,
    ContentEvalParams,
    parse_content_eval_params,
)


# ---------------------------------------------------------------------------
# Fixtures: a fully-valid content_eval block
# ---------------------------------------------------------------------------


def _valid_viewing_hours() -> dict:
    return {
        "intercept": "7.5",
        "betas": {
            "runtime_minutes": "0.003",
            "normalized_rating": "0.5",
            "franchise_flag": "0.3",
        },
        "floor": "2",
        "objective": "wape_log",
    }


def _valid_watch_time_elasticity() -> dict:
    return {
        "intercept": "0.9",
        "runtime_weight": "0.08",
        "serialization_lift": "0.12",
        "rating_weight": "0.25",
        "franchise_lift": "0.10",
        "min_value": "0.00",
        "max_value": "3.00",
    }


def _valid_ad_load_receptivity() -> dict:
    return {
        "centre": "1.00",
        "rating_weight": "0.08",
        "runtime_weight": "0.04",
        "franchise_lift": "0.02",
        "min_value": "0.50",
        "max_value": "1.50",
    }


def _valid_block(**overrides) -> dict:
    block = {
        "version_label": "ce-v3",
        "fit_dataset_version": "kpi-2024-06",
        "dominant_label_type": "OBSERVED",
        "link_churn_to_ltv": True,
        "viewing_hours": _valid_viewing_hours(),
        "engagement": {
            "watch_time_elasticity": _valid_watch_time_elasticity(),
            "ad_load_receptivity": _valid_ad_load_receptivity(),
        },
    }
    block.update(overrides)
    return block


# ---------------------------------------------------------------------------
# Valid parse -> MODEL_VERSION with nested blocks populated
# ---------------------------------------------------------------------------


def test_valid_parse_is_model_version_with_nested_blocks():
    params = parse_content_eval_params(_valid_block())

    assert isinstance(params, ContentEvalParams)
    assert params.source == "MODEL_VERSION"

    # Provenance / honesty fields read from the block.
    assert params.version_label == "ce-v3"
    assert params.fit_dataset_version == "kpi-2024-06"
    assert params.dominant_label_type == "OBSERVED"
    assert params.link_churn_to_ltv is True

    # Nested blocks parsed to MODEL_VERSION (not the illustrative defaults).
    assert params.viewing_hours_source == "MODEL_VERSION"
    assert params.watch_time_elasticity_source == "MODEL_VERSION"
    assert params.ad_load_receptivity_source == "MODEL_VERSION"

    assert isinstance(params.viewing_hours, vhmod.ViewingHoursParams)
    assert params.viewing_hours.intercept == Decimal("7.5")
    assert params.viewing_hours.floor == Decimal("2")
    assert params.viewing_hours.betas["normalized_rating"] == Decimal("0.5")

    assert isinstance(
        params.watch_time_elasticity, engmod.WatchTimeElasticityParams
    )
    assert params.watch_time_elasticity.intercept == Decimal("0.9")
    assert params.watch_time_elasticity.rating_weight == Decimal("0.25")

    assert isinstance(params.ad_load_receptivity, engmod.AdLoadReceptivityParams)
    assert params.ad_load_receptivity.centre == Decimal("1.00")
    assert params.ad_load_receptivity.rating_weight == Decimal("0.08")


# ---------------------------------------------------------------------------
# Invalid / missing / partial -> DEFAULTS (with sub-model defaults)
# ---------------------------------------------------------------------------


def test_none_input_is_defaults():
    params = parse_content_eval_params(None)
    assert params is DEFAULT_CONTENT_EVAL_PARAMS
    assert params.source == "DEFAULTS"
    assert params.viewing_hours_source == "DEFAULTS"
    assert params.watch_time_elasticity_source == "DEFAULTS"
    assert params.ad_load_receptivity_source == "DEFAULTS"
    assert params.version_label == DEFAULT_VERSION_LABEL
    assert params.fit_dataset_version is None
    assert params.dominant_label_type == DEFAULT_DOMINANT_LABEL_TYPE
    assert params.link_churn_to_ltv is DEFAULT_LINK_CHURN_TO_LTV


def test_non_mapping_input_is_defaults():
    for bad in ("not-a-mapping", 42, [1, 2, 3], object()):
        params = parse_content_eval_params(bad)  # type: ignore[arg-type]
        assert params is DEFAULT_CONTENT_EVAL_PARAMS
        assert params.source == "DEFAULTS"


def test_empty_mapping_is_model_version_with_all_sub_defaults():
    # An empty (but present) block is a usable mapping: overall source
    # MODEL_VERSION, but every nested slice and provenance field falls back to its
    # default (nested source DEFAULTS).
    params = parse_content_eval_params({})
    assert params.source == "MODEL_VERSION"
    assert params.version_label == DEFAULT_VERSION_LABEL
    assert params.fit_dataset_version is None
    assert params.dominant_label_type == DEFAULT_DOMINANT_LABEL_TYPE
    assert params.link_churn_to_ltv is False
    assert params.viewing_hours is vhmod.DEFAULT_VIEWING_HOURS_PARAMS
    assert (
        params.watch_time_elasticity
        is engmod.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert (
        params.ad_load_receptivity
        is engmod.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )
    assert params.viewing_hours_source == "DEFAULTS"
    assert params.watch_time_elasticity_source == "DEFAULTS"
    assert params.ad_load_receptivity_source == "DEFAULTS"


def test_partial_block_valid_slice_honored_invalid_slice_defaults():
    # viewing_hours valid; engagement malformed (negative weight) -> that nested
    # slice falls back to defaults while viewing_hours is honored.
    bad_wte = _valid_watch_time_elasticity()
    bad_wte["rating_weight"] = "-1"  # invalid: negative
    block = _valid_block(
        engagement={
            "watch_time_elasticity": bad_wte,
            "ad_load_receptivity": _valid_ad_load_receptivity(),
        }
    )
    params = parse_content_eval_params(block)

    assert params.source == "MODEL_VERSION"
    # Valid viewing_hours slice honored.
    assert params.viewing_hours_source == "MODEL_VERSION"
    assert params.viewing_hours.intercept == Decimal("7.5")
    # Malformed WTE slice collapsed to its own defaults.
    assert params.watch_time_elasticity_source == "DEFAULTS"
    assert (
        params.watch_time_elasticity
        is engmod.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    # ALR slice still honored.
    assert params.ad_load_receptivity_source == "MODEL_VERSION"
    assert params.ad_load_receptivity.centre == Decimal("1.00")


def test_malformed_nested_types_fall_back_without_raising():
    # Nested blocks that are not mappings are tolerated (fall back to defaults).
    block = {
        "version_label": "ce-weird",
        "viewing_hours": "not-a-mapping",
        "engagement": "also-not-a-mapping",
    }
    params = parse_content_eval_params(block)
    assert params.source == "MODEL_VERSION"
    assert params.version_label == "ce-weird"
    assert params.viewing_hours is vhmod.DEFAULT_VIEWING_HOURS_PARAMS
    assert params.viewing_hours_source == "DEFAULTS"
    assert (
        params.watch_time_elasticity
        is engmod.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS
    )
    assert (
        params.ad_load_receptivity
        is engmod.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS
    )


# ---------------------------------------------------------------------------
# link_churn_to_ltv: defaults false, round-trips true
# ---------------------------------------------------------------------------


def test_link_churn_to_ltv_defaults_false_when_absent():
    params = parse_content_eval_params({"version_label": "x"})
    assert params.link_churn_to_ltv is False


def test_link_churn_to_ltv_round_trips_true():
    params = parse_content_eval_params({"link_churn_to_ltv": True})
    assert params.link_churn_to_ltv is True


def test_link_churn_to_ltv_accepts_jsonish_encodings():
    # JSONB may serialize a bool as a string or int; both must parse.
    for truthy in (True, "true", "True", "1", 1, "yes", "on"):
        params = parse_content_eval_params({"link_churn_to_ltv": truthy})
        assert params.link_churn_to_ltv is True, truthy
    for falsey in (False, "false", "0", 0, "no", "off"):
        params = parse_content_eval_params({"link_churn_to_ltv": falsey})
        assert params.link_churn_to_ltv is False, falsey


def test_link_churn_to_ltv_ambiguous_defaults_false():
    params = parse_content_eval_params({"link_churn_to_ltv": "maybe"})
    assert params.link_churn_to_ltv is False


# ---------------------------------------------------------------------------
# Unknown keys ignored
# ---------------------------------------------------------------------------


def test_unknown_keys_are_ignored():
    block = _valid_block(unknown_future_key="ignored", another={"nested": 1})
    params = parse_content_eval_params(block)
    assert params.source == "MODEL_VERSION"
    # Recognized fields still parse exactly as without the unknown keys.
    assert params.version_label == "ce-v3"
    assert params.link_churn_to_ltv is True
    assert params.viewing_hours.intercept == Decimal("7.5")


# ---------------------------------------------------------------------------
# fit_dataset_version is optional (None) and trims
# ---------------------------------------------------------------------------


def test_fit_dataset_version_optional_none_when_blank_or_absent():
    for raw in ({}, {"fit_dataset_version": ""}, {"fit_dataset_version": "   "}):
        params = parse_content_eval_params(raw)
        assert params.fit_dataset_version is None


# ---------------------------------------------------------------------------
# Fork-forward: calibration copies guardrail_params via dict(...), carrying
# content_eval forward unchanged (mirrors app.engines.calibration).
# ---------------------------------------------------------------------------


def test_fork_forward_carries_content_eval_unchanged():
    # A fake "active" guardrail_params dict with a content_eval sub-object, in the
    # shape calibration.py forks: create_version(guardrail_params=dict(active...)).
    content_eval_block = _valid_block()
    active_guardrail_params = {
        "churn_model": {"intercept": "0.03"},
        "content_eval": content_eval_block,
        "some_other_guardrail": {"k": "v"},
    }

    # The exact operation calibration.Calibration_Controller performs on fork.
    forked = dict(active_guardrail_params)

    # content_eval is present and byte-identical in the forked copy.
    assert "content_eval" in forked
    assert forked["content_eval"] == content_eval_block

    # And it parses identically before and after the fork.
    before = parse_content_eval_params(active_guardrail_params["content_eval"])
    after = parse_content_eval_params(forked["content_eval"])
    assert before.source == after.source == "MODEL_VERSION"
    assert before == after


def test_fork_forward_preserves_defaults_when_content_eval_absent():
    # A version with no content_eval block forks forward with none added; the
    # reader then falls back to DEFAULTS cleanly (demo-invariant path).
    active_guardrail_params = {"churn_model": {"intercept": "0.03"}}
    forked = dict(active_guardrail_params)
    assert "content_eval" not in forked

    params = parse_content_eval_params(forked.get("content_eval"))
    assert params.source == "DEFAULTS"
    assert params is DEFAULT_CONTENT_EVAL_PARAMS
