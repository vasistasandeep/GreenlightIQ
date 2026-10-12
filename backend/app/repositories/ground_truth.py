"""Repository for ``historical_ground_truth`` (R11.1, R17.2).

Stores observed actual outcomes for a title used by the Backtesting_Module to
compute predictive variance (MAPE). Foreign key on ``title_id`` enforces
referential integrity (R17.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.historical_ground_truth import HistoricalGroundTruth
from app.repositories.base import BaseRepository


class GroundTruthRepository(BaseRepository[HistoricalGroundTruth]):
    """Async access to the ``historical_ground_truth`` table."""

    model = HistoricalGroundTruth
    pk = HistoricalGroundTruth.ground_truth_id

    async def list_for_title(
        self, title_id: uuid.UUID
    ) -> list[HistoricalGroundTruth]:
        """Return all recorded ground-truth metrics for a title."""
        stmt = select(HistoricalGroundTruth).where(
            HistoricalGroundTruth.title_id == title_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_metric(
        self, title_id: uuid.UUID, metric_name: str
    ) -> HistoricalGroundTruth | None:
        """Return the ground-truth entry for a title/metric pair, if any."""
        stmt = select(HistoricalGroundTruth).where(
            HistoricalGroundTruth.title_id == title_id,
            HistoricalGroundTruth.metric_name == metric_name,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
