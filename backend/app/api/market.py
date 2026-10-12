"""Market router: cached telemetry retrieval (task 16.1).

``GET /market/telemetry?genre=&territory=`` (R13.3) returns the cached market
telemetry indices for a genre/territory pair. The read is synchronous: it serves
the ``market_telemetry_cache`` snapshot maintained by the background
``poll_telemetry`` task. When a source was unavailable on the last poll the
indices are retained-but-stale and the response flags ``source_available=false``
(R13.4); a pair that has never been polled returns ``found=false``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, TelemetryConnectorDep, require_operation
from app.engines.rbac import Operation
from app.schemas.api import MarketTelemetryResponse

router = APIRouter(prefix="/market", tags=["market"])


@router.get(
    "/telemetry",
    response_model=MarketTelemetryResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Return cached market telemetry for a genre/territory pair (R13.3).",
)
async def get_market_telemetry(
    actor: CurrentUser,
    connector: TelemetryConnectorDep,
    genre: str = Query(..., description="The genre_tag to look up."),
    territory: str = Query(..., description="The territory code to look up."),
) -> MarketTelemetryResponse:
    """Return the cached telemetry snapshot filtered by genre + territory (R13.3)."""
    snapshot = await connector.get_telemetry(genre, territory)
    return MarketTelemetryResponse(
        genre_tag=snapshot.genre_tag,
        territory=snapshot.territory,
        social_sentiment_index=snapshot.social_sentiment_index,
        chart_velocity_score=snapshot.chart_velocity_score,
        licensing_inflation_multiplier=snapshot.licensing_inflation_multiplier,
        source_available=snapshot.source_available,
        found=snapshot.found,
    )


__all__ = ["router"]
