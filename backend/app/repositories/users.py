"""Repositories for ``users`` and ``sessions`` (R19, R20).

``UserRepository`` resolves principals by their external SSO subject (R19.2,
R20.1). ``SessionRepository`` manages server-side sessions used for idle-expiry
and revocation checks (R19.4, R19.6).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.session import Session
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Async access to the ``users`` table (R20.1)."""

    model = User
    pk = User.user_id

    async def get_by_external_subject(self, external_subject: str) -> User | None:
        """Return the user mapped from an SSO subject, if any (R19.2)."""
        stmt = select(User).where(User.external_subject == external_subject)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_role(self, role: str) -> User | None:
        """Return any user holding the given role, if one exists (R20.1).

        Used by the dev/demo sign-off helper to attribute an approval to a
        seeded user who actually holds the required executive role.
        """
        stmt = select(User).where(User.user_role == role).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()


class SessionRepository(BaseRepository[Session]):
    """Async access to the ``sessions`` table (R19.2, R19.4, R19.6)."""

    model = Session
    pk = Session.session_id

    async def list_for_user(self, user_id: uuid.UUID) -> list[Session]:
        """Return all sessions bound to a user."""
        stmt = select(Session).where(Session.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, session_id: uuid.UUID) -> Session | None:
        """Return a session only if it exists and is not revoked (R19.6)."""
        stmt = select(Session).where(
            Session.session_id == session_id,
            Session.revoked.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
