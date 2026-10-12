-- =============================================================================
-- CineROI AI — schema initialization (Requirement 17.7, 18.4)
-- =============================================================================
--
-- This script makes the database ready for the mock seed data in
-- 02_seed_data.sql. It is intentionally idempotent (safe to re-run).
--
-- Scope of THIS file:
--   1. Enable the pgvector extension (also done by Alembic migration
--      0001_core_tables; repeated here so the SQL path works standalone,
--      e.g. a Postgres docker-entrypoint that only runs /database/seed/*.sql).
--   2. Create the `subscriber_clusters` table that holds subscriber cluster
--      preference vectors for the Vector_Search_Engine (design R3 /
--      SimilarityResult.cluster_id). The existing Alembic migrations
--      (0001_core_tables, 0002_expanded_tables) define every other table but
--      do NOT define a cluster table, so the preference vectors need a home.
--      See seed/README.md for the rationale and the follow-up migration note.
--
-- The core/expanded relational schema itself (titles, metadata_vectors,
-- financial_projections, users, model_versions, exchange_rates, ...) is owned
-- by Alembic. The recommended, canonical way to build it is:
--
--     alembic upgrade head
--
-- (or `python database/seed/seed.py`, which runs the migrations for you and
-- then applies these SQL files). This file deliberately does not recreate the
-- Alembic-owned tables so the two sources of truth never drift.
-- =============================================================================

-- pgvector is required for VECTOR(1536) storage and cosine search (R17.6, R3.1).
CREATE EXTENSION IF NOT EXISTS vector;

-- gen_random_uuid() lives in pgcrypto on older servers; harmless on PG 16+
-- where it is built in. Enables UUID PK defaults for the cluster table.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- subscriber_clusters (seed-provided; design R3 Vector_Search_Engine)
-- -----------------------------------------------------------------------------
-- Each row is a subscriber cohort with a 1536-dim preference vector in the same
-- embedding space as metadata_vectors.narrative_dna, so the Vector_Search_Engine
-- can rank titles against cohorts with pgvector cosine distance:
--
--     SELECT cluster_id, 1 - (preference_vector <=> :title_vec) AS cosine_similarity
--     FROM subscriber_clusters
--     ORDER BY preference_vector <=> :title_vec;   -- ascending distance = descending similarity
--
-- When no rows exist the engine returns an empty set with NO_CLUSTERS (R3.3).
CREATE TABLE IF NOT EXISTS subscriber_clusters (
    cluster_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_name      TEXT        NOT NULL,
    description       TEXT        NULL,
    preference_vector VECTOR(1536) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_subscriber_clusters_name UNIQUE (cluster_name)
);

-- IVFFlat cosine index mirrors the metadata_vectors index so similarity search
-- over clusters uses the same operator class (R3.1).
CREATE INDEX IF NOT EXISTS ix_subscriber_clusters_preference_cosine
    ON subscriber_clusters
    USING ivfflat (preference_vector vector_cosine_ops)
    WITH (lists = 100);
