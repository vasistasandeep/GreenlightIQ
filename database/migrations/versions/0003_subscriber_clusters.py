"""subscriber_clusters: typed home for subscriber cohort preference vectors.

The Vector_Search_Engine (design R3, task 10.4) ranks a title's Narrative_DNA
against subscriber cluster *preference* vectors with pgvector's ``<=>`` cosine
operator (R3.1), returns results ranked by descending similarity (R3.2), and
returns an empty set with a ``NO_CLUSTERS`` status when the table is empty
(R3.3). The reference data lived only in the seed layer
(``database/seed/01_schema.sql``); this migration promotes the definition into
Alembic so the ORM model (``app.models.SubscriberCluster``) and the migration
history own the table too, matching the hand-written seed DDL exactly:

- UUID primary key defaulting to ``gen_random_uuid()``.
- ``cluster_name`` UNIQUE (``uq_subscriber_clusters_name``).
- a 1536-dim ``preference_vector`` in the same embedding space as
  ``metadata_vectors.narrative_dna`` (R17.6).
- an IVFFlat cosine index mirroring the one on ``metadata_vectors.narrative_dna``
  so similarity search uses the same operator class (R3.1).

Revision ID: 0003_subscriber_clusters
Revises: 0002_expanded_tables
Create Date: 2024-01-01 00:00:02.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_subscriber_clusters"
down_revision: Union[str, None] = "0002_expanded_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NARRATIVE_DNA_DIMENSIONS = 1536


def upgrade() -> None:
    # subscriber_clusters: subscriber cohort preference vectors (design R3).
    op.create_table(
        "subscriber_clusters",
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("cluster_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "preference_vector",
            Vector(NARRATIVE_DNA_DIMENSIONS),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("cluster_id"),
        sa.UniqueConstraint("cluster_name", name="uq_subscriber_clusters_name"),
    )
    # IVFFlat cosine index mirrors ix_metadata_vectors_narrative_dna_cosine so
    # cluster similarity search uses the same operator class (R3.1).
    op.create_index(
        "ix_subscriber_clusters_preference_cosine",
        "subscriber_clusters",
        ["preference_vector"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"preference_vector": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscriber_clusters_preference_cosine",
        table_name="subscriber_clusters",
    )
    op.drop_table("subscriber_clusters")
