"""Dashboard router: the Executive Command Dashboard aggregate (R14.1, R14.2).

Exposes ``GET /dashboard/summary`` - the single payload the frontend Executive
Command Dashboard renders: the four KPI header figures (R14.1) and the master
asset-grid rows (R14.2). It aggregates every pipeline title with its latest
persisted financial projection into the ``{kpis, titles}`` contract the typed
API client expects.

Read-only aggregate: this endpoint performs no state change and is intentionally
left unauthenticated so the dashboard landing view can render the portfolio at a
glance. Per-title detail, calculation, and all state-changing operations remain
behind the authenticated/authorized routers.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.domain.accuracy import actual_verdict, verdict_match_rate
from app.domain.cpvh import AssetType, cpvh_breaches, cpvh_ceiling
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.ground_truth import GroundTruthRepository
from app.repositories.titles import TitleRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardKpis(BaseModel):
    """KPI header-card figures for the dashboard (R14.1). ``None`` when uncomputable."""

    active_pipeline_valuation_usd: float | None = None
    avg_ltv_to_cost: float | None = None
    portfolio_risk_exposure: float | None = None
    model_accuracy_rate: float | None = None


class TitleSummary(BaseModel):
    """One master-grid row: title identity plus latest valuation outcome (R14.2)."""

    title_id: str
    title_name: str
    asset_type: str
    asking_price: float
    native_currency: str
    cpvh_status: str
    ltv_to_cost_multiple: float | None = None
    payback_horizon_months: int | None = None
    recommendation_status: str | None = None
    deal_stage: str = "SCREENING"


class DashboardSummaryResponse(BaseModel):
    """Aggregate dashboard payload: KPI figures + grid rows (R14)."""

    kpis: DashboardKpis
    titles: list[TitleSummary]


def _cpvh_status(asset_type: str, cpvh: Decimal | None) -> str:
    """Derive the grid CPVH badge from the computed value and asset ceiling (R4)."""
    if cpvh is None:
        return "PENDING"
    try:
        ceiling = cpvh_ceiling(AssetType(asset_type))
    except ValueError:
        return "NO_CEILING"
    if ceiling is None:
        return "NO_CEILING"
    return "BREACH" if cpvh_breaches(cpvh, ceiling) else "PASS"


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(session: SessionDep) -> DashboardSummaryResponse:
    """Return the Executive Command Dashboard aggregate (R14.1, R14.2).

    Joins every pipeline title to its most recent financial projection, derives
    the per-title CPVH badge, and rolls the set up into the four KPI figures.
    """
    titles_repo = TitleRepository(session)
    projections_repo = FinancialProjectionRepository(session)
    ground_truth_repo = GroundTruthRepository(session)

    titles = await titles_repo.list()

    rows: list[TitleSummary] = []
    total_valuation = Decimal("0")
    ltv_values: list[Decimal] = []
    non_greenlight = 0
    valued = 0
    # (predicted_verdict, actual_verdict) pairs for every title that has ground
    # truth; the accuracy rate is the verdict-match rate over the eligible subset.
    verdict_pairs: list[tuple[str | None, str | None]] = []

    for title in titles:
        projection = await projections_repo.get_latest_for_title(title.title_id)

        cpvh = projection.calculated_cpvh if projection else None
        ltv = projection.ltv_to_cost_multiple if projection else None
        payback = getattr(projection, "payback_horizon_months", None) if projection else None
        recommendation = projection.recommendation_status if projection else None

        # Verdict-match accuracy basis: only titles that actually have observed
        # outcomes (ground truth) contribute. The actual verdict is recomputed
        # from the actual metric values; absent/partial ground truth yields None
        # (excluded), and a null predicted verdict is also excluded downstream.
        truths = await ground_truth_repo.list_for_title(title.title_id)
        if truths:
            latest_actuals: dict[str, Decimal] = {}
            latest_recorded: dict[str, object] = {}
            for truth in truths:
                name = truth.metric_name
                recorded = truth.recorded_at
                if (
                    name not in latest_recorded
                    or recorded is None
                    or latest_recorded[name] is None
                    or recorded >= latest_recorded[name]
                ):
                    latest_actuals[name] = Decimal(truth.actual_value)
                    latest_recorded[name] = recorded
            verdict_pairs.append(
                (recommendation, actual_verdict(title.asset_type, latest_actuals))
            )

        if projection is not None:
            valued += 1
            cost = projection.normalized_cost_usd
            if cost is None:
                cost = title.acquisition_cost_or_budget
            total_valuation += Decimal(cost)
            if ltv is not None:
                ltv_values.append(Decimal(ltv))
            if recommendation and recommendation != "GREENLIGHT":
                non_greenlight += 1

        rows.append(
            TitleSummary(
                title_id=str(title.title_id),
                title_name=title.title_name,
                asset_type=title.asset_type,
                asking_price=float(title.acquisition_cost_or_budget),
                native_currency=title.native_currency,
                cpvh_status=_cpvh_status(title.asset_type, cpvh),
                ltv_to_cost_multiple=float(ltv) if ltv is not None else None,
                payback_horizon_months=int(payback) if payback is not None else None,
                recommendation_status=recommendation,
                deal_stage=getattr(title, "deal_stage", None) or "SCREENING",
            )
        )

    kpis = DashboardKpis(
        active_pipeline_valuation_usd=(
            float(total_valuation) if valued else None
        ),
        avg_ltv_to_cost=(
            float(sum(ltv_values) / len(ltv_values)) if ltv_values else None
        ),
        portfolio_risk_exposure=(
            round(non_greenlight / valued, 4) if valued else None
        ),
        # Verdict-match rate over titles with observed outcomes (ground truth);
        # null when no eligible title exists, never a fabricated value.
        model_accuracy_rate=verdict_match_rate(verdict_pairs),
    )

    return DashboardSummaryResponse(kpis=kpis, titles=rows)


__all__ = ["router"]