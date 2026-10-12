"""Calibration router: apply auto-tuning from historical MAPE (R12, R16.3).

Exposes ``POST /calibration/apply`` from the design's "Added endpoints": the
Backtesting & Calibration Studio requests auto-tuning offsets derived from a
historical backtest's MAPE and, when the error exceeds the threshold, installs a
new immutable model version carrying the adjusted feature weights (R12.3, R16.3).

Flow
----
1. Authorize the actor for the calibrate operation (R20.1) — DATA_ANALYST /
   CHIEF_CONTENT_OFFICER / CFO.
2. Run a backtest audit for the supplied historical title to obtain its MAPE
   scorecard (R11).
3. Hand the scorecard to :class:`~app.engines.calibration.Calibration_Controller`:
   MAPE > 10% forks a new model version and reports the applied offsets (R12.3);
   MAPE ≤ 10% (or no eligible metrics) reports no adjustment and leaves the active
   weights unchanged (R12.5); out-of-range offsets are rejected as
   ``422 CALIBRATION_OUT_OF_RANGE`` with the prior weights preserved (R12.4).

The valuation stamp and immutability guarantees (R26.3) are owned by the
model-versioning engine the controller delegates to; this router only wires the
audit → calibrate flow and commits the unit of work.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rbac_service
from app.core.db import get_db_session
from app.core.security import UserContext
from app.engines.backtesting import Backtesting_Module
from app.engines.calibration import Calibration_Controller
from app.engines.model_versioning import ModelVersioningEngine
from app.engines.rbac import Operation, RBACService
from app.repositories.model_versions import ModelVersionRepository

router = APIRouter(prefix="/calibration", tags=["calibration"])


class CalibrationApplyRequest(BaseModel):
    """Request to apply auto-calibration from a historical title's audit (R16.3)."""

    title_id: uuid.UUID = Field(
        description="The historical title whose backtest MAPE drives calibration."
    )


class CalibrationApplyResponse(BaseModel):
    """The outcome of a calibration-apply request (R12.3, R12.5)."""

    adjustment_required: bool
    mape: Decimal | None = None
    new_model_version_id: uuid.UUID | None = None
    offsets: dict[str, Decimal] | None = None


@router.post("/apply", response_model=CalibrationApplyResponse)
async def apply_calibration(
    body: CalibrationApplyRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: UserContext = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac_service),
) -> CalibrationApplyResponse:
    """Audit a historical title and apply calibration when its MAPE is too high (R12, R16.3).

    Returns ``adjustment_required = True`` with the new model-version id and the
    applied weight offsets when a new version was forked (MAPE > 10%); otherwise
    reports no adjustment and leaves the active weights unchanged. Out-of-range
    offsets propagate as ``422 CALIBRATION_OUT_OF_RANGE`` (R12.4) and a missing
    title / ground truth propagates the backtesting module's not-found/validation
    envelope — in every rejecting case no new version is created.
    """
    rbac.authorize(actor, Operation.CALIBRATE, resource=body.title_id)

    # 1) Historical backtest audit -> MAPE scorecard (R11).
    scorecard = await Backtesting_Module(session).audit(body.title_id)

    # 2) Evaluate + apply calibration from the audit's MAPE (R12).
    controller = Calibration_Controller(
        ModelVersioningEngine(ModelVersionRepository(session))
    )
    result = await controller.evaluate_and_apply(_ScorecardView(scorecard), actor)

    await session.commit()

    return CalibrationApplyResponse(
        adjustment_required=result["adjustment_required"],
        mape=scorecard["mape"],
        new_model_version_id=result["new_model_version_id"],
        offsets=result["offsets"],
    )


class _ScorecardView:
    """Adapt the backtesting ``AuditScorecard`` dict to the controller's protocol.

    :class:`~app.engines.calibration.Calibration_Controller` depends only on a
    ``mape`` attribute (``AuditScorecardLike``); the backtesting module returns a
    TypedDict. This thin view bridges the two without coupling either engine to
    the other's concrete shape.
    """

    __slots__ = ("_mape",)

    def __init__(self, scorecard: dict) -> None:
        self._mape = scorecard.get("mape")

    @property
    def mape(self) -> Decimal | None:
        return self._mape
