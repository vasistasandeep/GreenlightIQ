"""ORM model for the ``financial_projections`` core table.

Holds the guardrail outputs for a title: CPVH, LTV-to-cost multiple, churn
reduction, payback horizon, and the final recommendation status (R4.8, R5.4,
R7.4, R8.6). ``recommendation_status`` is constrained to the enumerated set
(R17.5) and the foreign key on ``title_id`` enforces integrity to ``titles``
(R17.2). ``calculated_cpvh`` is nullable (null when viewing hours = 0, R4.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk

RECOMMENDATION_STATUSES = ("GREENLIGHT", "NEGOTIATE_HARD", "PASS")


class FinancialProjection(Base):
    """Computed financial scorecard and recommendation for a title."""

    __tablename__ = "financial_projections"
    __table_args__ = (
        CheckConstraint(
            "recommendation_status IN ('GREENLIGHT', 'NEGOTIATE_HARD', 'PASS')",
            name="ck_financial_projections_recommendation_status",
        ),
    )

    projection_id: Mapped[uuid.UUID] = uuid_pk()
    title_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("titles.title_id", ondelete="CASCADE"),
        nullable=False,
    )
    # FK -> title_versions wired in task 2.2.
    title_version_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "title_versions.title_version_id",
            name="fk_financial_projections_title_version_id",
        ),
        nullable=True,
    )
    calculated_cpvh: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    ltv_to_cost_multiple: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    churn_reduction_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    payback_horizon_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2), nullable=True
    )
    # FK -> exchange_rates wired in task 2.2 (R21.4).
    exchange_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "exchange_rates.exchange_rate_id",
            name="fk_financial_projections_exchange_rate_id",
        ),
        nullable=True,
    )
    # FK -> model_versions wired in task 2.2; NOT NULL per design (R25.3, R26.2).
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "model_versions.model_version_id",
            name="fk_financial_projections_model_version_id",
        ),
        nullable=False,
    )
    explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    row_version: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
