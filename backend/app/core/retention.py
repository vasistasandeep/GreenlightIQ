"""Configurable data-retention policy: purge or archive eligible records (R28.3).

Each category of stored data (unreleased scripts, deal terms, PII, telemetry
cache, jobs, audit log) has a configurable retention window in days
(:attr:`~app.core.config.Settings.retention_periods_days`). When a record's age
exceeds its category's window the configured action applies: ``"purge"`` deletes
it, ``"archive"`` moves it to cold storage. The default action is
:attr:`~app.core.config.Settings.retention_default_action`.

This module provides the policy model and an async enforcement service that the
scheduled retention job (task 15 Celery beat / an operator-triggered sweep)
drives. It is intentionally data-model agnostic: callers register each
retention-eligible table as a :class:`RetentionTarget` describing the ORM model,
its timestamp column, its category, and an optional archive hook. The service
computes the cutoff per category and either deletes expired rows or hands them to
the archive hook before deleting them.

Audit-log safety (R25.2)
------------------------
The ``audit_log`` table is append-only and must never be purged; its policy is
pinned to ``archive`` and the service refuses to issue a DELETE against an
append-only target without a working archive hook.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.base import Base

__all__ = [
    "RetentionAction",
    "RetentionTarget",
    "RetentionResult",
    "RetentionError",
    "RetentionService",
]

log = get_logger("retention")


class RetentionAction(str, Enum):
    """What to do with a record whose retention window has elapsed."""

    PURGE = "purge"
    ARCHIVE = "archive"


class RetentionError(Exception):
    """Raised when a retention policy is misconfigured or cannot be enforced."""


#: An archive hook receives the expired rows about to be removed and is
#: responsible for persisting them to cold storage. It returns once the rows are
#: safely archived; the service then deletes them from the live table.
ArchiveHook = Callable[[Sequence[Any]], Awaitable[None]]


@dataclass(frozen=True)
class RetentionTarget:
    """A retention-eligible table and how to age its rows.

    Attributes:
        category: Key into ``retention_periods_days`` selecting the window.
        model: The ORM model class whose rows are swept.
        timestamp_column: The column used to measure a row's age (its creation
            or last-update time).
        append_only: When True the table must never be purged (e.g.
            ``audit_log``); the effective action is forced to ``ARCHIVE`` and a
            working ``archive_hook`` is required.
        archive_hook: Async callable that persists expired rows to cold storage
            before deletion. Required when the effective action is ``ARCHIVE``.
    """

    category: str
    model: type[Base]
    timestamp_column: InstrumentedAttribute[Any]
    append_only: bool = False
    archive_hook: ArchiveHook | None = field(default=None)


@dataclass(frozen=True)
class RetentionResult:
    """Outcome of enforcing retention for a single target."""

    category: str
    table: str
    action: RetentionAction
    cutoff: datetime | None
    examined: int
    affected: int
    skipped_reason: str | None = None


class RetentionService:
    """Enforces configurable retention windows across registered targets (R28.3).

    The service reads the per-category window and default action from
    :class:`~app.core.config.Settings`. For each registered
    :class:`RetentionTarget` it computes a cutoff (``now - window``), selects
    rows older than the cutoff, and either archives-then-deletes them or purges
    them outright. Categories with no configured window (``None``) are retained
    indefinitely and skipped.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        # Injectable clock keeps enforcement deterministic under test.
        self._now = now or datetime.now(timezone.utc)

    def _retention_days(self, category: str) -> int | None:
        """Return the configured retention window (days) for ``category``.

        ``None`` (or an absent key) means retain indefinitely.
        """
        return self.settings.retention_periods_days.get(category)

    def _effective_action(self, target: RetentionTarget) -> RetentionAction:
        """Resolve the action for a target, honoring append-only pinning."""
        if target.append_only:
            return RetentionAction.ARCHIVE
        return RetentionAction(self.settings.retention_default_action)

    def cutoff_for(self, category: str) -> datetime | None:
        """Return the cutoff timestamp for ``category`` (or ``None`` if unbounded).

        Rows whose timestamp is strictly older than the returned cutoff are
        eligible. ``None`` means the category is retained indefinitely.
        """
        days = self._retention_days(category)
        if days is None:
            return None
        return self._now - timedelta(days=days)

    async def enforce_target(self, target: RetentionTarget) -> RetentionResult:
        """Enforce retention for a single target and return the outcome.

        Flushes deletions to the current transaction but does not commit; the
        caller controls the unit-of-work boundary (so a sweep across targets is
        atomic or can be committed per-target as desired).
        """
        action = self._effective_action(target)
        table = target.model.__tablename__
        cutoff = self.cutoff_for(target.category)

        if cutoff is None:
            log.info(
                "retention_skip_unbounded", category=target.category, table=table
            )
            return RetentionResult(
                category=target.category,
                table=table,
                action=action,
                cutoff=None,
                examined=0,
                affected=0,
                skipped_reason="no_retention_window_configured",
            )

        if action is RetentionAction.ARCHIVE and target.archive_hook is None:
            raise RetentionError(
                f"Target {table!r} resolves to ARCHIVE but has no archive_hook; "
                "refusing to delete rows without first archiving them."
            )

        stmt = select(target.model).where(target.timestamp_column < cutoff)
        result = await self.session.execute(stmt)
        expired = list(result.scalars().all())

        if not expired:
            return RetentionResult(
                category=target.category,
                table=table,
                action=action,
                cutoff=cutoff,
                examined=0,
                affected=0,
            )

        if action is RetentionAction.ARCHIVE:
            # Archive first; only delete once cold storage confirms persistence.
            assert target.archive_hook is not None  # guarded above
            await target.archive_hook(expired)

        for row in expired:
            await self.session.delete(row)
        await self.session.flush()

        log.info(
            "retention_enforced",
            category=target.category,
            table=table,
            action=action.value,
            affected=len(expired),
            cutoff=cutoff.isoformat(),
        )
        return RetentionResult(
            category=target.category,
            table=table,
            action=action,
            cutoff=cutoff,
            examined=len(expired),
            affected=len(expired),
        )

    async def enforce(
        self, targets: Sequence[RetentionTarget]
    ) -> list[RetentionResult]:
        """Enforce retention across every target, returning per-target results."""
        results: list[RetentionResult] = []
        for target in targets:
            results.append(await self.enforce_target(target))
        return results
