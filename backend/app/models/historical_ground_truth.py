"""ORM model for the ``historical_ground_truth`` core table (R11.1, R17.2).

Stores actual observed outcomes for a title, used by the Backtesting_Module to
compute predictive variance (MAPE). Foreign key on ``title_id`` enforces
referential integrity to ``titles`` (R17.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk
from app.models.base import created_at_column


class HistoricalGroundTruth(Base):
    """A recorded actual-outcome metric for a historical title."""

    __tablename__ = "historical_ground_truth"

    ground_truth_id: Mapped[uuid.UUID] = uuid_pk()
    title_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("titles.title_id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    actual_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    recorded_at: Mapped[datetime] = created_at_column()
