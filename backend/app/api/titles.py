"""Titles router: batch ingestion dispatch (task 16.1).

``POST /titles/ingest`` is the asynchronous entry point for batch manifests
(R1, R23.1, R23.2). The handler:

1. authenticates the request and authorizes the ``INGEST`` operation (R19, R20),
2. validates the request *envelope* synchronously — the content type must be
   CSV/JSON/PDF (R1.4) and a CSV must not exceed the 10,000-row ceiling (R1.5),
   both whole-request guards that fail fast through the error envelope,
3. honors the ``Idempotency-Key`` header (R27.1): a replayed key whose job
   already completed is echoed back inline rather than re-dispatched,
4. persists a ``PENDING`` ``jobs`` row and dispatches the heavy per-row work to
   the Task_Queue, returning ``202 Accepted`` with the ``job_id`` (R23.2).

The per-row validation, title versioning, and feature-extraction fan-out run in
the worker (:func:`app.tasks.jobs.ingest_batch`); the client polls
``GET /jobs/{job_id}`` for the terminal accepted/rejected summary.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.api.deps import (
    CurrentUser,
    SessionDep,
    TaskDispatcherDep,
    get_audit_service,
    get_rbac_service,
    require_operation,
)
from app.core.errors import (
    RowLimitExceededError,
    TitleNotFoundError,
    UnsupportedFormatError,
    ValidationFailedError,
)
from app.domain.deal_stage import (
    DealStage,
    IllegalStageTransition,
    allowed_next_stages,
    coerce_stage,
    validate_transition,
)
from app.engines.audit import AuditLogService
from app.engines.rbac import Operation, RBACService
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.repositories.titles import TitleRepository
from app.schemas.api import (
    DealStageResponse,
    DealStageTransitionRequest,
    IngestAcceptedResponse,
    RejectionItem,
)

router = APIRouter(prefix="/titles", tags=["titles"])

#: The ingestion content-type allow-list (R1.4). Mirrors the Ingestion_Service.
_SUPPORTED_CONTENT_TYPES = {"csv", "json", "pdf"}
#: The maximum number of CSV data rows accepted in one batch (R1.5).
_MAX_CSV_ROWS = 10_000


def _normalize_content_type(raw: str | None) -> str:
    """Resolve the declared ingestion format to a supported token (R1.4).

    Accepts both the short token (``csv``) and a MIME type (``text/csv``,
    ``application/json``, ``application/pdf``). An unsupported value raises
    ``415 UNSUPPORTED_FORMAT`` through the envelope.
    """
    if not raw:
        raise UnsupportedFormatError(
            "A Content-Type (csv, json, or pdf) is required for ingestion."
        )
    token = raw.split(";", 1)[0].strip().lower()
    # Map common MIME types onto the short token the service expects.
    mime_map = {
        "text/csv": "csv",
        "application/csv": "csv",
        "application/json": "json",
        "text/json": "json",
        "application/pdf": "pdf",
    }
    token = mime_map.get(token, token)
    if token not in _SUPPORTED_CONTENT_TYPES:
        raise UnsupportedFormatError(
            f"Unsupported ingestion format {raw!r}; expected one of csv, json, pdf.",
            details={"content_type": raw},
        )
    return token


def _guard_csv_row_limit(payload: bytes, content_type: str) -> None:
    """Reject a CSV manifest exceeding the row ceiling as a whole-batch error (R1.5).

    Counts non-empty data rows (excluding the header). A manifest with more than
    :data:`_MAX_CSV_ROWS` data rows is rejected with ``422 ROW_LIMIT_EXCEEDED``
    before anything is dispatched.
    """
    if content_type != "csv":
        return
    text = payload.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    data_rows = max(len(lines) - 1, 0)  # first non-empty line is the header
    if data_rows > _MAX_CSV_ROWS:
        raise RowLimitExceededError(
            f"CSV manifest has {data_rows} rows; the maximum is {_MAX_CSV_ROWS}.",
            details={"rows": data_rows, "max_rows": _MAX_CSV_ROWS},
        )


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestAcceptedResponse,
    dependencies=[Depends(require_operation(Operation.INGEST))],
    summary="Dispatch a batch manifest for asynchronous ingestion (R1, R23.2).",
)
async def ingest_titles(
    request: Request,
    response: Response,
    actor: CurrentUser,
    session: SessionDep,
    dispatcher: TaskDispatcherDep,
    content_type: str | None = Header(default=None, alias="Content-Type"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestAcceptedResponse:
    """Validate, persist a job for, and dispatch a batch ingestion (R1, R23.2).

    Returns ``202 Accepted`` with the dispatched ``job_id``. On an idempotent
    replay of a batch that already completed, the stored summary is echoed inline
    with the original job id and its terminal status (R27.1).
    """
    normalized_type = _normalize_content_type(content_type)
    payload = await request.body()
    _guard_csv_row_limit(payload, normalized_type)

    jobs = JobRepository(session)

    # Idempotent replay (R27.1): a prior job for this key is returned unchanged.
    if idempotency_key:
        existing = await jobs.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _response_from_job(existing)

    # Persist a PENDING job the worker transitions through its lifecycle (R23.3).
    job = Job(
        job_type="ingest_batch",
        status="PENDING",
        idempotency_key=idempotency_key,
        requested_by=actor.user_id,
    )
    await jobs.create(job)
    # Durably commit the PENDING job BEFORE dispatching, so the worker (a
    # separate process/session) and the client's GET /jobs/{id} poll can both
    # see it. Engines/repositories flush but do not commit; this handler owns
    # the transaction boundary (R23.2, R23.3).
    await session.commit()

    # Dispatch the heavy per-row work to the Task_Queue (R23.1) and ack (R23.2).
    dispatcher.dispatch_ingest(
        job.job_id, payload, normalized_type, idempotency_key or ""
    )

    response.headers["Location"] = f"{request.url.path.rsplit('/titles', 1)[0]}/jobs/{job.job_id}"
    return IngestAcceptedResponse(job_id=job.job_id, status=job.status)


def _response_from_job(job: Job) -> IngestAcceptedResponse:
    """Render a stored job as an ingest response, echoing any terminal summary."""
    result = job.result or {}
    rejections_raw = result.get("rejections") or []
    rejections = [
        RejectionItem(
            row_index=int(item.get("row_index", 0)),
            field=str(item.get("field", "")),
            reason=str(item.get("reason", "")),
        )
        for item in rejections_raw
    ]
    return IngestAcceptedResponse(
        job_id=job.job_id,
        status=job.status,
        accepted_count=result.get("accepted_count"),
        rejected_count=result.get("rejected_count"),
        rejections=rejections or None,
    )


@router.get(
    "/{title_id}/deal-stage",
    response_model=DealStageResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Return a title's deal stage and its allowed next stages.",
)
async def get_deal_stage(
    title_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
) -> DealStageResponse:
    """Return the title's current acquisition deal stage and legal next moves.

    A missing title maps to ``404 TITLE_NOT_FOUND``. A title persisted before the
    stage column existed reads as the initial ``SCREENING`` stage.
    """
    titles = TitleRepository(session)
    title = await titles.get(title_id)
    if title is None:
        raise TitleNotFoundError(
            f"No title exists for id {title_id!r}.",
            details={"title_id": str(title_id)},
        )
    current = coerce_stage(getattr(title, "deal_stage", None))
    return DealStageResponse(
        title_id=title_id,
        deal_stage=current.value,
        allowed_next_stages=[s.value for s in allowed_next_stages(current)],
    )


@router.patch(
    "/{title_id}/deal-stage",
    response_model=DealStageResponse,
    summary="Advance a title to a new deal stage (guarded transition).",
)
async def transition_deal_stage(
    title_id: uuid.UUID,
    body: DealStageTransitionRequest,
    actor: CurrentUser,
    session: SessionDep,
    rbac: RBACService = Depends(get_rbac_service),
    audit: AuditLogService = Depends(get_audit_service),
) -> DealStageResponse:
    """Move a title to ``body.deal_stage`` if the transition is allowed (R20.2, R25.1).

    Managing where a title sits in the acquisition pipeline is a decision-making
    action, so it is gated to the same roles as a recommendation override
    (CONTENT_BUYER / CHIEF_CONTENT_OFFICER / CFO) via ``Operation.OVERRIDE``; any
    other role is rejected ``403``. The target must be a legal next stage from the
    current one (the pure state machine decides) - an illegal move or an unknown
    stage is a ``422``. The change is persisted under the title's optimistic lock
    and recorded as an append-only audit entry with its before/after stage (R25.1).
    """
    # Authorize before touching the record (mirrors the override path, R20.2).
    rbac.authorize(actor, Operation.OVERRIDE, resource=title_id)

    try:
        target = DealStage(body.deal_stage)
    except ValueError:
        raise ValidationFailedError(
            "Unknown deal stage.",
            details={
                "deal_stage": body.deal_stage,
                "allowed": [s.value for s in DealStage],
            },
        )

    titles = TitleRepository(session)
    title = await titles.get(title_id)
    if title is None:
        raise TitleNotFoundError(
            f"No title exists for id {title_id!r}.",
            details={"title_id": str(title_id)},
        )

    current = coerce_stage(getattr(title, "deal_stage", None))
    try:
        validate_transition(current, target)
    except IllegalStageTransition as exc:
        raise ValidationFailedError(
            str(exc),
            details={
                "from": current.value,
                "to": target.value,
                "allowed_next_stages": [s.value for s in allowed_next_stages(current)],
            },
        )

    await titles.update(title, deal_stage=target.value)
    await audit.record(
        actor=actor.user_id,
        action="deal_stage_transition",
        before={"deal_stage": current.value},
        after={"deal_stage": target.value},
        subject_id=title_id,
    )
    await session.commit()

    return DealStageResponse(
        title_id=title_id,
        deal_stage=target.value,
        allowed_next_stages=[s.value for s in allowed_next_stages(target)],
    )


__all__ = ["router"]
