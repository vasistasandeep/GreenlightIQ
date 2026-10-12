"""Database initialization + mock-seed runner (Requirement 17.7, 18.4).

This is the one-command entry point to bring an empty PostgreSQL 16 + pgvector
database to a fully seeded state:

  1. Run the Alembic migrations (``alembic upgrade head``) to build the canonical
     relational schema (titles, metadata_vectors, financial_projections, users,
     model_versions, exchange_rates, ... — owned by database/migrations).
  2. Apply ``01_schema.sql`` to enable pgvector and create the seed-provided
     ``subscriber_clusters`` table (preference vectors for the Vector_Search_Engine,
     design R3 — no cluster table exists in the migrations).
  3. Apply the generated ``02_seed_data.sql`` to load mock data: one user per
     role, an active model version, exchange rates, titles across every asset
     type with vectors + projections + license terms, and cluster preference
     vectors.

Usage::

    # uses CINEROI_DATABASE_URL (same env var the Alembic env.py reads)
    python database/seed/seed.py

    # skip migrations if the schema already exists
    python database/seed/seed.py --skip-migrations

    # only emit the SQL that would run, without connecting (offline check)
    python database/seed/seed.py --dry-run

The database URL resolution matches ``database/migrations/env.py``:
``CINEROI_DATABASE_URL`` first, falling back to the ``alembic.ini`` placeholder.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATABASE_DIR = HERE.parent
ALEMBIC_INI = DATABASE_DIR / "alembic.ini"
SCHEMA_SQL = HERE / "01_schema.sql"
SEED_SQL = HERE / "02_seed_data.sql"

_INI_URL_FALLBACK = "postgresql+psycopg://cineroi:cineroi@localhost:5432/cineroi"


def database_url() -> str:
    """Resolve the DB URL exactly like the Alembic environment does."""
    url = os.getenv("CINEROI_DATABASE_URL")
    if url:
        return url
    # Mirror env.py's fallback to the alembic.ini placeholder.
    try:
        import configparser

        cfg = configparser.ConfigParser()
        cfg.read(ALEMBIC_INI)
        return cfg.get("alembic", "sqlalchemy.url", fallback=_INI_URL_FALLBACK)
    except Exception:
        return _INI_URL_FALLBACK


def run_migrations() -> None:
    """Invoke ``alembic upgrade head`` from the database/ directory."""
    print("==> Running Alembic migrations (alembic upgrade head)")
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(DATABASE_DIR),
        check=True,
    )


def apply_sql(engine, path: Path) -> None:
    """Execute a .sql file against a live SQLAlchemy engine.

    This function is the single owner of the transaction boundary: the whole
    script runs inside one ``engine.begin()`` block that commits on success and
    rolls back on error. The seed .sql files therefore MUST NOT emit their own
    BEGIN/COMMIT — an inner COMMIT would close this transaction early and leave
    the remaining statements running outside any transaction, which breaks the
    container-startup initialization promised by R18.4.
    """
    sql = path.read_text(encoding="utf-8")
    print(f"==> Applying {path.name} ({len(sql)} bytes)")
    with engine.begin() as conn:
        # Hand the whole multi-statement script to the DBAPI so every statement
        # runs within this single transaction.
        conn.exec_driver_sql(sql)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Initialize and seed the database.")
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not run Alembic; assume the schema already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and verify the SQL files exist without connecting.",
    )
    args = parser.parse_args(argv)

    if not SCHEMA_SQL.exists():
        print(f"Missing {SCHEMA_SQL}", file=sys.stderr)
        return 1
    if not SEED_SQL.exists():
        print(
            f"Missing {SEED_SQL} — run `python database/seed/generate_seed_sql.py`.",
            file=sys.stderr,
        )
        return 1

    url = database_url()

    if args.dry_run:
        print("Dry run — no database connection will be opened.")
        print(f"  database url     : {url}")
        print(f"  run migrations   : {not args.skip_migrations}")
        print(f"  schema script    : {SCHEMA_SQL}")
        print(f"  seed script      : {SEED_SQL}")
        return 0

    if not args.skip_migrations:
        run_migrations()

    from sqlalchemy import create_engine

    engine = create_engine(url, future=True)
    try:
        apply_sql(engine, SCHEMA_SQL)
        apply_sql(engine, SEED_SQL)
    finally:
        engine.dispose()

    print("==> Database initialized and seeded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
