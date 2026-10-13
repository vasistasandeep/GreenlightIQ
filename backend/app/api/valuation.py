"""Valuation router: single-title calculation and scorecard retrieval (task 16.1).

Two endpoints make up the valuation surface:

* ``POST /valuation/calculate`` (R9) — runs the Guardrails_Engine inline. The
  valuation is pure in-memory math over already-persisted inputs and completes
  well within the 5-second persistence bound (R8.6), so it is synchronous. It
  writes the projection, stamps the active model version, and records an
  append-only audit entry, returning the computed CPVH, LTV-to-cost multiple,
  recommendation, and structured explanation (R9.2, R30.4). A missing title maps
  to ``404 TITLE_NOT_FOUND`` (R9.3).
* ``GET /valuation/{title_id}`` (R10) — returns the full persisted scorecard plus
  the metadata-vector breakdown and the explanation (R10.1, R10.2, R30.4). A
  missing title (or a title with no computed valuation) maps to
  ``404 TITLE_NOT_FOUND`` (R10.3).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import (
    CurrentUser,
    GuardrailsEngineDep,
    SessionDep,
    require_operation,
)
from app.core.errors import TitleNotFoundError
from app.engines.rbac import Operation
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.metadata_vectors import MetadataVectorRepository
from app.repositories.titles import TitleRepository
from app.schemas.api import (
    MetadataBreakdown,
    ValuationCalculateRequest,
    ValuationScorecardResponse,
    ValuationSummaryResponse,
)

router = APIRouter(prefix="/valuation", tags=["valuation"])


@router.post(
    "/calculate",
    response_model=ValuationSummaryResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Compute a single-title valuation inline (R9.2, R30.4).",
)
async def calculate_valuation(
    body: ValuationCalculateRequest,
    actor: CurrentUser,
    engine: GuardrailsEngineDep,
) -> ValuationSummaryResponse:
    """Run all guardrails for a title and return the recommendation (R9.2, R30.4).

    The Guardrails_Engine normalizes cost to USD, runs the CPVH/LTV/churn/payback
    checks, determines the recommendation, persists the scorecard, and writes the
    audit entry — all within this request's transaction. A missing title raises
    ``404 TITLE_NOT_FOUND`` (R9.3); a missing exchange rate raises
    ``422 EXCHANGE_RATE_UNAVAILABLE`` — both surfaced through the error envelope.
    """
    result = await engine.evaluate(
        body.title_id,
        body.model_version_id,
        actor=actor.user_id,
    )
    return ValuationSummaryResponse(
        title_id=result["title_id"],
        calculated_cpvh=result["calculated_cpvh"],
        ltv_to_cost_multiple=result["ltv_to_cost_multiple"],
        recommendation_status=str(result["recommendation_status"]),
        explanation=_explanation_dict(result["explanation"]),
    )


@router.get(
    "/{title_id}",
    response_model=ValuationScorecardResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Return the full valuation scorecard + metadata breakdown (R10, R30.4).",
)
async def get_valuation(
    title_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
) -> ValuationScorecardResponse:
    """Return the persisted scorecard, metadata breakdown, and explanation (R10).

    Raises ``404 TITLE_NOT_FOUND`` when the title does not exist or has no
    computed valuation yet (R10.3).
    """
    titles = TitleRepository(session)
    title = await titles.get(title_id)
    if title is None:
        raise TitleNotFoundError(
            f"No title exists for id {title_id!r}.",
            details={"title_id": str(title_id)},
        )

    projection = await FinancialProjectionRepository(session).get_latest_for_title(
        title_id
    )
    if projection is None:
        raise TitleNotFoundError(
            "No computed valuation exists for this title yet.",
            details={"title_id": str(title_id)},
        )

    breakdown = await _metadata_breakdown(session, title_id)

    return ValuationScorecardResponse(
        title_id=title_id,
        calculated_cpvh=projection.calculated_cpvh,
        ltv_to_cost_multiple=projection.ltv_to_cost_multiple,
        churn_reduction_pct=projection.churn_reduction_pct,
        payback_horizon_months=projection.payback_horizon_months,
        recommendation_status=projection.recommendation_status,
        normalized_cost_usd=projection.normalized_cost_usd,
        model_version_id=projection.model_version_id,
        explanation=projection.explanation,
        metadata_breakdown=breakdown,
    )


class TitleDecisionResponse(BaseModel):
    """The decision (latest financial projection) id for a title (R20.5).

    The sign-off / finalization endpoints key on a
    ``financial_projections.projection_id`` ("the decision"), not on a title id.
    This resolves a title to its most recent decision so a title-centric view
    (e.g. the Backtesting Studio) can look up finalization status.
    """

    title_id: uuid.UUID
    decision_id: uuid.UUID


@router.get(
    "/{title_id}/decision",
    response_model=TitleDecisionResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Resolve a title to its latest decision (projection) id (R20.5).",
)
async def get_title_decision(
    title_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
) -> TitleDecisionResponse:
    """Return the latest decision id for a title, or 404 when none exists.

    Raises ``404 TITLE_NOT_FOUND`` when the title does not exist or has no
    computed valuation yet, mirroring ``GET /valuation/{title_id}`` (R10.3).
    """
    titles = TitleRepository(session)
    title = await titles.get(title_id)
    if title is None:
        raise TitleNotFoundError(
            f"No title exists for id {title_id!r}.",
            details={"title_id": str(title_id)},
        )

    projection = await FinancialProjectionRepository(session).get_latest_for_title(
        title_id
    )
    if projection is None:
        raise TitleNotFoundError(
            "No computed valuation exists for this title yet.",
            details={"title_id": str(title_id)},
        )

    return TitleDecisionResponse(
        title_id=title_id,
        decision_id=projection.projection_id,
    )


async def _metadata_breakdown(
    session: SessionDep, title_id: uuid.UUID
) -> MetadataBreakdown | None:
    """Project the title's latest metadata vector into the response breakdown (R10.2)."""
    vectors = await MetadataVectorRepository(session).list_for_title(title_id)
    if not vectors:
        return None
    # Prefer the most recent extraction by creation time.
    vector = max(vectors, key=lambda v: v.created_at)
    narrative = getattr(vector, "narrative_dna", None)
    dimensions = (
        len(narrative)
        if isinstance(narrative, (list, tuple))
        else (NARRATIVE_DNA_DIMENSIONS if narrative is not None else None)
    )
    return MetadataBreakdown(
        affective_primary=vector.affective_primary,
        affective_secondary=vector.affective_secondary,
        talent_pedigree_score=vector.talent_pedigree_score,
        production_scale_metric=vector.production_scale_metric,
        narrative_dna_dimensions=dimensions,
        extraction_status=vector.extraction_status,
    )


def _explanation_dict(explanation: object) -> dict:
    """Normalize the engine's structured explanation into a JSON-able dict (R30.4).

    The Guardrails_Engine builds a dataclass/TypedDict ``Explanation``; routers
    return a plain mapping so the response is pure JSON. A mapping passes through
    unchanged; a dataclass is converted field-wise.
    """
    if isinstance(explanation, dict):
        return explanation
    if hasattr(explanation, "_asdict"):
        return explanation._asdict()  # type: ignore[no-any-return]
    if hasattr(explanation, "__dict__"):
        return dict(vars(explanation))
    return {"explanation": str(explanation)}


__all__ = ["router"]
