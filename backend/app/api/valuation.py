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
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser,
    GuardrailsEngineDep,
    SessionDep,
    require_operation,
)
from app.core.errors import TitleNotFoundError
from app.domain import cohort, negotiation
from app.engines.guardrails import churn_model_json
from app.engines.rbac import Operation
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.metadata_vectors import MetadataVectorRepository
from app.repositories.titles import TitleRepository
from app.schemas.api import (
    BaselineSummary,
    ChurnCohortOut,
    ComparableTitlesResponse,
    CounterProposalLeverOut,
    LtvAttributionOut,
    ScenarioInputOverrides,
    ScenarioThresholdOverrides,
    WhatIfResponse,
    MetadataBreakdown,
    TitleCompOut,
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

    # calculable-churn-model (task 10, R7.3): the engine's in-memory Explanation
    # does not carry a churn_model key — that key is attached only by the persist
    # path's _jsonable_explanation when writing JSONB, not to the in-memory dict
    # the engine returns. Surface it here from the resolved churn detail so the
    # calculate response exposes the churn method, borderline flag, breakdown,
    # missing features, params source, and model_version_id (same shape persisted
    # under explanation["churn_model"]), mirroring the what-if route. The
    # response explanation stays a plain dict.
    explanation = _explanation_dict(result["explanation"])
    churn_detail = result.get("churn_detail")
    if churn_detail is not None:
        explanation = {
            **explanation,
            "churn_model": churn_model_json(
                churn_detail, result.get("model_version_id")
            ),
        }

    return ValuationSummaryResponse(
        title_id=result["title_id"],
        calculated_cpvh=result["calculated_cpvh"],
        ltv_to_cost_multiple=result["ltv_to_cost_multiple"],
        recommendation_status=str(result["recommendation_status"]),
        explanation=explanation,
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

    # Deal Decision Support, reconstructed from the persisted projection + its
    # stored explanation (GET /valuation does not re-run the engine). The LTV
    # attribution split is not persisted, so this path carries only the total /
    # cost / multiple (subscription vs advertising split is null here); the
    # quick-evaluate path, which has the raw inputs, carries the full split.
    checks = (projection.explanation or {}).get("checks", []) if isinstance(
        projection.explanation, dict
    ) else []
    cost = projection.normalized_cost_usd
    ceiling = negotiation.target_purchase_ceiling(cost, checks)
    discount = negotiation.implied_discount_pct(cost, ceiling)
    levers = [
        CounterProposalLeverOut(name=lv["name"], correctable=lv["correctable"], message=lv["message"])
        for lv in negotiation.counter_proposal_levers(checks)
    ]
    ltv_attr = None
    multiple = projection.ltv_to_cost_multiple
    if multiple is not None and cost is not None:
        ltv_attr = LtvAttributionOut(
            subscription_value=None,
            advertising_value=None,
            total_modeled_value=multiple * cost,
            normalized_cost_usd=cost,
            multiple=multiple,
        )
    cohort_size = cohort.derive_modeled_cohort_size(cost)
    churn_cohort = ChurnCohortOut(
        churn_reduction_pct=projection.churn_reduction_pct,
        modeled_cohort_size=cohort_size,
        retained_subscribers=cohort.retained_subscribers(
            cohort_size, projection.churn_reduction_pct
        ),
        derived=True,
    )

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
        target_purchase_ceiling_usd=ceiling,
        implied_discount_pct=discount,
        counter_proposal_levers=levers,
        ltv_attribution=ltv_attr,
        churn_cohort=churn_cohort,
        genre_tag=getattr(title, "genre_tag", None),
        primary_territory=_primary_territory(title),
    )


@router.get(
    "/{title_id}/comps",
    response_model=ComparableTitlesResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Return the Top-3 most similar titles by Narrative_DNA (R2.6).",
)
async def get_comparable_titles(
    title_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
) -> ComparableTitlesResponse:
    """Return the title's nearest neighbours by Narrative_DNA cosine similarity.

    Resolves the title's latest stored embedding, then ranks every other title's
    ``narrative_dna`` against it with pgvector's cosine-distance operator and
    returns the three most similar (R2.6). A missing title raises
    ``404 TITLE_NOT_FOUND`` (R10.3). A title with no stored embedding returns
    ``found=False`` with an empty list rather than a 404, so the UI can render a
    graceful empty state.
    """
    titles = TitleRepository(session)
    title = await titles.get(title_id)
    if title is None:
        raise TitleNotFoundError(
            f"No title exists for id {title_id!r}.",
            details={"title_id": str(title_id)},
        )

    vectors_repo = MetadataVectorRepository(session)
    vectors = await vectors_repo.list_for_title(title_id)
    if not vectors:
        return ComparableTitlesResponse(title_id=title_id, found=False, comps=[])

    # Rank against the most recent extraction, matching GET /valuation.
    vector = max(vectors, key=lambda v: v.created_at)
    neighbours = await vectors_repo.rank_similar_titles(
        vector.narrative_dna, exclude_title_id=title_id, limit=3
    )
    comps = [
        TitleCompOut(
            title_id=n.title_id,
            title_name=n.title_name,
            genre_tag=n.genre_tag,
            recommendation_status=n.recommendation_status,
            cosine_similarity=round(n.cosine_similarity, 4),
        )
        for n in neighbours
    ]
    return ComparableTitlesResponse(title_id=title_id, found=True, comps=comps)


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


def _primary_territory(title: object) -> str | None:
    """Return a title's first target territory, if any (for telemetry lookup)."""
    raw = getattr(title, "target_territories", None)
    if isinstance(raw, dict):
        if isinstance(raw.get("territories"), list) and raw["territories"]:
            return str(raw["territories"][0])
        return next((str(k) for k in raw.keys()), None)
    if isinstance(raw, (list, tuple)) and raw:
        return str(raw[0])
    return None


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


class WhatIfRequest(BaseModel):
    """Bounded scenario multipliers for POST /valuation/{title_id}/what-if (R4).

    Each multiplier is strictly positive and within the inclusive demo range
    [0.5, 2.0]; the range includes 1.0 (the identity scenario). churn_multiplier
    defaults to 1.0 when omitted (R1.5).
    """

    cost_multiplier: Decimal = Field(..., gt=Decimal("0"), ge=Decimal("0.5"), le=Decimal("2.0"))
    viewership_multiplier: Decimal = Field(
        ..., gt=Decimal("0"), ge=Decimal("0.5"), le=Decimal("2.0")
    )
    churn_multiplier: Decimal = Field(
        default=Decimal("1.0"), gt=Decimal("0"), ge=Decimal("0.5"), le=Decimal("2.0")
    )
    # WhatIf_Explorer: optional direct overrides (range-validated by their
    # schemas). Absent => Baseline. Direct overrides win over multipliers (R1.6).
    input_overrides: ScenarioInputOverrides | None = None
    threshold_overrides: ScenarioThresholdOverrides | None = None


@router.post(
    "/{title_id}/what-if",
    response_model=WhatIfResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Recompute a scorecard over scenario overrides + multipliers without persisting (R1-R4).",
)
async def what_if_valuation(
    title_id: uuid.UUID,
    body: WhatIfRequest,
    actor: CurrentUser,
    session: SessionDep,
    engine: GuardrailsEngineDep,
) -> WhatIfResponse:
    """Return a freshly computed Scenario scorecard plus the Baseline, read-only.

    Delegates to the engine's non-persisting ``evaluate_scenario``; writes
    nothing and records no audit entry (R2). Computes the Baseline once at
    identity (no overrides, multipliers 1.0) for the Scenario_Diff, then the
    Scenario from the request overrides. A missing title raises
    ``404 TITLE_NOT_FOUND`` (R1.3); invalid overrides are rejected ``422`` by the
    request model before this handler runs (R4.6).
    """
    # Baseline: identity scenario (no overrides) -> the Scenario_Diff reference
    # and the Target Deal negotiation ceiling (WhatIf_Explorer R2, R3.4, R4.4).
    baseline_result = await engine.evaluate_scenario(
        title_id,
        cost_multiplier=Decimal("1"),
        viewership_multiplier=Decimal("1"),
        churn_multiplier=Decimal("1"),
    )
    b_expl = baseline_result["explanation"]
    b_checks = b_expl["checks"] if isinstance(b_expl, dict) else []
    baseline = BaselineSummary(
        recommendation_status=str(baseline_result["recommendation_status"]),
        calculated_cpvh=baseline_result["calculated_cpvh"],
        ltv_to_cost_multiple=baseline_result["ltv_to_cost_multiple"],
        churn_reduction_pct=baseline_result["churn_reduction_pct"],
        payback_horizon_months=baseline_result["payback_horizon_months"],
        ltv_subscription_value=baseline_result.get("ltv_subscription_value"),
        ltv_advertising_value=baseline_result.get("ltv_advertising_value"),
        explanation=b_expl if isinstance(b_expl, dict) else None,
        inputs=baseline_result.get("inputs_snapshot"),
    )
    negotiation_ceiling = negotiation.target_purchase_ceiling(
        baseline_result["normalized_cost_usd"], b_checks
    )

    result = await engine.evaluate_scenario(
        title_id,
        cost_multiplier=body.cost_multiplier,
        viewership_multiplier=body.viewership_multiplier,
        churn_multiplier=body.churn_multiplier,
        input_overrides=body.input_overrides,
        threshold_overrides=body.threshold_overrides,
    )

    explanation = result["explanation"]
    checks = explanation["checks"] if isinstance(explanation, dict) else []

    # calculable-churn-model (task 7, R7.5/R7.6): the engine's in-memory
    # Explanation does not carry a churn_model key (that key is attached only by
    # the persist path's _jsonable_explanation). Surface it here from the
    # scenario churn detail so the read-only what-if response exposes the scaled
    # churn method, the recomputed Borderline_Sensitivity flag, and a null
    # churn_breakdown (omitted for a scaled scenario). This persists nothing.
    churn_detail = result.get("churn_detail")
    if isinstance(explanation, dict) and churn_detail is not None:
        explanation = {
            **explanation,
            "churn_model": churn_model_json(
                churn_detail, result["model_version_id"]
            ),
        }
    cost = result["normalized_cost_usd"]
    ceiling = negotiation.target_purchase_ceiling(cost, checks)
    discount = negotiation.implied_discount_pct(cost, ceiling)
    levers = [
        CounterProposalLeverOut(name=lv["name"], correctable=lv["correctable"], message=lv["message"])
        for lv in negotiation.counter_proposal_levers(checks)
    ]
    ltv_attr = None
    if result["ltv_to_cost_multiple"] is not None:
        ltv_attr = LtvAttributionOut(
            subscription_value=result.get("ltv_subscription_value"),
            advertising_value=result.get("ltv_advertising_value"),
            total_modeled_value=result.get("ltv_total_modeled_value"),
            normalized_cost_usd=cost,
            multiple=result["ltv_to_cost_multiple"],
        )
    churn_cohort = ChurnCohortOut(
        churn_reduction_pct=result.get("churn_reduction_pct"),
        modeled_cohort_size=result.get("modeled_cohort_size"),
        retained_subscribers=result.get("retained_subscribers"),
        derived=True,
    )

    # No session.commit(): the scenario path is strictly read-only (R2).
    return WhatIfResponse(
        title_id=title_id,
        calculated_cpvh=result["calculated_cpvh"],
        ltv_to_cost_multiple=result["ltv_to_cost_multiple"],
        churn_reduction_pct=result["churn_reduction_pct"],
        payback_horizon_months=result["payback_horizon_months"],
        recommendation_status=result["recommendation_status"],
        normalized_cost_usd=cost,
        model_version_id=result["model_version_id"],
        explanation=explanation if isinstance(explanation, dict) else None,
        metadata_breakdown=await _metadata_breakdown(session, title_id),
        target_purchase_ceiling_usd=ceiling,
        implied_discount_pct=discount,
        counter_proposal_levers=levers,
        ltv_attribution=ltv_attr,
        churn_cohort=churn_cohort,
        baseline=baseline,
        negotiation_ceiling_usd=negotiation_ceiling,
    )


__all__ = ["router"]
