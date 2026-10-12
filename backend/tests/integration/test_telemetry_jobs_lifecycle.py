"""Integration tests: telemetry caching, DLQ re-dispatch, and SLA alerting (task 15.4).

Exercises the async-processing failure/recovery controls end-to-end against a
real PostgreSQL 16 + pgvector database provisioned by ``conftest.py`` (via
testcontainers or an externally supplied ``CINEROI_DATABASE_URL`` /
``TEST_DATABASE_URL``). The whole module skips cleanly when no database is
available.

Telemetry source-unavailability (R13.4)
---------------------------------------
:class:`~app.engines.telemetry.TelemetryConnector`, backed by the real
:class:`~app.repositories.telemetry.TelemetryRepository`, is polled with a
source that first succeeds (populating the cache) and then raises
:class:`~app.engines.telemetry.TelemetrySourceUnavailable`. After the failing
poll the cache row must retain its last-known indices and flip
``source_available`` to ``False`` -- confirming no good data is discarded when a
feed goes dark.

DLQ routing and operator re-dispatch (R29.3, R29.5)
---------------------------------------------------
:class:`~app.tasks.lifecycle.JobLifecycle`, backed by the real
:class:`~app.repositories.jobs.JobRepository`, fails a job with its retries
exhausted so it is routed to the dead-letter queue (``dead_lettered = True``),
then an operator ``redispatch`` returns it to ``PENDING`` with the dead-letter
flag and failure reason cleared, so a worker can pick it up again.

SLA alerting (R29.2)
--------------------
``check_sla`` scans jobs that are ``PROCESSING`` and flags any whose elapsed
time since entering ``PROCESSING`` exceeds the 15-minute SLA, leaving
within-SLA jobs untouched.

Requirements: 13.4, 29.3, 29.5
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

try:  # pragma: no cover - import guard; conftest skips when missing
    import psycopg

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

from app.engines.telemetry import (
    TelemetryConnector,
    TelemetryReading,
    TelemetrySourceUnavailable,
)
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.tasks import lifecycle as lifecycle_module
from app.tasks.lifecycle import JobLifecycle

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# URL / fixtures (mirrors test_encryption_retention.py conventions).
# --------------------------------------------------------------------------- #
def _psycopg_url_to_async_sqlalchemy(url: str) -> str:
    """Convert a raw psycopg/libpq URL into an async SQLAlchemy URL.

    The conftest ``postgres_url`` fixture yields a ``postgresql://...`` libpq
    string; SQLAlchemy's async engine needs the ``postgresql+psycopg://`` driver
    prefix (psycopg 3 supports async natively).
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
    conftest fixture provisioned, so the engines/repositories run against the
    exact same schema. Skips cleanly if async SQLAlchemy is unavailable, and
    always disposes the engine on teardown.
    """
    if not _HAS_SQLALCHEMY_ASYNC:  # pragma: no cover - env guard
        pytest.skip("async SQLAlchemy is not available; cannot run async DB test")

    async_url = _psycopg_url_to_async_sqlalchemy(postgres_url)
    engine = create_async_engine(async_url, future=True, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Test doubles: pluggable telemetry sources.
# --------------------------------------------------------------------------- #
class _StaticSource:
    """A pluggable source that returns a fixed set of readings on every poll."""

    def __init__(self, name: str, readings: list[TelemetryReading]) -> None:
        self.name = name
        self._readings = readings

    async def fetch(self) -> list[TelemetryReading]:
        return list(self._readings)


class _UnavailableSource:
    """A pluggable source that always reports its feed as unavailable (R13.4)."""

    def __init__(self, name: str, coverage: list[tuple[str, str]]) -> None:
        self.name = name
        self._coverage = coverage

    async def fetch(self) -> list[TelemetryReading]:
        raise TelemetrySourceUnavailable(
            f"{self.name} feed is down", coverage=self._coverage
        )


# --------------------------------------------------------------------------- #
# R13.4 - source unavailable retains cache and marks unavailable.
# --------------------------------------------------------------------------- #
async def test_source_unavailable_retains_cache_and_marks_unavailable(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R13.4: a failed poll keeps the last-known values and flags unavailable.

    Polls once with a healthy source so the ``(genre_tag, territory)`` cache row
    is populated and ``source_available=True``. Then re-polls with a source that
    raises :class:`TelemetrySourceUnavailable` for the same pair: the cached
    indices must be retained unchanged while ``source_available`` flips to
    ``False`` -- the connector never discards good data on a dark feed.
    """
    genre = f"thriller-{uuid.uuid4().hex[:8]}"
    territory = "US"
    reading = TelemetryReading(
        genre_tag=genre,
        territory=territory,
        social_sentiment_index=Decimal("72.50"),
        chart_velocity_score=Decimal("18.25"),
        licensing_inflation_multiplier=Decimal("1.150"),
    )

    # --- Poll 1: healthy source populates the cache. ------------------------ #
    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(
            session, sources=[_StaticSource("good-feed", [reading])]
        )
        await connector.poll()
        await session.commit()

        snapshot = await connector.get_telemetry(genre, territory)
        assert snapshot.found is True
        assert snapshot.source_available is True
        assert snapshot.social_sentiment_index == Decimal("72.50")
        assert snapshot.chart_velocity_score == Decimal("18.25")
        assert snapshot.licensing_inflation_multiplier == Decimal("1.150")

    # --- Poll 2: the source goes dark for the same pair. -------------------- #
    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(
            session,
            sources=[_UnavailableSource("good-feed", coverage=[(genre, territory)])],
        )
        await connector.poll()
        await session.commit()

    # --- A fresh connector reads the persisted state. ----------------------- #
    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(session)
        snapshot = await connector.get_telemetry(genre, territory)

    # Values retained, source marked unavailable (R13.4).
    assert snapshot.found is True
    assert snapshot.source_available is False
    assert snapshot.social_sentiment_index == Decimal("72.50")
    assert snapshot.chart_velocity_score == Decimal("18.25")
    assert snapshot.licensing_inflation_multiplier == Decimal("1.150")


async def test_mixed_poll_applies_good_source_and_retains_failed_one(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R13.4: one dark feed never aborts the poll for a healthy feed.

    A single poll runs two sources concurrently: a healthy source for pair A and
    a failing source covering pair B (already cached). Pair A is refreshed and
    stays available; pair B retains its values and is marked unavailable.
    """
    genre_a = f"comedy-{uuid.uuid4().hex[:8]}"
    genre_b = f"drama-{uuid.uuid4().hex[:8]}"
    territory = "GB"

    # Seed pair B with a prior good value so there is something to retain.
    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(
            session,
            sources=[
                _StaticSource(
                    "seed-feed",
                    [
                        TelemetryReading(
                            genre_tag=genre_b,
                            territory=territory,
                            social_sentiment_index=Decimal("40.00"),
                        )
                    ],
                )
            ],
        )
        await connector.poll()
        await session.commit()

    # Mixed poll: good source for A, failing source covering B.
    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(
            session,
            sources=[
                _StaticSource(
                    "good-feed",
                    [
                        TelemetryReading(
                            genre_tag=genre_a,
                            territory=territory,
                            social_sentiment_index=Decimal("88.00"),
                        )
                    ],
                ),
                _UnavailableSource("flaky-feed", coverage=[(genre_b, territory)]),
            ],
        )
        await connector.poll()
        await session.commit()

    async with async_sessionmaker_factory() as session:
        connector = TelemetryConnector(session)
        snap_a = await connector.get_telemetry(genre_a, territory)
        snap_b = await connector.get_telemetry(genre_b, territory)

    # Healthy pair refreshed and available.
    assert snap_a.found is True
    assert snap_a.source_available is True
    assert snap_a.social_sentiment_index == Decimal("88.00")

    # Dark pair retained and flagged unavailable.
    assert snap_b.found is True
    assert snap_b.source_available is False
    assert snap_b.social_sentiment_index == Decimal("40.00")


# --------------------------------------------------------------------------- #
# Job seeding helper.
# --------------------------------------------------------------------------- #
async def _seed_job(
    factory: "async_sessionmaker[AsyncSession]",
    *,
    status: str,
    updated_at: datetime | None = None,
) -> uuid.UUID:
    """Persist a job in a given status (optionally back-dating ``updated_at``)."""
    async with factory() as session:
        job = Job(
            job_type="POLL_TELEMETRY",
            status=status,
            idempotency_key=f"job-{uuid.uuid4()}",
        )
        if updated_at is not None:
            job.updated_at = updated_at
            job.created_at = updated_at
        session.add(job)
        await session.commit()
        return job.job_id


# --------------------------------------------------------------------------- #
# R29.3 / R29.5 - DLQ routing and operator re-dispatch.
# --------------------------------------------------------------------------- #
async def test_exhausted_retries_route_to_dlq_then_operator_redispatch(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R29.3 + R29.5: an exhausted job is dead-lettered, then re-dispatched.

    A ``PROCESSING`` job is failed with ``retries_exhausted=True`` so it is
    routed to the dead-letter queue (``dead_lettered=True``) with its failure
    reason recorded and surfaced by ``list_dead_lettered`` (R29.3). An operator
    ``redispatch`` then returns it to ``PENDING``, clears the dead-letter flag
    and failure reason, and removes it from the DLQ listing (R29.5).
    """
    job_id = await _seed_job(async_sessionmaker_factory, status="PROCESSING")

    # --- Fail with retries exhausted -> dead-lettered (R29.3). -------------- #
    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        lifecycle = JobLifecycle(repo)
        await lifecycle.fail(
            job_id, "upstream timeout", retries_exhausted=True
        )
        await session.commit()

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        failed = await repo.get(job_id)
        assert failed is not None
        assert failed.status == "FAILED"
        assert failed.dead_lettered is True
        assert failed.failure_reason == "upstream timeout"

        dead_lettered_ids = {j.job_id for j in await repo.list_dead_lettered()}
        assert job_id in dead_lettered_ids

    # --- Operator re-dispatch after remediation -> PENDING (R29.5). --------- #
    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        lifecycle = JobLifecycle(repo)
        redispatched = await lifecycle.redispatch(job_id)
        await session.commit()
        assert redispatched.status == "PENDING"

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        reread = await repo.get(job_id)
        assert reread is not None
        assert reread.status == "PENDING"
        assert reread.dead_lettered is False
        assert reread.failure_reason is None

        dead_lettered_ids = {j.job_id for j in await repo.list_dead_lettered()}
        assert job_id not in dead_lettered_ids


async def test_fail_without_exhausted_retries_is_not_dead_lettered(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R29.3: a failure with retries remaining is not routed to the DLQ.

    Only jobs that exhaust their configured retries are dead-lettered; a failure
    reported with ``retries_exhausted=False`` records the reason but leaves
    ``dead_lettered=False`` so it never appears in the DLQ listing.
    """
    job_id = await _seed_job(async_sessionmaker_factory, status="PROCESSING")

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        lifecycle = JobLifecycle(repo)
        await lifecycle.fail(
            job_id, "transient error", retries_exhausted=False
        )
        await session.commit()

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        job = await repo.get(job_id)
        assert job is not None
        assert job.status == "FAILED"
        assert job.dead_lettered is False
        assert job.failure_reason == "transient error"

        dead_lettered_ids = {j.job_id for j in await repo.list_dead_lettered()}
        assert job_id not in dead_lettered_ids


# --------------------------------------------------------------------------- #
# R29.2 - SLA alert past 15 minutes.
# --------------------------------------------------------------------------- #
async def test_check_sla_flags_job_past_15_minutes(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R29.2: a job PROCESSING longer than 15 minutes breaches the SLA.

    Seeds a ``PROCESSING`` job whose ``updated_at`` (the moment it entered
    PROCESSING) is 16 minutes in the past and a second one only 1 minute in the
    past. ``check_sla`` must flag only the over-15-minute job, identifying it in
    the returned breach list, and leave the within-SLA job alone.
    """
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # ``_now`` is indirected in the lifecycle module specifically so tests can
    # pin "now" deterministically relative to the seeded ``updated_at`` values.
    monkeypatch.setattr(lifecycle_module, "_now", lambda: now)

    breaching_id = await _seed_job(
        async_sessionmaker_factory,
        status="PROCESSING",
        updated_at=now - timedelta(minutes=16),
    )
    within_sla_id = await _seed_job(
        async_sessionmaker_factory,
        status="PROCESSING",
        updated_at=now - timedelta(minutes=1),
    )

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        lifecycle = JobLifecycle(repo)
        breaching = await lifecycle.check_sla()

    breaching_ids = {job.job_id for job in breaching}
    assert breaching_id in breaching_ids
    assert within_sla_id not in breaching_ids


async def test_check_sla_no_breach_within_limit(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R29.2: a job exactly at the 15-minute boundary does not breach.

    The SLA is a strict ``elapsed > limit`` comparison, so a job PROCESSING for
    exactly 15 minutes is still within SLA and ``check_sla`` returns no breaches.
    """
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(lifecycle_module, "_now", lambda: now)

    at_limit_id = await _seed_job(
        async_sessionmaker_factory,
        status="PROCESSING",
        updated_at=now - timedelta(minutes=15),
    )

    async with async_sessionmaker_factory() as session:
        repo = JobRepository(session)
        lifecycle = JobLifecycle(repo)
        breaching = await lifecycle.check_sla()

    assert at_limit_id not in {job.job_id for job in breaching}
