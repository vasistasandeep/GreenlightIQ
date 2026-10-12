"""End-to-end auth-flow integration tests (task 14.5, Requirement 19).

Where ``tests/engines/test_auth.py`` exercises :class:`AuthService` against
*in-memory* repository fakes, this module drives the **full** authentication
flow against real :class:`~app.repositories.users.UserRepository` /
:class:`~app.repositories.users.SessionRepository` instances bound to a live
PostgreSQL 16 + pgvector database provisioned by ``conftest.py`` (via
testcontainers or an externally supplied ``CINEROI_DATABASE_URL`` /
``TEST_DATABASE_URL``). The tests skip cleanly when no database is available,
matching the project's DB-dependent integration-test convention
(see ``test_optimistic_lock.py``).

Coverage of Requirement 19 end to end over real persistence:

* **R19.1 / R19.2** — a signed OIDC assertion is verified by the real
  :class:`~app.core.security.JwtOidcProvider`, the user is provisioned in the
  ``users`` table, and a ``sessions`` row **bound to that identity** is
  persisted and committed; a returning subject reuses the same row.
* **R19.2 / R19.4** — the issued token validates against the persisted session,
  returns the bound :class:`~app.core.security.UserContext` (with its encrypted
  ``display_name`` round-tripped through the DB), and active use slides the
  stored ``last_activity_at`` forward.
* **R19.4 / R19.6** — a session idle past 30 minutes is expired on next use and
  the expiry is *sticky* (the stored row is marked ``revoked``).
* **R19.3 / R19.6** — missing, unknown, and revoked credentials are rejected
  with the correct ``revoked_or_expired`` flag against the real repositories.
* **R19.5 / R19.6** — a minted service-to-service credential authenticates, and
  an expired one is rejected as expired.

Because the engine ``flush``es (the surrounding unit-of-work owns the
transaction), each phase that must be observed by an independent session commits
explicitly, mirroring how a request/task boundary behaves in production.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import jwt
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

from app.core.config import get_settings
from app.core.security import (
    AuthError,
    JwtOidcProvider,
    UserContext,
    UserRole,
    encode_service_credential,
    encode_session_token,
    is_session_idle_expired,
    utcnow,
)
from app.engines.auth import AuthService
from app.repositories.users import SessionRepository, UserRepository

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _configure_encryption_key() -> AsyncIterator[None]:
    """Provision a Fernet encryption key so the encrypted ``display_name`` round-trips.

    ``users.display_name`` is an :class:`~app.core.encryption.EncryptedString`
    (PII encrypted at rest, R28.1). With the default ``encryption_required=True``
    policy, persisting a user without a configured key raises. Rather than
    weaken the policy, we configure a real key for the test process and reset
    the cached settings/encryptor so the ciphertext round-trips through the real
    database — exercising the production code path end to end.
    """
    import os

    from cryptography.fernet import Fernet

    from app.core import encryption

    previous = os.environ.get("CINEROI_ENCRYPTION_KEY")
    os.environ["CINEROI_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")
    get_settings.cache_clear()
    encryption._build_encryptor.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CINEROI_ENCRYPTION_KEY", None)
        else:
            os.environ["CINEROI_ENCRYPTION_KEY"] = previous
        get_settings.cache_clear()
        encryption._build_encryptor.cache_clear()


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
    conftest fixture provisioned, so the async repository code runs against the
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


def _make_service(session: "AsyncSession") -> AuthService:
    """Build an :class:`AuthService` over real repositories bound to ``session``.

    Uses the real :class:`JwtOidcProvider` so SSO verification exercises the
    production assertion-parsing path (R19.1) rather than a stub.
    """
    return AuthService(
        users=UserRepository(session),
        sessions=SessionRepository(session),
        sso_provider=JwtOidcProvider(),
    )


def _signed_assertion(
    subject: str,
    *,
    name: str,
    role: str | None = None,
    territories: list[str] | None = None,
) -> str:
    """Mint a signed OIDC id-token the real :class:`JwtOidcProvider` accepts.

    Signed with the same ``secret_key``/algorithm the provider verifies with;
    ``sso_audience`` is unset in test settings so the audience check is disabled.
    """
    settings = get_settings()
    claims: dict[str, object] = {"sub": subject, "name": name}
    if role is not None:
        claims["role"] = role
    if territories is not None:
        claims["territories"] = territories
    return jwt.encode(
        claims, settings.secret_key, algorithm=settings.access_token_algorithm
    )


# ---------------------------------------------------------------------------
# SSO login + session issuance (R19.1, R19.2)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.1 / 19.2: SSO login issues an identity-bound session
async def test_sso_login_provisions_user_and_persists_bound_session(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A verified SSO assertion provisions a user and persists a bound session.

    Drives the real OIDC provider + repositories: after ``login_sso`` and a
    commit, an independent session observes (a) the provisioned ``users`` row
    resolvable by its external subject with the asserted role/territories, and
    (b) a ``sessions`` row whose ``user_id`` is that user (R19.2) — proving the
    session is bound to the authenticated identity through real persistence.
    """
    subject = f"idp|{uuid.uuid4()}"
    assertion = _signed_assertion(
        subject, name="Alice Analyst", role="CONTENT_BUYER", territories=["US", "GB"]
    )

    async with async_sessionmaker_factory() as session:
        service = _make_service(session)
        session_row, token = await service.login_sso(assertion)
        await session.commit()
        session_id = session_row.session_id

    # An independent session must observe the committed, bound rows.
    async with async_sessionmaker_factory() as verify:
        users = UserRepository(verify)
        sessions = SessionRepository(verify)

        user = await users.get_by_external_subject(subject)
        assert user is not None
        assert user.display_name == "Alice Analyst"  # decrypted round-trip (R28.1)
        assert user.user_role == UserRole.CONTENT_BUYER.value
        assert list(user.authorized_territories) == ["US", "GB"]

        stored_session = await sessions.get(session_id)
        assert stored_session is not None
        assert stored_session.user_id == user.user_id  # bound to identity (R19.2)
        assert stored_session.revoked is False

    # The token carries both ids so it can never be replayed against another id.
    from app.core.security import decode_session_token

    claims = decode_session_token(token)
    assert claims["sid"] == str(session_id)


# Feature: cineroi-ai, Requirement 19.2: a returning subject reuses its user
async def test_sso_login_reuses_existing_user_across_sessions(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A returning subject reuses the persisted user rather than duplicating it.

    Two logins for the same IdP subject (committed between them so the first is
    visible) must resolve to a single ``users`` row while issuing two distinct
    ``sessions`` rows (R19.2).
    """
    subject = f"idp|{uuid.uuid4()}"
    assertion = _signed_assertion(subject, name="Returning User", role="CFO")

    async with async_sessionmaker_factory() as first:
        service = _make_service(first)
        first_session, _ = await service.login_sso(assertion)
        await first.commit()
        first_user_id = first_session.user_id
        first_session_id = first_session.session_id

    async with async_sessionmaker_factory() as second:
        service = _make_service(second)
        second_session, _ = await service.login_sso(assertion)
        await second.commit()
        second_user_id = second_session.user_id
        second_session_id = second_session.session_id

    assert first_user_id == second_user_id  # same identity reused (R19.2)
    assert first_session_id != second_session_id  # distinct sessions issued


# ---------------------------------------------------------------------------
# Request validation + idle-window sliding (R19.2, R19.4)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.2 / 19.4: token validates and slides the idle window
async def test_validate_returns_context_and_slides_idle_window(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A fresh token validates to the bound context and advances last_activity_at.

    After login+commit, a request on a fresh async session validates the token,
    returns the bound :class:`UserContext` (R19.2), and the stored
    ``last_activity_at`` slides forward to the reference time on active use
    (R19.4). The advance is verified from an independent session after commit.
    """
    subject = f"idp|{uuid.uuid4()}"
    assertion = _signed_assertion(
        subject, name="Carol CFO", role="CFO", territories=["US"]
    )

    async with async_sessionmaker_factory() as login:
        service = _make_service(login)
        session_row, token = await service.login_sso(assertion)
        await login.commit()
        session_id = session_row.session_id
        original_activity = session_row.last_activity_at

    within_window = original_activity + timedelta(minutes=10)
    async with async_sessionmaker_factory() as request:
        service = _make_service(request)
        ctx = await service.validate(token, now=within_window)
        await request.commit()

        assert isinstance(ctx, UserContext)
        assert ctx.display_name == "Carol CFO"
        assert ctx.role == UserRole.CFO
        assert ctx.authorized_territories == ("US",)

    async with async_sessionmaker_factory() as verify:
        stored = await SessionRepository(verify).get(session_id)
        assert stored is not None
        assert stored.last_activity_at == within_window  # slid forward (R19.4)
        assert stored.revoked is False


# ---------------------------------------------------------------------------
# 30-minute idle expiry (R19.4, R19.6)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.4 / 19.6: idle sessions expire and the expiry is sticky
async def test_idle_session_expires_after_30_minutes_and_is_sticky(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A session idle past 30 minutes is expired on next use and stays revoked.

    Validating 31 minutes after the last activity raises an
    ``revoked_or_expired`` :class:`AuthError` (R19.4/R19.6); the stored row is
    marked ``revoked`` (committed), so a later request against an independent
    session is still rejected — the expiry is sticky.
    """
    subject = f"idp|{uuid.uuid4()}"
    assertion = _signed_assertion(subject, name="Idle User", role="DATA_ANALYST")

    async with async_sessionmaker_factory() as login:
        service = _make_service(login)
        session_row, token = await service.login_sso(assertion)
        await login.commit()
        session_id = session_row.session_id
        last_activity = session_row.last_activity_at

    expired_at = last_activity + timedelta(minutes=31)
    async with async_sessionmaker_factory() as request:
        service = _make_service(request)
        with pytest.raises(AuthError) as exc:
            await service.validate(token, now=expired_at)
        await request.commit()  # persist the sticky revocation
        assert exc.value.revoked_or_expired is True

    async with async_sessionmaker_factory() as verify:
        stored = await SessionRepository(verify).get(session_id)
        assert stored is not None
        assert stored.revoked is True  # sticky expiry persisted (R19.4/R19.6)

        # A later request still fails (now as revoked) even inside the window.
        service = _make_service(verify)
        with pytest.raises(AuthError) as exc2:
            await service.validate(token, now=utcnow())
        assert exc2.value.revoked_or_expired is True


# ---------------------------------------------------------------------------
# Credential rejection (R19.3, R19.6)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.3: a missing credential is rejected as unauthenticated
async def test_validate_rejects_missing_credential(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A request with no credential is rejected as plain unauthenticated (R19.3)."""
    async with async_sessionmaker_factory() as session:
        service = _make_service(session)
        with pytest.raises(AuthError) as exc:
            await service.validate(None)
        assert exc.value.revoked_or_expired is False


# Feature: cineroi-ai, Requirement 19.3: an unknown session is rejected
async def test_validate_rejects_token_for_unknown_session(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A well-formed token referencing a nonexistent session is rejected (R19.3).

    The token signature verifies, but no ``sessions`` row exists for its ``sid``
    in the real database, so validation fails as unauthenticated.
    """
    token = encode_session_token(uuid.uuid4(), uuid.uuid4())
    async with async_sessionmaker_factory() as session:
        service = _make_service(session)
        with pytest.raises(AuthError):
            await service.validate(token)


# Feature: cineroi-ai, Requirement 19.6: a revoked session is rejected as revoked
async def test_validate_rejects_revoked_session(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """An explicitly revoked session is rejected as expired/revoked (R19.6).

    Logs in and commits, revokes the session through the engine (committed),
    then validates on an independent session and asserts the failure is flagged
    ``revoked_or_expired`` against the persisted ``revoked`` state.
    """
    subject = f"idp|{uuid.uuid4()}"
    assertion = _signed_assertion(subject, name="Revoked User", role="DATA_ANALYST")

    async with async_sessionmaker_factory() as login:
        service = _make_service(login)
        session_row, token = await service.login_sso(assertion)
        await login.commit()
        session_id = session_row.session_id

    async with async_sessionmaker_factory() as revoke:
        service = _make_service(revoke)
        await service.revoke(session_id)
        await revoke.commit()

    async with async_sessionmaker_factory() as request:
        service = _make_service(request)
        with pytest.raises(AuthError) as exc:
            await service.validate(token)
        assert exc.value.revoked_or_expired is True


# ---------------------------------------------------------------------------
# Service-to-service credentials (R19.5, R19.6)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.5: a minted service credential authenticates
async def test_service_credential_round_trip(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """A minted service credential authenticates and returns its service name (R19.5)."""
    async with async_sessionmaker_factory() as session:
        service = _make_service(session)
        credential = encode_service_credential("ingestion-worker")
        assert service.authenticate_service(credential) == "ingestion-worker"


# Feature: cineroi-ai, Requirement 19.6: an expired service credential is rejected
async def test_service_credential_rejects_expired(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """An expired service credential is rejected and flagged as expired (R19.6)."""
    async with async_sessionmaker_factory() as session:
        service = _make_service(session)
        credential = encode_service_credential(
            "ingestion-worker",
            expires_in=timedelta(minutes=5),
            issued_at=utcnow() - timedelta(minutes=10),
        )
        with pytest.raises(AuthError) as exc:
            service.authenticate_service(credential)
        assert exc.value.revoked_or_expired is True


# ---------------------------------------------------------------------------
# Idle-policy boundary sanity (R19.4) — pure helper, DB-independent control
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Requirement 19.4: the 30-minute idle boundary is exclusive
async def test_idle_boundary_matches_30_minute_policy(
    async_sessionmaker_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """The idle policy applied in the flow triggers strictly past 30 minutes.

    A control that pins the boundary the DB-backed expiry test relies on: at
    exactly 30 minutes a session is still live; one second past it is expired.
    """
    now = utcnow()
    assert is_session_idle_expired(now - timedelta(minutes=30), now=now) is False
    assert is_session_idle_expired(now - timedelta(minutes=30, seconds=1), now=now) is True
