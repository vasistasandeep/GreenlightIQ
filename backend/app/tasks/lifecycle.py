"""Job lifecycle state machine and SLA/DLQ handling (R23.3, R23.5, R29.2, R29.3).

This module holds the *testable core* of async job processing, independent of
Celery: given a :class:`~app.repositories.jobs.JobRepository`, it drives a job
through the lifecycle

    PENDING -> PROCESSING -> COMPLETED | FAILED        (R23.3)

recording a ``failure_reason`` on failure (R23.5), firing a terminal-status
webhook exactly once per event (R23.6, R27.4) via an injected
:class:`~app.tasks.webhooks.WebhookDispatcher`, routing a job that has exhausted
its retries to the dead-letter queue (R29.3), and emitting structured logs +
metrics for every transition (R29.1). An SLA monitor raises an alert when a
job's processing time exceeds 15 minutes (R29.2).

Only forward transitions along the state machine are permitted; attempting an
illegal transition (e.g. completing a job that already FAILED, or re-starting a
terminal job) raises :class:`IllegalJobTransition`. The Celery tasks in
:mod:`app.tasks.jobs` call ``start`` before doing work and ``complete`` /
``fail`` after, so the DB row always reflects the true lifecycle state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger
from app.repositories.jobs import JobRepository
from app.tasks import metrics
from app.tasks.webhooks import TERMINAL_STATUSES, WebhookDispatcher

_log = get_logger("jobs")

# --- Lifecycle states (mirror the jobs.status CHECK constraint, R23.3). ----- #
PENDING = "PENDING"
PROCESSING = "PROCESSING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

TERMINAL = frozenset({COMPLETED, FAILED})

#: Allowed forward transitions. A status may only move to a status listed here;
#: terminal states have no outgoing transitions (R23.3).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({PROCESSING, FAILED}),
    PROCESSING: frozenset({COMPLETED, FAILED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
}

#: Processing-time SLA: a job PROCESSING longer than this raises an alert (R29.2).
SLA_LIMIT = timedelta(minutes=15)


class IllegalJobTransition(Exception):
    """Raised when a lifecycle transition violates the state machine (R23.3)."""

    def __init__(self, job_id: Any, from_status: str, to_status: str) -> None:
        self.job_id = job_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Illegal job transition for {job_id!r}: {from_status} -> {to_status}"
        )


def is_allowed_transition(from_status: str, to_status: str) -> bool:
    """Return whether ``from_status`` may transition to ``to_status`` (R23.3)."""
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def _now() -> datetime:
    """Return the current UTC time (indirected so tests can monkeypatch)."""
    return datetime.now(timezone.utc)


def _as_aware(moment: datetime) -> datetime:
    """Return ``moment`` as a UTC-aware datetime (DB values may be naive)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class JobLifecycle:
    """Drives one job's PENDING -> PROCESSING -> COMPLETED|FAILED lifecycle (R23).

    Wraps a :class:`JobRepository` and an injected webhook dispatcher. Every
    transition validates against :data:`ALLOWED_TRANSITIONS`, persists the new
    status (plus ``result`` / ``failure_reason`` / ``dead_lettered`` as
    appropriate), emits a structured log and a metric, and — on a terminal
    status — fires the idempotent webhook (R23.6, R27.4).
    """

    def __init__(
        self,
        job_repository: JobRepository,
        *,
        webhooks: WebhookDispatcher | None = None,
        max_retries: int = 3,
    ) -> None:
        self.jobs = job_repository
        self.webhooks = webhooks or WebhookDispatcher()
        self.max_retries = max_retries

    # ------------------------------------------------------------------ #
    # Transitions.
    # ------------------------------------------------------------------ #
    async def start(self, job_id: Any) -> Any:
        """Transition a job PENDING -> PROCESSING when a worker picks it up (R23.3).

        Stamps ``updated_at`` so the SLA monitor can measure processing time from
        this point (R29.2).
        """
        job = await self._require_job(job_id)
        self._guard(job, PROCESSING)
        await self.jobs.update(job, status=PROCESSING, updated_at=_now())
        self._observe(job, PROCESSING)
        return job

    async def complete(self, job_id: Any, result: dict | None = None) -> Any:
        """Transition a job PROCESSING -> COMPLETED and record its result (R23.3).

        Fires the terminal-status webhook exactly once (R23.6, R27.4).
        """
        job = await self._require_job(job_id)
        self._guard(job, COMPLETED)
        await self.jobs.update(
            job, status=COMPLETED, result=result, updated_at=_now()
        )
        self._observe(job, COMPLETED)
        self._fire_terminal_webhook(job)
        return job

    async def fail(
        self,
        job_id: Any,
        reason: str,
        *,
        retries_exhausted: bool = True,
    ) -> Any:
        """Transition a job to FAILED, recording the failure reason (R23.5).

        When ``retries_exhausted`` is true the job is also routed to the
        dead-letter queue (``dead_lettered = True``, R29.3) so an operator can
        inspect and later re-dispatch it (R29.5). The terminal-status webhook
        fires exactly once (R23.6, R27.4).

        Args:
            job_id: The job to fail.
            reason: The human-readable failure reason persisted on the row (R23.5).
            retries_exhausted: Whether the configured retries are spent; when
                ``True`` the job is dead-lettered.
        """
        job = await self._require_job(job_id)
        self._guard(job, FAILED)
        await self.jobs.update(
            job,
            status=FAILED,
            failure_reason=reason,
            dead_lettered=bool(retries_exhausted),
            updated_at=_now(),
        )
        self._observe(job, FAILED, failure_reason=reason)
        if retries_exhausted:
            _log.warning(
                "job_dead_lettered job_id=%s job_type=%s reason=%s",
                job.job_id,
                job.job_type,
                reason,
            )
            metrics.emit_counter("jobs.dead_lettered", job_type=job.job_type)
        self._fire_terminal_webhook(job)
        return job

    async def redispatch(self, job_id: Any) -> Any:
        """Reset a dead-lettered job to PENDING for re-processing (R29.5).

        An operator calls this after remediating the cause of failure; it clears
        the dead-letter flag and failure reason and returns the job to the queue
        head state so a worker can pick it up again.
        """
        job = await self._require_job(job_id)
        if not job.dead_lettered:
            raise IllegalJobTransition(job_id, job.status, PENDING)
        await self.jobs.update(
            job,
            status=PENDING,
            dead_lettered=False,
            failure_reason=None,
            updated_at=_now(),
        )
        _log.info("job_redispatched job_id=%s job_type=%s", job.job_id, job.job_type)
        metrics.emit_counter("jobs.redispatched", job_type=job.job_type)
        return job

    # ------------------------------------------------------------------ #
    # SLA monitoring (R29.2).
    # ------------------------------------------------------------------ #
    async def check_sla(self, *, limit: timedelta = SLA_LIMIT) -> list[Any]:
        """Raise an alert for every job PROCESSING longer than the SLA (R29.2).

        Returns the list of breaching jobs so a caller/monitor can act on them.
        A job breaches when ``now - updated_at`` (the moment it entered
        PROCESSING) exceeds ``limit`` (default 15 minutes).
        """
        now = _now()
        breaching: list[Any] = []
        for job in await self.jobs.list_by_status(PROCESSING):
            started = _as_aware(job.updated_at)
            elapsed = now - started
            if elapsed > limit:
                breaching.append(job)
                self._raise_sla_alert(job, elapsed, limit)
        return breaching

    def _raise_sla_alert(self, job: Any, elapsed: timedelta, limit: timedelta) -> None:
        """Emit the SLA-breach alert identifying the job (R29.2)."""
        _log.error(
            "job_sla_breach job_id=%s job_type=%s elapsed_seconds=%.1f limit_seconds=%.1f",
            job.job_id,
            job.job_type,
            elapsed.total_seconds(),
            limit.total_seconds(),
        )
        metrics.emit_counter("jobs.sla_breach", job_type=job.job_type)

    # ------------------------------------------------------------------ #
    # Internals.
    # ------------------------------------------------------------------ #
    async def _require_job(self, job_id: Any) -> Any:
        job = await self.jobs.get(job_id)
        if job is None:
            raise IllegalJobTransition(job_id, "<missing>", "<any>")
        return job

    def _guard(self, job: Any, to_status: str) -> None:
        if not is_allowed_transition(job.status, to_status):
            raise IllegalJobTransition(job.job_id, job.status, to_status)

    def _observe(self, job: Any, to_status: str, **extra: Any) -> None:
        """Emit the structured log + metric for a transition (R29.1)."""
        fields = " ".join(f"{k}={v}" for k, v in extra.items())
        _log.info(
            "job_transition job_id=%s job_type=%s status=%s %s",
            job.job_id,
            job.job_type,
            to_status,
            fields,
        )
        metrics.emit_counter(
            "jobs.transition", job_type=job.job_type, status=to_status
        )

    def _fire_terminal_webhook(self, job: Any) -> None:
        """Fire the idempotent terminal-status webhook (R23.6, R27.4)."""
        if job.status in TERMINAL_STATUSES:
            self.webhooks.deliver(job.job_id, job.status)
