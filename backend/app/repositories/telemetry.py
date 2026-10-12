"""Repository for ``market_telemetry_cache`` (R13.2, R13.4).

Caches external market telemetry keyed uniquely by ``(genre_tag, territory)``.
Exposes an upsert-style accessor to look up an existing cache row for a
genre/territory pair so callers can refresh it in place (R13.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.market_telemetry_cache import MarketTelemetryCache
from app.repositories.base import BaseRepository


class TelemetryRepository(BaseRepository[MarketTelemetryCache]):
    """Async access to the ``market_telemetry_cache`` table."""

    model = MarketTelemetryCache
    pk = MarketTelemetryCache.telemetry_id

    async def get_for_genre_territory(
        self, genre_tag: str, territory: str
    ) -> MarketTelemetryCache | None:
        """Return the cached telemetry row for a genre/territory pair (R13.2)."""
        stmt = select(MarketTelemetryCache).where(
            MarketTelemetryCache.genre_tag == genre_tag,
            MarketTelemetryCache.territory == territory,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert(
        self,
        *,
        genre_tag: str,
        territory: str,
        social_sentiment_index: Decimal | None = None,
        chart_velocity_score: Decimal | None = None,
        licensing_inflation_multiplier: Decimal | None = None,
        source_available: bool = True,
    ) -> MarketTelemetryCache:
        """Insert or refresh the cache row for a ``(genre_tag, territory)`` pair (R13.2).

        Looks up the existing row via the unique ``(genre_tag, territory)`` key.
        If present, the supplied indices and ``source_available`` are assigned in
        place and ``last_updated_at`` is refreshed; otherwise a new row is
        created. Index arguments left as ``None`` are only written through on an
        insert — on an update, a ``None`` is treated as "no fresh reading" and the
        prior cached value is retained (R13.4). Pass explicit values to overwrite.

        Returns the managed, flushed :class:`MarketTelemetryCache` instance.
        """
        existing = await self.get_for_genre_territory(genre_tag, territory)
        now = datetime.now(timezone.utc)

        if existing is None:
            instance = MarketTelemetryCache(
                genre_tag=genre_tag,
                territory=territory,
                social_sentiment_index=social_sentiment_index,
                chart_velocity_score=chart_velocity_score,
                licensing_inflation_multiplier=licensing_inflation_multiplier,
                source_available=source_available,
                last_updated_at=now,
            )
            return await self.create(instance)

        # Refresh in place; retain prior values for any index not freshly read.
        if social_sentiment_index is not None:
            existing.social_sentiment_index = social_sentiment_index
        if chart_velocity_score is not None:
            existing.chart_velocity_score = chart_velocity_score
        if licensing_inflation_multiplier is not None:
            existing.licensing_inflation_multiplier = licensing_inflation_multiplier
        existing.source_available = source_available
        existing.last_updated_at = now
        await self.session.flush()
        return existing

    async def mark_source_unavailable(
        self, genre_tag: str, territory: str
    ) -> MarketTelemetryCache | None:
        """Record a source as unavailable while retaining cached values (R13.4).

        Flips ``source_available`` to ``False`` on the existing row for the
        ``(genre_tag, territory)`` pair without touching the cached indices, so
        the last-known values survive the failed poll. Returns the updated row,
        or ``None`` when no cache row exists yet (nothing to retain).
        """
        existing = await self.get_for_genre_territory(genre_tag, territory)
        if existing is None:
            return None
        existing.source_available = False
        await self.session.flush()
        return existing
