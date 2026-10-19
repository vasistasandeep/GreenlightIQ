"""HTTP-contract tests for the WhatIf_Explorer endpoint.

Feature: whatif-explore-inputs-guardrails. Drives POST /api/v1/valuation/{id}/
what-if through the TestClient with a focused fake engine, verifying the
baseline/scenario contract, override pass-through, validation, 404, and the
negotiation ceiling. Read-only (the engine fake is non-persisting by nature).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.api import deps
import app.api.valuation as val_mod
from app.core.errors import TitleNotFoundError
from app.core.security import UserContext, UserRole
from app.main import create_app


def _analyst() -> UserContext:
    return UserContext(user_id=uuid.uuid4(), display_name="A", role=UserRole.DATA_ANALYST)


def _result(cost: Decimal, rec: str, ltv: Decimal, checks: list[dict]) -> dict[str, Any]:
    return {
        "title_id": uuid.uuid4(),
        "calculated_cpvh": Decimal("0.04"),
        "ltv_to_cost_multiple": ltv,
        "churn_reduction_pct": Decimal("2.00"),
        "payback_horizon_months": 8,
        "recommendation_status": rec,
        "normalized_cost_usd": cost,
        "exchange_rate_id": None,
        "model_version_id": uuid.uuid4(),
        "explanation": {"checks": checks, "dominant_factor": None, "unclassifiable": False},
        "churn_detail": None,
        "ltv_subscription_value": Decimal("100"),
        "ltv_advertising_value": Decimal("50"),
        "ltv_total_modeled_value": Decimal("150"),
        "modeled_cohort_size": Decimal("1000"),
        "retained_subscribers": Decimal("20"),
    }


_LTV_BREACH_CHECK = {
    "name": "LTV_TO_COST",
    "computed_value": Decimal("2.90"),
    "threshold": Decimal("3.2"),
    "passed": False,
    "breached": True,
    "shortfall_magnitude": Decimal("0.09"),
    "correctable": True,
}


class _FakeEngine:
    """Returns a baseline (identity) result, and a scenario result that reflects
    a cost_usd override when present, so the endpoint contract is exercised."""

    def __init__(self, known: uuid.UUID) -> None:
        self._known = known

    async def evaluate_scenario(self, title_id, *, cost_multiplier, viewership_multiplier,
                                churn_multiplier, input_overrides=None, threshold_overrides=None):
        if title_id != self._known:
            raise TitleNotFoundError("no title", details={"title_id": str(title_id)})
        if input_overrides is not None and getattr(input_overrides, "cost_usd", None) is not None:
            # Scenario: lower cost clears LTV -> GREENLIGHT.
            return _result(Decimal(input_overrides.cost_usd), "GREENLIGHT", Decimal("3.5"),
                           [{**_LTV_BREACH_CHECK, "computed_value": Decimal("3.5"), "passed": True, "breached": False, "shortfall_magnitude": None, "correctable": None}])
        # Baseline: NEGOTIATE_HARD with an LTV breach.
        return _result(Decimal("1000000"), "NEGOTIATE_HARD", Decimal("2.90"), [dict(_LTV_BREACH_CHECK)])


def _client(known: uuid.UUID, monkeypatch) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_current_user] = _analyst
    app.dependency_overrides[deps.get_db_session] = lambda: object()
    app.dependency_overrides[deps.get_guardrails_engine] = lambda: _FakeEngine(known)

    async def _no_metadata(session, title_id):
        return None

    monkeypatch.setattr(val_mod, "_metadata_breakdown", _no_metadata)
    return TestClient(app, raise_server_exceptions=False)


def test_identity_returns_baseline_and_scenario(monkeypatch):
    tid = uuid.uuid4()
    client = _client(tid, monkeypatch)
    resp = client.post(
        f"/api/v1/valuation/{tid}/what-if",
        json={"cost_multiplier": "1.0", "viewership_multiplier": "1.0", "churn_multiplier": "1.0"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "baseline" in body
    assert body["baseline"]["recommendation_status"] == "NEGOTIATE_HARD"
    # No overrides -> scenario mirrors baseline verdict.
    assert body["recommendation_status"] == "NEGOTIATE_HARD"
    # The baseline LTV breach yields a negotiation ceiling.
    assert body["negotiation_ceiling_usd"] is not None


def test_cost_override_moves_verdict(monkeypatch):
    tid = uuid.uuid4()
    client = _client(tid, monkeypatch)
    resp = client.post(
        f"/api/v1/valuation/{tid}/what-if",
        json={
            "cost_multiplier": "1.0",
            "viewership_multiplier": "1.0",
            "churn_multiplier": "1.0",
            "input_overrides": {"cost_usd": "600000"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendation_status"] == "GREENLIGHT"  # scenario moved
    assert body["baseline"]["recommendation_status"] == "NEGOTIATE_HARD"  # baseline intact


def test_invalid_override_rejected_422(monkeypatch):
    tid = uuid.uuid4()
    client = _client(tid, monkeypatch)
    resp = client.post(
        f"/api/v1/valuation/{tid}/what-if",
        json={
            "cost_multiplier": "1.0",
            "viewership_multiplier": "1.0",
            "churn_multiplier": "1.0",
            "input_overrides": {"cpm": "0.1"},  # below the 0.50 floor
        },
    )
    assert resp.status_code == 422


def test_missing_title_404(monkeypatch):
    known = uuid.uuid4()
    client = _client(known, monkeypatch)
    other = uuid.uuid4()
    resp = client.post(
        f"/api/v1/valuation/{other}/what-if",
        json={"cost_multiplier": "1.0", "viewership_multiplier": "1.0", "churn_multiplier": "1.0"},
    )
    assert resp.status_code == 404