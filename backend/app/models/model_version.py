"""ORM model for the ``model_versions`` expanded table (R26, R12.2).

Model versions are immutable rows — calibration never mutates weights in place;
it inserts a new version with ``supersedes_id`` pointing at the prior one and
flips ``is_active`` (R26.1, R26.3, R26.4). A partial unique index guarantees
exactly one active version. A CHECK enforces that the two coupled feature
weights sum to exactly 1.00 (R12.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk


class ModelVersion(Base):
    """An immutable feature-extraction weight set + guardrail parameters."""

    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(
            "talent_pedigree_weight BETWEEN 0.00 AND 1.00",
            name="ck_model_versions_talent_pedigree_weight_range",
        ),
        CheckConstraint(
            "narrative_trope_weight BETWEEN 0.00 AND 1.00",
            name="ck_model_versions_narrative_trope_weight_range",
        ),
        CheckConstraint(
            "talent_pedigree_weight + narrative_trope_weight = 1.00",
            name="ck_model_versions_weights_sum",
        ),
        # Partial unique index: at most one active model version at a time.
        Index(
            "uq_model_versions_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    model_version_id: Mapped[uuid.UUID] = uuid_pk()
    talent_pedigree_weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False
    )
    narrative_trope_weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False
    )
    guardrail_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("model_versions.model_version_id"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at_column()
