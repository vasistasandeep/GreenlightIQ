"""Async SQLAlchemy engine and session factory (task 6).

Provides a single lazily-created async engine bound to
``Settings.database_url`` (``CINEROI_DATABASE_URL``) and an
:class:`async_sessionmaker` the repository layer and API dependencies use to
obtain :class:`~sqlalchemy.ext.asyncio.AsyncSession` instances.

The engine/sessionmaker are created lazily so importing this module (and the
repository package) never requires a live database connection — construction of
an engine does not open a connection until a session actually executes a
statement. This keeps ``python -c "import app.repositories"`` and unit tests
that use in-memory repository fakes free of any DB dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use.

    The engine is bound to ``CINEROI_DATABASE_URL`` (via :func:`get_settings`)
    and uses the async ``psycopg`` driver already declared as a dependency.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide :class:`async_sessionmaker`, creating it lazily."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional async session as a context manager.

    Commits on success and rolls back on any exception, then always closes the
    session. Suitable for background tasks and scripts.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    The caller (route/service) is responsible for committing; the session is
    always closed when the request finishes.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose of the engine and reset the cached factory (shutdown/tests)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
