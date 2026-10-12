"""Backtest router: ground-truth submission and audit scorecard (task 16.1).

``POST /backtest/audit`` (R11.1, R11.6) persists a ground-truth submission for a
historical title and returns the audit scorecard comparing predicted vs actual
with the computed MAPE. The ground-truth validation and MAPE computation live in
the Backtesting_Module; the router shapes the request/response and enforces the
cross-cutting auth/RBAC concerns.

Both steps run inline within the request transaction: ground-truth persistence
and scorecard construction are modest reads/writes over already-persisted data.
Invalid ground truth maps to ``422 GROUND_TRUTH_INVALID`` (R11.2) and a
historical title lacking ground truth to ``404 GROUND_TRUTH_MISSING`` (R11.4),
both surfaced through the shared error envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import BacktestingDep, CurrentUser, require_operation
from app.engines.backtesting import GroundTruthMetric, GroundTruthRecord
from app.engines.rbac import Operation
from app.schemas.api import (
    AuditMetricResponse,
    BacktestAuditRequest,
    BacktestAuditResponse,
)

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post(
    "/audit",
    response_model=BacktestAuditResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Persist ground truth and return the audit scorecard (R11.1, R11.6).",
)
async def backtest_audit(
    body: BacktestAuditRequest,
    actor: CurrentUser,
    module: BacktestingDep,
) -> BacktestAuditResponse:
    """Validate + persist ground truth, then return the audit scorecard (R11.6).

    Invalid ground truth raises ``422 GROUND_TRUTH_INVALID`` and persists nothing
    (R11.2); a historical title with no ground truth raises
    ``404 GROUND_TRUTH_MISSING`` (R11.4) — both via the error envelope.
    """
    record: GroundTruthRecord = {
        "title_id": body.title_id,
        "metrics": [
            GroundTruthMetric(
                metric_name=metric.metric_name,
                actual_value=metric.actual_value,
            )
            for metric in body.metrics
        ],
    }
    await module.persist_ground_truth(record)

    scorecard = await module.audit(body.title_id)
    return BacktestAuditResponse(
        title_id=scorecard["title_id"],
        metrics=[
            AuditMetricResponse(
                metric=row["metric"],
                predicted=row["predicted"],
                actual=row["actual"],
                excluded=row["excluded"],
            )
            for row in scorecard["metrics"]
        ],
        mape=scorecard["mape"],
        no_eligible_metrics=scorecard["no_eligible_metrics"],
    )


__all__ = ["router"]
