"""Shared fixtures for schema-integrity integration tests (task 2.4).

The goal of these fixtures is to provide a *real* PostgreSQL 16 + pgvector
database whose schema is built by running the project's Alembic migrations
(``0001_core_tables`` and ``0002_expanded_tables``), so the tests verify the
exact DDL that ships with the system.

Database resolution order
-------------------------
1. An externally provided database via ``CINEROI_DATABASE_URL`` or
   ``TEST_DATABASE_URL`` (useful in CI where Postgres is a service container).
2. An ephemeral container started with ``testcontainers`` using the
   ``pgvector/pgvector:pg16`` image (requires a reachable Docker daemon).

If neither is available the whole module is **skipped** (never failed) so the
suite stays green in environments without Docker or a database -- matching the
task requirement that these tests skip gracefully.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# psycopg is a hard runtime dependency of the backend, but guard the import so
# collection never explodes if the environment is incomplete.
try:  # pragma: no cover - import guard
    import psycopg

    _HAS_PSYCOPG = True
except Exception:  # pragma: no cover - import guard
    psycopg = None  # type: ignore[assignment]
    _HAS_PSYCOPG = False


# Repository layout: backend/tests/integration/conftest.py -> project root is
# three parents up; the Alembic project lives under ``database/``.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATABASE_DIR = _PROJECT_ROOT / "database"
_ALEMBIC_INI = _DATABASE_DIR / "alembic.ini"


def _sqlalchemy_url_to_psycopg(url: str) -> str:
    """Strip the SQLAlchemy driver suffix so psycopg can connect directly.

    SQLAlchemy URLs look like ``postgresql+psycopg://user:pass@host/db``; the
    raw psycopg / libpq connection string wants ``postgresql://...``.
    """
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def _env_database_url() -> str | None:
    """Return an externally provided test database URL, if any."""
    for var in ("CINEROI_DATABASE_URL", "TEST_DATABASE_URL"):
        value = os.getenv(var)
        if value:
            return value
    return None


def _can_reach(psycopg_url: str) -> bool:
    """Return True if a psycopg connection to ``psycopg_url`` succeeds."""
    if not _HAS_PSYCOPG:
        return False
    try:
        with psycopg.connect(psycopg_url, connect_timeout=5) as conn:  # type: ignore[union-attr]
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _run_migrations(sqlalchemy_url: str) -> None:
    """Build the schema by running Alembic migrations to ``head``."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_DATABASE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    # env.py prefers CINEROI_DATABASE_URL; set it so both paths agree.
    os.environ["CINEROI_DATABASE_URL"] = sqlalchemy_url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Yield a psycopg connection string to a migrated Postgres+pgvector DB.

    Skips the entire test if no database can be provisioned or reached.
    """
    if not _HAS_PSYCOPG:
        pytest.skip("psycopg is not installed; cannot run schema integration tests")

    # --- Option 1: externally provided database -------------------------------
    env_url = _env_database_url()
    if env_url:
        psycopg_url = _sqlalchemy_url_to_psycopg(env_url)
        if not _can_reach(psycopg_url):
            pytest.skip(
                "A database URL was provided but the server is not reachable; "
                "skipping schema integration tests."
            )
        # Ensure the SQLAlchemy-style URL carries the +psycopg driver for Alembic.
        sqlalchemy_url = env_url
        if sqlalchemy_url.startswith("postgresql://"):
            sqlalchemy_url = sqlalchemy_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        _run_migrations(sqlalchemy_url)
        yield psycopg_url
        return

    # --- Option 2: ephemeral testcontainers Postgres + pgvector ---------------
    try:
        from testcontainers.postgres import PostgresContainer
    except Exception:
        pytest.skip(
            "testcontainers is not installed and no database URL was provided; "
            "skipping schema integration tests."
        )

    container = None
    try:
        container = PostgresContainer(
            image="pgvector/pgvector:pg16",
            username="cineroi",
            password="cineroi",
            dbname="cineroi",
            driver="psycopg",
        )
        container.start()
    except Exception as exc:  # Docker not running / image unavailable / offline
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(
            "Could not start a PostgreSQL+pgvector container (Docker may be "
            f"unavailable): {exc!r}"
        )

    try:
        sqlalchemy_url = container.get_connection_url()
        # Some testcontainers versions emit ``postgresql+psycopg2``; normalize.
        if "+psycopg2" in sqlalchemy_url:
            sqlalchemy_url = sqlalchemy_url.replace("+psycopg2", "+psycopg")
        _run_migrations(sqlalchemy_url)
        yield _sqlalchemy_url_to_psycopg(sqlalchemy_url)
    finally:
        container.stop()


@pytest.fixture()
def conn(postgres_url: str) -> Iterator["psycopg.Connection"]:
    """Yield a fresh autocommit-disabled psycopg connection per test.

    Each test manages its own transactions/rollbacks so a failed constraint in
    one test does not leak into the next.
    """
    connection = psycopg.connect(postgres_url)  # type: ignore[union-attr]
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
