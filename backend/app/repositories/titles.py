"""Repository for ``titles`` (R17.1, R17.2) and ``title_versions`` (R24).

``titles`` carries a ``row_version`` optimistic-lock column, so this repository
exposes :meth:`TitleRepository.update_with_version` (inherited) for safe
concurrent updates (R27.2). ``title_versions`` snapshots are immutable, so its
repository is insert-/read-only plus active-version lookup helpers (R24).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.title import Title
from app.models.title_version import TitleVersion
from app.repositories.base import BaseRepository


class TitleRepository(BaseRepository[Title]):
    """Async access to the ``titles`` table (optimistic-lock aware, R27.2)."""

    model = Title
    pk = Title.title_id

    async def list_historical(self) -> list[Title]:
        """Return titles flagged as historical (used by backtesting)."""
        stmt = select(Title).where(Title.is_historical.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class TitleVersionRepository(BaseRepository[TitleVersion]):
    """Async access to immutable ``title_versions`` snapshots (R24)."""

    model = TitleVersion
    pk = TitleVersion.title_version_id

    async def list_for_title(self, title_id: uuid.UUID) -> list[TitleVersion]:
        """Return all versions of a title ordered by ascending version number."""
        stmt = (
            select(TitleVersion)
            .where(TitleVersion.title_id == title_id)
            .order_by(TitleVersion.version_number.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, title_id: uuid.UUID) -> TitleVersion | None:
        """Return the single active version for a title, if any (R24.4)."""
        stmt = select(TitleVersion).where(
            TitleVersion.title_id == title_id,
            TitleVersion.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def latest_version_number(self, title_id: uuid.UUID) -> int:
        """Return the highest ``version_number`` for a title (0 if none, R24.2)."""
        stmt = select(TitleVersion.version_number).where(
            TitleVersion.title_id == title_id
        )
        result = await self.session.execute(stmt)
        numbers = result.scalars().all()
        return max(numbers, default=0)
