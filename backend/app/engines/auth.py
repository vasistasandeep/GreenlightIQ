"""Auth_Service: SSO login, session lifecycle, and credential validation (R19).

This engine is the single authentication authority for the platform. It composes
the stateless primitives in :mod:`app.core.security` with the ``users`` and
``sessions`` repositories to implement Requirement 19 end to end:

* :meth:`AuthService.login_sso` — verify an OIDC/SAML assertion through a
  pluggable :class:`~app.core.security.SsoProvider`, resolve (or provision) the
  local user, and issue a server-side session **bound to that identity**,
  returning the session and a signed session token (R19.1, R19.2).
* :meth:`AuthService.validate` — authenticate a protected request from its
  session token: decode the token, load the bound session, reject when the
  session is missing/revoked (R19.3, R19.6) or has been idle past 30 minutes
  (R19.4), slide the idle window forward, and return the request's
  :class:`~app.core.security.UserContext`.
* :meth:`AuthService.authenticate_service` — validate a service-to-service API
  credential before an internal call is processed (R19.5), rejecting
  missing/expired credentials with a descriptive error (R19.3, R19.6).
* :meth:`AuthService.revoke` — explicitly invalidate a session so subsequent
  requests presenting its token are rejected as revoked (R19.6).

The engine ``flush``es through its repositories rather than committing, so the
surrounding request/task unit-of-work owns the transaction boundary — matching
every other engine in this package.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.security import (
    AuthError,
    Session as SessionContext,
    SsoProvider,
    UserContext,
    UserRole,
    decode_service_credential,
    decode_session_token,
    encode_session_token,
    is_session_idle_expired,
    utcnow,
)
from app.models.session import Session as SessionRow
from app.models.user import User
from app.repositories.users import SessionRepository, UserRepository


class AuthService:
    """SSO login, session lifecycle, and credential validation (R19).

    Constructed with the ``users``/``sessions`` repositories (bound to the
    surrounding unit-of-work's session) and an :class:`SsoProvider` that
    verifies incoming OIDC/SAML assertions. The provider is injected so the
    engine stays agnostic to the federation protocol and is trivially testable
    with a double.
    """

    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        sso_provider: SsoProvider,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._sso = sso_provider

    # -- SSO login (R19.1, R19.2) -------------------------------------------

    async def login_sso(self, assertion: Any) -> tuple[SessionRow, str]:
        """Authenticate via SSO and issue an identity-bound session (R19.1, R19.2).

        Verifies the OIDC/SAML ``assertion`` through the injected provider,
        resolves the local user by the IdP subject (provisioning one on first
        login), then creates a server-side ``sessions`` row bound to that user
        and returns it together with a signed session token the client presents
        on subsequent requests.

        The session is **bound to the authenticated identity** (R19.2): its
        ``user_id`` is the resolved user and the token carries both the session
        id and that user id, so a token can never be replayed against a
        different identity.

        Args:
            assertion: The raw OIDC id-token or SAML assertion from the IdP.

        Returns:
            A ``(session_row, session_token)`` tuple. The token is what the
            client stores and presents to :meth:`validate`.

        Raises:
            AuthError: The assertion is missing, malformed, or fails
                verification (R19.1).
        """
        identity = self._sso.verify(assertion)
        user = await self._resolve_user(identity)

        now = utcnow()
        session_row = SessionRow(
            session_id=uuid.uuid4(),
            user_id=user.user_id,
            issued_at=now,
            last_activity_at=now,
            revoked=False,
        )
        await self._sessions.create(session_row)

        token = encode_session_token(
            session_row.session_id,
            user.user_id,
            issued_at=now,
        )
        return session_row, token

    async def _resolve_user(self, identity: Any) -> User:
        """Return the local user for an SSO identity, provisioning on first login.

        Looks the principal up by the IdP ``subject``; when absent a new
        :class:`User` is created from the asserted claims. The role defaults to
        the least-privileged ``DATA_ANALYST`` when the IdP carries no (valid)
        role, so provisioning never silently grants elevated access.
        """
        user = await self._users.get_by_external_subject(identity.subject)
        if user is not None:
            return user

        role = identity.role or UserRole.DATA_ANALYST
        new_user = User(
            user_id=uuid.uuid4(),
            external_subject=identity.subject,
            display_name=identity.display_name,
            user_role=role.value,
            authorized_territories=list(identity.authorized_territories),
        )
        return await self._users.create(new_user)

    # -- Request validation (R19.3, R19.4, R19.6) ---------------------------

    async def validate(self, credential: str | None, *, now: datetime | None = None) -> UserContext:
        """Authenticate a protected request from its session token (R19.3, R19.4, R19.6).

        Decodes the token, loads the bound server-side session, and enforces the
        session's authority over its own lifetime:

        * a missing/malformed token, an unknown session, or a session whose
          bound user no longer exists is rejected as *unauthenticated* (R19.3);
        * a revoked session is rejected as *expired/revoked* (R19.6);
        * a session idle for more than 30 minutes is expired, rejected as
          *expired/revoked*, and requires re-authentication (R19.4, R19.6).

        On success the session's idle window slides forward (``last_activity_at``
        is set to ``now``) so active use keeps the session alive, and the
        request's :class:`UserContext` is returned.

        Args:
            credential: The signed session token presented by the client.
            now: Reference time for the idle check (defaults to the current UTC
                instant); injectable for deterministic tests.

        Returns:
            The authenticated :class:`UserContext`.

        Raises:
            AuthError: The credential is missing/invalid (R19.3) or the session
                is revoked/expired (R19.4, R19.6, flagged via
                ``revoked_or_expired``).
        """
        if not credential:
            raise AuthError("No credential presented.")

        claims = decode_session_token(credential)  # raises AuthError on bad signature
        session_id = self._claim_uuid(claims, "sid")

        session_row = await self._sessions.get(session_id)
        if session_row is None:
            # Token references a session that does not exist — treat as unauth.
            raise AuthError("Session not found.")
        if session_row.revoked:
            raise AuthError("Session has been revoked.", revoked_or_expired=True)

        reference = now or utcnow()
        if is_session_idle_expired(session_row.last_activity_at, now=reference):
            # Mark it revoked so the expiry is sticky, then reject (R19.4/R19.6).
            await self._sessions.update(session_row, revoked=True)
            raise AuthError(
                "Session expired after idle timeout; re-authentication required.",
                revoked_or_expired=True,
            )

        user = await self._users.get(session_row.user_id)
        if user is None:
            raise AuthError("Session is not bound to a known identity.")

        # Slide the idle window forward on successful, active use.
        await self._sessions.update(session_row, last_activity_at=reference)

        return self._to_user_context(user)

    # -- Service-to-service credentials (R19.5, R19.6) ----------------------

    def authenticate_service(self, credential: str | None) -> str:
        """Authenticate an internal service-to-service call (R19.5, R19.6).

        Validates the signed API credential before the internal call is
        processed and returns the calling service's name. Rejects a missing or
        malformed credential as unauthenticated (R19.3) and an expired one as
        expired (R19.6) — both via :class:`AuthError`.

        Args:
            credential: The service-to-service API credential.

        Returns:
            The authenticated calling service's name.

        Raises:
            AuthError: The credential is missing/invalid or expired.
        """
        return decode_service_credential(credential)

    # -- Session revocation (R19.6) -----------------------------------------

    async def revoke(self, session_id: uuid.UUID) -> None:
        """Revoke a session so later requests presenting its token fail (R19.6).

        Idempotent: revoking an unknown or already-revoked session is a no-op.
        """
        session_row = await self._sessions.get(session_id)
        if session_row is None or session_row.revoked:
            return
        await self._sessions.update(session_row, revoked=True)

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _claim_uuid(claims: dict[str, Any], key: str) -> uuid.UUID:
        """Parse a required UUID claim, raising :class:`AuthError` when invalid."""
        raw = claims.get(key)
        if not raw:
            raise AuthError("Credential is missing a required claim.")
        try:
            return uuid.UUID(str(raw))
        except (ValueError, AttributeError) as exc:
            raise AuthError("Credential carries a malformed identifier.") from exc

    @staticmethod
    def _to_user_context(user: User) -> UserContext:
        """Map a persisted :class:`User` to the request :class:`UserContext`."""
        territories = user.authorized_territories or []
        if isinstance(territories, dict):  # defensive: JSONB may deserialize oddly
            territories = list(territories.values())
        return UserContext(
            user_id=user.user_id,
            display_name=user.display_name,
            role=UserRole(user.user_role),
            authorized_territories=tuple(str(t) for t in territories),
        )


__all__ = ["AuthService"]
