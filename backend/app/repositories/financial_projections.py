"""Repository for ``financial_projections`` (R17.2, R17.5, R27.2).

Holds the computed guardrail scorecard for a title. Like ``titles`` it carries a
``row_version`` column, so :meth:`update_with_version` (inherited) provides the
optimistic-lock-aware update path mapped to ``409 STALE_VERSION`` (R27.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.financial_projection import FinancialProjection
from app.repositories.base import BaseRepository


class FinancialProjectionRepository(BaseRepository[FinancialProjection]):
    """Async access to ``financial_projections`` (optimistic-lock aware)."""

    model = FinancialProjection
    pk = FinancialProjection.projection_id

    async def list_for_title(
        self, title_id: uuid.UUID
    ) -> list[FinancialProjection]:
        """Return all projections for a title, newest first."""
        stmt = (
            select(FinancialProjection)
            .where(FinancialProjection.title_id == title_id)
            .order_by(FinancialProjection.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_title(
        self, title_id: uuid.UUID
    ) -> FinancialProjection | None:
        """Return the most recent projection for a title, if any."""
        stmt = (
            select(FinancialProjection)
            .where(FinancialProjection.title_id == title_id)
            .order_by(FinancialProjection.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
