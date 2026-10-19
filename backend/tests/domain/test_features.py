"""Unit tests for the pure Content_Eval feature-derivation module.

# Feature: content-eval-model

Targets :mod:`app.domain.features` (task 1). These are example-based unit tests
that pin the documented derivation behavior; the formal property tests (P5, P7,
P14) for this module are added in task 4. The tests import only the pure domain
module -- no database, no app framework.

They exercise: provenance tagging and the ``assumed`` flag, neutral (never
penalizing-zero) defaults for every absent open-data correlate (R2.4), domain
clamping (R2.1), the unknown-feature-key rule that keeps older fitted versions
unaffected (R7.2 / R9.7), and the split-only, never-predictive treatment of
``release_year``.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.features import (
    AWARD_NEUTRAL,
    FRANCHISE_NEUTRAL,
    LOG_VOTE_COUNT_NEUTRAL,
    PREDICTIVE_FEATURES,
    RATING_NEUTRAL,
    RUNTIME_NEUTRAL,
    SOURCE_DEFAULT,
    SOURCE_TITLE,
    FeatureVector,
    derive_features,
    normalize_asset_type,
    normalize_genre,
)

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def test_normalize_genre_collapses_separators() -> None:
    assert normalize_genre("Crime Biopic") == "crime-biopic"
    assert normalize_genre("crime_biopic") == "crime-biopic"
    assert normalize_genre("crime-biopic") == "crime-biopic"
    assert normalize_genre("  ") is None
    assert normalize_genre(None) is None


def test_normalize_asset_type_upper_snake() -> None:
    assert normalize_asset_type("original series") == "ORIGINAL_SERIES"
    assert normalize_asset_type("Original-Film") == "ORIGINAL_FILM"
    assert normalize_asset_type("ORIGINAL_SERIES") == "ORIGINAL_SERIES"
    assert normalize_asset_type("") is None
    assert normalize_asset_type(None) is None


# ---------------------------------------------------------------------------
# Empty / None raw -> all-defaults, every correlate assumed and non-penalizing
# ---------------------------------------------------------------------------


def test_none_raw_yields_all_defaults_vector() -> None:
    fv = derive_features(None)
    assert isinstance(fv, FeatureVector)

    # Open-data correlates fall back to their NEUTRAL defaults (never a
    # penalizing zero) and are flagged assumed with the DEFAULTS source.
    assert fv.normalized_rating.value == RATING_NEUTRAL
    assert fv.normalized_rating.value != Decimal("0")
    assert fv.normalized_rating.assumed is True
    assert fv.normalized_rating.source == SOURCE_DEFAULT

    assert fv.log_vote_count.value == LOG_VOTE_COUNT_NEUTRAL
    assert fv.log_vote_count.value != Decimal("0")
    assert fv.log_vote_count.assumed is True

    assert fv.award_signal.value == AWARD_NEUTRAL
    assert fv.award_signal.value != Decimal("0")
    assert fv.award_signal.assumed is True

    # Franchise flag's neutral default is 0 (standalone), but still assumed.
    assert fv.franchise_flag.value == FRANCHISE_NEUTRAL
    assert fv.franchise_flag.assumed is True

    # Every correlate shows up in the convenience assumed tuple.
    for name in (
        "normalized_rating",
        "log_vote_count",
        "franchise_flag",
        "award_signal",
    ):
        assert name in fv.assumed_features


def test_empty_mapping_matches_none_raw() -> None:
    assert derive_features({}) == derive_features(None)


# ---------------------------------------------------------------------------
# Present values are tagged TITLE and not assumed
# ---------------------------------------------------------------------------


def test_present_values_tagged_title() -> None:
    fv = derive_features(
        {
            "asset_type": "Original Series",
            "genre": "Crime Drama",
            "content_format": "Limited Series",
            "runtime_minutes": 52,
            "is_exclusive": True,
            "production_scale": "7.5",
            "talent_pedigree": 8,
            "normalized_rating": "0.82",
            "log_vote_count": "9.1",
            "franchise_flag": 1,
            "award_signal": "0.4",
            "release_year": 2021,
        }
    )

    assert fv.asset_type.value == "ORIGINAL_SERIES"
    assert fv.asset_type.source == SOURCE_TITLE
    assert fv.asset_type.assumed is False

    assert fv.genre.value == "crime-drama"
    assert fv.content_format.value == "limited-series"
    assert fv.runtime_minutes.value == Decimal("52")
    assert fv.is_exclusive.value is True
    assert fv.production_scale.value == Decimal("7.5")
    assert fv.talent_pedigree.value == Decimal("8")
    assert fv.normalized_rating.value == Decimal("0.82")
    assert fv.log_vote_count.value == Decimal("9.1")
    assert fv.franchise_flag.value == Decimal("1")
    assert fv.award_signal.value == Decimal("0.4")

    # Nothing assumed when every field was supplied.
    assert fv.assumed_features == ()


# ---------------------------------------------------------------------------
# Domain clamping (R2.1 / Property 5)
# ---------------------------------------------------------------------------


def test_numeric_features_clamped_to_domain() -> None:
    fv = derive_features(
        {
            "normalized_rating": "1.7",  # above [0, 1] -> clamp to 1
            "award_signal": "-0.5",  # below [0, 1] -> clamp to 0
            "production_scale": "99",  # above [0, 10] -> clamp to 10
            "talent_pedigree": "-3",  # below [0, 10] -> clamp to 0
            "log_vote_count": "-2",  # below floor 0 -> clamp to 0
            "runtime_minutes": "-10",  # below floor 0 -> clamp to 0
        }
    )
    assert fv.normalized_rating.value == Decimal("1")
    assert fv.award_signal.value == Decimal("0")
    assert fv.production_scale.value == Decimal("10")
    assert fv.talent_pedigree.value == Decimal("0")
    assert fv.log_vote_count.value == Decimal("0")
    assert fv.runtime_minutes.value == Decimal("0")


# ---------------------------------------------------------------------------
# Invalid numerics degrade to neutral default (never raise, never penalize)
# ---------------------------------------------------------------------------


def test_invalid_numeric_falls_back_to_neutral_default() -> None:
    fv = derive_features(
        {
            "normalized_rating": "not-a-number",
            "runtime_minutes": None,
            "award_signal": "",
        }
    )
    assert fv.normalized_rating.value == RATING_NEUTRAL
    assert fv.normalized_rating.assumed is True
    assert fv.runtime_minutes.value == RUNTIME_NEUTRAL
    assert fv.runtime_minutes.assumed is True
    assert fv.award_signal.value == AWARD_NEUTRAL
    assert fv.award_signal.assumed is True


# ---------------------------------------------------------------------------
# Unknown keys are ignored (R7.2 / R9.7)
# ---------------------------------------------------------------------------


def test_unknown_keys_are_ignored() -> None:
    base = derive_features({"genre": "Thriller"})
    with_extra = derive_features(
        {
            "genre": "Thriller",
            "some_future_open_data_signal": "1234",
            "another_unseen_feature": {"nested": "value"},
        }
    )
    # Adding unknown keys must not change the derived vector at all.
    assert base == with_extra


def test_release_year_is_not_a_predictive_feature() -> None:
    # release_year is derivable (for the Temporal_Split) but excluded from the
    # authoritative predictor list, so no model can consume it.
    assert "release_year" not in PREDICTIVE_FEATURES
    fv = derive_features({"release_year": "2019"})
    assert fv.release_year.value == Decimal("2019")
    assert fv.release_year.source == SOURCE_TITLE
    # ... and a missing release_year is None-valued, not a neutral number.
    assert derive_features({}).release_year.value is None


# ---------------------------------------------------------------------------
# Determinism (Property 1 flavour) -- same raw yields an equal vector
# ---------------------------------------------------------------------------


def test_derivation_is_deterministic() -> None:
    raw = {"genre": "Drama", "normalized_rating": "0.6", "runtime_minutes": 40}
    assert derive_features(raw) == derive_features(dict(raw))
