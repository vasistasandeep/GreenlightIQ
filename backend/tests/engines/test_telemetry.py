"""Unit tests for the Telemetry_Connector (R13.1, R13.2, R13.4).

Targets :class:`app.engines.telemetry.TelemetryConnector`. The connector is a
thin orchestration layer: it fans out across pluggable :class:`TelemetrySource`
feeds, upserts the readings into ``market_telemetry_cache`` keyed by
``(genre_tag, territory)``, and — when a source is unavailable — retains the
last cached values while flipping ``source_available`` to ``False``.

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database**. A single stand-in,
:class:`_FakeTelemetryRepository`, reproduces the three methods the connector
relies on (``upsert``, ``mark_source_unavailable``,
``get_for_genre_territory``) with an in-memory dict keyed by
``(genre_tag, territory)``, mirroring the real repository's retain-prior-on-None
upsert semantics. Database-backed caching/DLQ/SLA behaviour is covered
separately by task 15.4's integration tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.engines.telemetry import (
    TelemetryConnector,
    TelemetryReading,
    TelemetrySource,
    TelemetrySourceUnavailable,
)


# --------------------------------------------------------------------------- #
# In-memory collaborator stand-ins (no database).
# --------------------------------------------------------------------------- #
@dataclass
class _FakeRow:
    """A ``MarketTelemetryCache``-like row carrying the cached indices + flag."""

    genre_tag: str
    territory: str
    social_sentiment_index: Decimal | None = None
    chart_velocity_score: Decimal | None = None
    licensing_inflation_multiplier: Decimal | None = None
    source_available: bool = True


class _FakeTelemetryRepository:
    """In-memory fake of ``TelemetryRepository`` keyed by (genre_tag, territory).

    Reproduces the real repository's upsert contract: on an existing row an index
    passed as ``None`` is *not* overwritten (the prior value is retained), while
    ``source_available`` is always assigned. ``mark_source_unavailable`` flips the
    flag without touching the indices and returns ``None`` when no row exists.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _FakeRow] = {}

    async def get_for_genre_territory(
        self, genre_tag: str, territory: str
    ) -> _FakeRow | None:
        return self.rows.get((genre_tag, territory))

    async def upsert(
        self,
        *,
        genre_tag: str,
        territory: str,
        social_sentiment_index: Decimal | None = None,
        chart_velocity_score: Decimal | None = None,
        licensing_inflation_multiplier: Decimal | None = None,
        source_available: bool = True,
    ) -> _FakeRow:
        key = (genre_tag, territory)
        existing = self.rows.get(key)
        if existing is None:
            row = _FakeRow(
                genre_tag=genre_tag,
                territory=territory,
                social_sentiment_index=social_sentiment_index,
                chart_velocity_score=chart_velocity_score,
                licensing_inflation_multiplier=licensing_inflation_multiplier,
                source_available=source_available,
            )
            self.rows[key] = row
            return row
        if social_sentiment_index is not None:
            existing.social_sentiment_index = social_sentiment_index
        if chart_velocity_score is not None:
            existing.chart_velocity_score = chart_velocity_score
        if licensing_inflation_multiplier is not None:
            existing.licensing_inflation_multiplier = licensing_inflation_multiplier
        existing.source_available = source_available
        return existing

    async def mark_source_unavailable(
        self, genre_tag: str, territory: str
    ) -> _FakeRow | None:
        existing = self.rows.get((genre_tag, territory))
        if existing is None:
            return None
        existing.source_available = False
        return existing


@dataclass
class _StandInSession:
    """A placeholder passed to the connector; the fake replaces the repository."""

    marker: str = field(default="no-db")


class _StaticSource:
    """A pluggable source that returns a fixed set of readings (R13.1)."""

    def __init__(self, name: str, readings: list[TelemetryReading]) -> None:
        self.name = name
        self._readings = readings

    async def fetch(self) -> list[TelemetryReading]:
        return list(self._readings)


class _FailingSource:
    """A pluggable source that is unavailable for a declared coverage set (R13.4)."""

    def __init__(self, name: str, coverage: list[tuple[str, str]]) -> None:
        self.name = name
        self._coverage = coverage

    async def fetch(self) -> list[TelemetryReading]:
        raise TelemetrySourceUnavailable(
            f"{self.name} is unreachable", coverage=self._coverage
        )


def _build_connector(
    sources: list[TelemetrySource],
) -> tuple[TelemetryConnector, _FakeTelemetryRepository]:
    """Construct the real connector and swap in the in-memory repository fake."""
    connector = TelemetryConnector(session=_StandInSession(), sources=sources)  # type: ignore[arg-type]
    fake_repo = _FakeTelemetryRepository()
    connector.repository = fake_repo  # type: ignore[assignment]
    return connector, fake_repo


# --------------------------------------------------------------------------- #
# R13.1 / R13.2: polling persists readings keyed by (genre_tag, territory).
# --------------------------------------------------------------------------- #
async def test_poll_upserts_readings_keyed_by_genre_territory() -> None:
    """Validates: Requirements 13.1, 13.2

    Polling a source upserts each reading into the cache keyed by
    ``(genre_tag, territory)`` with its three indices and ``source_available``
    set to ``True``.
    """
    source = _StaticSource(
        "sentiment",
        [
            TelemetryReading(
                genre_tag="action",
                territory="US",
                social_sentiment_index=Decimal("7.50"),
                chart_velocity_score=Decimal("3.20"),
                licensing_inflation_multiplier=Decimal("1.150"),
            )
        ],
    )
    connector, repo = _build_connector([source])

    await connector.poll()

    row = repo.rows[("action", "US")]
    assert row.social_sentiment_index == Decimal("7.50")
    assert row.chart_velocity_score == Decimal("3.20")
    assert row.licensing_inflation_multiplier == Decimal("1.150")
    assert row.source_available is True


async def test_poll_merges_multiple_sources_for_same_key() -> None:
    """Validates: Requirements 13.1, 13.2

    Two sources covering the same ``(genre_tag, territory)`` pair but owning
    different indices are merged onto one cache row; each source's ``None``
    indices retain the other source's values.
    """
    sentiment = _StaticSource(
        "sentiment",
        [TelemetryReading("drama", "GB", social_sentiment_index=Decimal("6.00"))],
    )
    inflation = _StaticSource(
        "inflation",
        [
            TelemetryReading(
                "drama", "GB", licensing_inflation_multiplier=Decimal("1.250")
            )
        ],
    )
    connector, repo = _build_connector([sentiment, inflation])

    await connector.poll()

    row = repo.rows[("drama", "GB")]
    assert row.social_sentiment_index == Decimal("6.00")
    assert row.licensing_inflation_multiplier == Decimal("1.250")
    assert row.source_available is True


# --------------------------------------------------------------------------- #
# R13.4: source unavailable retains cache and marks the source unavailable.
# --------------------------------------------------------------------------- #
async def test_unavailable_source_retains_cache_and_marks_unavailable() -> None:
    """Validates: Requirements 13.4

    When a source is unavailable, the previously cached indices for its covered
    pairs are retained and the row is marked ``source_available = False``.
    """
    connector, repo = _build_connector([])
    # Seed a prior good cache value.
    repo.rows[("comedy", "US")] = _FakeRow(
        genre_tag="comedy",
        territory="US",
        social_sentiment_index=Decimal("5.00"),
        chart_velocity_score=Decimal("2.00"),
        licensing_inflation_multiplier=Decimal("1.100"),
        source_available=True,
    )
    connector.register_source(_FailingSource("sentiment", [("comedy", "US")]))

    await connector.poll()

    row = repo.rows[("comedy", "US")]
    # Values retained unchanged (R13.4).
    assert row.social_sentiment_index == Decimal("5.00")
    assert row.chart_velocity_score == Decimal("2.00")
    assert row.licensing_inflation_multiplier == Decimal("1.100")
    # Source marked unavailable (R13.4).
    assert row.source_available is False


async def test_one_failing_source_does_not_abort_others() -> None:
    """Validates: Requirements 13.1, 13.4

    A failing source does not prevent a healthy source polled in the same cycle
    from refreshing its own cache row.
    """
    good = _StaticSource(
        "velocity",
        [TelemetryReading("horror", "US", chart_velocity_score=Decimal("9.90"))],
    )
    bad = _FailingSource("sentiment", [("horror", "US")])
    connector, repo = _build_connector([good, bad])
    # Pre-existing row so the failing source has something to retain/flag.
    repo.rows[("horror", "US")] = _FakeRow(
        genre_tag="horror",
        territory="US",
        social_sentiment_index=Decimal("4.00"),
        source_available=True,
    )

    await connector.poll()

    row = repo.rows[("horror", "US")]
    # Healthy source applied its fresh reading.
    assert row.chart_velocity_score == Decimal("9.90")
    # Prior sentiment retained; the failing source wins the final availability flag.
    assert row.social_sentiment_index == Decimal("4.00")
    assert row.source_available is False


async def test_unavailable_source_skips_pairs_without_cache_row() -> None:
    """Validates: Requirements 13.4

    An unavailable source covering a pair that was never polled has nothing to
    retain, so no cache row is created for it.
    """
    connector, repo = _build_connector(
        [_FailingSource("sentiment", [("thriller", "FR")])]
    )

    await connector.poll()

    assert ("thriller", "FR") not in repo.rows


async def test_poll_with_no_sources_is_a_noop() -> None:
    """Validates: Requirements 13.1

    Polling with no registered sources performs no cache writes.
    """
    connector, repo = _build_connector([])

    await connector.poll()

    assert repo.rows == {}


# --------------------------------------------------------------------------- #
# R13.3 companion: get_telemetry surfaces the retained snapshot.
# --------------------------------------------------------------------------- #
async def test_get_telemetry_returns_cached_snapshot() -> None:
    """Validates: Requirements 13.2, 13.4

    ``get_telemetry`` returns the cached indices and the ``source_available``
    flag for an existing pair.
    """
    connector, repo = _build_connector([])
    repo.rows[("action", "US")] = _FakeRow(
        genre_tag="action",
        territory="US",
        social_sentiment_index=Decimal("8.00"),
        chart_velocity_score=Decimal("1.50"),
        licensing_inflation_multiplier=Decimal("1.300"),
        source_available=False,
    )

    snapshot = await connector.get_telemetry("action", "US")

    assert snapshot.found is True
    assert snapshot.social_sentiment_index == Decimal("8.00")
    assert snapshot.chart_velocity_score == Decimal("1.50")
    assert snapshot.licensing_inflation_multiplier == Decimal("1.300")
    assert snapshot.source_available is False


async def test_get_telemetry_missing_pair_reports_not_found() -> None:
    """Validates: Requirements 13.3

    ``get_telemetry`` for a pair with no cache row reports ``found=False`` and an
    unavailable, empty snapshot.
    """
    connector, _repo = _build_connector([])

    snapshot = await connector.get_telemetry("missing", "US")

    assert snapshot.found is False
    assert snapshot.source_available is False
    assert snapshot.social_sentiment_index is None
    assert snapshot.chart_velocity_score is None
    assert snapshot.licensing_inflation_multiplier is None
