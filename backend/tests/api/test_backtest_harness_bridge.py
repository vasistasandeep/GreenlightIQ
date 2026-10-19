"""API test for the Backtest_Harness -> audit-contract bridge (task 17, R6.7).

Task 9's offline ``Backtest_Harness`` scores the four content-eval modeled
drivers. Task 17 bridges those drivers to the EXISTING
``POST /api/v1/backtest/audit`` metric contract so churn / CPVH (via viewing
hours) / the LTV drivers can be scored through the very path the Backtest Studio
already uses for CPVH and LTV-to-Cost, reusing the MAPE-excludes-zero convention
owned by :mod:`app.domain.mape` (no MAPE logic is duplicated or forked).

These tests prove, through real FastAPI routing and the shared error envelope:

* ``audit_metrics_for_row`` maps each modeled driver to an audit metric name that
  the existing ``PREDICTED_METRIC_FIELDS`` contract already knows
  (``churn_reduction`` / ``cpvh`` / ``ltv_to_cost``), emitting exactly the
  ``{metric_name, actual_value}`` shape the endpoint accepts.
* Posting those bridged metric names to ``/backtest/audit`` scores correctly: the
  scorecard pairs each actual against the stored predicted projection column and
  returns a real computed MAPE (not a canned value).
* A zero-actual metric is EXCLUDED from MAPE (the existing convention) while still
  appearing in the per-metric rows flagged ``excluded``.

The backtesting module here is an in-memory fake that runs the REAL
:func:`app.domain.mape.compute_mape` against a fake ``financial_projections`` row
using the REAL ``PREDICTED_METRIC_FIELDS`` mapping, so the scoring path under test
is the production contract, not a hardcoded scorecard. No live DB is used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.security import UserContext, UserRole
from app.engines.backtesting import PREDICTED_METRIC_FIELDS, Backtesting_Module
from app.engines.backtest_harness import (
    DRIVER_AUDIT_METRICS,
    audit_metric_name_for_driver,
    audit_metrics_for_row,
)
from app.main import create_app


# --------------------------------------------------------------------------- #
# Fakes (in-memory; exercise the REAL audit-scoring contract)
# --------------------------------------------------------------------------- #


def _analyst() -> UserContext:
    return UserContext(
        user_id=uuid.uuid4(),
        display_name="Bridge Analyst",
        role=UserRole.DATA_ANALYST,
        authorized_territories=(),
    )


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class _FakeProjection:
    """A stand-in ``financial_projections`` row carrying the predicted columns.

    The field names match ``PREDICTED_METRIC_FIELDS`` values so the real
    ``Backtesting_Module._predicted_for`` reads them by ``getattr`` exactly as it
    would a persisted ORM row.
    """

    calculated_cpvh: Decimal | None = None
    ltv_to_cost_multiple: Decimal | None = None
    churn_reduction_pct: Decimal | None = None
    payback_horizon_months: Decimal | None = None


@dataclass
class _FakeGroundTruth:
    metric_name: str
    actual_value: Decimal
    recorded_at: Any = None


class FakeBacktestingModule:
    """Records persisted ground truth and scores via the REAL audit contract.

    ``audit`` reuses the production ``PREDICTED_METRIC_FIELDS`` mapping and the
    pure :func:`app.domain.mape.compute_mape` (via the real
    ``Backtesting_Module._predicted_for`` + the same pairing/exclusion rule the
    engine uses), so a request that posts the bridged metric names is scored by
    the same logic the Backtest Studio exercises -- no canned scorecard.
    """

    def __init__(self, projection: _FakeProjection) -> None:
        self.projection = projection
        self.persisted: list[dict] = []
        self.session = _FakeSession()

    async def persist_ground_truth(self, record: dict) -> uuid.UUID:
        self.persisted.append(record)
        return record["title_id"]

    async def audit(self, title_id: uuid.UUID) -> dict[str, Any]:
        from app.domain.mape import compute_mape

        # Collapse to one actual per metric from everything persisted so far,
        # mirroring the real module's one-value-per-metric behavior.
        latest: dict[str, Decimal] = {}
        for record in self.persisted:
            for metric in record["metrics"]:
                latest[metric["metric_name"]] = Decimal(str(metric["actual_value"]))

        rows: list[dict[str, Any]] = []
        pairs: list[tuple[Decimal, Decimal]] = []
        for metric_name, actual in latest.items():
            predicted = Backtesting_Module._predicted_for(self.projection, metric_name)
            if predicted is None:
                continue
            excluded = actual == 0  # the existing zero-actual exclusion rule
            rows.append(
                {
                    "metric": metric_name,
                    "predicted": predicted,
                    "actual": actual,
                    "excluded": excluded,
                }
            )
            if not excluded:
                pairs.append((actual, predicted))

        mape = compute_mape(pairs)
        return {
            "title_id": title_id,
            "metrics": rows,
            "mape": mape,
            "no_eligible_metrics": mape is None,
        }


# --------------------------------------------------------------------------- #
# App + client fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def projection() -> _FakeProjection:
    # Predicted columns the content-eval drivers map onto. CPVH is the viewing-
    # hours-derived metric; ltv_to_cost is the LTV-driver metric; churn_reduction
    # is the churn metric.
    return _FakeProjection(
        calculated_cpvh=Decimal("0.0400"),
        ltv_to_cost_multiple=Decimal("3.00"),
        churn_reduction_pct=Decimal("2.00"),
    )


@pytest.fixture()
def backtesting(projection: _FakeProjection) -> FakeBacktestingModule:
    return FakeBacktestingModule(projection)


@pytest.fixture()
def client(backtesting: FakeBacktestingModule) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_current_user] = _analyst
    app.dependency_overrides[deps.get_db_session] = lambda: _FakeSession()
    app.dependency_overrides[deps.get_backtesting_module] = lambda: backtesting
    return TestClient(app)


# --------------------------------------------------------------------------- #
# The bridge maps drivers onto the existing contract's metric names
# --------------------------------------------------------------------------- #


def test_driver_audit_metric_names_are_known_to_the_existing_contract() -> None:
    # Every audit metric name the bridge emits must already have a predicted
    # column in PREDICTED_METRIC_FIELDS -- the bridge reuses the contract, it does
    # not invent new metric names (R6.7).
    assert set(DRIVER_AUDIT_METRICS.values()) <= set(PREDICTED_METRIC_FIELDS)
    assert audit_metric_name_for_driver("churn_reduction_pct") == "churn_reduction"
    assert audit_metric_name_for_driver("projected_viewing_hours") == "cpvh"
    assert audit_metric_name_for_driver("watch_time_elasticity") == "ltv_to_cost"
    assert audit_metric_name_for_driver("ad_load_receptivity") == "ltv_to_cost"
    # A driver not scored through the shared contract has no audit metric.
    assert audit_metric_name_for_driver("not_a_driver") is None


def test_audit_metrics_for_row_emits_contract_shape() -> None:
    row = {
        "title_id": "demo-1",
        "expected_drivers": {
            "projected_viewing_hours": "0.0500",
            "churn_reduction_pct": "1.80",
            "watch_time_elasticity": "1.20",
            "ad_load_receptivity": "1.05",
        },
    }
    metrics = audit_metrics_for_row(row)
    names = {m["metric_name"] for m in metrics}
    # cpvh (viewing hours), churn_reduction (churn), ltv_to_cost (LTV drivers);
    # the two LTV drivers collapse to a single ltv_to_cost entry.
    assert names == {"cpvh", "churn_reduction", "ltv_to_cost"}
    assert len(metrics) == 3
    for metric in metrics:
        assert set(metric.keys()) == {"metric_name", "actual_value"}
        assert isinstance(metric["actual_value"], Decimal)


# --------------------------------------------------------------------------- #
# Posting the bridged metric names scores through the audit endpoint
# --------------------------------------------------------------------------- #


def test_bridged_metrics_score_through_audit_endpoint(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    title_id = uuid.uuid4()
    row = {
        "title_id": str(title_id),
        "expected_drivers": {
            "projected_viewing_hours": "0.0500",  # -> cpvh,  predicted 0.0400
            "churn_reduction_pct": "1.80",  # -> churn_reduction, predicted 2.00
            "watch_time_elasticity": "3.60",  # -> ltv_to_cost, predicted 3.00
        },
    }
    metrics = audit_metrics_for_row(row)

    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "metrics": [
                {"metric_name": m["metric_name"], "actual_value": str(m["actual_value"])}
                for m in metrics
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_id"] == str(title_id)

    scored = {row["metric"]: row for row in body["metrics"]}
    assert set(scored) == {"cpvh", "churn_reduction", "ltv_to_cost"}

    # Real MAPE over the three eligible pairs (none zero):
    #   cpvh:            |0.05 - 0.04| / 0.05 = 0.2000
    #   churn_reduction: |1.80 - 2.00| / 1.80 = 0.1111...
    #   ltv_to_cost:     |3.60 - 3.00| / 3.60 = 0.1666...
    #   mean * 100 = (0.2 + 0.11111 + 0.16667) / 3 * 100 = 15.93%
    assert body["no_eligible_metrics"] is False
    assert body["mape"] == "15.93"
    assert all(not scored[name]["excluded"] for name in scored)


def test_zero_actual_bridged_metric_excluded_from_mape(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    # A zero-actual churn_reduction is excluded from MAPE (the existing
    # convention), while the remaining cpvh metric still scores (R6.7 reuse).
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "metrics": [
                {"metric_name": "cpvh", "actual_value": "0.0500"},
                {"metric_name": "churn_reduction", "actual_value": "0"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    scored = {row["metric"]: row for row in body["metrics"]}

    # The zero-actual churn metric is present but excluded; cpvh carries MAPE.
    assert scored["churn_reduction"]["excluded"] is True
    assert scored["cpvh"]["excluded"] is False
    # MAPE is over cpvh alone: |0.05 - 0.04| / 0.05 * 100 = 20.00%.
    assert body["no_eligible_metrics"] is False
    assert body["mape"] == "20.00"


def test_all_zero_actuals_yield_no_eligible_metrics(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "metrics": [{"metric_name": "cpvh", "actual_value": "0"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mape"] is None
    assert body["no_eligible_metrics"] is True
