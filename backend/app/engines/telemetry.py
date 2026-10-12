"""Telemetry_Connector: pluggable market-telemetry polling and retrieval (R13).

The connector keeps the ``market_telemetry_cache`` table fresh with external
market signals — social sentiment, chart velocity, and licensing inflation —
keyed by ``(genre_tag, territory)`` (R13.2). Each external signal is a pluggable
:class:`TelemetrySource` implementing a common async interface, so new sources
can be added without touching the orchestration (per the design's "pluggable
``TelemetrySource`` interface" note).

Polling (R13.1)
---------------
:meth:`TelemetryConnector.poll` fans out across the configured sources
concurrently (``asyncio.gather``) and upserts whatever readings come back,
each keyed by its ``(genre_tag, territory)`` pair (R13.2).

Source unavailability (R13.4)
-----------------------------
A source that raises :class:`TelemetrySourceUnavailable` (or any exception)
during a poll does not fail the whole cycle and does not overwrite good data:
for every ``(genre_tag, territory)`` the failed source was expected to cover,
the connector retains the last cached values and flips ``source_available`` to
``False`` on the existing cache row (R13.4). Sources that succeed are applied
normally in the same cycle.

Retrieval (R13.3)
-----------------
:meth:`TelemetryConnector.get_telemetry` reads the cached row for a
``(genre_tag, territory)`` pair and returns a :class:`TelemetrySnapshot`,
including the ``source_available`` flag so callers can tell live data from a
retained-but-stale cache.

The connector is a thin orchestration layer over :class:`TelemetryRepository`;
it holds the injected :class:`~sqlalchemy.ext.asyncio.AsyncSession` only to flush
upserts and does not open a database connection on import.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.telemetry import TelemetryRepository

__all__ = [
    "TelemetryReading",
    "TelemetrySnapshot",
    "TelemetrySource",
    "TelemetrySourceUnavailable",
    "TelemetryConnector",
]

_log = get_logger("telemetry")


class TelemetrySourceUnavailable(Exception):
    """Raised by a :class:`TelemetrySource` when its backing feed cannot be read.

    Signals that the external source was unreachable or returned an error for
    this poll. The connector responds by retaining the last cached values and
    marking the affected cache rows as unavailable rather than discarding data
    (R13.4). The ``coverage`` attribute (optional) lists the
    ``(genre_tag, territory)`` pairs the source would have refreshed, so the
    connector knows which rows to flag even though the fetch produced nothing.
    """

    def __init__(
        self,
        message: str,
        *,
        coverage: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.coverage = coverage or []


@dataclass(frozen=True)
class TelemetryReading:
    """One source's fresh reading for a single ``(genre_tag, territory)`` pair.

    A source emits zero or more readings per poll. Any index left as ``None`` is
    treated as "no fresh value from this source" and the prior cached value is
    retained on upsert (R13.2, R13.4); a source therefore only needs to populate
    the indices it actually owns.
    """

    genre_tag: str
    territory: str
    social_sentiment_index: Decimal | None = None
    chart_velocity_score: Decimal | None = None
    licensing_inflation_multiplier: Decimal | None = None


@dataclass(frozen=True)
class TelemetrySnapshot:
    """The cached telemetry for a ``(genre_tag, territory)`` pair (R13.3).

    Mirrors the ``market_telemetry_cache`` row. ``found`` is ``False`` when no
    cache row exists yet for the pair; ``source_available`` reflects whether the
    most recent poll that touched this row succeeded (R13.4) — ``False`` means
    the values are retained-but-stale.
    """

    genre_tag: str
    territory: str
    social_sentiment_index: Decimal | None
    chart_velocity_score: Decimal | None
    licensing_inflation_multiplier: Decimal | None
    source_available: bool
    found: bool


@runtime_checkable
class TelemetrySource(Protocol):
    """Common pluggable interface every external telemetry feed implements.

    A concrete source fetches its signal(s) and returns one
    :class:`TelemetryReading` per ``(genre_tag, territory)`` pair it covers. On
    an unreachable or failing feed it raises :class:`TelemetrySourceUnavailable`
    so the connector can retain cached values and mark the source unavailable
    (R13.4). Implementations are registered with the connector, enabling modular
    addition of new sources without changing the orchestration.
    """

    #: Stable, human-readable identifier used in structured logs.
    name: str

    async def fetch(self) -> list[TelemetryReading]:
        """Return fresh readings, or raise :class:`TelemetrySourceUnavailable`."""
        ...


class TelemetryConnector:
    """Polls pluggable telemetry sources and serves the cached snapshot (R13).

    Wraps :class:`TelemetryRepository`. Construction never touches the database;
    the injected session is used lazily when :meth:`poll` or
    :meth:`get_telemetry` executes a statement.

    Args:
        session: The async unit-of-work session; the surrounding caller owns the
            transaction boundary (the connector only flushes).
        sources: The pluggable :class:`TelemetrySource` connectors to poll. New
            sources can be supplied here without any change to this class.
    """

    def __init__(
        self,
        session: AsyncSession,
        sources: list[TelemetrySource] | None = None,
    ) -> None:
        self.session = session
        self.repository = TelemetryRepository(session)
        self.sources: list[TelemetrySource] = list(sources or [])

    def register_source(self, source: TelemetrySource) -> None:
        """Register an additional pluggable source for subsequent polls (R13.1)."""
        self.sources.append(source)

    async def poll(self) -> None:
        """Poll every registered source asynchronously and refresh the cache (R13).

        Fetches from all sources concurrently (R13.1). For each source that
        succeeds, every returned :class:`TelemetryReading` is upserted into
        ``market_telemetry_cache`` keyed by ``(genre_tag, territory)``; indices
        left ``None`` retain their prior cached value (R13.2). For each source
        that raises :class:`TelemetrySourceUnavailable` (or any other error), the
        last cached values are retained and the affected rows are marked
        ``source_available = False`` (R13.4); one failing source never aborts the
        poll for the others.
        """
        if not self.sources:
            return

        results = await asyncio.gather(
            *(self._fetch_source(source) for source in self.sources),
            return_exceptions=True,
        )

        for source, result in zip(self.sources, results):
            if isinstance(result, BaseException):
                await self._handle_source_failure(source, result)
            else:
                await self._apply_readings(result)

    async def get_telemetry(self, genre: str, territory: str) -> TelemetrySnapshot:
        """Return the cached telemetry snapshot for a genre/territory pair (R13.3).

        Reads the ``market_telemetry_cache`` row for ``(genre, territory)``. When
        no row exists yet the snapshot carries ``found=False`` with ``None``
        indices and ``source_available=False`` so callers can distinguish "never
        polled" from "polled and available".

        Args:
            genre: The ``genre_tag`` to look up.
            territory: The two-letter territory code to look up.

        Returns:
            A :class:`TelemetrySnapshot` for the pair, reflecting the retained
            cache values and the current ``source_available`` flag (R13.4).
        """
        row = await self.repository.get_for_genre_territory(genre, territory)
        if row is None:
            return TelemetrySnapshot(
                genre_tag=genre,
                territory=territory,
                social_sentiment_index=None,
                chart_velocity_score=None,
                licensing_inflation_multiplier=None,
                source_available=False,
                found=False,
            )
        return TelemetrySnapshot(
            genre_tag=row.genre_tag,
            territory=row.territory,
            social_sentiment_index=row.social_sentiment_index,
            chart_velocity_score=row.chart_velocity_score,
            licensing_inflation_multiplier=row.licensing_inflation_multiplier,
            source_available=row.source_available,
            found=True,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers.
    # ------------------------------------------------------------------ #
    async def _fetch_source(self, source: TelemetrySource) -> list[TelemetryReading]:
        """Fetch one source's readings (errors propagate to :meth:`poll`)."""
        return await source.fetch()

    async def _apply_readings(self, readings: list[TelemetryReading]) -> None:
        """Upsert each fresh reading, keyed by ``(genre_tag, territory)`` (R13.2).

        A successful poll marks the row ``source_available = True``. Index values
        left ``None`` are not overwritten on an existing row — the repository
        retains the prior cached value for that index.
        """
        for reading in readings:
            await self.repository.upsert(
                genre_tag=reading.genre_tag,
                territory=reading.territory,
                social_sentiment_index=reading.social_sentiment_index,
                chart_velocity_score=reading.chart_velocity_score,
                licensing_inflation_multiplier=reading.licensing_inflation_multiplier,
                source_available=True,
            )

    async def _handle_source_failure(
        self, source: TelemetrySource, error: BaseException
    ) -> None:
        """Retain cached values and mark affected rows unavailable (R13.4).

        For every ``(genre_tag, territory)`` the failed source was expected to
        cover, flips ``source_available`` to ``False`` on the existing cache row
        without touching its cached indices, so the last-known values survive the
        failed poll. Pairs with no cache row yet are skipped — there is nothing to
        retain. Coverage is taken from
        :attr:`TelemetrySourceUnavailable.coverage` when the source supplied it.
        """
        source_name = getattr(source, "name", source.__class__.__name__)
        coverage: list[tuple[str, str]] = []
        if isinstance(error, TelemetrySourceUnavailable):
            coverage = error.coverage

        # Formatted into the message so the log is identical whether the
        # structlog backend or the stdlib fallback is active (the fallback does
        # not accept structured keyword fields).
        _log.warning(
            "telemetry_source_unavailable source=%s affected_pairs=%d error=%s",
            source_name,
            len(coverage),
            error,
        )

        for genre_tag, territory in coverage:
            await self.repository.mark_source_unavailable(genre_tag, territory)
