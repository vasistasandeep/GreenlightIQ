"""ORM model for the ``metadata_vectors`` core table (R2.6, R17.2, R17.6).

Stores the extracted semantic profile for a title: a 1536-dimension Narrative_DNA
embedding (R17.6, pgvector ``VECTOR(1536)``), affective tone triggers (R2.3), and
the talent-pedigree / production-scale scores (R2.4, R2.5). Foreign key on
``title_id`` enforces referential integrity to ``titles`` (R17.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Numeric, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk

NARRATIVE_DNA_DIMENSIONS = 1536


class MetadataVector(Base):
    """Extracted metadata profile and embedding for a title."""

    __tablename__ = "metadata_vectors"
    __table_args__ = (
        CheckConstraint(
            "talent_pedigree_score BETWEEN 0.00 AND 10.00",
            name="ck_metadata_vectors_talent_pedigree_range",
        ),
        CheckConstraint(
            "production_scale_metric BETWEEN 0.00 AND 10.00",
            name="ck_metadata_vectors_production_scale_range",
        ),
        CheckConstraint(
            "extraction_status IN ('SUCCESS', 'FAILED')",
            name="ck_metadata_vectors_extraction_status",
        ),
    )

    metadata_id: Mapped[uuid.UUID] = uuid_pk()
    title_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("titles.title_id", ondelete="CASCADE"),
        nullable=False,
    )
    # FK -> title_versions wired in task 2.2 (R24.3).
    title_version_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "title_versions.title_version_id",
            name="fk_metadata_vectors_title_version_id",
        ),
        nullable=True,
    )
    narrative_dna: Mapped[list[float]] = mapped_column(
        Vector(NARRATIVE_DNA_DIMENSIONS), nullable=False
    )
    affective_primary: Mapped[str] = mapped_column(Text, nullable=False)
    affective_secondary: Mapped[str] = mapped_column(Text, nullable=False)
    talent_pedigree_score: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    production_scale_metric: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    # FK -> model_versions wired in task 2.2.
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "model_versions.model_version_id",
            name="fk_metadata_vectors_model_version_id",
        ),
        nullable=True,
    )
    extraction_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
