"""Auth router: SSO login, logout, and session introspection (R19).

Exposes the three session endpoints from the design's "Added endpoints":

* ``POST /auth/login`` — exchange a verified OIDC/SAML assertion for a
  server-side session bound to the authenticated identity, returning a signed
  session token the client presents on later requests (R19.1, R19.2).
* ``POST /auth/logout`` — revoke the current session so subsequent requests
  presenting its token are rejected (R19.6).
* ``GET /auth/session`` — introspect the current session, returning the
  authenticated principal (R19.3); a missing/expired credential maps to the
  shared ``401`` envelope.

The router is a thin HTTP shell over :class:`~app.engines.auth.AuthService`; the
engine owns provisioning, idle-expiry (R19.4), and revocation. The session token
carries the ``sid``/``sub`` claims; logout decodes it to resolve the session id
to revoke without trusting the client for anything but the signed token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_service, get_current_user
from app.core.db import get_db_session
from app.core.errors import CredentialExpiredError, UnauthenticatedError
from app.core.security import (
    AuthError,
    SESSION_ID_CLAIM,
    UserContext,
    decode_session_token,
)
from app.engines.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    """Extract the raw session token from the ``Authorization`` header.

    Accepts ``Authorization: Bearer <token>`` (case-insensitive scheme) and
    falls back to a bare token with no scheme. Returns ``None`` when no usable
    credential is present. Logout needs the raw token to resolve the session id
    to revoke, which the shared ``get_current_user`` dependency does not expose.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return authorization.strip() or None


class LoginRequest(BaseModel):
    """An SSO login request carrying the IdP assertion (R19.1)."""

    assertion: str = Field(
        description="The signed OIDC id-token or SAML assertion from the IdP."
    )


class LoginResponse(BaseModel):
    """The issued session token and the authenticated principal (R19.2)."""

    session_token: str
    user_id: str
    display_name: str
    role: str
    authorized_territories: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    """The current authenticated principal (R19.3)."""

    user_id: str
    display_name: str
    role: str
    authorized_territories: list[str] = Field(default_factory=list)


def _user_payload(user: UserContext) -> dict:
    """Serialize a :class:`UserContext` into the common response fields."""
    return {
        "user_id": str(user.user_id),
        "display_name": user.display_name,
        "role": user.role.value,
        "authorized_territories": list(user.authorized_territories),
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    auth: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Authenticate via SSO and issue an identity-bound session (R19.1, R19.2).

    Verifies the assertion through the configured SSO provider, provisions the
    user on first login, and returns a signed session token plus the resolved
    principal. A missing/invalid assertion maps to ``401 UNAUTHENTICATED``; an
    expired assertion maps to ``401 CREDENTIAL_EXPIRED``.
    """
    try:
        _session_row, token = await auth.login_sso(body.assertion)
    except AuthError as exc:
        if exc.revoked_or_expired:
            raise CredentialExpiredError(str(exc)) from exc
        raise UnauthenticatedError(str(exc)) from exc

    # ``login_sso`` created and flushed the identity-bound session; validate
    # reads it back (sharing this router's session via dependency caching) and
    # yields the resolved principal for the response body.
    user = await auth.validate(token)
    await session.commit()
    return LoginResponse(session_token=token, **_user_payload(user))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(
    token: str | None = Depends(_bearer_token),
    session: AsyncSession = Depends(get_db_session),
    auth: AuthService = Depends(get_auth_service),
) -> Response:
    """Revoke the current session so its token stops authenticating (R19.6).

    Decodes the presented token to resolve the server-side session id and
    revokes it. A missing/invalid token maps to ``401 UNAUTHENTICATED``. Logout
    is idempotent — revoking an already-revoked session is a no-op.
    """
    if not token:
        raise UnauthenticatedError("No credential presented.")
    try:
        claims = decode_session_token(token)
    except AuthError as exc:
        raise UnauthenticatedError(str(exc)) from exc

    raw_sid = claims.get(SESSION_ID_CLAIM)
    if not raw_sid:
        raise UnauthenticatedError("Credential is missing a session identifier.")
    try:
        session_id = uuid.UUID(str(raw_sid))
    except ValueError as exc:
        raise UnauthenticatedError("Credential carries a malformed session id.") from exc

    await auth.revoke(session_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session", response_model=SessionResponse)
async def session(
    user: UserContext = Depends(get_current_user),
) -> SessionResponse:
    """Introspect the current session and return its principal (R19.3).

    Authentication is enforced by the :func:`get_current_user` dependency: a
    missing/invalid credential maps to ``401 UNAUTHENTICATED`` and a
    revoked/expired one to ``401 CREDENTIAL_EXPIRED`` via the shared envelope.
    """
    return SessionResponse(**_user_payload(user))
