"""Celery application and queue topology for async job processing (R23, R29).

Defines the process-wide Celery app bound to the configured broker / result
backend (``CINEROI_BROKER_URL`` / ``CINEROI_RESULT_BACKEND_URL``) and the
dedicated per-operation queues the design calls for:

======================  ========  ============================================
Task                    Queue     Operation
======================  ========  ============================================
``ingest_batch``        ingest    Batch ingestion (R1, R23.1)
``extract_features``    extract   Feature extraction / vector generation (R2)
``run_backtest_audit``  audit     Backtest audit (R11)
``poll_telemetry``      telemetry Scheduled telemetry polling (R13.1)
======================  ========  ============================================

Routing each task to its own queue lets the worker fleet tune concurrency per
operation (NLP-heavy extraction vs. light telemetry polling) as described in the
design's "Async Job Processing Design" section.

Reliability knobs (R29.3):

* ``task_acks_late`` + ``task_reject_on_worker_lost`` so a crashed worker's job
  is redelivered rather than silently lost.
* A bounded ``max_retries`` with exponential backoff; once retries are exhausted
  the job is routed to the dead-letter queue (see :func:`dead_letter_queue_name`
  and the lifecycle service).

The Celery app is created lazily via :func:`get_celery_app` so importing this
module (and ``app.tasks``) never requires a reachable broker — unit/property
tests exercise the lifecycle core (:mod:`app.tasks.lifecycle`) without Celery.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from celery import Celery

#: Logical queue names, one per heavy operation (R23.1). Imported by the task
#: module so the queue a task runs on is declared in exactly one place.
QUEUE_INGEST = "ingest"
QUEUE_EXTRACT = "extract"
QUEUE_AUDIT = "audit"
QUEUE_TELEMETRY = "telemetry"

#: Suffix appended to a queue name to form its dead-letter companion (R29.3).
DEAD_LETTER_SUFFIX = ".dlq"

#: Maximum automatic retries before a failed job is dead-lettered (R29.3).
MAX_RETRIES = 3

#: Task-name -> queue routing table consumed by ``task_routes`` and by the
#: dispatch helpers so a caller never has to name a queue by hand.
TASK_ROUTES = {
    "app.tasks.jobs.ingest_batch": {"queue": QUEUE_INGEST},
    "app.tasks.jobs.extract_features": {"queue": QUEUE_EXTRACT},
    "app.tasks.jobs.run_backtest_audit": {"queue": QUEUE_AUDIT},
    "app.tasks.jobs.poll_telemetry": {"queue": QUEUE_TELEMETRY},
}


def dead_letter_queue_name(queue: str) -> str:
    """Return the dead-letter queue paired with ``queue`` (R29.3).

    A job that exhausts its retries on ``queue`` is routed here for operator
    inspection and later re-dispatch (R29.5).
    """
    return f"{queue}{DEAD_LETTER_SUFFIX}"


@lru_cache
def get_celery_app() -> "Celery":
    """Return the process-wide Celery app, configuring it on first use.

    Lazily constructed so the broker URL is only resolved when a worker (or a
    dispatcher) actually needs it. Repeated calls return the same cached app.
    """
    from celery import Celery  # imported lazily so tests need no broker

    settings = get_settings()
    app = Celery("cineroi", broker=settings.broker_url, backend=settings.result_backend_url)

    app.conf.update(
        task_default_queue=QUEUE_INGEST,
        task_routes=TASK_ROUTES,
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_prefetch_multiplier=1,
        result_extended=True,
        timezone="UTC",
        enable_utc=True,
    )
    # Ensure task modules are imported so the tasks register on the app.
    app.autodiscover_tasks(["app.tasks"])
    return app

# Module-level Celery application instance for the `celery -A` worker/beat
# entrypoint. Tests and dispatch helpers continue to use get_celery_app();
# this simply gives the CLI a concrete app object to attach to.
celery_app = get_celery_app()
