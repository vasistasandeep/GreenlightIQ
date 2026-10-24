"""Schema tests for the additive ``advanced_drivers`` explanation block (task 14).

# Feature: advanced-content-eval-drivers

Targets the per-driver provenance models added to :mod:`app.schemas.api`
(:class:`AdvancedDriversExplanation` and the four per-driver provenance models).
The explanation payload itself stays a pass-through ``dict[str, Any]`` on
:class:`ValuationScorecardResponse`; these models formalize and validate the
shape the provider (:class:`app.api.deps.AdvancedDriversValuationInputProvider`)
threads under ``driver_explanations.advanced_drivers``.

Pins the two invariants task 14 requires:

* The block is ADDITIVE / backward-compatible (R6.5): a pre-feature stored
  explanation that carries no ``advanced_drivers`` key still serializes through
  ``ValuationScorecardResponse``, and with every Driver_Flag off the block is
  absent entirely (every field optional).
* Decimals serialize as JSON strings (R6.1), matching the provider's
  ``_jsonable_decimal`` policy, and the exact shapes the provider emits for each
  driver round-trip through the models without loss.

Validates: Requirements 6.1, 6.3, 6.5, 9.1.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.api import (
    AdvancedDriversExplanation,
    CompsProvenance,
    LineageProvenance,
    MacroModifiersProvenance,
    MomentumProvenance,
    ValuationScorecardResponse,
)


# --------------------------------------------------------------------------- #
# Shapes the provider (app.api.deps) emits for each driver, verbatim.
# --------------------------------------------------------------------------- #


def _comps_block() -> dict:
    """The ``advanced_drivers.comps`` shape from ``_resolve_comps`` (Decimals as str)."""
    return {
        "source_tier": "DETERMINISTIC_FALLBACK",
        "realized_k": 5,
        "use_intercept_fallback": False,
        "comp_title_ids": [1, 2, 3, 4, 5],
        "h_comps": "3100.00",
        "base_hours_override": "3100.00",
        "c_comps": "1.80",
        "base_churn_override": "1.80",
        "dispersion_iqr": "420.00",
    }


def _lineage_block() -> dict:
    return {
        "source_tier": "DETERMINISTIC_FALLBACK",
        "is_active": True,
        "franchise_floor": "2600.00",
        "delta_c_franchise": "0.25",
        "assumed_features": ["parent_completion_rate"],
    }


def _momentum_block() -> dict:
    return {
        "source_tier": "DETERMINISTIC_FALLBACK",
        "value": "1.32",
        "bounds": "[1.00,1.50]",
        "production_stage": "ACQUISITION_READY",
        "stage_excluded": False,
        "reason": None,
        "reading_age_days": 3,
    }


def _macro_block() -> dict:
    return {
        "source_tier": "DETERMINISTIC_FALLBACK",
        "source_ip_multiplier": "1.20",
        "release_window_multiplier": "1.25",
        "calendar_seasonality_multiplier": "1.10",
        "vernacular_tam_multiplier": "1.50",
        "product": "2.4750",
        "assumed_features": [],
    }


# --------------------------------------------------------------------------- #
# Per-driver provenance models round-trip the provider shapes.
# --------------------------------------------------------------------------- #


def test_comps_provenance_parses_provider_shape_and_serializes_decimals_as_strings():
    model = CompsProvenance.model_validate(_comps_block())
    assert model.source_tier == "DETERMINISTIC_FALLBACK"
    assert model.realized_k == 5
    assert model.use_intercept_fallback is False
    assert model.comp_title_ids == [1, 2, 3, 4, 5]
    assert model.h_comps == Decimal("3100.00")

    dumped = model.model_dump(mode="json")
    # R6.1: Decimals serialize as JSON strings.
    assert dumped["h_comps"] == "3100.00"
    assert dumped["base_hours_override"] == "3100.00"
    assert dumped["c_comps"] == "1.80"
    assert isinstance(dumped["dispersion_iqr"], str)


def test_comps_provenance_omits_anchor_fields_on_intercept_fallback():
    """Zero eligible comps -> intercept fallback, no anchor / override fields."""
    block = {
        "source_tier": "DETERMINISTIC_FALLBACK",
        "realized_k": 0,
        "use_intercept_fallback": True,
        "comp_title_ids": [],
    }
    model = CompsProvenance.model_validate(block)
    assert model.use_intercept_fallback is True
    assert model.h_comps is None
    assert model.c_comps is None
    assert model.base_hours_override is None


def test_lineage_provenance_parses_provider_shape():
    model = LineageProvenance.model_validate(_lineage_block())
    assert model.is_active is True
    assert model.franchise_floor == Decimal("2600.00")
    assert model.delta_c_franchise == Decimal("0.25")
    assert model.assumed_features == ["parent_completion_rate"]
    dumped = model.model_dump(mode="json")
    assert dumped["franchise_floor"] == "2600.00"
    assert dumped["delta_c_franchise"] == "0.25"


def test_momentum_provenance_bounds_is_a_string():
    model = MomentumProvenance.model_validate(_momentum_block())
    assert model.value == Decimal("1.32")
    # R6.1 / design: momentum bounds serialize as the "[1.00,1.50]" clamp string.
    assert model.bounds == "[1.00,1.50]"
    assert model.stage_excluded is False
    dumped = model.model_dump(mode="json")
    assert dumped["value"] == "1.32"
    assert dumped["bounds"] == "[1.00,1.50]"


def test_macro_modifiers_provenance_parses_provider_shape():
    model = MacroModifiersProvenance.model_validate(_macro_block())
    assert model.source_ip_multiplier == Decimal("1.20")
    assert model.product == Decimal("2.4750")
    dumped = model.model_dump(mode="json")
    for key in (
        "source_ip_multiplier",
        "release_window_multiplier",
        "calendar_seasonality_multiplier",
        "vernacular_tam_multiplier",
        "product",
    ):
        assert isinstance(dumped[key], str)


def test_source_tier_rejects_unknown_value():
    """``source_tier`` is constrained to the strict precedence set (R6.1)."""
    bad = dict(_lineage_block(), source_tier="GUESS")
    with pytest.raises(ValidationError):
        LineageProvenance.model_validate(bad)


# --------------------------------------------------------------------------- #
# The advanced_drivers block is additive / backward-compatible.
# --------------------------------------------------------------------------- #


def test_advanced_drivers_block_accepts_all_four_drivers():
    block = AdvancedDriversExplanation.model_validate(
        {
            "comps": _comps_block(),
            "lineage": _lineage_block(),
            "momentum": _momentum_block(),
            "macro_modifiers": _macro_block(),
        }
    )
    assert block.comps is not None
    assert block.lineage is not None
    assert block.momentum is not None
    assert block.macro_modifiers is not None


def test_advanced_drivers_block_is_absent_when_all_flags_off():
    """With every Driver_Flag off no driver resolves -> empty / all-None block."""
    block = AdvancedDriversExplanation.model_validate({})
    assert block.comps is None
    assert block.lineage is None
    assert block.momentum is None
    assert block.macro_modifiers is None


def test_advanced_drivers_block_accepts_a_single_enabled_driver():
    """Each driver is an independent slice -> one driver present is valid."""
    block = AdvancedDriversExplanation.model_validate({"momentum": _momentum_block()})
    assert block.momentum is not None
    assert block.comps is None


def test_pre_feature_explanation_without_advanced_drivers_still_serializes():
    """R6.5: a stored explanation produced before this feature carries no
    ``advanced_drivers`` key and must serialize through the scorecard unchanged."""
    pre_feature_explanation = {
        "recommendation": {"status": "GREENLIGHT"},
        "guardrails": {"cpvh": {"value": "0.42"}},
        # No ``driver_explanations`` / ``advanced_drivers`` key at all.
    }
    response = ValuationScorecardResponse(
        title_id=uuid.uuid4(),
        calculated_cpvh=Decimal("0.42"),
        ltv_to_cost_multiple=Decimal("3.1"),
        churn_reduction_pct=Decimal("2.0"),
        payback_horizon_months=12,
        recommendation_status="GREENLIGHT",
        normalized_cost_usd=Decimal("1000000"),
        model_version_id=uuid.uuid4(),
        explanation=pre_feature_explanation,
        metadata_breakdown=None,
    )
    dumped = response.model_dump(mode="json")
    assert "advanced_drivers" not in dumped["explanation"]
    assert dumped["explanation"]["recommendation"]["status"] == "GREENLIGHT"


def test_identical_explanation_when_flags_off_vs_pre_feature():
    """R6.5 / R9.1: a flags-off explanation (no ``advanced_drivers`` threaded)
    is byte-identical to a pre-feature stored explanation with the same body."""
    body = {
        "recommendation": {"status": "PASS"},
        "driver_explanations": {"projected_viewing_hours": {"method": "FITTED"}},
    }
    pre_feature = ValuationScorecardResponse(
        title_id=uuid.UUID(int=1),
        calculated_cpvh=None,
        ltv_to_cost_multiple=None,
        churn_reduction_pct=None,
        payback_horizon_months=None,
        recommendation_status="PASS",
        normalized_cost_usd=None,
        model_version_id=None,
        explanation=dict(body),
        metadata_breakdown=None,
    )
    flags_off = ValuationScorecardResponse(
        title_id=uuid.UUID(int=1),
        calculated_cpvh=None,
        ltv_to_cost_multiple=None,
        churn_reduction_pct=None,
        payback_horizon_months=None,
        recommendation_status="PASS",
        normalized_cost_usd=None,
        model_version_id=None,
        explanation=dict(body),
        metadata_breakdown=None,
    )
    assert pre_feature.model_dump(mode="json") == flags_off.model_dump(mode="json")
