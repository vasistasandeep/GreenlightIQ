"""Versions router: model-version catalog and title evaluation history (R26.3, R24.5).

Exposes the read-only catalog endpoints from the design's "Added endpoints":

* ``GET /models/versions`` and ``GET /models/versions/{id}`` — the immutable
  model-version catalog. Every calibration forks a new version rather than
  mutating weights in place, and all historical versions are retained so a prior
  valuation can be reproduced from its stamped version (R26.3). The catalog lets
  operators and the UI browse that history and inspect any single version.
* ``GET /titles/{id}/versions`` — a title's evaluation history across its
  versioned snapshots (R24.5). Each ingestion creates an immutable, incrementing
  title version; this returns them oldest-first with the active flag.

Both are authenticated reads (R19.3) returning the shared error envelope on an
unknown id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_service, get_current_user, get_rbac_service
from app.core.db import get_db_session
from app.core.errors import NotFoundError, TitleNotFoundError
from app.engines.audit import AuditLogService
from app.engines.rbac import Operation, RBACService
from app.core.security import UserContext
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.titles import TitleRepository, TitleVersionRepository

router = APIRouter(tags=["versions"])


class ModelVersionResponse(BaseModel):
    """A single immutable model version (R26.1, R26.3)."""

    model_version_id: uuid.UUID
    talent_pedigree_weight: Decimal
    narrative_trope_weight: Decimal
    guardrail_params: dict
    supersedes_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime | None = None


class TitleVersionResponse(BaseModel):
    """A single immutable title snapshot in a title's history (R24.5)."""

    title_version_id: uuid.UUID
    title_id: uuid.UUID
    version_number: int
    is_active: bool
    created_at: datetime | None = None


def _to_model_version(row) -> ModelVersionResponse:
    return ModelVersionResponse(
        model_version_id=row.model_version_id,
        talent_pedigree_weight=row.talent_pedigree_weight,
        narrative_trope_weight=row.narrative_trope_weight,
        guardrail_params=dict(row.guardrail_params or {}),
        supersedes_id=row.supersedes_id,
        is_active=row.is_active,
        created_at=row.created_at,
    )


@router.get("/models/versions", response_model=list[ModelVersionResponse])
async def list_model_versions(
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> list[ModelVersionResponse]:
    """Return the full model-version catalog, newest first (R26.3)."""
    repo = ModelVersionRepository(session)
    rows = await repo.list_all()
    return [_to_model_version(row) for row in rows]


@router.get("/models/versions/{model_version_id}", response_model=ModelVersionResponse)
async def get_model_version(
    model_version_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> ModelVersionResponse:
    """Return a single model version by id (R26.3).

    Retained-forever versions make a historical valuation reproducible from its
    stamped version; an unknown id maps to ``404 NOT_FOUND``.
    """
    repo = ModelVersionRepository(session)
    row = await repo.get(model_version_id)
    if row is None:
        raise NotFoundError(
            "The requested model version was not found.",
            details={"model_version_id": str(model_version_id)},
        )
    return _to_model_version(row)


@router.get("/titles/{title_id}/versions", response_model=list[TitleVersionResponse])
async def list_title_versions(
    title_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> list[TitleVersionResponse]:
    """Return a title's versioned evaluation history, oldest first (R24.5).

    An unknown title id maps to ``404 TITLE_NOT_FOUND`` so the client can
    distinguish "no such title" from "title with no versions yet" (empty list).
    """
    title = await TitleRepository(session).get(title_id)
    if title is None:
        raise TitleNotFoundError(details={"title_id": str(title_id)})
    rows = await TitleVersionRepository(session).list_for_title(title_id)
    return [
        TitleVersionResponse(
            title_version_id=row.title_version_id,
            title_id=row.title_id,
            version_number=row.version_number,
            is_active=row.is_active,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/models/versions/{model_version_id}/activate",
    response_model=ModelVersionResponse,
)
async def activate_model_version(
    model_version_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    actor: UserContext = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac_service),
    audit: AuditLogService = Depends(get_audit_service),
) -> ModelVersionResponse:
    """Roll back to a prior model version by making it the active one (R26.3).

    Deactivates the currently active version and activates the target, recording
    the change in the append-only audit log. Gated to the CALIBRATE operation
    (data-science / executive governance). Model-version rows are never mutated
    beyond the ``is_active`` flag, preserving the immutable weight history.
    """
    rbac.authorize(actor, Operation.CALIBRATE, resource=model_version_id)

    repo = ModelVersionRepository(session)
    target = await repo.get(model_version_id)
    if target is None:
        raise NotFoundError(
            "The requested model version was not found.",
            details={"model_version_id": str(model_version_id)},
        )

    current = await repo.get_active()
    previous_id = current.model_version_id if current is not None else None
    if current is not None and current.model_version_id != target.model_version_id:
        await repo.update(current, is_active=False)
    if not target.is_active:
        await repo.update(target, is_active=True)

    await audit.record(
        actor=actor.user_id,
        action="model_version_rollback",
        before={"active_model_version_id": str(previous_id) if previous_id else None},
        after={"active_model_version_id": str(target.model_version_id)},
        subject_id=target.model_version_id,
        model_version_id=target.model_version_id,
    )
    await session.commit()

    refreshed = await repo.get(model_version_id)
    return _to_model_version(refreshed if refreshed is not None else target)
