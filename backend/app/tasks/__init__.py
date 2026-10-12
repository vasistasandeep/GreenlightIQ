"""Async job processing: Celery app, tasks, and the job lifecycle (task 15.1).

This package implements the backend's asynchronous operations (R23, R27.4, R29):

* :mod:`app.tasks.celery_app` — the lazily-constructed Celery app and the
  dedicated per-operation queue topology (ingest / extract / audit / telemetry),
  retry policy, and dead-letter queue naming (R23.1, R29.3).
* :mod:`app.tasks.jobs` — the four Celery tasks ``ingest_batch``,
  ``extract_features``, ``run_backtest_audit``, ``poll_telemetry`` that wire the
  engines to the job lifecycle (R23.1).
* :mod:`app.tasks.lifecycle` — the Celery-independent, unit-testable job state
  machine (PENDING -> PROCESSING -> COMPLETED|FAILED, R23.3), failure-reason
  recording (R23.5), SLA alerting (R29.2), and DLQ routing/re-dispatch
  (R29.3, R29.5).
* :mod:`app.tasks.webhooks` — idempotent terminal-status webhook delivery with a
  per-event dedupe key (R23.6, R27.4).
* :mod:`app.tasks.metrics` — structured-log-backed metrics emission (R29.1).

Only the lifecycle/webhook/metrics modules are imported here; the Celery app and
task modules are imported lazily by workers so that importing ``app.tasks`` (and
the test suite) never requires a reachable broker.
"""

from __future__ import annotations

from app.tasks.lifecycle import (
    ALLOWED_TRANSITIONS,
    COMPLETED,
    FAILED,
    PENDING,
    PROCESSING,
    SLA_LIMIT,
    IllegalJobTransition,
    JobLifecycle,
    is_allowed_transition,
)
from app.tasks.webhooks import (
    TERMINAL_STATUSES,
    InMemoryDedupeStore,
    WebhookDispatcher,
    WebhookEvent,
    build_dedupe_key,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "COMPLETED",
    "FAILED",
    "PENDING",
    "PROCESSING",
    "SLA_LIMIT",
    "IllegalJobTransition",
    "JobLifecycle",
    "is_allowed_transition",
    "TERMINAL_STATUSES",
    "InMemoryDedupeStore",
    "WebhookDispatcher",
    "WebhookEvent",
    "build_dedupe_key",
]
