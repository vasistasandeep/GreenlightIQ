"""Security primitives for authentication, sessions, and service credentials.

This module holds the *pure*, dependency-light building blocks the
:class:`~app.engines.auth.AuthService` composes (Requirement 19):

* identity/session value types (:class:`UserContext`, :class:`Session`),
* the role enum (:class:`UserRole`),
* the idle-expiry policy (R19.4),
* signed session-token encode/decode (R19.2, R19.3),
* the SSO assertion abstraction that normalizes an OIDC or SAML assertion into
  verified identity claims (R19.1), and
* service-to-service API credential encode/decode (R19.5).

Database access, user provisioning, and session persistence live in the
engine (:mod:`app.engines.auth`); everything here is stateless and testable
without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

import jwt

from app.core.config import get_settings


class UserRole(str, Enum):
    """Role-based access control roles (R20.1)."""

    DATA_ANALYST = "DATA_ANALYST"
    CONTENT_BUYER = "CONTENT_BUYER"
    CHIEF_CONTENT_OFFICER = "CHIEF_CONTENT_OFFICER"
    CFO = "CFO"


@dataclass(frozen=True)
class UserContext:
    """The authenticated actor passed through the request pipeline.

    This is the identity used by RBAC checks, audit logging, and approval
    workflows. It is a stub shape here; populated for real by the Auth_Service.
    """

    user_id: UUID
    display_name: str
    role: UserRole
    authorized_territories: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Session:
    """A session bound to an authenticated identity (R19.2)."""

    session_id: UUID
    user_id: UUID
    issued_at: datetime
    last_activity_at: datetime
    revoked: bool = False


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class AuthError(Exception):
    """Raised when a credential is missing, expired, or revoked (R19.3, R19.6).

    The ``revoked_or_expired`` flag distinguishes the two authentication
    failure modes so the engine can map them to the right error envelope: a
    *missing/malformed* credential is a plain ``UNAUTHENTICATED`` (R19.3) while
    a credential that was once valid but is now *expired or revoked* is a
    ``CREDENTIAL_EXPIRED`` (R19.6).
    """

    def __init__(self, message: str, *, revoked_or_expired: bool = False) -> None:
        super().__init__(message)
        self.revoked_or_expired = revoked_or_expired


# ---------------------------------------------------------------------------
# Idle-expiry policy (R19.4)
# ---------------------------------------------------------------------------

#: Minutes a session may sit idle before it is considered expired (R19.4). The
#: value mirrors ``Settings.session_idle_timeout_minutes`` and is exposed as a
#: module constant so pure-logic callers (and tests) can reference the policy
#: without constructing settings.
SESSION_IDLE_TIMEOUT_MINUTES: int = 30


def session_idle_timeout() -> timedelta:
    """Return the configured idle-expiry window as a :class:`timedelta` (R19.4).

    Reads ``session_idle_timeout_minutes`` from settings so deployments can
    tune the window, falling back to the 30-minute policy default.
    """
    minutes = get_settings().session_idle_timeout_minutes
    return timedelta(minutes=minutes)


def is_session_idle_expired(last_activity_at: datetime, *, now: datetime) -> bool:
    """Return ``True`` when a session has been idle past the timeout (R19.4).

    A session whose ``last_activity_at`` is older than the idle window is
    expired and must trigger re-authentication on the next request. Both
    timestamps are treated as timezone-aware UTC; a naive ``last_activity_at``
    is assumed to be UTC for comparison robustness.
    """
    if last_activity_at.tzinfo is None:
        last_activity_at = last_activity_at.replace(tzinfo=timezone.utc)
    return (now - last_activity_at) > session_idle_timeout()


# ---------------------------------------------------------------------------
# Session-token encode / decode (R19.2, R19.3)
# ---------------------------------------------------------------------------

#: JWT claim carrying the server-side session identifier the token represents.
SESSION_ID_CLAIM = "sid"
#: JWT claim carrying the authenticated user identifier bound to the session.
USER_ID_CLAIM = "sub"


def encode_session_token(
    session_id: UUID,
    user_id: UUID,
    *,
    issued_at: datetime | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Encode a signed session token for an issued session (R19.2).

    The token is a stateless pointer to the server-side session row: it carries
    the session id (:data:`SESSION_ID_CLAIM`) and the bound user id
    (:data:`USER_ID_CLAIM`). Authority over expiry/revocation remains with the
    server-side ``sessions`` record (idle expiry R19.4, revocation R19.6); the
    token itself is only a signed carrier, so decoding does not enforce ``exp``.

    Args:
        session_id: The server-side session this token represents.
        user_id: The authenticated identity bound to the session.
        issued_at: Optional issue time recorded in the ``iat`` claim.
        extra_claims: Additional claims to merge into the payload.

    Returns:
        A compact, signed JWT string.
    """
    settings = get_settings()
    payload: dict[str, Any] = {
        SESSION_ID_CLAIM: str(session_id),
        USER_ID_CLAIM: str(user_id),
    }
    if issued_at is not None:
        payload["iat"] = int(issued_at.timestamp())
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.access_token_algorithm,
    )


def decode_session_token(token: str) -> dict[str, Any]:
    """Decode and verify the signature of a session token (R19.3).

    Verifies only the token signature; expiry/revocation are decided by the
    server-side session record, not the token. Raises :class:`AuthError` when
    the token is malformed or its signature does not verify so callers can map
    the failure to an authentication error.

    Args:
        token: The signed session token.

    Returns:
        The decoded claims mapping.

    Raises:
        AuthError: The token is invalid or its signature failed verification.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.access_token_algorithm],
            # The server-side session row is the source of truth for lifetime;
            # don't let a missing/zero ``exp`` claim reject an otherwise valid
            # signed token.
            options={"verify_exp": False},
        )
    except jwt.PyJWTError as exc:  # malformed, bad signature, wrong algorithm
        raise AuthError("Invalid session token.") from exc


# ---------------------------------------------------------------------------
# SSO assertion abstraction (R19.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SsoIdentity:
    """Verified identity claims extracted from an SSO assertion (R19.1).

    This is the provider-agnostic result of validating an OIDC or SAML
    assertion: a stable ``subject`` (the IdP's unique principal identifier used
    to resolve/provision the local user), a human-readable ``display_name``,
    and optional role/territory hints the IdP may carry.
    """

    subject: str
    display_name: str
    role: UserRole | None = None
    authorized_territories: tuple[str, ...] = field(default_factory=tuple)


class SsoProvider(Protocol):
    """Pluggable SSO identity provider that verifies an assertion (R19.1).

    A provider validates an OIDC or SAML assertion (signature, audience,
    expiry) and returns the verified :class:`SsoIdentity`. The protocol lets the
    Auth_Service remain agnostic to the concrete federation protocol: deployments
    inject an OIDC provider, a SAML provider, or a test double.

    Implementations MUST raise :class:`AuthError` when the assertion is missing,
    malformed, or fails verification so the login flow surfaces an
    authentication error rather than provisioning an unverified identity.
    """

    def verify(self, assertion: Any) -> SsoIdentity:
        """Validate the assertion and return the verified identity.

        Raises:
            AuthError: The assertion is absent, malformed, or fails signature /
                audience / expiry verification.
        """
        ...


class JwtOidcProvider:
    """OIDC :class:`SsoProvider` backed by a signed JWT id-token (R19.1).

    Verifies the id-token's signature (and audience, when
    ``Settings.sso_audience`` is configured) using the configured algorithm,
    then maps standard OIDC claims onto an :class:`SsoIdentity`:

    * ``sub``   → :attr:`SsoIdentity.subject` (required),
    * ``name``  → :attr:`SsoIdentity.display_name` (falls back to ``email`` /
      ``preferred_username`` / ``sub``),
    * ``role``  → :attr:`SsoIdentity.role` when it names a valid
      :class:`UserRole`,
    * ``territories`` → :attr:`SsoIdentity.authorized_territories`.

    SAML deployments provide a sibling provider that parses a signed SAML
    assertion into the same :class:`SsoIdentity` shape; both satisfy
    :class:`SsoProvider` so the engine is protocol-agnostic.
    """

    def __init__(self, *, signing_key: str | None = None, audience: str | None = None) -> None:
        settings = get_settings()
        self._key = signing_key or settings.secret_key
        self._algorithm = settings.access_token_algorithm
        # An explicit audience arg wins; otherwise fall back to settings. None
        # disables the audience check (local/dev only).
        self._audience = audience if audience is not None else settings.sso_audience

    def verify(self, assertion: Any) -> SsoIdentity:
        """Verify a signed OIDC id-token and extract its identity claims (R19.1)."""
        if not assertion or not isinstance(assertion, str):
            raise AuthError("Missing or malformed SSO assertion.")
        decode_kwargs: dict[str, Any] = {
            "key": self._key,
            "algorithms": [self._algorithm],
        }
        if self._audience is not None:
            decode_kwargs["audience"] = self._audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        try:
            claims = jwt.decode(assertion, **decode_kwargs)
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("SSO assertion has expired.", revoked_or_expired=True) from exc
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid SSO assertion.") from exc

        subject = claims.get("sub")
        if not subject:
            raise AuthError("SSO assertion is missing a subject claim.")

        display_name = (
            claims.get("name")
            or claims.get("email")
            or claims.get("preferred_username")
            or str(subject)
        )

        role: UserRole | None = None
        raw_role = claims.get("role")
        if raw_role is not None:
            try:
                role = UserRole(raw_role)
            except ValueError:
                role = None

        raw_territories = claims.get("territories") or ()
        if isinstance(raw_territories, (list, tuple)):
            territories = tuple(str(t) for t in raw_territories)
        else:
            territories = ()

        return SsoIdentity(
            subject=str(subject),
            display_name=str(display_name),
            role=role,
            authorized_territories=territories,
        )


# ---------------------------------------------------------------------------
# Service-to-service API credentials (R19.5)
# ---------------------------------------------------------------------------

#: JWT claim marking a token as a service-to-service credential rather than a
#: user session. :func:`decode_service_credential` requires it to be truthy.
SERVICE_CLAIM = "svc"
#: JWT claim carrying the calling service's name/identifier.
SERVICE_NAME_CLAIM = "svc_name"


def _service_signing_key() -> str:
    """Return the signing key for service credentials (R19.5).

    Uses ``Settings.service_credential_secret`` when configured so service
    identity is keyed separately from user sessions, falling back to
    ``secret_key`` so local/dev still boots.
    """
    settings = get_settings()
    return settings.service_credential_secret or settings.secret_key


def encode_service_credential(
    service_name: str,
    *,
    expires_in: timedelta | None = None,
    issued_at: datetime | None = None,
) -> str:
    """Mint a signed service-to-service API credential (R19.5).

    The credential is a JWT marked with :data:`SERVICE_CLAIM` and naming the
    caller via :data:`SERVICE_NAME_CLAIM`. Unlike user sessions (whose lifetime
    the server-side ``sessions`` row owns), a service credential is stateless
    and MAY carry an ``exp`` claim so it expires without server coordination.

    Args:
        service_name: Identifier of the calling service.
        expires_in: Optional validity window; when supplied an ``exp`` claim is
            stamped and enforced on decode.
        issued_at: Optional issue time (defaults to now when ``expires_in`` is
            given, so ``exp`` is computed relative to issue).

    Returns:
        A compact signed JWT credential.
    """
    now = issued_at or utcnow()
    payload: dict[str, Any] = {
        SERVICE_CLAIM: True,
        SERVICE_NAME_CLAIM: service_name,
        "iat": int(now.timestamp()),
    }
    if expires_in is not None:
        payload["exp"] = int((now + expires_in).timestamp())
    settings = get_settings()
    return jwt.encode(
        payload,
        _service_signing_key(),
        algorithm=settings.access_token_algorithm,
    )


def decode_service_credential(credential: str | None) -> str:
    """Verify a service credential and return the calling service name (R19.5, R19.6).

    Verifies the signature and, when present, the ``exp`` claim. Rejects a
    credential that is missing, malformed, not marked as a service credential,
    or expired.

    Args:
        credential: The signed service credential.

    Returns:
        The calling service's name from :data:`SERVICE_NAME_CLAIM`.

    Raises:
        AuthError: The credential is missing/malformed (R19.3) or expired/invalid
            (R19.6, flagged via ``revoked_or_expired``).
    """
    if not credential:
        raise AuthError("Missing service credential.")
    settings = get_settings()
    try:
        claims = jwt.decode(
            credential,
            _service_signing_key(),
            algorithms=[settings.access_token_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(
            "Service credential has expired.", revoked_or_expired=True
        ) from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid service credential.") from exc

    if not claims.get(SERVICE_CLAIM):
        raise AuthError("Credential is not a service-to-service credential.")
    service_name = claims.get(SERVICE_NAME_CLAIM)
    if not service_name:
        raise AuthError("Service credential is missing a service name.")
    return str(service_name)
