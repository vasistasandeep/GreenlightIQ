"""Core tables: titles, metadata_vectors, financial_projections,
historical_ground_truth, market_telemetry_cache.

Enables the pgvector extension (R17.6) and creates the five core tables with
UUID primary keys (R17.1), foreign keys on title_id (R17.2), target_territories
JSONB (R17.3), asset_type / recommendation_status enum CHECKs (R17.4, R17.5),
the acquisition_cost_or_budget range CHECK (R1.8), the (genre_tag, territory)
unique key on telemetry (R13.2), and an IVFFlat cosine index on the 1536-dim
narrative_dna vector (R3.1).

Revision ID: 0001_core_tables
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_core_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension required for VECTOR(1536) storage (R17.6).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- titles (R17.1, R17.3, R17.4) ---
    op.create_table(
        "titles",
        sa.Column(
            "title_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_name", sa.Text(), nullable=False),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("acquisition_cost_or_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("native_currency", sa.String(length=3), nullable=False),
        sa.Column("target_territories", postgresql.JSONB(), nullable=False),
        sa.Column("genre_tag", sa.Text(), nullable=True),
        sa.Column("projected_viewing_hours", sa.Numeric(16, 2), nullable=True),
        sa.Column(
            "is_historical",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("title_id"),
        sa.CheckConstraint(
            "asset_type IN ('ORIGINAL_SERIES', 'ORIGINAL_FILM', "
            "'LICENSED_LIBRARY', 'CO_PRODUCTION')",
            name="ck_titles_asset_type",
        ),
        sa.CheckConstraint(
            "acquisition_cost_or_budget BETWEEN 0.01 AND 999999999.99",
            name="ck_titles_acquisition_cost_range",
        ),
    )

    # --- metadata_vectors (R2.6, R17.2, R17.6) ---
    op.create_table(
        "metadata_vectors",
        sa.Column(
            "metadata_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("narrative_dna", Vector(1536), nullable=False),
        sa.Column("affective_primary", sa.Text(), nullable=False),
        sa.Column("affective_secondary", sa.Text(), nullable=False),
        sa.Column("talent_pedigree_score", sa.Numeric(4, 2), nullable=True),
        sa.Column("production_scale_metric", sa.Numeric(4, 2), nullable=True),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extraction_status", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("metadata_id"),
        sa.ForeignKeyConstraint(
            ["title_id"], ["titles.title_id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "talent_pedigree_score BETWEEN 0.00 AND 10.00",
            name="ck_metadata_vectors_talent_pedigree_range",
        ),
        sa.CheckConstraint(
            "production_scale_metric BETWEEN 0.00 AND 10.00",
            name="ck_metadata_vectors_production_scale_range",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('SUCCESS', 'FAILED')",
            name="ck_metadata_vectors_extraction_status",
        ),
    )
    # IVFFlat cosine index for pgvector similarity search (R3.1).
    op.create_index(
        "ix_metadata_vectors_narrative_dna_cosine",
        "metadata_vectors",
        ["narrative_dna"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"narrative_dna": "vector_cosine_ops"},
    )

    # --- financial_projections (R4.8, R5.4, R7.4, R8.6, R17.2, R17.5) ---
    op.create_table(
        "financial_projections",
        sa.Column(
            "projection_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("calculated_cpvh", sa.Numeric(10, 4), nullable=True),
        sa.Column("ltv_to_cost_multiple", sa.Numeric(10, 4), nullable=True),
        sa.Column("churn_reduction_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("payback_horizon_months", sa.Integer(), nullable=True),
        sa.Column("recommendation_status", sa.Text(), nullable=True),
        sa.Column("normalized_cost_usd", sa.Numeric(16, 2), nullable=True),
        sa.Column("exchange_rate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("explanation", postgresql.JSONB(), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("projection_id"),
        sa.ForeignKeyConstraint(
            ["title_id"], ["titles.title_id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "recommendation_status IN ('GREENLIGHT', 'NEGOTIATE_HARD', 'PASS')",
            name="ck_financial_projections_recommendation_status",
        ),
    )

    # --- historical_ground_truth (R11.1, R17.2) ---
    op.create_table(
        "historical_ground_truth",
        sa.Column(
            "ground_truth_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("actual_value", sa.Numeric(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ground_truth_id"),
        sa.ForeignKeyConstraint(
            ["title_id"], ["titles.title_id"], ondelete="CASCADE"
        ),
    )

    # --- market_telemetry_cache (R13.2) ---
    op.create_table(
        "market_telemetry_cache",
        sa.Column(
            "telemetry_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("genre_tag", sa.Text(), nullable=False),
        sa.Column("territory", sa.String(length=2), nullable=False),
        sa.Column("social_sentiment_index", sa.Numeric(6, 2), nullable=True),
        sa.Column("chart_velocity_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("licensing_inflation_multiplier", sa.Numeric(6, 3), nullable=True),
        sa.Column(
            "source_available",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("telemetry_id"),
        sa.UniqueConstraint(
            "genre_tag", "territory", name="uq_market_telemetry_genre_territory"
        ),
    )


def downgrade() -> None:
    op.drop_table("market_telemetry_cache")
    op.drop_table("historical_ground_truth")
    op.drop_table("financial_projections")
    op.drop_index(
        "ix_metadata_vectors_narrative_dna_cosine",
        table_name="metadata_vectors",
    )
    op.drop_table("metadata_vectors")
    op.drop_table("titles")
    op.execute("DROP EXTENSION IF EXISTS vector")
