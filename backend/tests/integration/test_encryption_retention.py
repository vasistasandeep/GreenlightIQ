"""Encryption-at-rest and data-retention integration tests (task 17.2).

Exercises the data-protection controls end-to-end against a real
PostgreSQL 16 + pgvector database provisioned by ``conftest.py`` (via
testcontainers or an externally supplied ``CINEROI_DATABASE_URL`` /
``TEST_DATABASE_URL``). The whole module skips cleanly when no database is
available.

Encryption at rest (R28.1)
--------------------------
The sensitive columns ``users.display_name``, the ``license_terms`` deal-term
fields, and ``title_versions.source_snapshot`` are declared with the
:class:`~app.core.encryption.EncryptedString` / ``EncryptedJSON`` type
decorators. These tests write those columns through the async ORM with a real
Fernet key configured, then read the *raw* stored bytes with a second,
plain psycopg connection to confirm that what sits on disk is ciphertext (not
the plaintext) and that it still round-trips back to plaintext through the ORM.

Retention (R28.3)
-----------------
The :class:`~app.core.retention.RetentionService` enforces configurable
per-category windows: records older than ``now - window`` are purged (deleted)
or archived (handed to a cold-storage hook, then deleted) according to the
configured policy. These tests seed rows with back-dated timestamps and verify
that elapsed-retention records are removed per policy while in-window records
survive, and that an append-only target is archived rather than purged.

Requirements: 28.1, 28.3
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from cryptography.fernet import Fernet

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

from app.core import encryption as encryption_module
from app.core.config import Settings, get_settings
from app.core.retention import (
    RetentionAction,
    RetentionError,
    RetentionService,
    RetentionTarget,
)
from app.models.job import Job
from app.models.license_term import LicenseTerm
from app.models.market_telemetry_cache import MarketTelemetryCache
from app.models.title import Title
from app.models.title_version import TitleVersion
from app.models.user import User

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# URL / fixtures
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
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Configure a real Fernet key for the process and reset caches around it.

    The ``EncryptedString`` / ``EncryptedJSON`` column decorators resolve the
    key from :func:`app.core.config.get_settings` (cached) via
    :func:`app.core.encryption.get_encryptor` (also cached). This fixture sets
    ``CINEROI_ENCRYPTION_KEY`` + ``CINEROI_ENCRYPTION_REQUIRED=true``, clears the
    two caches so the new key takes effect, and restores them on teardown so the
    key never leaks into other tests.
    """
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("CINEROI_ENCRYPTION_KEY", key)
    monkeypatch.setenv("CINEROI_ENCRYPTION_REQUIRED", "true")
    get_settings.cache_clear()
    encryption_module._build_encryptor.cache_clear()
    try:
        yield key
    finally:
        get_settings.cache_clear()
        encryption_module._build_encryptor.cache_clear()


@pytest.fixture()
async def async_sessionmaker_factory(
    postgres_url: str,
) -> "AsyncIterator[async_sessionmaker[AsyncSession]]":
    """Yield an async sessionmaker bound to the provisioned test database.

    Builds a dedicated async engine from the (migrated) database URL the sync
    conftest fixture provisioned, so the ORM/retention code runs against the
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
# Seed helpers (ORM instances satisfying NOT NULL / CHECK constraints).
# --------------------------------------------------------------------------- #
def _new_title() -> Title:
    """A minimal valid, unpersisted ``titles`` row (parent for FK children)."""
    return Title(
        title_name="Encryption Retention Test Title",
        asset_type="ORIGINAL_FILM",
        acquisition_cost_or_budget=Decimal("1000000.00"),
        native_currency="USD",
        target_territories=["US"],
    )


def _raw_scalar(postgres_url: str, sql: str, params: tuple[Any, ...]) -> Any:
    """Read a single raw column value with a fresh plain psycopg connection.

    Bypasses the ORM entirely so the value returned is exactly what is stored at
    rest (no decryption decorator in the path).
    """
    with psycopg.connect(postgres_url) as raw:  # type: ignore[union-attr]
        row = raw.execute(sql, params).fetchone()
    return None if row is None else row[0]


# --------------------------------------------------------------------------- #
# R28.1 - encryption at rest
# --------------------------------------------------------------------------- #
async def test_user_display_name_is_ciphertext_at_rest(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
    encryption_key: str,
    postgres_url: str,
) -> None:
    """R28.1: ``users.display_name`` (PII) is stored encrypted, not as plaintext.

    Writes a user through the ORM, then reads the raw column via a plain psycopg
    connection: the stored value must differ from the plaintext, must decrypt
    back to the plaintext with the configured key, and must round-trip through
    the ORM.
    """
    plaintext = "Jane Q. Confidential"
    async with async_sessionmaker_factory() as session:
        user = User(
            external_subject=f"sso|{uuid.uuid4()}",
            display_name=plaintext,
            user_role="CONTENT_BUYER",
            authorized_territories=["US"],
        )
        session.add(user)
        await session.commit()
        user_id = user.user_id

    stored = _raw_scalar(
        postgres_url,
        "SELECT display_name FROM users WHERE user_id = %s",
        (user_id,),
    )
    assert stored is not None
    # Stored value is ciphertext: not the plaintext and not merely containing it.
    assert stored != plaintext
    assert plaintext not in stored
    # The ciphertext decrypts back to the plaintext with the configured key.
    assert Fernet(encryption_key.encode()).decrypt(stored.encode()).decode() == plaintext

    # And the ORM transparently decrypts on read.
    async with async_sessionmaker_factory() as read_session:
        reread = await read_session.get(User, user_id)
        assert reread is not None
        assert reread.display_name == plaintext


async def test_license_terms_deal_fields_are_ciphertext_at_rest(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
    encryption_key: str,
    postgres_url: str,
) -> None:
    """R28.1: confidential ``license_terms`` deal fields are encrypted at rest.

    The windowing rules, holdbacks, and milestone schedule are declared with
    ``EncryptedJSON``; the raw stored columns must be opaque ciphertext (not
    readable JSON) yet round-trip to the original structures through the ORM.
    """
    windowing = [{"window": "SVOD", "start_month": 0, "end_month": 18}]
    holdbacks = [{"against": "AVOD", "months": 6}]
    milestones = [{"name": "signing", "pct": 50}, {"name": "delivery", "pct": 50}]

    async with async_sessionmaker_factory() as session:
        title = _new_title()
        session.add(title)
        await session.flush()
        term = LicenseTerm(
            title_id=title.title_id,
            license_duration_months=24,
            is_exclusive=True,
            windowing_rules=windowing,
            holdbacks=holdbacks,
            milestone_schedule=milestones,
        )
        session.add(term)
        await session.commit()
        license_id = term.license_id

    for column, plaintext_fragment in (
        ("windowing_rules", "SVOD"),
        ("holdbacks", "AVOD"),
        ("milestone_schedule", "signing"),
    ):
        stored = _raw_scalar(
            postgres_url,
            f"SELECT {column} FROM license_terms WHERE license_id = %s",
            (license_id,),
        )
        assert stored is not None
        # The confidential JSON content must not be readable at rest.
        assert plaintext_fragment not in stored

    # The ORM decrypts and deserializes the structures intact.
    async with async_sessionmaker_factory() as read_session:
        reread = await read_session.get(LicenseTerm, license_id)
        assert reread is not None
        assert reread.windowing_rules == windowing
        assert reread.holdbacks == holdbacks
        assert reread.milestone_schedule == milestones


async def test_title_version_source_snapshot_is_ciphertext_at_rest(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
    encryption_key: str,
    postgres_url: str,
) -> None:
    """R28.1: an unreleased-script ``source_snapshot`` is encrypted at rest.

    ``title_versions.source_snapshot`` carries submitted (possibly unreleased)
    source material and is declared ``EncryptedJSON``; the raw column must be
    ciphertext and must round-trip through the ORM.
    """
    snapshot = {
        "logline": "A secret unreleased script premise",
        "synopsis": "Confidential plot details that must never leak at rest.",
    }
    async with async_sessionmaker_factory() as session:
        title = _new_title()
        session.add(title)
        await session.flush()
        version = TitleVersion(
            title_id=title.title_id,
            version_number=1,
            source_snapshot=snapshot,
            is_active=True,
        )
        session.add(version)
        await session.commit()
        title_version_id = version.title_version_id

    stored = _raw_scalar(
        postgres_url,
        "SELECT source_snapshot FROM title_versions WHERE title_version_id = %s",
        (title_version_id,),
    )
    assert stored is not None
    assert "unreleased script premise" not in stored
    assert "Confidential plot details" not in stored

    async with async_sessionmaker_factory() as read_session:
        reread = await read_session.get(TitleVersion, title_version_id)
        assert reread is not None
        assert reread.source_snapshot == snapshot


# --------------------------------------------------------------------------- #
# R28.3 - retention: purge / archive elapsed records per policy
# --------------------------------------------------------------------------- #
def _retention_settings(**overrides: Any) -> Settings:
    """Build a Settings instance with explicit retention policy for a test.

    Keeps the retention tests independent of ambient environment by injecting
    the policy directly into :class:`RetentionService` rather than relying on
    process-wide configuration.
    """
    base: dict[str, Any] = {
        "retention_default_action": "purge",
        "retention_periods_days": {"job": 180, "market_telemetry_cache": 90},
        # Retention runs on non-encrypted tables here; keep encryption optional
        # so this fixture-free path never trips the required-key guard.
        "encryption_required": False,
    }
    base.update(overrides)
    return Settings(**base)


async def test_retention_purges_only_elapsed_jobs(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R28.3: jobs older than the window are purged; in-window jobs are kept.

    Seeds one job back-dated well past the 180-day window and one freshly
    created job, then runs the retention sweep with ``purge`` as the action and
    asserts only the elapsed job is removed.
    """
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    old_created = now - timedelta(days=400)  # well past the 180-day job window
    recent_created = now - timedelta(days=10)  # inside the window

    async with async_sessionmaker_factory() as session:
        old_job = Job(
            job_type="VALUATION",
            status="COMPLETED",
            idempotency_key=f"old-{uuid.uuid4()}",
            created_at=old_created,
            updated_at=old_created,
        )
        recent_job = Job(
            job_type="VALUATION",
            status="COMPLETED",
            idempotency_key=f"recent-{uuid.uuid4()}",
            created_at=recent_created,
            updated_at=recent_created,
        )
        session.add_all([old_job, recent_job])
        await session.commit()
        old_id = old_job.job_id
        recent_id = recent_job.job_id

    async with async_sessionmaker_factory() as session:
        service = RetentionService(
            session, settings=_retention_settings(), now=now
        )
        target = RetentionTarget(
            category="job",
            model=Job,
            timestamp_column=Job.created_at,
        )
        [result] = await service.enforce([target])
        await session.commit()

    assert result.action is RetentionAction.PURGE
    assert result.affected == 1

    async with async_sessionmaker_factory() as verify:
        assert await verify.get(Job, old_id) is None  # purged
        assert await verify.get(Job, recent_id) is not None  # retained


async def test_retention_skips_category_with_no_window(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R28.3: a category configured to retain indefinitely purges nothing.

    When a category's window is ``None`` the sweep treats it as "retain
    indefinitely" and reports a skip without deleting any rows, even for very
    old records.
    """
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    old_created = now - timedelta(days=5000)

    async with async_sessionmaker_factory() as session:
        job = Job(
            job_type="BACKTEST",
            status="COMPLETED",
            idempotency_key=f"keep-{uuid.uuid4()}",
            created_at=old_created,
            updated_at=old_created,
        )
        session.add(job)
        await session.commit()
        job_id = job.job_id

    async with async_sessionmaker_factory() as session:
        service = RetentionService(
            session,
            settings=_retention_settings(retention_periods_days={"job": None}),
            now=now,
        )
        target = RetentionTarget(
            category="job", model=Job, timestamp_column=Job.created_at
        )
        [result] = await service.enforce([target])
        await session.commit()

    assert result.cutoff is None
    assert result.affected == 0
    assert result.skipped_reason == "no_retention_window_configured"

    async with async_sessionmaker_factory() as verify:
        assert await verify.get(Job, job_id) is not None  # retained indefinitely


async def test_retention_archives_before_delete(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R28.3: an archive policy hands elapsed rows to cold storage, then deletes.

    With the default action set to ``archive``, the elapsed telemetry row is
    passed to the archive hook (which records it) before being removed from the
    live table, confirming no row is deleted without first being archived.
    """
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    old_updated = now - timedelta(days=200)  # past the 90-day telemetry window

    async with async_sessionmaker_factory() as session:
        telemetry = MarketTelemetryCache(
            genre_tag=f"thriller-{uuid.uuid4()}",
            territory="US",
            source_available=True,
            last_updated_at=old_updated,
        )
        session.add(telemetry)
        await session.commit()
        telemetry_id = telemetry.telemetry_id
        genre_tag = telemetry.genre_tag

    archived: list[Any] = []

    async def archive_hook(rows: Sequence[Any]) -> None:
        archived.extend(rows)

    async with async_sessionmaker_factory() as session:
        service = RetentionService(
            session,
            settings=_retention_settings(retention_default_action="archive"),
            now=now,
        )
        target = RetentionTarget(
            category="market_telemetry_cache",
            model=MarketTelemetryCache,
            timestamp_column=MarketTelemetryCache.last_updated_at,
            archive_hook=archive_hook,
        )
        [result] = await service.enforce([target])
        await session.commit()

    assert result.action is RetentionAction.ARCHIVE
    assert result.affected == 1
    # The row was archived before deletion.
    assert len(archived) == 1
    assert archived[0].genre_tag == genre_tag

    async with async_sessionmaker_factory() as verify:
        assert await verify.get(MarketTelemetryCache, telemetry_id) is None


async def test_retention_archive_requires_hook(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R28.3: an archive policy without a hook refuses to delete rows.

    The service must never delete rows under an ``archive`` policy when no
    cold-storage hook is configured; it raises rather than silently losing the
    data it was supposed to preserve.
    """
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    old_updated = now - timedelta(days=200)

    async with async_sessionmaker_factory() as session:
        telemetry = MarketTelemetryCache(
            genre_tag=f"drama-{uuid.uuid4()}",
            territory="US",
            source_available=True,
            last_updated_at=old_updated,
        )
        session.add(telemetry)
        await session.commit()

    async with async_sessionmaker_factory() as session:
        service = RetentionService(
            session,
            settings=_retention_settings(retention_default_action="archive"),
            now=now,
        )
        target = RetentionTarget(
            category="market_telemetry_cache",
            model=MarketTelemetryCache,
            timestamp_column=MarketTelemetryCache.last_updated_at,
        )
        with pytest.raises(RetentionError):
            await service.enforce([target])
        await session.rollback()
