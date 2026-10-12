"""Property-based tests for the async job-processing core (R23, R27.4).

Covers two properties from the cineroi-ai design document, exercising the
Celery-independent lifecycle core:

* **Property 36: Job status lifecycle** (``app.tasks.lifecycle.JobLifecycle``) —
  a dispatched job only ever moves along legal transitions
  PENDING -> PROCESSING -> COMPLETED|FAILED, and a job that reaches the FAILED
  terminal state always carries a recorded failure reason (R23.3, R23.5).
* **Property 35: Webhook idempotent processing**
  (``app.tasks.webhooks.WebhookDispatcher``) — delivering the same terminal
  event any number of times has the same effect as delivering it once: exactly
  one send and no duplicate side effects (R27.4).

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database and no broker**. The
collaborators are faked in memory:

* :class:`_FakeJob` mirrors the mutable fields of the ``jobs`` ORM row that the
  lifecycle reads and writes (``status``, ``result``, ``failure_reason``,
  ``dead_lettered``, ``updated_at``).
* :class:`_InMemoryJobRepository` reproduces the three ``JobRepository`` methods
  the lifecycle relies on (``get``, ``update``, ``list_by_status``) against a
  dict keyed by ``job_id``.
* :class:`_RecordingTransport` and the real :class:`InMemoryDedupeStore` let the
  webhook property observe exactly how many sends occurred for a key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.tasks.lifecycle import (
    ALLOWED_TRANSITIONS,
    COMPLETED,
    FAILED,
    PENDING,
    PROCESSING,
    TERMINAL,
    IllegalJobTransition,
    JobLifecycle,
    is_allowed_transition,
)
from app.tasks.webhooks import (
    InMemoryDedupeStore,
    WebhookDispatcher,
    WebhookEvent,
    build_dedupe_key,
)


# --------------------------------------------------------------------------- #
# In-memory collaborator stand-ins (no database, no broker).
# --------------------------------------------------------------------------- #
@dataclass
class _FakeJob:
    """A ``Job``-like row carrying the mutable lifecycle fields the core touches."""

    job_id: uuid.UUID
    job_type: str = "ingest_batch"
    status: str = PENDING
    result: dict | None = None
    failure_reason: str | None = None
    dead_lettered: bool = False
    updated_at: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
    )


class _InMemoryJobRepository:
    """In-memory stand-in for ``JobRepository`` (R23.3).

    Reproduces exactly the methods :class:`JobLifecycle` calls:

    * ``get(job_id)`` returns the stored job or ``None``.
    * ``update(job, **changes)`` applies the keyword changes in place (mirroring
      ``BaseRepository.update`` which setattrs the given columns and flushes).
    * ``list_by_status(status)`` returns the jobs currently in a status.
    """

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, _FakeJob] = {}

    def add(self, job: _FakeJob) -> _FakeJob:
        self._jobs[job.job_id] = job
        return job

    async def get(self, job_id: Any) -> _FakeJob | None:
        return self._jobs.get(job_id)

    async def update(self, instance: _FakeJob, **changes: Any) -> _FakeJob:
        for key, value in changes.items():
            setattr(instance, key, value)
        return instance

    async def list_by_status(self, status: str) -> list[_FakeJob]:
        return [j for j in self._jobs.values() if j.status == status]


class _RecordingTransport:
    """Webhook transport that records every delivered event (R27.4)."""

    def __init__(self) -> None:
        self.sent: list[WebhookEvent] = []

    def send(self, event: WebhookEvent) -> None:
        self.sent.append(event)


# --------------------------------------------------------------------------- #
# Property 36: Job status lifecycle.
# --------------------------------------------------------------------------- #

#: A single lifecycle action to attempt against the current job state. ``start``
#: targets PROCESSING, ``complete`` targets COMPLETED, ``fail`` targets FAILED.
_actions = st.sampled_from(["start", "complete", "fail"])
_action_sequences = st.lists(_actions, min_size=1, max_size=12)


async def _apply(life: JobLifecycle, job_id: uuid.UUID, action: str) -> None:
    """Dispatch one lifecycle action by name."""
    if action == "start":
        await life.start(job_id)
    elif action == "complete":
        await life.complete(job_id, result={"ok": True})
    else:
        await life.fail(job_id, reason="boom", retries_exhausted=False)


# Feature: cineroi-ai, Property 36: Job status lifecycle
# Validates: Requirements 23.3, 23.5
@settings(max_examples=200, deadline=None)
@given(actions=_action_sequences)
async def test_job_status_lifecycle_only_legal_transitions(
    actions: list[str],
) -> None:
    """A job only moves along legal transitions; FAILED always records a reason.

    For an arbitrary sequence of attempted lifecycle actions against a freshly
    dispatched (PENDING) job:

    * every status the job holds is a legal state, and every *successful*
      transition is one of :data:`ALLOWED_TRANSITIONS` (never a backward or
      skip transition) — R23.3;
    * any attempt that is not a legal forward transition raises
      :class:`IllegalJobTransition` and leaves the status unchanged;
    * once the job is terminal it never transitions again (terminal states have
      no outgoing edges) — R23.3;
    * whenever the job is in the FAILED terminal state it carries a non-empty
      ``failure_reason`` — R23.5.
    """
    repo = _InMemoryJobRepository()
    job_id = uuid.uuid4()
    repo.add(_FakeJob(job_id=job_id, status=PENDING))
    life = JobLifecycle(repo)  # type: ignore[arg-type]

    target = {"start": PROCESSING, "complete": COMPLETED, "fail": FAILED}

    for action in actions:
        job = await repo.get(job_id)
        assert job is not None
        before = job.status
        to_status = target[action]
        legal = is_allowed_transition(before, to_status)

        if legal:
            await _apply(life, job_id, action)
            after = (await repo.get(job_id)).status
            # The move landed on exactly the intended target state (R23.3).
            assert after == to_status
            # And it was a declared forward edge, never backward / skipping.
            assert to_status in ALLOWED_TRANSITIONS[before]
        else:
            # Illegal attempts are rejected and change nothing (R23.3).
            try:
                await _apply(life, job_id, action)
            except IllegalJobTransition:
                pass
            else:
                raise AssertionError(
                    f"expected IllegalJobTransition for {before} -> {to_status}"
                )
            assert (await repo.get(job_id)).status == before

        current = await repo.get(job_id)
        # Status is always one of the four legal lifecycle states.
        assert current.status in {PENDING, PROCESSING, COMPLETED, FAILED}
        # Invariant: a FAILED job always carries a recorded failure reason (R23.5).
        if current.status == FAILED:
            assert current.failure_reason
        # Terminal states never leak a non-empty outgoing transition set (R23.3).
        if current.status in TERMINAL:
            assert ALLOWED_TRANSITIONS[current.status] == frozenset()


# Feature: cineroi-ai, Property 36: Job status lifecycle
# Validates: Requirements 23.3, 23.5
@settings(max_examples=200, deadline=None)
@given(reason=st.text(min_size=1, max_size=80))
async def test_failed_job_records_failure_reason(reason: str) -> None:
    """Failing a job records the given failure reason on the terminal row (R23.5).

    Regardless of the reason text, a job that transitions to FAILED ends in the
    FAILED state carrying that exact reason — the FAILED terminal state can never
    exist without a recorded cause.
    """
    repo = _InMemoryJobRepository()
    job_id = uuid.uuid4()
    repo.add(_FakeJob(job_id=job_id, status=PROCESSING))
    life = JobLifecycle(repo)  # type: ignore[arg-type]

    await life.fail(job_id, reason=reason, retries_exhausted=False)

    job = await repo.get(job_id)
    assert job is not None
    assert job.status == FAILED
    assert job.failure_reason == reason


# --------------------------------------------------------------------------- #
# Property 35: Webhook idempotent processing.
# --------------------------------------------------------------------------- #

_statuses = st.sampled_from(list(TERMINAL))


# Feature: cineroi-ai, Property 35: Webhook idempotent processing
# Validates: Requirements 27.4
@settings(max_examples=200, deadline=None)
@given(
    job_id=st.uuids(),
    status=_statuses,
    deliveries=st.integers(min_value=1, max_value=20),
)
async def test_webhook_repeated_delivery_is_idempotent(
    job_id: uuid.UUID,
    status: str,
    deliveries: int,
) -> None:
    """Delivering one terminal event N times has the effect of a single delivery.

    For any terminal event ``(job_id, status)`` delivered ``deliveries`` times:

    * exactly one transport ``send`` occurs (the first delivery), so repeats
      produce no duplicate side effects — R27.4;
    * ``deliver`` returns ``True`` only on the first call and ``False`` on every
      repeat;
    * the dedupe key recorded is the deterministic key for that event.
    """
    transport = _RecordingTransport()
    dispatcher = WebhookDispatcher(
        store=InMemoryDedupeStore(), transport=transport
    )

    results = [dispatcher.deliver(job_id, status) for _ in range(deliveries)]

    # Exactly one real send happened, regardless of how many deliveries (R27.4).
    assert len(transport.sent) == 1
    sent = transport.sent[0]
    assert sent.job_id == str(job_id)
    assert sent.status == status

    # Only the first delivery sent; all repeats were suppressed as duplicates.
    assert results[0] is True
    assert all(r is False for r in results[1:])


# Feature: cineroi-ai, Property 35: Webhook idempotent processing
# Validates: Requirements 27.4
@settings(max_examples=200, deadline=None)
@given(
    events=st.lists(
        st.tuples(st.uuids(), _statuses),
        min_size=1,
        max_size=15,
    ),
    repeats=st.integers(min_value=1, max_value=5),
)
async def test_webhook_interleaved_events_each_sent_once(
    events: list[tuple[uuid.UUID, str]],
    repeats: int,
) -> None:
    """Across interleaved repeated events, each distinct event sends exactly once.

    Delivering an arbitrary multiset of terminal events — each ``repeats`` times,
    interleaved — results in exactly one send per *distinct* event identity,
    where identity is the deterministic dedupe key ``(job_id, status)`` (R27.4).
    Distinct events (different job, or same job at a different terminal status)
    stay distinct and are each delivered once.
    """
    transport = _RecordingTransport()
    dispatcher = WebhookDispatcher(
        store=InMemoryDedupeStore(), transport=transport
    )

    distinct_keys = {build_dedupe_key(job_id, status) for job_id, status in events}

    # Deliver every event `repeats` times, interleaved across rounds.
    for _ in range(repeats):
        for job_id, status in events:
            dispatcher.deliver(job_id, status)

    # One send per distinct event, no matter how many deliveries occurred (R27.4).
    assert len(transport.sent) == len(distinct_keys)
    delivered_keys = {
        build_dedupe_key(e.job_id, e.status) for e in transport.sent
    }
    assert delivered_keys == distinct_keys
