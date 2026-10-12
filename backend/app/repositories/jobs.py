"""Repository for ``jobs`` (R23, R27.1, R29.3).

Tracks asynchronous units of work through the PENDING -> PROCESSING ->
COMPLETED|FAILED lifecycle (R23.3). ``idempotency_key`` is unique so a replayed
submission can be detected and the stored result returned (R27.1).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.job import Job
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Async access to the ``jobs`` table (R23)."""

    model = Job
    pk = Job.job_id

    async def get_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        """Return the job previously stored for an idempotency key (R27.1)."""
        stmt = select(Job).where(Job.idempotency_key == idempotency_key)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_status(self, status: str) -> list[Job]:
        """Return jobs currently in a given lifecycle status (R23.3)."""
        stmt = select(Job).where(Job.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_dead_lettered(self) -> list[Job]:
        """Return jobs routed to the dead-letter queue (R29.3)."""
        stmt = select(Job).where(Job.dead_lettered.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
