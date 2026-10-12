"""Optimistic-lock conflict-rejection integration test (task 6.3).

Exercises the real optimistic-locking path (R27.2) end-to-end against a live
PostgreSQL 16 + pgvector database provisioned by ``conftest.py`` (via
testcontainers or an externally supplied ``CINEROI_DATABASE_URL`` /
``TEST_DATABASE_URL``). The test skips cleanly when no database is available.

Property 34 (Optimistic-lock conflict rejection): given two updates racing on
the same ``titles`` row, the first update succeeds and increments
``row_version``; the second update, submitted with the now-stale
``expected_version``, is rejected with :class:`OptimisticLockError`
(``error_code == "STALE_VERSION"``). This matches the acceptance criterion
R27.2 — a valuation update against a stale title version is rejected via
optimistic locking and surfaces a conflict error.

The test drives :class:`app.repositories.titles.TitleRepository` over async
SQLAlchemy sessions (``app.core.db`` sessionmaker shape) bound to the same
database the sync conftest fixture provisioned. Because the global
``app.core.db`` engine is bound to ``CINEROI_DATABASE_URL`` (which the conftest
sets to the provisioned DB while running migrations), we build a dedicated
async engine from the provisioned URL here so the test is self-contained and
does not depend on process-global engine state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

try:  # pragma: no cover - import guard; conftest skips when missing
    import psycopg  # noqa: F401

    _HAS_PSYCOPG = True
except Exception:  # pragma: no cover - import guard
    psycopg = None  # type: ignore[assignment]
    _HAS_PSYCOPG = False

try:  # pragma: no cover - import guard
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    _HAS_SQLALCHEMY_ASYNC = True
except Exception:  # pragma: no cover - import guard
    AsyncSession = None  # type: ignore[assignment,misc]
    async_sessionmaker = None  # type: ignore[assignment]
    create_async_engine = None  # type: ignore[assignment]
    _HAS_SQLALCHEMY_ASYNC = False

from app.models.title import Title
from app.repositories.base import OptimisticLockError
from app.repositories.titles import TitleRepository

pytestmark = pytest.mark.integration


def _psycopg_url_to_async_sqlalchemy(url: str) -> str:
    """Convert a raw psycopg/libpq URL into an async SQLAlchemy URL.

    The conftest ``postgres_url`` fixture yields a ``postgresql://...`` libpq
    string; SQLAlchemy's async engine needs the ``postgresql+psycopg://``
    driver prefix (psycopg 3 supports async natively).
    """
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture()
async def async_sessionmaker_factory(
    postgres_url: str,
) -> "AsyncIterator[async_sessionmaker[AsyncSession]]":
    """Yield an async sessionmaker bound to the provisioned test database.

    Builds a dedicated async engine from the (migrated) database URL the sync
    conftest fixture provisioned, so the async repository code runs against the
    exact same schema. Skips cleanly if async SQLAlchemy is unavailable, and
    always disposes the engine on teardown.
    """
    if not _HAS_SQLALCHEMY_ASYNC:  # pragma: no cover - env guard
        pytest.skip("async SQLAlchemy is not available; cannot run async DB test")

    async_url = _psycopg_url_to_async_sqlalchemy(postgres_url)
    engine = create_async_engine(async_url, future=True, pool_pre_ping=True)
    factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    try:
        yield factory
    finally:
        await engine.dispose()


def _new_title() -> Title:
    """Build a minimal valid, unpersisted ``titles`` ORM instance.

    Satisfies the NOT NULL / CHECK constraints: valid enumerated asset_type,
    in-range acquisition cost, 3-char currency, and JSONB territories. The
    server populates ``title_id`` and ``row_version`` (defaults to 0).
    """
    return Title(
        title_name="Optimistic Lock Test Title",
        asset_type="ORIGINAL_FILM",
        acquisition_cost_or_budget=Decimal("1000000.00"),
        native_currency="USD",
        target_territories=["US"],
    )


# Feature: cineroi-ai, Property 34: Optimistic-lock conflict rejection
async def test_optimistic_lock_conflict_rejects_stale_update(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R27.2 / Property 34: a stale-version update is rejected with a conflict.

    Scenario (two concurrent writers on one ``titles`` row):

    1. Seed a title; it starts at ``row_version == 0``.
    2. Writer A reads version 0 and updates with ``expected_version == 0`` ->
       succeeds and the stored ``row_version`` advances to 1.
    3. Writer B still believes the row is at version 0 (its read is now stale)
       and updates with ``expected_version == 0`` -> rejected with
       :class:`OptimisticLockError` (``STALE_VERSION``), and the row is
       unchanged by B (still version 1, carrying A's write).
    """
    # 1) Seed a title and commit so independent sessions observe it.
    async with async_sessionmaker_factory() as seed_session:
        repo = TitleRepository(seed_session)
        title = await repo.create(_new_title())
        await seed_session.commit()
        title_id = title.title_id
        assert title.row_version == 0

    # 2) Writer A: update with the current (expected) version 0 -> succeeds.
    async with async_sessionmaker_factory() as session_a:
        repo_a = TitleRepository(session_a)
        updated = await repo_a.update_with_version(
            title_id,
            expected_version=0,
            title_name="Updated By Writer A",
        )
        await session_a.commit()
        assert updated is not None
        assert updated.row_version == 1
        assert updated.title_name == "Updated By Writer A"

    # 3) Writer B: still holds the stale version 0 -> rejected.
    async with async_sessionmaker_factory() as session_b:
        repo_b = TitleRepository(session_b)
        with pytest.raises(OptimisticLockError) as exc_info:
            await repo_b.update_with_version(
                title_id,
                expected_version=0,
                title_name="Updated By Writer B",
            )
        await session_b.rollback()

    err = exc_info.value
    assert err.error_code == "STALE_VERSION"
    assert err.entity == "titles"
    assert err.entity_id == title_id
    assert err.expected_version == 0

    # The conflicting write must not have taken effect: A's write survives and
    # the row remains at version 1.
    async with async_sessionmaker_factory() as verify_session:
        repo_v = TitleRepository(verify_session)
        final = await repo_v.get(title_id)
        assert final is not None
        assert final.row_version == 1
        assert final.title_name == "Updated By Writer A"


# Feature: cineroi-ai, Property 34: Optimistic-lock conflict rejection
async def test_optimistic_lock_allows_sequential_fresh_updates(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R27.2 / Property 34 (positive control): fresh-version updates chain.

    Confirms the lock only rejects *stale* writes: when each writer supplies the
    current ``row_version``, successive updates succeed and monotonically
    increment the version (0 -> 1 -> 2). This guards against a false-positive
    where every update is rejected.
    """
    async with async_sessionmaker_factory() as seed_session:
        repo = TitleRepository(seed_session)
        title = await repo.create(_new_title())
        await seed_session.commit()
        title_id = title.title_id

    async with async_sessionmaker_factory() as session_1:
        repo_1 = TitleRepository(session_1)
        first = await repo_1.update_with_version(
            title_id, expected_version=0, title_name="v1"
        )
        await session_1.commit()
        assert first.row_version == 1

    async with async_sessionmaker_factory() as session_2:
        repo_2 = TitleRepository(session_2)
        second = await repo_2.update_with_version(
            title_id, expected_version=1, title_name="v2"
        )
        await session_2.commit()
        assert second.row_version == 2
        assert second.title_name == "v2"
