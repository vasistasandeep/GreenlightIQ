"""Repository for ``license_terms`` (R22).

Captures the licensing / windowing contract structure for a title used by
milestone-based payback computation (R22.2). Foreign key on ``title_id`` ties
each row to its title.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.license_term import LicenseTerm
from app.repositories.base import BaseRepository


class LicenseTermRepository(BaseRepository[LicenseTerm]):
    """Async access to the ``license_terms`` table (R22)."""

    model = LicenseTerm
    pk = LicenseTerm.license_id

    async def list_for_title(self, title_id: uuid.UUID) -> list[LicenseTerm]:
        """Return all license terms recorded for a title."""
        stmt = select(LicenseTerm).where(LicenseTerm.title_id == title_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
