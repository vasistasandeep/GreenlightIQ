"""ORM model for the ``exchange_rates`` expanded table (R21.4).

Stores dated normalization rates from a native currency to the base currency
(USD). ``(from_currency, to_currency, rate_date)`` is unique so a valuation can
look up a single rate for a given day (R21.4).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class ExchangeRate(Base):
    """A dated currency conversion rate into the base currency (R21.4)."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "from_currency",
            "to_currency",
            "rate_date",
            name="uq_exchange_rates_from_to_date",
        ),
    )

    exchange_rate_id: Mapped[uuid.UUID] = uuid_pk()
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
