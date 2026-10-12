"""Repository for immutable ``model_versions`` (R26, R12.2).

Model versions are never mutated in place: calibration inserts a new row with
``supersedes_id`` pointing at the prior one and flips ``is_active`` (R26.1,
R26.3, R26.4). This repository therefore exposes active-version lookup and chain
helpers but relies on the service layer (task 7) for the create+flip workflow.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.model_version import ModelVersion
from app.repositories.base import BaseRepository


class ModelVersionRepository(BaseRepository[ModelVersion]):
    """Async access to the ``model_versions`` table (R26)."""

    model = ModelVersion
    pk = ModelVersion.model_version_id

    async def get_active(self) -> ModelVersion | None:
        """Return the single active model version, if any (R26.4)."""
        stmt = select(ModelVersion).where(ModelVersion.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> list[ModelVersion]:
        """Return all model versions, newest first (version catalog, R26.3)."""
        stmt = select(ModelVersion).order_by(ModelVersion.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_superseded_by(
        self, model_version_id: uuid.UUID
    ) -> ModelVersion | None:
        """Return the version that supersedes ``model_version_id``, if any."""
        stmt = select(ModelVersion).where(
            ModelVersion.supersedes_id == model_version_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
