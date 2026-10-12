"""ORM model for the ``subscriber_clusters`` table (design R3, R3.1-R3.3).

Each row is a subscriber cohort with a 1536-dimension *preference* embedding in
the **same** vector space as ``metadata_vectors.narrative_dna``, so the
Vector_Search_Engine (``app/engines/vector_search.py``) can rank a title's
Narrative_DNA against cohorts using pgvector's ``<=>`` cosine-distance operator
(R3.1) and return results ranked by descending cosine similarity (R3.2). When no
rows exist the engine returns an empty set with a ``NO_CLUSTERS`` status (R3.3).

Provenance
----------
This table was introduced by the seed layer (``database/seed/01_schema.sql``)
so R17.7 and the Vector_Search_Engine's reference data were satisfied before the
engine existed. The seed README flagged a follow-up: *promote the definition
into a formal Alembic migration once the engine is built so the ORM and
migration history own it too.* Task 10.4 does exactly that — this model plus
migration ``0003_subscriber_clusters`` make the table a first-class,
typed, queryable member of the stack, matching the hand-written seed DDL
(same columns, UNIQUE on ``cluster_name``, and the IVFFlat cosine index).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS


class SubscriberCluster(Base):
    """A subscriber cohort and its 1536-dim preference vector (design R3)."""

    __tablename__ = "subscriber_clusters"
    __table_args__ = (
        UniqueConstraint("cluster_name", name="uq_subscriber_clusters_name"),
        # IVFFlat cosine index mirrors the one on metadata_vectors.narrative_dna
        # so similarity search over clusters uses the same operator class (R3.1).
        Index(
            "ix_subscriber_clusters_preference_cosine",
            "preference_vector",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"preference_vector": "vector_cosine_ops"},
        ),
    )

    cluster_id: Mapped[uuid.UUID] = uuid_pk()
    cluster_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    preference_vector: Mapped[list[float]] = mapped_column(
        Vector(NARRATIVE_DNA_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
