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
    require_operation,
)
from app.core.errors import RowLimitExceededError, UnsupportedFormatError
from app.engines.rbac import Operation
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.schemas.api import IngestAcceptedResponse, RejectionItem

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


__all__ = ["router"]
