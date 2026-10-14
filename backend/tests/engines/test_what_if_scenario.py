"""Property + example tests for the stateless what-if scenario path.

Feature: what-if-sensitivity. Covers Property 1 (identity), Property 4 (cost
monotonicity), Property 5 (viewership monotonicity), and the engine-level
no-persist / no-audit invariant (R2.4), using the in-memory engine fakes.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.guardrails import Guardrails_Engine, ValuationInputs
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
        milestone_schedule=[{"month": 1, "amount": Decimal("1"), "currency": "USD"}],
    )


def _engine(inputs: ValuationInputs):
    title_id = uuid.uuid4()
    title = FakeTitle(title_id=title_id)
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


_mult = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("2.0"),
                    allow_nan=False, allow_infinity=False, places=2)


# Feature: what-if-sensitivity, Property 1: Identity scenario reproduces the persisted scorecard
# Validates: Requirements 3.1, 3.2, 3.3, 3.4
def test_property_1_identity_matches_evaluate():
    async def run():
        inputs = _inputs()
        engine, title_id, _, _ = _engine(inputs)
        persisted = await engine.evaluate(title_id)
        engine2, title_id2, _, _ = _engine(inputs)
        scenario = await engine2.evaluate_scenario(
            title_id2,
            cost_multiplier=Decimal("1.0"),
            viewership_multiplier=Decimal("1.0"),
            churn_multiplier=Decimal("1.0"),
        )
        assert scenario["recommendation_status"] == persisted["recommendation_status"]
        assert scenario["calculated_cpvh"] == persisted["calculated_cpvh"]
        assert scenario["ltv_to_cost_multiple"] == persisted["ltv_to_cost_multiple"]
        assert scenario["churn_reduction_pct"] == persisted["churn_reduction_pct"]
        assert scenario["payback_horizon_months"] == persisted["payback_horizon_months"]
    asyncio.run(run())


# Feature: what-if-sensitivity, Property 4: Cost multiplier moves CPVH and the LTV multiple in the modeled direction
# Validates: Requirements 5.1
@settings(max_examples=100, deadline=None)
@given(m1=_mult, m2=_mult)
def test_property_4_cost_monotonicity(m1, m2):
    lo, hi = (m1, m2) if m1 <= m2 else (m2, m1)

    async def run():
        inputs = _inputs()
        e1, t1, _, _ = _engine(inputs)
        e2, t2, _, _ = _engine(inputs)
        a = await e1.evaluate_scenario(t1, cost_multiplier=lo, viewership_multiplier=Decimal("1.0"), churn_multiplier=Decimal("1.0"))
        b = await e2.evaluate_scenario(t2, cost_multiplier=hi, viewership_multiplier=Decimal("1.0"), churn_multiplier=Decimal("1.0"))
        if a["calculated_cpvh"] is not None and b["calculated_cpvh"] is not None:
            assert b["calculated_cpvh"] >= a["calculated_cpvh"]
        assert b["ltv_to_cost_multiple"] <= a["ltv_to_cost_multiple"]
    asyncio.run(run())


# Feature: what-if-sensitivity, Property 5: Viewership multiplier moves CPVH down and the LTV multiple up
# Validates: Requirements 5.2, 5.3
@settings(max_examples=100, deadline=None)
@given(m1=_mult, m2=_mult)
def test_property_5_viewership_monotonicity(m1, m2):
    lo, hi = (m1, m2) if m1 <= m2 else (m2, m1)

    async def run():
        inputs = _inputs()
        e1, t1, _, _ = _engine(inputs)
        e2, t2, _, _ = _engine(inputs)
        a = await e1.evaluate_scenario(t1, cost_multiplier=Decimal("1.0"), viewership_multiplier=lo, churn_multiplier=Decimal("1.0"))
        b = await e2.evaluate_scenario(t2, cost_multiplier=Decimal("1.0"), viewership_multiplier=hi, churn_multiplier=Decimal("1.0"))
        if a["calculated_cpvh"] is not None and b["calculated_cpvh"] is not None:
            assert b["calculated_cpvh"] <= a["calculated_cpvh"]
        assert b["ltv_to_cost_multiple"] >= a["ltv_to_cost_multiple"]
    asyncio.run(run())


# Feature: calculable-churn-model, Property 11: What-if borderline
# Validates: Requirements 7.5, 7.6
def test_what_if_churn_multiplier_omits_breakdown_and_recomputes_borderline():
    """A churn multiplier != 1 yields a scaled churn_detail that omits the
    per-feature breakdown and recomputes is_borderline on the SCALED value, and
    crossing the [1.45, 1.55] band flips the flag (R7.5, R7.6)."""
    from app.domain.churn import is_borderline

    async def run():
        inputs = _inputs()  # SUPPLIED base churn of 2.0

        # In-band: 2.0 * 0.75 = 1.50 -> borderline true, breakdown omitted.
        e_in, t_in, _, _ = _engine(inputs)
        in_band = await e_in.evaluate_scenario(
            t_in,
            cost_multiplier=Decimal("1.0"),
            viewership_multiplier=Decimal("1.0"),
            churn_multiplier=Decimal("0.75"),
        )
        detail_in = in_band["churn_detail"]
        assert detail_in is not None
        assert detail_in.breakdown is None  # omitted for a scaled scenario
        assert in_band["churn_reduction_pct"] == Decimal("1.50")
        assert detail_in.is_borderline is True
        assert detail_in.is_borderline == is_borderline(in_band["churn_reduction_pct"])
        # method carried from the base resolution (SUPPLIED here).
        assert detail_in.method == "SUPPLIED"

        # Out-of-band: 2.0 * 0.5 = 1.00 -> borderline false, flag flips.
        e_out, t_out, _, _ = _engine(inputs)
        out_band = await e_out.evaluate_scenario(
            t_out,
            cost_multiplier=Decimal("1.0"),
            viewership_multiplier=Decimal("1.0"),
            churn_multiplier=Decimal("0.5"),
        )
        detail_out = out_band["churn_detail"]
        assert detail_out is not None
        assert detail_out.breakdown is None
        assert out_band["churn_reduction_pct"] == Decimal("1.00")
        assert detail_out.is_borderline is False
        assert detail_out.is_borderline == is_borderline(out_band["churn_reduction_pct"])

    asyncio.run(run())


def test_evaluate_scenario_does_not_persist_or_audit():
    """R2.4: the scenario path writes no projection and records no audit entry."""
    async def run():
        inputs = _inputs()
        engine, title_id, projections, audit = _engine(inputs)
        result = await engine.evaluate_scenario(
            title_id,
            cost_multiplier=Decimal("1.2"),
            viewership_multiplier=Decimal("0.8"),
            churn_multiplier=Decimal("1.0"),
        )
        assert result["recommendation_status"] in {"GREENLIGHT", "NEGOTIATE_HARD", "PASS"}
        assert projections.created is None  # no projection write
        assert audit.records == []          # no audit entry
    asyncio.run(run())