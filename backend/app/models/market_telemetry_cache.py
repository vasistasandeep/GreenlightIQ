"""ORM model for the ``market_telemetry_cache`` core table (R13.2).

Caches external market telemetry (social sentiment, chart velocity, licensing
inflation) keyed uniquely by ``(genre_tag, territory)`` for upserts (R13.2).
``source_available`` records whether the last poll succeeded (R13.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk


class MarketTelemetryCache(Base):
    """Cached market telemetry indices for a genre/territory pair."""

    __tablename__ = "market_telemetry_cache"
    __table_args__ = (
        UniqueConstraint(
            "genre_tag", "territory", name="uq_market_telemetry_genre_territory"
        ),
    )

    telemetry_id: Mapped[uuid.UUID] = uuid_pk()
    genre_tag: Mapped[str] = mapped_column(Text, nullable=False)
    territory: Mapped[str] = mapped_column(String(2), nullable=False)
    social_sentiment_index: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    chart_velocity_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    licensing_inflation_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    source_available: Mapped[bool] = mapped_column(
        nullable=False, server_default="true"
    )
    last_updated_at: Mapped[datetime] = created_at_column()
