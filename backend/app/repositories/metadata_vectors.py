"""Repository for ``metadata_vectors`` (R17.2, R17.6).

Stores the extracted Narrative_DNA embedding and affective/pedigree scores for a
title. Foreign key on ``title_id`` enforces referential integrity (R17.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.metadata_vector import MetadataVector
from app.repositories.base import BaseRepository


class MetadataVectorRepository(BaseRepository[MetadataVector]):
    """Async access to the ``metadata_vectors`` table."""

    model = MetadataVector
    pk = MetadataVector.metadata_id

    async def list_for_title(
        self, title_id: uuid.UUID
    ) -> list[MetadataVector]:
        """Return all metadata vectors recorded for a title."""
        stmt = select(MetadataVector).where(
            MetadataVector.title_id == title_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_title_version(
        self, title_version_id: uuid.UUID
    ) -> MetadataVector | None:
        """Return the metadata vector tied to a specific title version (R24.3)."""
        stmt = select(MetadataVector).where(
            MetadataVector.title_version_id == title_version_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
