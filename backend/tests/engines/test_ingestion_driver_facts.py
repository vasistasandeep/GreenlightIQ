"""Example tests for batch driver-fact capture: anti-inference + conservation.

These cover the batch-path acceptance criteria that task 3.5 of the
``driver-input-capture`` spec pins down, exercising
:meth:`app.engines.ingestion.IngestionService.ingest` end-to-end against
in-memory repository fakes (no database), following the convention established by
``test_ingestion_batch_properties.py``:

* **R3.6 (no inference).** A record supplying ``target_territories`` with three
  entries and ``vernacular_track_count=1`` persists ``1`` — the supplied value —
  never ``3`` inferred from the territory count. The two fields are independent.
* **R3.5 (per-field rejection + conservation).** A record carrying an
  out-of-bounds driver fact is rejected with a per-field ``RejectionDetail``
  naming the offending field and bound, while its valid sibling records are
  accepted, and ``accepted_count + rejected_count == total`` holds across the
  whole batch.
* **R8.3 (neutral passthrough).** A manifest with no driver columns persists each
  record exactly as today, writing none of the twelve driver keys into any
  ``source_snapshot``.

Design Correctness Properties 3 (out-of-bounds rejected, never written) and 4
(supplied facts persist under exact keys; omitted facts absent) are the
properties these examples witness.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.domain import drivers
from app.engines.ingestion import IngestionService


# --------------------------------------------------------------------------- #
# In-memory collaborator fakes (no database) — mirrors the convention in
# ``test_ingestion_batch_properties.py``, extended so the persisted versions
# (and thus their ``source_snapshot``) can be inspected.
# --------------------------------------------------------------------------- #
class _FakeSession:
    """Session stand-in: ``flush`` is a no-op (no DB round-trip to force)."""

    async def flush(self) -> None:
        return None


class _FakeTitleRepository:
    """In-memory fake of ``TitleRepository`` assigning ``title_id`` on create."""

    def __init__(self) -> None:
        self.created: list[Any] = []
        self._by_id: dict[uuid.UUID, Any] = {}

    async def create(self, instance: Any) -> Any:
        if getattr(instance, "title_id", None) is None:
            instance.title_id = uuid.uuid4()
        self.created.append(instance)
        self._by_id[instance.title_id] = instance
        return instance

    async def get(self, entity_id: uuid.UUID) -> Any | None:
        return self._by_id.get(entity_id)


class _FakeTitleVersionRepository:
    """In-memory fake of ``TitleVersionRepository`` (R24 version bookkeeping).

    The ``created`` list retains every appended version, so a test can read back
    the persisted ``source_snapshot`` the ingest path wrote.
    """

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def latest_version_number(self, title_id: uuid.UUID) -> int:
        numbers = [v.version_number for v in self.created if v.title_id == title_id]
        return max(numbers, default=0)

    async def get_active(self, title_id: uuid.UUID) -> Any | None:
        for version in self.created:
            if version.title_id == title_id and version.is_active:
                return version
        return None

    async def create(self, instance: Any) -> Any:
        if getattr(instance, "title_version_id", None) is None:
            instance.title_version_id = uuid.uuid4()
        self.created.append(instance)
        return instance

    async def update(self, instance: Any, **values: Any) -> Any:
        for key, value in values.items():
            setattr(instance, key, value)
        return instance


class _FakeJobRepository:
    """In-memory fake of ``JobRepository``; fresh keys resolve to ``None``."""

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def get_by_idempotency_key(self, key: str) -> Any | None:
        return None

    async def create(self, instance: Any) -> Any:
        if getattr(instance, "job_id", None) is None:
            instance.job_id = uuid.uuid4()
        self.created.append(instance)
        return instance


class _FakeLicenseTermRepository:
    """In-memory fake of ``LicenseTermRepository`` capturing created rows."""

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, instance: Any) -> Any:
        self.created.append(instance)
        return instance


class _FakeMetadataVectorRepository:
    """Stand-in for ``MetadataVectorRepository`` (unused on the ingest path)."""


@dataclass
class _CapturingTrigger:
    """A no-op async extraction trigger recording each invocation (R1.6)."""

    calls: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]] = field(default_factory=list)

    async def __call__(
        self,
        title_id: uuid.UUID,
        title_version_id: uuid.UUID,
        model_version_id: uuid.UUID | None,
    ) -> None:
        self.calls.append((title_id, title_version_id, model_version_id))


def _build_service() -> tuple[IngestionService, _FakeTitleVersionRepository]:
    """Wire an :class:`IngestionService` against the in-memory fakes.

    Returns the service plus the version repository so a test can read back each
    persisted ``source_snapshot``.
    """
    versions = _FakeTitleVersionRepository()
    service = IngestionService(
        session=_FakeSession(),  # type: ignore[arg-type]
        title_repository=_FakeTitleRepository(),  # type: ignore[arg-type]
        title_version_repository=versions,  # type: ignore[arg-type]
        job_repository=_FakeJobRepository(),  # type: ignore[arg-type]
        license_term_repository=_FakeLicenseTermRepository(),  # type: ignore[arg-type]
        metadata_vector_repository=_FakeMetadataVectorRepository(),  # type: ignore[arg-type]
        extraction_trigger=_CapturingTrigger(),
    )
    return service, versions


def _json_payload(records: list[dict[str, Any]]) -> bytes:
    """Serialize a list of record dicts into a JSON manifest body (R1.2)."""
    return json.dumps(records).encode("utf-8")


# --------------------------------------------------------------------------- #
# R3.6 — vernacular_track_count is never inferred from target_territories.
# --------------------------------------------------------------------------- #
async def test_vernacular_track_count_persisted_as_supplied_not_inferred() -> None:
    """Validates: Requirements 3.6

    A record naming three target territories but a ``vernacular_track_count`` of
    1 persists 1 — the supplied value — never 3 inferred from the territory list.
    The two fields are independent.
    """
    service, versions = _build_service()

    record = {
        "title_name": "Trilingual Release",
        "acquisition_cost_or_budget": "500000.00",
        "target_territories": ["US", "IN", "BR"],
        "vernacular_track_count": 1,
    }

    result = await service.ingest(
        payload=_json_payload([record]),
        content_type="json",
        idempotency_key="",
    )

    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 0

    snapshot = versions.created[0].source_snapshot
    # Persisted exactly as supplied (native int), not derived from the 3 territories.
    assert snapshot["vernacular_track_count"] == 1
    assert snapshot["vernacular_track_count"] != 3
    # The territory list itself is untouched and independent of the track count.
    assert snapshot["target_territories"] == ["US", "IN", "BR"]


# --------------------------------------------------------------------------- #
# R3.5 — out-of-bounds driver fact rejected per-field; siblings accepted;
# conservation accepted + rejected == total holds.
# --------------------------------------------------------------------------- #
async def test_out_of_bounds_driver_fact_rejects_only_offending_record() -> None:
    """Validates: Requirements 3.5

    A record carrying an out-of-bounds driver fact
    (``vernacular_track_count=0``) is rejected with a per-field
    ``RejectionDetail`` naming the offending field and bound, while its valid
    sibling records are accepted, and ``accepted_count + rejected_count`` equals
    the total number of records submitted.
    """
    service, versions = _build_service()

    records: list[dict[str, Any]] = [
        {
            "title_name": "Valid Franchise Entry",
            "acquisition_cost_or_budget": "1200000.00",
            "is_franchise": True,
            "franchise_order": 2,
            "vernacular_track_count": 3,
        },
        {
            # Out of bounds: vernacular_track_count must be an integer >= 1.
            "title_name": "Bad Track Count",
            "acquisition_cost_or_budget": "800000.00",
            "vernacular_track_count": 0,
        },
        {
            "title_name": "Valid Macro Row",
            "acquisition_cost_or_budget": "650000.00",
            "source_ip_provenance": "BESTSELLER_BOOK",
            "release_window": "THEATRICAL_30D",
        },
    ]

    result = await service.ingest(
        payload=_json_payload(records),
        content_type="json",
        idempotency_key="",
    )

    total = len(records)
    # Conservation invariant (R3.5): nothing dropped, nothing double-counted.
    assert result["accepted_count"] + result["rejected_count"] == total
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 1

    # Exactly one per-field rejection, pointing back at the offending row/field.
    assert len(result["rejections"]) == 1
    rejection = result["rejections"][0]
    assert rejection["row_index"] == 1
    assert rejection["field"] == "vernacular_track_count"
    assert rejection["reason"]  # names the violated bound
    assert "1" in rejection["reason"]

    # The two valid siblings were persisted; the rejected row wrote no version.
    assert len(versions.created) == 2
    persisted_names = {v.source_snapshot["title_name"] for v in versions.created}
    assert persisted_names == {"Valid Franchise Entry", "Valid Macro Row"}
    # And the rejected fact never reached any snapshot (never written — Property 3).
    for version in versions.created:
        assert version.source_snapshot.get("vernacular_track_count") != 0


async def test_out_of_bounds_enum_driver_fact_names_field_and_bound() -> None:
    """Validates: Requirements 3.5

    An out-of-set enum driver fact (``release_window``) is rejected with a
    ``RejectionDetail`` naming the offending field, while the conservation
    invariant still holds and the valid sibling is accepted.
    """
    service, versions = _build_service()

    records: list[dict[str, Any]] = [
        {
            "title_name": "Bad Window",
            "acquisition_cost_or_budget": "300000.00",
            "release_window": "STRAIGHT_TO_VHS",  # not a Release_Window_Set member
        },
        {
            "title_name": "Clean Row",
            "acquisition_cost_or_budget": "450000.00",
        },
    ]

    result = await service.ingest(
        payload=_json_payload(records),
        content_type="json",
        idempotency_key="",
    )

    assert result["accepted_count"] + result["rejected_count"] == len(records)
    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 1

    rejection = result["rejections"][0]
    assert rejection["row_index"] == 0
    assert rejection["field"] == "release_window"
    assert rejection["reason"]

    # The rejected enum value never reached a snapshot.
    assert len(versions.created) == 1
    assert versions.created[0].source_snapshot.get("release_window") is None


# --------------------------------------------------------------------------- #
# R8.3 — a manifest with no driver columns writes no driver keys.
# --------------------------------------------------------------------------- #
async def test_manifest_without_driver_columns_writes_no_driver_keys() -> None:
    """Validates: Requirements 8.3

    When a manifest carries none of the twelve driver columns/fields, each record
    is accepted and persisted exactly as today, with no driver-fact key present
    in any ``source_snapshot`` (the title stays a Neutral_Title).
    """
    service, versions = _build_service()

    records: list[dict[str, Any]] = [
        {
            "title_name": "Plain Title One",
            "acquisition_cost_or_budget": "250000.00",
            "asset_type": "LICENSED_LIBRARY",
            "genre_tag": "DRAMA",
        },
        {
            "title_name": "Plain Title Two",
            "acquisition_cost_or_budget": "750000.00",
            "target_territories": ["US", "CA"],
        },
    ]

    result = await service.ingest(
        payload=_json_payload(records),
        content_type="json",
        idempotency_key="",
    )

    assert result["accepted_count"] == len(records)
    assert result["rejected_count"] == 0
    assert len(versions.created) == len(records)

    for version in versions.created:
        snapshot = version.source_snapshot
        for key in drivers.DRIVER_FACT_KEYS:
            assert key not in snapshot, f"unexpected driver key {key!r} in snapshot"
        # The non-driver record fields are preserved exactly (R6.4 passthrough).
        assert snapshot["title_name"] in {"Plain Title One", "Plain Title Two"}
