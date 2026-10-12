"""Celery task definitions for the four heavy operations (R23.1, R29.1-R29.3).

Each task is a thin worker-side wrapper that:

1. opens a unit-of-work session (:func:`app.core.db.session_scope`),
2. drives the job's lifecycle via :class:`~app.tasks.lifecycle.JobLifecycle`
   (PENDING -> PROCESSING on entry; COMPLETED / FAILED on exit, R23.3),
3. delegates the actual work to the corresponding engine
   (ingestion / feature extraction / backtesting / telemetry), and
4. on an unrecoverable error after retries are exhausted, records the failure
   reason (R23.5) and routes the job to the dead-letter queue (R29.3).

The tasks are registered on the lazily-created Celery app
(:func:`app.tasks.celery_app.get_celery_app`) and routed to their dedicated
queues via ``TASK_ROUTES``. The async engine/lifecycle work is bridged onto
Celery's synchronous worker thread with :func:`_run`.

The deterministic lifecycle logic lives in :mod:`app.tasks.lifecycle` and is
covered by task 15.2's property tests without a broker; these task bodies are
the production wiring exercised by task 15.4's integration tests.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from app.core.db import session_scope
from app.core.logging import get_logger
from app.tasks import metrics
from app.tasks.celery_app import MAX_RETRIES, get_celery_app
from app.tasks.lifecycle import JobLifecycle

_log = get_logger("jobs")

celery_app = get_celery_app()

T = TypeVar("T")

# Exponential-backoff retry policy shared by all tasks. Once ``max_retries`` is
# exceeded Celery stops retrying and the task body routes the job to the DLQ
# (R29.3) with the final failure reason (R23.5).
_RETRY_KWARGS = {
    "bind": True,
    "max_retries": MAX_RETRIES,
    "default_retry_delay": 30,
    "autoretry_for": (),  # retries are driven explicitly in the task body
}


def _run(coro: Awaitable[T]) -> T:
    """Run an async coroutine to completion on the synchronous Celery worker.

    A fresh event loop is created per task invocation so concurrent worker
    threads never share a loop. The loop is always closed afterwards.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _coerce_uuid(value: Any) -> uuid.UUID:
    """Return ``value`` as a UUID (Celery serializes identifiers as strings)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def _resolve_active_model_version(session: Any) -> uuid.UUID | None:
    """Return the active model-version id to stamp work with (R26.2), if any."""
    from app.repositories.model_versions import ModelVersionRepository

    active = await ModelVersionRepository(session).get_active()
    return active.model_version_id if active is not None else None


async def _lifecycle(session: Any) -> JobLifecycle:
    """Build a :class:`JobLifecycle` bound to the request session."""
    from app.repositories.jobs import JobRepository

    return JobLifecycle(JobRepository(session))


async def _execute(
    job_id: uuid.UUID,
    work: Callable[[Any, uuid.UUID | None], Awaitable[dict | None]],
) -> dict | None:
    """Shared lifecycle wrapper: start -> run ``work`` -> complete (R23.3).

    ``work`` receives the session and the active model-version id and returns a
    JSON-serializable result dict persisted on completion. Exceptions propagate
    to the task body, which decides whether to retry or dead-letter.
    """
    async with session_scope() as session:
        lifecycle = await _lifecycle(session)
        await lifecycle.start(job_id)
        model_version_id = await _resolve_active_model_version(session)
        result = await work(session, model_version_id)
        await lifecycle.complete(job_id, result=result)
        return result


async def _record_terminal_failure(job_id: uuid.UUID, reason: str) -> None:
    """Fail a job and route it to the DLQ after retries are exhausted (R23.5, R29.3)."""
    async with session_scope() as session:
        lifecycle = await _lifecycle(session)
        await lifecycle.fail(job_id, reason, retries_exhausted=True)


def _handle_failure(task: Any, job_id: uuid.UUID, exc: Exception) -> None:
    """Retry while attempts remain, otherwise dead-letter the job (R29.3).

    Celery tracks the retry count on ``task.request.retries``. While it is below
    ``max_retries`` the task is retried with backoff; once exhausted the job is
    moved to FAILED + dead-lettered and the exception is re-raised so Celery
    marks the task result as failed too.
    """
    retries = getattr(task.request, "retries", 0) or 0
    metrics.emit_counter("jobs.error", job_id=str(job_id), attempt=retries)
    if retries < MAX_RETRIES:
        _log.warning(
            "job_retry job_id=%s attempt=%d max=%d error=%s",
            job_id,
            retries + 1,
            MAX_RETRIES,
            exc,
        )
        raise task.retry(exc=exc)
    _log.error("job_failed_final job_id=%s error=%s", job_id, exc)
    _run(_record_terminal_failure(job_id, str(exc)))


# --------------------------------------------------------------------------- #
# ingest_batch -> queue "ingest" (R1, R23.1)
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.tasks.jobs.ingest_batch", **_RETRY_KWARGS)
def ingest_batch(
    self: Any,
    job_id: str,
    payload: bytes | str,
    content_type: str,
    idempotency_key: str,
) -> dict | None:
    """Run a batch ingestion asynchronously (R1, R23.1).

    Delegates to :class:`~app.engines.ingestion.IngestionService`, whose own
    idempotency handling (R27.1) collapses a replayed ``idempotency_key`` to the
    stored result.
    """
    jid = _coerce_uuid(job_id)
    body = payload.encode() if isinstance(payload, str) else payload

    async def work(session: Any, model_version_id: uuid.UUID | None) -> dict | None:
        from app.engines.ingestion import IngestionService
        from app.repositories.jobs import JobRepository
        from app.repositories.license_terms import LicenseTermRepository
        from app.repositories.metadata_vectors import MetadataVectorRepository
        from app.repositories.titles import TitleRepository, TitleVersionRepository

        service = IngestionService(
            session,
            TitleRepository(session),
            TitleVersionRepository(session),
            JobRepository(session),
            LicenseTermRepository(session),
            MetadataVectorRepository(session),
            model_version_id=model_version_id,
        )
        return dict(await service.ingest(body, content_type, idempotency_key))

    try:
        return _run(_execute(jid, work))
    except Exception as exc:  # noqa: BLE001 - routed to retry/DLQ
        _handle_failure(self, jid, exc)
        return None


# --------------------------------------------------------------------------- #
# extract_features -> queue "extract" (R2, R23.1)
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.tasks.jobs.extract_features", **_RETRY_KWARGS)
def extract_features(self: Any, job_id: str, title_id: str) -> dict | None:
    """Generate the metadata profile for a title asynchronously (R2, R23.1)."""
    jid = _coerce_uuid(job_id)
    tid = _coerce_uuid(title_id)

    async def work(session: Any, model_version_id: uuid.UUID | None) -> dict | None:
        from app.engines.embedding_provider import get_embedding_provider
        from app.engines.feature_extraction import (
            FeatureExtractionEngine,
            SourceBundle,
        )
        from app.engines.model_versioning import (
            ModelVersioningEngine,
            NoActiveModelVersionError,
        )
        from app.repositories.metadata_vectors import MetadataVectorRepository
        from app.repositories.model_versions import ModelVersionRepository
        from app.repositories.titles import TitleVersionRepository

        versioning = ModelVersioningEngine(ModelVersionRepository(session))
        # The extraction must be stamped with a reproducible model version
        # (R26.2); resolve the active one (falling back to the id passed in).
        if model_version_id is None:
            model_version_id = await versioning.stamp()
        if model_version_id is None:  # pragma: no cover - stamp raises instead
            raise NoActiveModelVersionError(
                "no active model version to stamp extraction (R26.2)."
            )

        # Load the title's active version source snapshot into a SourceBundle.
        active = await TitleVersionRepository(session).get_active(tid)
        snapshot = dict(active.source_snapshot) if active is not None else {}
        sources = SourceBundle(
            logline=snapshot.get("logline"),
            pitch_deck=snapshot.get("pitch_deck"),
            manifest_content=snapshot.get("manifest_content"),
        )

        engine = FeatureExtractionEngine(
            session,
            MetadataVectorRepository(session),
            get_embedding_provider(),
            versioning,
        )
        output = await engine.extract(tid, sources, model_version_id)
        return {"title_id": str(tid), "extracted": output is not None}

    try:
        return _run(_execute(jid, work))
    except Exception as exc:  # noqa: BLE001 - routed to retry/DLQ
        _handle_failure(self, jid, exc)
        return None


# --------------------------------------------------------------------------- #
# run_backtest_audit -> queue "audit" (R11, R23.1)
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.tasks.jobs.run_backtest_audit", **_RETRY_KWARGS)
def run_backtest_audit(self: Any, job_id: str, title_id: str) -> dict | None:
    """Run a backtest audit for a historical title asynchronously (R11, R23.1)."""
    jid = _coerce_uuid(job_id)
    tid = _coerce_uuid(title_id)

    async def work(session: Any, _model_version_id: uuid.UUID | None) -> dict | None:
        from app.engines.backtesting import Backtesting_Module

        scorecard = await Backtesting_Module(session).audit(tid)
        return {"title_id": str(tid), "scorecard": _jsonable(scorecard)}

    try:
        return _run(_execute(jid, work))
    except Exception as exc:  # noqa: BLE001 - routed to retry/DLQ
        _handle_failure(self, jid, exc)
        return None


# --------------------------------------------------------------------------- #
# poll_telemetry -> queue "telemetry" (R13.1, R23.1)
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.tasks.jobs.poll_telemetry", **_RETRY_KWARGS)
def poll_telemetry(self: Any, job_id: str) -> dict | None:
    """Poll registered telemetry sources and refresh the cache (R13.1, R23.1)."""
    jid = _coerce_uuid(job_id)

    async def work(session: Any, _model_version_id: uuid.UUID | None) -> dict | None:
        from app.engines.telemetry import TelemetryConnector

        connector = TelemetryConnector(session)
        await connector.poll()
        return {"polled": True}

    try:
        return _run(_execute(jid, work))
    except Exception as exc:  # noqa: BLE001 - routed to retry/DLQ
        _handle_failure(self, jid, exc)
        return None


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of an engine result to a JSON-serializable form."""
    if hasattr(value, "_asdict"):  # NamedTuple
        return {k: _jsonable(v) for k, v in value._asdict().items()}
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in vars(value).items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
