# Database seed & initialization (Requirement 17.7)

Scripts that build the full schema and load mock seed data so a fresh
PostgreSQL 16 + pgvector instance comes up ready to use. On `docker compose up`
these are what initialize the database (Requirement 18.4).

## Files

| File | Purpose |
|---|---|
| `seed.py` | One-command runner: runs migrations, then applies the SQL below. |
| `01_schema.sql` | Enables `pgvector` and creates the `subscriber_clusters` table. |
| `02_seed_data.sql` | **Generated** mock data (users, model version, rates, titles, vectors, clusters). |
| `generate_seed_sql.py` | Regenerates `02_seed_data.sql` deterministically. |

## Quick start

```bash
# point at your database (same variable the Alembic env.py reads)
export CINEROI_DATABASE_URL=postgresql+psycopg://cineroi:cineroi@localhost:5432/cineroi

# build schema (alembic upgrade head) + apply 01_schema.sql + 02_seed_data.sql
python database/seed/seed.py
```

Useful flags:

- `--skip-migrations` — the relational schema already exists; only apply the
  seed SQL.
- `--dry-run` — print the plan and verify the SQL files exist without opening a
  connection.

### Pure-SQL path (e.g. a Postgres docker-entrypoint)

If you prefer to drive initialization with `psql` and the schema is already
migrated, apply the files in order:

```bash
alembic -c database/alembic.ini upgrade head
psql "$CINEROI_DATABASE_URL" -f database/seed/01_schema.sql
psql "$CINEROI_DATABASE_URL" -f database/seed/02_seed_data.sql
```

Both SQL files are **idempotent**: `01_schema.sql` uses `CREATE ... IF NOT
EXISTS`, and `02_seed_data.sql` uses deterministic primary keys with
`ON CONFLICT DO NOTHING`, so re-running them is safe.

## What gets seeded

- **Users — one per role** (R20.1): `DATA_ANALYST`, `CONTENT_BUYER`,
  `CHIEF_CONTENT_OFFICER`, `CFO`, each with authorized territories.
- **One active model version** (R12.2, R26.1): `talent_pedigree_weight` +
  `narrative_trope_weight = 1.00`, `is_active = TRUE`, with guardrail
  parameters.
- **Exchange rates** (R21.4): dated USD normalization rates for USD/INR/EUR/GBP.
- **Titles** across every `asset_type` (R17.4), each with an active
  `title_version`, a `metadata_vectors` row holding a **1536-dim Narrative_DNA
  vector** (R17.6), a `financial_projections` row stamped with the active model
  version, and `license_terms` (R22).
- **Subscriber cluster preference vectors** — four cohorts, each with a
  **1536-dim preference vector** for similarity matching (see below).

## Why a `subscriber_clusters` table?

The Vector_Search_Engine (design R3) ranks a title's Narrative_DNA against
"subscriber cluster preference vectors" and returns `SimilarityResult` rows
keyed by `cluster_id`. The Alembic migrations (`0001_core_tables`,
`0002_expanded_tables`) define every table in the Data Models section **except**
a cluster table — there is no home for those preference vectors.

Rather than overload `metadata_vectors` (which requires a `title_id` FK and
affective-tone fields that make no sense for a cohort), `01_schema.sql` creates
a dedicated, minimal `subscriber_clusters` table in the **same 1536-dim embedding
space**, with an IVFFlat cosine index that mirrors the one on
`metadata_vectors.narrative_dna`. The engine queries it with pgvector's `<=>`
cosine-distance operator:

```sql
SELECT cluster_id,
       1 - (preference_vector <=> :title_vec) AS cosine_similarity
FROM subscriber_clusters
ORDER BY preference_vector <=> :title_vec;   -- ascending distance = descending similarity
```

An empty table yields an empty result set with the `NO_CLUSTERS` status (R3.3).

> **Follow-up:** this table is introduced by the seed layer so R17.7 and R3 are
> satisfied today. When the Vector_Search_Engine is implemented (task 10.4),
> promote this definition into a formal Alembic migration so the ORM and
> migration history own it too. Until then the seed script is the single source
> of truth for `subscriber_clusters`.

## Regenerating the seed data

`02_seed_data.sql` is generated so the 1536-dimension vector literals stay out
of hand-maintained SQL. The generator uses a fixed RNG seed, so output is
byte-stable:

```bash
python database/seed/generate_seed_sql.py          # rewrite the SQL
python database/seed/generate_seed_sql.py --check   # CI: fail if out of date
```

Edit the seed definitions (users, titles, clusters, ...) near the top of
`generate_seed_sql.py`, then regenerate.
