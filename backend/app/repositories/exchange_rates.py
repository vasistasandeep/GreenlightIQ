"""Repository for ``exchange_rates`` (R21.4).

Stores dated normalization rates from a native currency to the base currency
(USD). ``(from_currency, to_currency, rate_date)`` is unique, so valuation can
look up a single rate for a given day (R21.4).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.exchange_rate import ExchangeRate
from app.repositories.base import BaseRepository


class ExchangeRateRepository(BaseRepository[ExchangeRate]):
    """Async access to the ``exchange_rates`` table (R21.4)."""

    model = ExchangeRate
    pk = ExchangeRate.exchange_rate_id

    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRate | None:
        """Return the dated rate for a currency pair, if available (R21.4, R21.5)."""
        stmt = select(ExchangeRate).where(
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.rate_date == rate_date,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_latest_rate(
        self, from_currency: str, to_currency: str
    ) -> ExchangeRate | None:
        """Return the most recent dated rate for a currency pair, if any."""
        stmt = (
            select(ExchangeRate)
            .where(
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == to_currency,
            )
            .order_by(ExchangeRate.rate_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
