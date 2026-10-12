"""Unit tests for the Auth_Service and its security primitives (R19).

Covers the Requirement 19 authentication flows exercised by
``app.engines.auth.AuthService`` and the stateless helpers in
``app.core.security``:

* SSO login issues an identity-bound session + token (R19.1, R19.2),
* request validation rejects missing/unknown/revoked credentials (R19.3, R19.6)
  and enforces the 30-minute idle expiry (R19.4),
* service-to-service credentials are minted and validated (R19.5),
* expired service credentials are rejected (R19.6).

Per the design testing strategy, engine orchestration is tested against
*in-memory* repository fakes rather than a real database. The fakes model only
the methods the engine uses: ``get`` / ``create`` / ``update`` /
``get_by_external_subject``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    AuthError,
    JwtOidcProvider,
    SsoIdentity,
    UserContext,
    UserRole,
    decode_service_credential,
    decode_session_token,
    encode_service_credential,
    is_session_idle_expired,
    utcnow,
)
from app.engines.auth import AuthService
from app.models.session import Session as SessionRow
from app.models.user import User


# ---------------------------------------------------------------------------
# In-memory repository fakes
# ---------------------------------------------------------------------------


class FakeUserRepository:
    """In-memory stand-in for ``UserRepository`` (R19.2, R20.1)."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, User] = {}
        self._by_subject: dict[str, User] = {}

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_external_subject(self, external_subject: str) -> User | None:
        return self._by_subject.get(external_subject)

    async def create(self, instance: User) -> User:
        self._by_id[instance.user_id] = instance
        if instance.external_subject is not None:
            self._by_subject[instance.external_subject] = instance
        return instance


class FakeSessionRepository:
    """In-memory stand-in for ``SessionRepository`` (R19.2, R19.4, R19.6)."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, SessionRow] = {}

    async def get(self, session_id: uuid.UUID) -> SessionRow | None:
        return self._by_id.get(session_id)

    async def create(self, instance: SessionRow) -> SessionRow:
        self._by_id[instance.session_id] = instance
        return instance

    async def update(self, instance: SessionRow, **values: object) -> SessionRow:
        for key, value in values.items():
            setattr(instance, key, value)
        return instance


class StubSsoProvider:
    """Deterministic ``SsoProvider`` returning a fixed identity.

    When ``raise_error`` is set, :meth:`verify` raises it instead, modelling a
    rejected assertion.
    """

    def __init__(self, identity: SsoIdentity | None = None, raise_error: Exception | None = None):
        self._identity = identity
        self._raise = raise_error

    def verify(self, assertion: object) -> SsoIdentity:
        if self._raise is not None:
            raise self._raise
        assert self._identity is not None
        return self._identity


def _make_service(
    *,
    identity: SsoIdentity | None = None,
    raise_error: Exception | None = None,
) -> tuple[AuthService, FakeUserRepository, FakeSessionRepository]:
    users = FakeUserRepository()
    sessions = FakeSessionRepository()
    provider = StubSsoProvider(identity=identity, raise_error=raise_error)
    service = AuthService(users=users, sessions=sessions, sso_provider=provider)  # type: ignore[arg-type]
    return service, users, sessions


_IDENTITY = SsoIdentity(
    subject="idp|alice",
    display_name="Alice Analyst",
    role=UserRole.CONTENT_BUYER,
    authorized_territories=("US", "GB"),
)


# ---------------------------------------------------------------------------
# SSO login (R19.1, R19.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sso_provisions_user_and_issues_bound_session():
    """First login provisions the user and issues a session bound to it (R19.1, R19.2)."""
    service, users, sessions = _make_service(identity=_IDENTITY)

    session_row, token = await service.login_sso("assertion")

    # A user was provisioned from the asserted subject.
    user = await users.get_by_external_subject("idp|alice")
    assert user is not None
    assert user.display_name == "Alice Analyst"
    assert user.user_role == UserRole.CONTENT_BUYER.value

    # The session is bound to that identity and the token carries both ids.
    assert session_row.user_id == user.user_id
    assert session_row.revoked is False
    claims = decode_session_token(token)
    assert claims["sid"] == str(session_row.session_id)
    assert claims["sub"] == str(user.user_id)


@pytest.mark.asyncio
async def test_login_sso_reuses_existing_user():
    """A returning subject reuses the existing user rather than duplicating it (R19.2)."""
    service, users, _ = _make_service(identity=_IDENTITY)

    first, _ = await service.login_sso("assertion")
    second, _ = await service.login_sso("assertion")

    first_user = await users.get(first.user_id)
    second_user = await users.get(second.user_id)
    assert first_user is not None and second_user is not None
    assert first_user.user_id == second_user.user_id


@pytest.mark.asyncio
async def test_login_sso_rejects_bad_assertion():
    """A failed assertion verification surfaces an AuthError (R19.1)."""
    service, _, _ = _make_service(raise_error=AuthError("bad assertion"))
    with pytest.raises(AuthError):
        await service.login_sso("garbage")


@pytest.mark.asyncio
async def test_login_sso_defaults_to_least_privileged_role():
    """Provisioning without an asserted role defaults to DATA_ANALYST (no silent elevation)."""
    identity = SsoIdentity(subject="idp|bob", display_name="Bob", role=None)
    service, users, _ = _make_service(identity=identity)

    await service.login_sso("assertion")

    user = await users.get_by_external_subject("idp|bob")
    assert user is not None
    assert user.user_role == UserRole.DATA_ANALYST.value


# ---------------------------------------------------------------------------
# Request validation (R19.3, R19.4, R19.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_returns_user_context_for_active_session():
    """A fresh session validates and yields the bound UserContext (R19.2)."""
    service, _, _ = _make_service(identity=_IDENTITY)
    _, token = await service.login_sso("assertion")

    ctx = await service.validate(token)

    assert isinstance(ctx, UserContext)
    assert ctx.display_name == "Alice Analyst"
    assert ctx.role == UserRole.CONTENT_BUYER
    assert ctx.authorized_territories == ("US", "GB")


@pytest.mark.asyncio
async def test_validate_rejects_missing_credential():
    """A missing credential is rejected as unauthenticated (R19.3)."""
    service, _, _ = _make_service()
    with pytest.raises(AuthError) as exc:
        await service.validate(None)
    assert exc.value.revoked_or_expired is False


@pytest.mark.asyncio
async def test_validate_rejects_unknown_session():
    """A well-formed token for a nonexistent session is rejected (R19.3)."""
    from app.core.security import encode_session_token

    service, _, _ = _make_service()
    token = encode_session_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(AuthError):
        await service.validate(token)


@pytest.mark.asyncio
async def test_validate_rejects_revoked_session():
    """A revoked session is rejected as expired/revoked (R19.6)."""
    service, _, _ = _make_service(identity=_IDENTITY)
    session_row, token = await service.login_sso("assertion")

    await service.revoke(session_row.session_id)

    with pytest.raises(AuthError) as exc:
        await service.validate(token)
    assert exc.value.revoked_or_expired is True


@pytest.mark.asyncio
async def test_validate_expires_idle_session_after_30_minutes():
    """A session idle past the 30-minute window is expired on next use (R19.4, R19.6)."""
    service, _, sessions = _make_service(identity=_IDENTITY)
    session_row, token = await service.login_sso("assertion")

    # 31 minutes after last activity -> expired.
    later = session_row.last_activity_at + timedelta(minutes=31)
    with pytest.raises(AuthError) as exc:
        await service.validate(token, now=later)
    assert exc.value.revoked_or_expired is True
    # Expiry is sticky: the session row is now marked revoked.
    stored = await sessions.get(session_row.session_id)
    assert stored is not None and stored.revoked is True


@pytest.mark.asyncio
async def test_validate_slides_idle_window_on_active_use():
    """Active use within the window slides last_activity_at forward (R19.4)."""
    service, _, sessions = _make_service(identity=_IDENTITY)
    session_row, token = await service.login_sso("assertion")

    within = session_row.last_activity_at + timedelta(minutes=10)
    await service.validate(token, now=within)

    stored = await sessions.get(session_row.session_id)
    assert stored is not None
    assert stored.last_activity_at == within


# ---------------------------------------------------------------------------
# Service-to-service credentials (R19.5, R19.6)
# ---------------------------------------------------------------------------


def test_service_credential_round_trip():
    """A minted service credential authenticates and returns its service name (R19.5)."""
    service, _, _ = _make_service()
    credential = encode_service_credential("ingestion-worker")
    assert service.authenticate_service(credential) == "ingestion-worker"


def test_service_credential_rejects_missing():
    """A missing service credential is rejected (R19.3)."""
    service, _, _ = _make_service()
    with pytest.raises(AuthError):
        service.authenticate_service(None)


def test_service_credential_rejects_expired():
    """An expired service credential is rejected as expired (R19.6)."""
    service, _, _ = _make_service()
    credential = encode_service_credential(
        "ingestion-worker",
        expires_in=timedelta(minutes=5),
        issued_at=utcnow() - timedelta(minutes=10),
    )
    with pytest.raises(AuthError) as exc:
        service.authenticate_service(credential)
    assert exc.value.revoked_or_expired is True


def test_service_credential_rejects_plain_session_token():
    """A user-session token must not pass as a service credential (R19.5)."""
    from app.core.security import encode_session_token

    token = encode_session_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(AuthError):
        decode_service_credential(token)


# ---------------------------------------------------------------------------
# SSO provider + idle-policy helpers (R19.1, R19.4)
# ---------------------------------------------------------------------------


def test_jwt_oidc_provider_extracts_identity():
    """The OIDC provider maps standard claims onto an SsoIdentity (R19.1)."""
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "idp|carol",
            "name": "Carol CFO",
            "role": "CFO",
            "territories": ["US"],
        },
        settings.secret_key,
        algorithm=settings.access_token_algorithm,
    )
    provider = JwtOidcProvider()
    identity = provider.verify(token)
    assert identity.subject == "idp|carol"
    assert identity.display_name == "Carol CFO"
    assert identity.role == UserRole.CFO
    assert identity.authorized_territories == ("US",)


def test_jwt_oidc_provider_rejects_missing_subject():
    """An assertion without a subject claim is rejected (R19.1)."""
    settings = get_settings()
    token = jwt.encode(
        {"name": "No Subject"},
        settings.secret_key,
        algorithm=settings.access_token_algorithm,
    )
    provider = JwtOidcProvider()
    with pytest.raises(AuthError):
        provider.verify(token)


def test_jwt_oidc_provider_rejects_empty_assertion():
    """A missing/empty assertion is rejected (R19.1)."""
    provider = JwtOidcProvider()
    with pytest.raises(AuthError):
        provider.verify("")


def test_idle_expiry_boundary():
    """Idle expiry triggers strictly past the window, not at it (R19.4)."""
    now = utcnow()
    # Exactly at the 30-minute boundary is not yet expired.
    at_boundary = now - timedelta(minutes=30)
    assert is_session_idle_expired(at_boundary, now=now) is False
    # One second past the boundary is expired.
    past = now - timedelta(minutes=30, seconds=1)
    assert is_session_idle_expired(past, now=now) is True
