"""Jobs router: status polling and dead-letter re-dispatch (R23.4, R29.5).

Exposes the two job-management endpoints from the design's "Added endpoints":

* ``GET /jobs/{job_id}`` → ``{status, result?, failure_reason?}`` so a client
  that received a ``202`` job id from a heavy operation can poll for terminal
  status (R23.4).
* ``POST /jobs/{job_id}/retry`` → re-dispatch a dead-lettered job. An operator
  calls this after remediating a failure; the job lifecycle resets the row to
  PENDING and clears the dead-letter flag (R29.5), and the task is re-queued on
  its dedicated Celery queue.

Both endpoints require an authenticated principal (R19.3) and surface the shared
error envelope — an unknown job id maps to ``404 NOT_FOUND``, re-dispatching a
job that is not dead-lettered maps to ``409 CONFLICT``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db_session
from app.core.errors import ConflictError, NotFoundError
from app.core.security import UserContext
from app.repositories.jobs import JobRepository
from app.tasks.lifecycle import IllegalJobTransition, JobLifecycle

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobStatusResponse(BaseModel):
    """The pollable status of an asynchronous job (R23.4)."""

    job_id: uuid.UUID
    job_type: str
    status: str = Field(description="PENDING | PROCESSING | COMPLETED | FAILED")
    result: dict | None = None
    failure_reason: str | None = None
    dead_lettered: bool = False


async def _require_job(jobs: JobRepository, job_id: uuid.UUID):
    """Load a job or raise ``404 NOT_FOUND`` with the id in details."""
    job = await jobs.get(job_id)
    if job is None:
        raise NotFoundError(
            "The requested job was not found.",
            details={"job_id": str(job_id)},
        )
    return job


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> JobStatusResponse:
    """Return a job's current lifecycle status and terminal payload (R23.4).

    A client that submitted a heavy operation (ingest / backtest) received a
    ``202`` with this job id and polls here until ``status`` is COMPLETED
    (``result`` populated) or FAILED (``failure_reason`` populated).
    """
    jobs = JobRepository(session)
    job = await _require_job(jobs, job_id)
    return JobStatusResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        result=job.result,
        failure_reason=job.failure_reason,
        dead_lettered=job.dead_lettered,
    )


@router.post("/{job_id}/retry", response_model=JobStatusResponse)
async def retry_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> JobStatusResponse:
    """Re-dispatch a dead-lettered job for reprocessing (R29.5).

    Resets the job to PENDING and clears its dead-letter flag via the lifecycle
    state machine, then re-queues the corresponding Celery task on its dedicated
    queue. A job that is not dead-lettered cannot be retried and maps to
    ``409 CONFLICT`` so operators do not accidentally re-run a healthy job.
    """
    jobs = JobRepository(session)
    job = await _require_job(jobs, job_id)

    if not job.dead_lettered:
        raise ConflictError(
            "Only a dead-lettered job can be retried.",
            details={"job_id": str(job_id), "status": job.status},
        )

    lifecycle = JobLifecycle(jobs)
    try:
        await lifecycle.redispatch(job_id)
    except IllegalJobTransition as exc:
        raise ConflictError(
            "The job cannot be re-dispatched from its current state.",
            details={"job_id": str(job_id), "status": job.status},
        ) from exc

    await session.commit()
    _redispatch_to_queue(job.job_type, job.job_id)

    refreshed = await _require_job(jobs, job_id)
    return JobStatusResponse(
        job_id=refreshed.job_id,
        job_type=refreshed.job_type,
        status=refreshed.status,
        result=refreshed.result,
        failure_reason=refreshed.failure_reason,
        dead_lettered=refreshed.dead_lettered,
    )


def _redispatch_to_queue(job_type: str, job_id: uuid.UUID) -> None:
    """Re-enqueue the Celery task matching a re-dispatched job's type (R29.5).

    Best-effort: the DB row has already been reset to PENDING and committed, so a
    broker that is momentarily unavailable does not fail the request — the job is
    picked up by the worker when the task is re-sent (or by a reconciliation of
    PENDING jobs). The task name is resolved from the job's ``job_type`` so the
    task lands on its dedicated queue via the configured routing table.
    """
    task_name = _TASK_FOR_JOB_TYPE.get(job_type)
    if task_name is None:
        return
    try:  # pragma: no cover - requires a reachable broker
        from app.tasks.celery_app import get_celery_app

        get_celery_app().send_task(task_name, args=[str(job_id)])
    except Exception:  # noqa: BLE001 - broker optional at request time
        # The row is already PENDING; swallow transport errors so the operator's
        # retry request succeeds and the job is reconciled onto the queue later.
        pass


#: Map a job's ``job_type`` to the Celery task that processes it. Used to
#: re-enqueue a re-dispatched job onto its dedicated queue (R29.5).
_TASK_FOR_JOB_TYPE: dict[str, str] = {
    "ingest_batch": "app.tasks.jobs.ingest_batch",
    "extract_features": "app.tasks.jobs.extract_features",
    "run_backtest_audit": "app.tasks.jobs.run_backtest_audit",
    "poll_telemetry": "app.tasks.jobs.poll_telemetry",
}
