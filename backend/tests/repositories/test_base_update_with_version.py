"""DB-less unit tests for BaseRepository.update_with_version statement building.

Regression guard for a bug where the versioned-update path accessed the primary
key as ``self.pk`` (off the repository *instance*). ``pk`` is a class attribute
holding a SQLAlchemy ``InstrumentedAttribute``; reading it from an instance
re-invokes the attribute descriptor against the repository - not a mapped ORM
object - raising ``UnmappedInstanceError`` before any SQL runs. That broke every
optimistic-locked update (e.g. recomputing a valuation for a title that already
has a stored projection). These tests build the UPDATE statement against a fake
session (no database), so they catch the regression in any environment.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models.financial_projection import FinancialProjection
from app.repositories.base import OptimisticLockError
from app.repositories.financial_projections import FinancialProjectionRepository


class _FakeResult:
    """Mimics the subset of a SQLAlchemy Result the repo reads: rowcount."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """Captures the statement passed to execute() without touching a database.

    ``rowcount`` controls whether the versioned update is treated as a hit (1)
    or a stale-version miss (0). ``get`` returns a sentinel so the post-update
    refresh path is exercised without a real identity map.
    """

    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executed: list[Any] = []
        self.refreshed: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        # The statement must COMPILE - this is what regressed. Compiling against
        # the Postgres dialect forces the WHERE/VALUES clauses to render.
        from sqlalchemy.dialects import postgresql

        stmt.compile(dialect=postgresql.dialect())
        self.executed.append(stmt)
        return _FakeResult(self.rowcount)

    async def flush(self) -> None:
        return None

    async def get(self, model: Any, entity_id: Any) -> Any:
        return object()  # non-None so refresh runs

    async def refresh(self, instance: Any) -> None:
        self.refreshed.append(instance)


async def test_update_with_version_builds_statement_without_descriptor_error() -> None:
    """A versioned update compiles its UPDATE and returns the refreshed row.

    Before the fix this raised ``UnmappedInstanceError`` at statement-build time
    because the pk column was read off the repository instance.
    """
    session = _FakeSession(rowcount=1)
    repo = FinancialProjectionRepository(session)  # type: ignore[arg-type]

    result = await repo.update_with_version(
        uuid.uuid4(),
        expected_version=0,
        recommendation_status="GREENLIGHT",
    )

    assert result is not None
    assert len(session.executed) == 1
    # The compiled statement targets the right table and pk column.
    compiled = str(session.executed[0])
    assert "financial_projections" in compiled
    assert "projection_id" in compiled
    assert "row_version" in compiled


async def test_update_with_version_raises_on_stale_version() -> None:
    """A zero-rowcount update (stale version) raises OptimisticLockError."""
    session = _FakeSession(rowcount=0)
    repo = FinancialProjectionRepository(session)  # type: ignore[arg-type]

    entity_id = uuid.uuid4()
    with pytest.raises(OptimisticLockError) as exc:
        await repo.update_with_version(
            entity_id, expected_version=3, recommendation_status="PASS"
        )

    assert exc.value.error_code == "STALE_VERSION"
    assert exc.value.entity == FinancialProjection.__tablename__
    assert exc.value.expected_version == 3


async def test_update_with_version_rejects_table_without_row_version() -> None:
    """Guards the precondition: a model lacking row_version is rejected early."""
    # ExchangeRate has no row_version column; pick any such repo.
    from app.repositories.exchange_rates import ExchangeRateRepository

    session = _FakeSession()
    repo = ExchangeRateRepository(session)  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        await repo.update_with_version(uuid.uuid4(), expected_version=0)