"""Audit_Log_Service: the append-only audit trail and lineage reader (R25).

This engine is the single write path for the ``audit_log`` table. State-changing
operations across the system (ingest, valuation, override, approval, calibration)
call :meth:`AuditLogService.record` to capture *who* did *what*, *when*, and the
*before*/*after* values of the affected subject (R25.1). Entries are append-only:
each :meth:`record` call writes exactly one row and never updates or deletes an
existing one — append-only is additionally enforced in the database by revoked
UPDATE/DELETE privileges and a mutation-blocking trigger (R25.2).

When a valuation is produced it is associated with the model version in effect
at the time via ``model_version_id`` (R25.3). :meth:`AuditLogService.lineage`
returns the complete, chronologically ordered trail for a subject so compliance
can trace every input and change for a title or decision (R25.4).

The service is a thin orchestration layer over :class:`AuditLogRepository`; it
holds the injected :class:`~sqlalchemy.ext.asyncio.AsyncSession` only to flush
new rows and does not open a database connection on import.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.audit_log import AuditLogRepository


class AuditLogService:
    """Append-only audit recorder and lineage reader (R25).

    Wraps :class:`AuditLogRepository` to provide the two operations the rest of
    the system needs: appending a single immutable entry for a state-changing
    action, and reading back the ordered lineage for a subject.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AuditLogRepository(session)

    async def record(
        self,
        actor: uuid.UUID | None,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        model_version_id: uuid.UUID | None = None,
        *,
        subject_id: uuid.UUID,
    ) -> AuditLog:
        """Append exactly one audit entry for a state-changing action (R25.1-R25.3).

        Writes a single append-only row capturing the actor identity, the action,
        and the before/after values of the affected subject (R25.1). The
        timestamp is supplied by the database ``created_at`` server default so
        the recorded time reflects the server clock at insert, not the caller's
        (R25.1). When the action produces a valuation, ``model_version_id``
        associates the entry with the model version active at the time (R25.3).

        The entry is insert-only; this method never mutates or deletes an
        existing row, upholding the append-only guarantee (R25.2).

        Args:
            actor: The identity performing the action, or ``None`` for a
                system-initiated action with no human actor.
            action: A short label for the state-changing operation (e.g.
                ``"ingest"``, ``"valuation"``, ``"override"``, ``"approval"``,
                ``"calibration"``).
            before: The subject's prior state as a JSON-serializable mapping, or
                ``None`` when the action created the subject.
            after: The subject's resulting state as a JSON-serializable mapping,
                or ``None`` when the action removed/retired the subject.
            model_version_id: The model version in effect when a valuation was
                produced; ``None`` for actions that are not valuations (R25.3).
            subject_id: The title or decision the entry pertains to; used to
                reconstruct lineage (R25.4).

        Returns:
            The persisted :class:`AuditLog` entry with its generated
            ``audit_id`` and server-assigned ``created_at`` populated.
        """
        entry = AuditLog(
            subject_id=subject_id,
            actor_id=actor,
            action=action,
            before_value=before,
            after_value=after,
            model_version_id=model_version_id,
        )
        return await self.repository.create(entry)

    async def lineage(self, subject_id: uuid.UUID) -> list[AuditLog]:
        """Return the complete, chronologically ordered trail for a subject (R25.4).

        Args:
            subject_id: The title or decision whose lineage is requested.

        Returns:
            Every audit entry for ``subject_id`` ordered oldest-first by
            ``created_at``, giving the full ordered set of inputs and changes.
        """
        return await self.repository.list_for_subject(subject_id)
