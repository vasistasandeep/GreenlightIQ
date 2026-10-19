"""Focused tests for the ContentEvalValuationInputProvider (content-eval-model, task 13).

# Feature: content-eval-model

Targets :class:`app.api.deps.ContentEvalValuationInputProvider`, the provider-
layer wrapper that applies the Content_Eval_System precedence
``SUPPLIED > FITTED > FALLBACK`` over the existing
:class:`app.api.deps.SnapshotValuationInputProvider` and implements the opt-in
churn<->LTV linkage (design Components 4 and 8).

The dedicated end-to-end engine resolution tests are task 14; this module pins
the two invariants that matter for wiring the provider in safely:

* The CRITICAL default-off invariant (Property 12): with NO active fitted
  ``content_eval`` version and ``link_churn_to_ltv`` off (the seeded default),
  the wrapper returns a :class:`ValuationInputs` BYTE-IDENTICAL to the snapshot
  provider's output, with ``driver_explanations`` left ``None``.
* The opt-in churn<->LTV link derives ``churn_reduction_value`` from the modeled
  churn percentage only when the toggle is on and no value was supplied.

The repository/DB seams are stubbed via monkeypatch so no database is required.
Validates: Requirements 1.4, 1.5, 1.6, 8.3; Properties 6, 12.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.api import deps
from app.engines.guardrails import ValuationInputs


def _baseline_inputs() -> ValuationInputs:
    """A representative snapshot-provider output (the 'today' baseline)."""
    return ValuationInputs(
        churn_reduction_value=Decimal("1"),
        ltv=Decimal("4200"),
        watch_time_elasticity=Decimal("1.10"),
        cpm=Decimal("22"),
        ad_impressions=Decimal("500000"),
        monthly_margin=Decimal("3.5"),
        churn_reduction_pct=Decimal("2.0"),
        milestone_schedule=None,
        rate_date=None,
    )


class _FakeModelVersion:
    """Minimal stand-in for a ``model_versions`` row."""

    def __init__(self, guardrail_params: dict | None) -> None:
        self.guardrail_params = guardrail_params


class _FakeTitleVersion:
    def __init__(self, snapshot: dict | None) -> None:
        self.source_snapshot = snapshot


def _patch_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    baseline: ValuationInputs,
    active_guardrail_params: dict | None,
    snapshot: dict | None,
) -> None:
    """Stub the three DB seams the provider reaches through."""

    async def _fake_get_inputs(self, title_id):  # noqa: ANN001
        return baseline

    monkeypatch.setattr(
        deps.SnapshotValuationInputProvider, "get_inputs", _fake_get_inputs
    )

    from app.engines.model_versioning import ModelVersioningEngine
    from app.repositories.titles import TitleVersionRepository

    active = (
        _FakeModelVersion(active_guardrail_params)
        if active_guardrail_params is not None
        else None
    )

    async def _fake_read_active(self):  # noqa: ANN001
        return active

    monkeypatch.setattr(ModelVersioningEngine, "read_active", _fake_read_active)

    async def _fake_tv_get_active(self, title_id):  # noqa: ANN001
        return _FakeTitleVersion(snapshot)

    monkeypatch.setattr(TitleVersionRepository, "get_active", _fake_tv_get_active)


async def test_default_off_path_is_byte_identical_to_snapshot(monkeypatch):
    """No fitted version + link off -> snapshot inputs returned unchanged.

    The wrapper must short-circuit to the exact object the snapshot provider
    produced (same field values, ``driver_explanations`` None) so demo verdicts,
    projections, and explanation JSON are byte-identical (Property 12).
    """
    baseline = _baseline_inputs()
    _patch_seams(
        monkeypatch,
        baseline=baseline,
        active_guardrail_params=None,  # no active model version at all
        snapshot={"genre": "drama"},
    )

    provider = deps.ContentEvalValuationInputProvider(session=object())
    import uuid

    result = await provider.get_inputs(uuid.uuid4())

    assert result is baseline  # same object, no copy/replace on the default path
    assert result.driver_explanations is None
    assert result == baseline


async def test_default_off_with_empty_content_eval_block(monkeypatch):
    """An active version WITHOUT a content_eval block is still the inert path.

    ``parse_content_eval_params(None)`` yields source DEFAULTS and link off, so
    the provider must still return the snapshot inputs untouched.
    """
    baseline = _baseline_inputs()
    _patch_seams(
        monkeypatch,
        baseline=baseline,
        active_guardrail_params={"churn_model": {}},  # no 'content_eval' key
        snapshot={"genre": "drama"},
    )

    provider = deps.ContentEvalValuationInputProvider(session=object())
    import uuid

    result = await provider.get_inputs(uuid.uuid4())

    assert result is baseline
    assert result.driver_explanations is None


async def test_link_churn_to_ltv_derives_value_when_opted_in(monkeypatch):
    """link on + no supplied churn_reduction_value -> value = base * pct/100.

    The churn<->LTV link is a provider-layer toggle; with it on and no SUPPLIED
    ``churn_reduction_value`` on the snapshot it derives the LTV numerator's
    churn contribution from the modeled percentage, using the configured
    Base_Retained_Cohort_Value Platform_Rate.
    """
    baseline = replace(_baseline_inputs(), churn_reduction_value=Decimal("0"))
    # A snapshot carrying NO churn_reduction_value (so the link applies) and a
    # per-title Base_Retained_Cohort_Value override for a deterministic expected.
    snapshot = {
        "genre": "drama",
        "base_retained_cohort_value": "500000",
    }
    _patch_seams(
        monkeypatch,
        baseline=baseline,
        active_guardrail_params={"content_eval": {"link_churn_to_ltv": True}},
        snapshot=snapshot,
    )

    provider = deps.ContentEvalValuationInputProvider(session=object())
    import uuid

    result = await provider.get_inputs(uuid.uuid4())

    # churn_reduction_pct is 2.0 on the baseline -> 500000 * 2/100 = 10000.
    assert result.churn_reduction_value == Decimal("10000")


async def test_link_off_preserves_churn_value_even_with_fitted_version(monkeypatch):
    """A fitted version is active but link off -> churn_reduction_value untouched.

    A present ``content_eval`` block means a fitted version is active, so the
    FITTED path may override OTHER drivers; but with ``link_churn_to_ltv`` off the
    churn<->LTV linkage is a no-op and ``churn_reduction_value`` is preserved
    exactly as the snapshot provider produced it (today's independent behavior).
    """
    baseline = _baseline_inputs()  # churn_reduction_value == Decimal("1")
    _patch_seams(
        monkeypatch,
        baseline=baseline,
        active_guardrail_params={"content_eval": {"link_churn_to_ltv": False}},
        snapshot={"genre": "drama"},
    )

    provider = deps.ContentEvalValuationInputProvider(session=object())
    import uuid

    result = await provider.get_inputs(uuid.uuid4())

    # The churn<->LTV link is off, so churn_reduction_value is exactly preserved.
    assert result.churn_reduction_value == Decimal("1")


async def test_link_on_does_not_override_supplied_value(monkeypatch):
    """SUPPLIED churn_reduction_value on the snapshot wins even with link on."""
    baseline = _baseline_inputs()
    snapshot = {
        "genre": "drama",
        "churn_reduction_value": "1234",  # SUPPLIED on the snapshot
    }
    _patch_seams(
        monkeypatch,
        baseline=baseline,
        active_guardrail_params={"content_eval": {"link_churn_to_ltv": True}},
        snapshot=snapshot,
    )

    provider = deps.ContentEvalValuationInputProvider(session=object())
    import uuid

    result = await provider.get_inputs(uuid.uuid4())

    # The snapshot value was supplied, so the link does not touch it; it stays
    # whatever the snapshot provider produced (baseline's churn_reduction_value).
    assert result.churn_reduction_value == baseline.churn_reduction_value


async def test_get_input_provider_returns_content_eval_wrapper():
    """The DI factory wires the Content_Eval provider as the active one."""
    provider = deps.get_input_provider(session=object())
    assert isinstance(provider, deps.ContentEvalValuationInputProvider)
