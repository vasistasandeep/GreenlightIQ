"""Repository for the append-only ``audit_log`` (R25.1, R25.2).

The audit trail is insert-only — append-only is enforced in the database by
revoking UPDATE/DELETE and a mutation-blocking trigger. This repository
therefore exposes only create and lineage read helpers and intentionally omits
``update``/``delete`` from its surface (the inherited methods would be rejected
by the database trigger).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    """Async insert/read access to the append-only ``audit_log`` (R25)."""

    model = AuditLog
    pk = AuditLog.audit_id

    async def list_for_subject(self, subject_id: uuid.UUID) -> list[AuditLog]:
        """Return the chronological lineage of entries for a subject (R25.4)."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.subject_id == subject_id)
            .order_by(AuditLog.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
