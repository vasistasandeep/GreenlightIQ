"""Audit router: ordered lineage retrieval (R25.4).

Exposes ``GET /audit/lineage/{subject_id}`` from the design's "Added endpoints":
the complete, chronologically ordered audit trail for a subject (a title or a
decision), so compliance can trace every input and change (R25.4). Entries are
append-only (R25.2); this is a read-only view over
:class:`~app.engines.audit.AuditLogService`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_service, get_current_user
from app.core.security import UserContext
from app.engines.audit import AuditLogService

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryResponse(BaseModel):
    """One append-only audit entry in a subject's lineage (R25.1, R25.4)."""

    audit_id: uuid.UUID
    subject_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    action: str
    before_value: dict | None = None
    after_value: dict | None = None
    model_version_id: uuid.UUID | None = None
    created_at: datetime | None = None


class LineageResponse(BaseModel):
    """The ordered lineage for a subject (R25.4)."""

    subject_id: uuid.UUID
    entries: list[AuditEntryResponse] = Field(default_factory=list)


@router.get("/lineage/{subject_id}", response_model=LineageResponse)
async def get_lineage(
    subject_id: uuid.UUID,
    audit: AuditLogService = Depends(get_audit_service),
    _actor: UserContext = Depends(get_current_user),
) -> LineageResponse:
    """Return the chronological audit lineage for a subject (R25.4).

    Entries are returned oldest-first. A subject with no recorded actions yields
    an empty ``entries`` list rather than a 404 — absence of lineage is a valid,
    expressible state (nothing has happened to the subject yet).
    """
    entries = await audit.lineage(subject_id)
    return LineageResponse(
        subject_id=subject_id,
        entries=[
            AuditEntryResponse(
                audit_id=e.audit_id,
                subject_id=e.subject_id,
                actor_id=e.actor_id,
                action=e.action,
                before_value=e.before_value,
                after_value=e.after_value,
                model_version_id=e.model_version_id,
                created_at=e.created_at,
            )
            for e in entries
        ],
    )
