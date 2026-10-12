"""Property-based tests for the Audit_Log_Service orchestration engine (R25).

Covers Property 37 (Audit append-only completeness, R25.1/R25.2) and Property 38
(Lineage ordering and completeness, R25.4) from the cineroi-ai design document,
exercising ``app.engines.audit.AuditLogService``.

Per the design testing strategy, engine orchestration is tested against an
*in-memory* repository fake rather than a real database. The fake below models
the append-only ``audit_log`` contract exactly:

* ``create(entry)`` appends the entry (never replacing an existing one), assigns
  a fresh ``audit_id`` and a strictly increasing ``created_at``/sequence, and
  returns the stored instance (mirroring ``BaseRepository.create`` which flushes
  so server defaults populate).
* ``list_for_subject(subject_id)`` returns the entries for that subject ordered
  oldest-first by ``created_at`` (mirroring ``AuditLogRepository.list_for_subject``).
* There is intentionally **no** ``update`` or ``delete`` — append-only.

The real :class:`AuditLogService` constructs its own ``AuditLogRepository`` in
``__init__``; these tests build the service with any session stand-in and then
replace ``service.repository`` with the in-memory fake so no DB is involved.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.audit import AuditLogService
from app.models.audit_log import AuditLog


class InMemoryAuditLogRepository:
    """Append-only in-memory stand-in for ``AuditLogRepository`` (R25.1, R25.2).

    Stores entries in insert order, assigning each a unique ``audit_id`` and a
    strictly increasing ``created_at`` so chronological ordering is well-defined
    even when inserts happen within the same wall-clock instant. Exposes only
    ``create`` and ``list_for_subject`` — it has no mutation path, modelling the
    database's revoked UPDATE/DELETE privileges.
    """

    _EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def __init__(self) -> None:
        self._entries: list[AuditLog] = []
        self._sequence = 0

    async def create(self, instance: AuditLog) -> AuditLog:
        """Append exactly one entry, assigning id + monotonic timestamp."""
        if instance.audit_id is None:
            instance.audit_id = uuid.uuid4()
        # Strictly increasing server-side timestamp, independent of the caller.
        instance.created_at = self._EPOCH + timedelta(seconds=self._sequence)
        self._sequence += 1
        self._entries.append(instance)
        return instance

    async def list_for_subject(self, subject_id: uuid.UUID) -> list[AuditLog]:
        """Return this subject's entries oldest-first by ``created_at``."""
        matching = [e for e in self._entries if e.subject_id == subject_id]
        return sorted(matching, key=lambda e: e.created_at)

    # Deliberately no update/delete: the audit_log is append-only.

    def all_entries(self) -> list[AuditLog]:
        """Test helper: every stored entry in insert order."""
        return list(self._entries)


def _make_service() -> tuple[AuditLogService, InMemoryAuditLogRepository]:
    """Build an ``AuditLogService`` wired to a fresh in-memory fake repository."""
    fake = InMemoryAuditLogRepository()
    # The session is never touched once the repository is swapped out.
    service = AuditLogService(session=object())  # type: ignore[arg-type]
    service.repository = fake  # type: ignore[assignment]
    return service, fake


def _snapshot(entry: AuditLog) -> tuple[Any, ...]:
    """Capture an entry's observable fields to detect later mutation."""
    return (
        entry.audit_id,
        entry.subject_id,
        entry.actor_id,
        entry.action,
        _freeze(entry.before_value),
        _freeze(entry.after_value),
        entry.model_version_id,
        entry.created_at,
    )


def _freeze(value: dict[str, Any] | None) -> Any:
    """Hashable, comparable snapshot of a JSON-ish mapping (or ``None``)."""
    if value is None:
        return None
    return tuple(sorted(value.items()))


# A small pool of fixed subject UUIDs so generated record sequences realistically
# interleave several subjects (rather than each record getting a unique subject).
_SUBJECT_POOL = [uuid.uuid4() for _ in range(5)]

_actions = st.sampled_from(
    ["ingest", "valuation", "override", "approval", "calibration"]
)

# JSON-serializable before/after payloads (or None), kept small and simple.
_json_values = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=8),
        values=st.one_of(
            st.integers(min_value=-1000, max_value=1000),
            st.text(max_size=12),
            st.booleans(),
        ),
        max_size=4,
    ),
)

# One generated record: (subject_id, actor, action, before, after, model_version_id).
_record = st.tuples(
    st.sampled_from(_SUBJECT_POOL),
    st.one_of(st.none(), st.uuids()),
    _actions,
    _json_values,
    _json_values,
    st.one_of(st.none(), st.uuids()),
)

_record_lists = st.lists(_record, min_size=1, max_size=40)


# Feature: cineroi-ai, Property 37: Audit append-only completeness
# Validates: Requirements 25.1, 25.2
@settings(max_examples=150, deadline=None)
@given(records=_record_lists)
async def test_record_is_append_only_and_complete(
    records: list[tuple[Any, ...]],
) -> None:
    """N record() calls append exactly N entries; prior entries never change.

    Append-only completeness: each ``record`` writes exactly one new entry
    capturing actor/action/before/after (R25.1), the total count equals the
    number of calls, and no previously appended entry is mutated or removed
    (R25.2).
    """
    service, fake = _make_service()

    snapshots: list[tuple[Any, ...]] = []

    for i, (subject_id, actor, action, before, after, mv_id) in enumerate(records):
        entry = await service.record(
            actor,
            action,
            before,
            after,
            model_version_id=mv_id,
            subject_id=subject_id,
        )

        # Exactly one entry was appended by this call.
        assert len(fake.all_entries()) == i + 1

        # The returned entry faithfully captured the recorded fields (R25.1).
        assert entry.subject_id == subject_id
        assert entry.actor_id == actor
        assert entry.action == action
        assert entry.before_value == before
        assert entry.after_value == after
        assert entry.model_version_id == mv_id
        assert entry.audit_id is not None
        assert entry.created_at is not None

        # Every previously appended entry is byte-for-byte unchanged (R25.2).
        stored = fake.all_entries()
        for prior_index, prior_snapshot in enumerate(snapshots):
            assert _snapshot(stored[prior_index]) == prior_snapshot

        snapshots.append(_snapshot(entry))

    # Final count matches the number of record() calls exactly.
    assert len(fake.all_entries()) == len(records)

    # audit_ids are all distinct (one fresh identity per append).
    audit_ids = [e.audit_id for e in fake.all_entries()]
    assert len(set(audit_ids)) == len(audit_ids)


# Feature: cineroi-ai, Property 38: Lineage ordering and completeness
# Validates: Requirements 25.4
@settings(max_examples=150, deadline=None)
@given(records=_record_lists)
async def test_lineage_is_ordered_and_complete(
    records: list[tuple[Any, ...]],
) -> None:
    """lineage(subject) returns all and only that subject's entries, oldest-first.

    Completeness: the lineage count for a subject equals the number of records
    appended for it, and every returned entry belongs to that subject.
    Ordering: entries come back in chronological (ascending ``created_at``)
    order (R25.4).
    """
    service, fake = _make_service()

    # Record every generated entry, tracking expected per-subject counts and the
    # order (by creation) in which each subject's entries were appended.
    expected_counts: dict[uuid.UUID, int] = {}
    expected_order: dict[uuid.UUID, list[uuid.UUID]] = {}

    for subject_id, actor, action, before, after, mv_id in records:
        entry = await service.record(
            actor,
            action,
            before,
            after,
            model_version_id=mv_id,
            subject_id=subject_id,
        )
        expected_counts[subject_id] = expected_counts.get(subject_id, 0) + 1
        expected_order.setdefault(subject_id, []).append(entry.audit_id)

    # Check lineage for every subject in the pool, including ones never recorded
    # (which must come back empty).
    for subject_id in _SUBJECT_POOL:
        lineage = await service.lineage(subject_id)

        # Completeness: count matches, and all entries belong to this subject.
        assert len(lineage) == expected_counts.get(subject_id, 0)
        assert all(e.subject_id == subject_id for e in lineage)

        # Ordering: chronological, oldest-first by created_at.
        timestamps = [e.created_at for e in lineage]
        assert timestamps == sorted(timestamps)

        # The ordered set exactly matches what was recorded, in creation order.
        assert [e.audit_id for e in lineage] == expected_order.get(subject_id, [])

    # Global completeness: no entry is lost or duplicated across all lineages.
    total_lineage = 0
    for subject_id in _SUBJECT_POOL:
        total_lineage += len(await service.lineage(subject_id))
    assert total_lineage == len(records)
