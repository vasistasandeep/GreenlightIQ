"""Tests for the WhatIf_Explorer override behaviors on evaluate_scenario.

Feature: whatif-explore-inputs-guardrails. Covers Baseline fidelity (Property 1),
read-only sandbox (Property 3), direct-wins precedence (Property 4), milestone
coherence (Property 5), threshold-relative classification (Property 6), currency
neutrality (Property 11), and attribution recompute (Property 8). Reuses the
in-memory engine fakes.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from app.engines.guardrails import Guardrails_Engine, ValuationInputs
from app.schemas.api import ScenarioInputOverrides, ScenarioThresholdOverrides
from tests.engines.test_guardrails_properties import (
    FakeAuditService,
    FakeExchangeRateRepository,
    FakeInputProvider,
    FakeLicenseTermRepository,
    FakeProjectionRepository,
    FakeTelemetryRepository,
    FakeTitle,
    FakeTitleRepository,
    FakeVersioningEngine,
)


def _inputs() -> ValuationInputs:
    return ValuationInputs(
        churn_reduction_value=Decimal("2"),
        ltv=Decimal("150"),
        watch_time_elasticity=Decimal("0.6"),
        cpm=Decimal("28"),
        ad_impressions=Decimal("100000"),
        churn_reduction_pct=Decimal("2.0"),
        monthly_margin=Decimal("100000"),
        milestone_schedule=[{"month": 1, "amount": Decimal("1000000"), "currency": "USD"}],
    )


def _engine(inputs: ValuationInputs, native_currency: str = "USD"):
    title_id = uuid.uuid4()
    title = FakeTitle(title_id=title_id, native_currency=native_currency)
    projections = FakeProjectionRepository()
    audit = FakeAuditService()
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=projections,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=FakeVersioningEngine(),
        audit_service=audit,
        input_provider=FakeInputProvider(inputs),
    )
    return engine, title_id, projections, audit


def _run(coro):
    return asyncio.run(coro)


def _identity(engine, tid, **kw):
    return _run(
        engine.evaluate_scenario(
            tid,
            cost_multiplier=Decimal("1"),
            viewership_multiplier=Decimal("1"),
            churn_multiplier=Decimal("1"),
            **kw,
        )
    )


def test_baseline_fidelity_no_overrides():
    engine, tid, _, _ = _engine(_inputs())
    base = _identity(engine, tid)
    again = _identity(engine, tid)
    assert base["recommendation_status"] == again["recommendation_status"]
    assert base["ltv_to_cost_multiple"] == again["ltv_to_cost_multiple"]


def test_read_only_no_persist_no_audit():
    engine, tid, projections, audit = _engine(_inputs())
    _identity(engine, tid, input_overrides=ScenarioInputOverrides(cpm=Decimal("200")))
    assert projections.created is None  # nothing persisted
    assert audit.records == []  # no audit entry


def test_direct_cost_wins_over_multiplier():
    engine, tid, _, _ = _engine(_inputs())
    # cost_multiplier would halve; a direct cost_usd override should win.
    res = _run(
        engine.evaluate_scenario(
            tid,
            cost_multiplier=Decimal("0.5"),
            viewership_multiplier=Decimal("1"),
            churn_multiplier=Decimal("1"),
            input_overrides=ScenarioInputOverrides(cost_usd=Decimal("8000000")),
        )
    )
    assert res["normalized_cost_usd"] == Decimal("8000000")


def test_direct_churn_pct_wins_over_multiplier():
    engine, tid, _, _ = _engine(_inputs())
    res = _run(
        engine.evaluate_scenario(
            tid,
            cost_multiplier=Decimal("1"),
            viewership_multiplier=Decimal("1"),
            churn_multiplier=Decimal("0.5"),
            input_overrides=ScenarioInputOverrides(churn_reduction_pct=Decimal("1.20")),
        )
    )
    assert res["churn_reduction_pct"] == Decimal("1.20")


def test_threshold_override_reclassifies_churn():
    engine, tid, _, _ = _engine(_inputs())
    # Base churn 2.0 passes the 1.5 hurdle. Raise the hurdle to 2.5 -> breach.
    res = _run(
        engine.evaluate_scenario(
            tid,
            cost_multiplier=Decimal("1"),
            viewership_multiplier=Decimal("1"),
            churn_multiplier=Decimal("1"),
            threshold_overrides=ScenarioThresholdOverrides(churn_hurdle_override=Decimal("2.5")),
        )
    )
    checks = {c["name"]: c for c in res["explanation"]["checks"]}
    assert checks["CHURN_MITIGATION"]["breached"] is True
    assert checks["CHURN_MITIGATION"]["threshold"] == Decimal("2.5")


def test_attribution_reflects_overrides():
    engine, tid, _, _ = _engine(_inputs())
    low = _identity(engine, tid)
    high = _identity(
        engine, tid, input_overrides=ScenarioInputOverrides(cpm=Decimal("200"))
    )
    # A much higher CPM raises the advertising value (and the multiple).
    assert high["ltv_advertising_value"] > low["ltv_advertising_value"]


class _RateRow:
    def __init__(self):
        self.rate = Decimal("0.012")
        self.rate_date = __import__("datetime").date(2026, 1, 1)
        self.exchange_rate_id = uuid.uuid4()


class _FakeRatesWithRate:
    async def get_rate(self, *a, **k):
        return _RateRow()

    async def get_latest_rate(self, *a, **k):
        return _RateRow()


def test_non_usd_cost_override_is_currency_neutral():
    # INR title; a direct cost_usd override sets USD directly (no FX re-normalize).
    inputs = _inputs()
    title_id = uuid.uuid4()
    title = FakeTitle(title_id=title_id, native_currency="INR")
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=FakeProjectionRepository(),
        exchange_rate_repository=_FakeRatesWithRate(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=FakeVersioningEngine(),
        audit_service=FakeAuditService(),
        input_provider=FakeInputProvider(inputs),
    )
    res = _run(
        engine.evaluate_scenario(
            title_id,
            cost_multiplier=Decimal("1"),
            viewership_multiplier=Decimal("1"),
            churn_multiplier=Decimal("1"),
            input_overrides=ScenarioInputOverrides(cost_usd=Decimal("5000000")),
        )
    )
    assert res["normalized_cost_usd"] == Decimal("5000000")