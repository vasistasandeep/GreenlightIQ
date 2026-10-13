"""Regression test: the engine falls back to the latest available FX rate.

A dated exchange_rates table rarely carries a row for *today*; the engine must
use the most recent available rate rather than raising
ExchangeRateUnavailableError, so re-valuation / what-if works on non-USD titles
seeded with historical rates.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engines.guardrails import Guardrails_Engine, ValuationInputs
from tests.engines.test_guardrails_properties import (
    FakeAuditService,
    FakeInputProvider,
    FakeLicenseTermRepository,
    FakeProjectionRepository,
    FakeTelemetryRepository,
    FakeTitle,
    FakeTitleRepository,
    FakeVersioningEngine,
)


@dataclass
class _Rate:
    rate: Decimal
    rate_date: date
    exchange_rate_id: uuid.UUID


class _ExactMissLatestHitRepo:
    """No row for the exact date, but a latest-available EUR->USD rate exists."""

    def __init__(self) -> None:
        self.exact_calls = 0
        self.latest_calls = 0

    async def get_rate(self, frm, to, when):
        self.exact_calls += 1
        return None  # no rate dated exactly `when`

    async def get_latest_rate(self, frm, to):
        self.latest_calls += 1
        return _Rate(rate=Decimal("1.09"), rate_date=date(2024, 1, 2), exchange_rate_id=uuid.uuid4())


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


def test_engine_uses_latest_rate_when_exact_date_missing():
    async def run():
        title_id = uuid.uuid4()
        title = FakeTitle(title_id=title_id, native_currency="EUR")
        fx = _ExactMissLatestHitRepo()
        engine = Guardrails_Engine(
            title_repository=FakeTitleRepository(title),
            projection_repository=FakeProjectionRepository(),
            exchange_rate_repository=fx,
            license_term_repository=FakeLicenseTermRepository(),
            telemetry_repository=FakeTelemetryRepository(),
            model_versioning_engine=FakeVersioningEngine(),
            audit_service=FakeAuditService(),
            input_provider=FakeInputProvider(_inputs()),
        )
        result = await engine.evaluate_scenario(
            title_id,
            cost_multiplier=Decimal("1.0"),
            viewership_multiplier=Decimal("1.0"),
            churn_multiplier=Decimal("1.0"),
        )
        # It did not raise, and it consulted the latest-rate fallback.
        assert fx.exact_calls == 1
        assert fx.latest_calls == 1
        assert result["normalized_cost_usd"] > 0
    asyncio.run(run())