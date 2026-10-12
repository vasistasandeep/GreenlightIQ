"""Property-based tests for Ingestion_Service batch invariants (R1).

Targets :meth:`app.engines.ingestion.IngestionService.ingest` end-to-end,
exercising the whole-request format guard, per-row validation, and the batch
summary it returns (:class:`~app.engines.ingestion.IngestionResult`).

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database**. A set of light-weight
stand-ins reproduce exactly the collaborator contract ``ingest`` relies on:

* :class:`_FakeSession` — a session stand-in whose ``flush`` is a no-op (there is
  no DB round-trip to force), satisfying ``_append_version``'s ``session.flush``.
* :class:`_FakeTitleRepository` — ``create`` assigns a ``title_id`` and records
  the row; ``get`` reads it back (matching ``TitleRepository``).
* :class:`_FakeTitleVersionRepository` — ``latest_version_number`` /
  ``get_active`` / ``create`` / ``update`` over an in-memory list, assigning a
  ``title_version_id`` on create (matching ``TitleVersionRepository``).
* :class:`_FakeJobRepository` — ``get_by_idempotency_key`` returns ``None`` for a
  fresh key; ``create`` assigns a ``job_id`` (matching ``JobRepository``).
* :class:`_FakeLicenseTermRepository` / :class:`_FakeMetadataVectorRepository` —
  minimal ``create`` capture; the metadata-vector repo is unused on this path.
* ``_CapturingTrigger`` — a no-op async extraction trigger that records every
  ``(title_id, title_version_id, model_version_id)`` it is invoked with (R1.6).

Payloads are built as JSON manifests (a list of record dicts) because JSON is the
format that round-trips a Python dict deterministically — the generators control
exactly which rows are valid and which are invalid, so the known valid/invalid
split can be asserted against the returned counts.

Covers design Property 1 (Batch summary conservation, R1.1/R1.9/R1.10),
Property 2 (Mixed-batch partial acceptance, R1.7/R1.8) and Property 3
(Unsupported format rejection, R1.4).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import UnsupportedFormatError
from app.engines.ingestion import (
    MAX_ACQUISITION_COST,
    MIN_ACQUISITION_COST,
    IngestionService,
)
from app.models.title import ASSET_TYPES


# --------------------------------------------------------------------------- #
# In-memory collaborator fakes (no database).
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
    """In-memory fake of ``TitleVersionRepository`` (R24 version bookkeeping)."""

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

    calls: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]] = field(
        default_factory=list
    )

    async def __call__(
        self,
        title_id: uuid.UUID,
        title_version_id: uuid.UUID,
        model_version_id: uuid.UUID | None,
    ) -> None:
        self.calls.append((title_id, title_version_id, model_version_id))


def _build_service() -> tuple[IngestionService, _FakeTitleRepository, _CapturingTrigger]:
    """Wire an :class:`IngestionService` against the in-memory fakes."""
    titles = _FakeTitleRepository()
    trigger = _CapturingTrigger()
    service = IngestionService(
        session=_FakeSession(),  # type: ignore[arg-type]
        title_repository=titles,  # type: ignore[arg-type]
        title_version_repository=_FakeTitleVersionRepository(),  # type: ignore[arg-type]
        job_repository=_FakeJobRepository(),  # type: ignore[arg-type]
        license_term_repository=_FakeLicenseTermRepository(),  # type: ignore[arg-type]
        metadata_vector_repository=_FakeMetadataVectorRepository(),  # type: ignore[arg-type]
        extraction_trigger=trigger,
    )
    return service, titles, trigger


def _json_payload(records: list[dict[str, Any]]) -> bytes:
    """Serialize a list of record dicts into a JSON manifest body (R1.2)."""
    return json.dumps(records).encode("utf-8")


# --------------------------------------------------------------------------- #
# Record strategies: valid rows and each distinct invalid-row kind.
# --------------------------------------------------------------------------- #
def _valid_cost_str() -> st.SearchStrategy[str]:
    """A cost string strictly inside the inclusive [0.01, 999999999.99] range."""
    return st.decimals(
        min_value=MIN_ACQUISITION_COST,
        max_value=MAX_ACQUISITION_COST,
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ).map(str)


def _title_names() -> st.SearchStrategy[str]:
    """Title names guaranteed to carry at least one non-whitespace character."""
    return st.text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")


@st.composite
def _valid_records(draw: st.DrawFn) -> dict[str, Any]:
    """A fully valid record: present title_name, in-range cost, valid asset_type."""
    record: dict[str, Any] = {
        "title_name": draw(_title_names()),
        "acquisition_cost_or_budget": draw(_valid_cost_str()),
    }
    # asset_type is optional; when present it must be from the enum set.
    asset_type = draw(st.one_of(st.none(), st.sampled_from(ASSET_TYPES)))
    if asset_type is not None:
        record["asset_type"] = asset_type
    return record


@st.composite
def _missing_title_name_records(draw: st.DrawFn) -> dict[str, Any]:
    """Invalid: title_name absent or blank (R1.7)."""
    record: dict[str, Any] = {
        "acquisition_cost_or_budget": draw(_valid_cost_str()),
    }
    # Either omit title_name entirely, or make it blank/whitespace.
    blank = draw(st.one_of(st.none(), st.sampled_from(["", "   ", "\t"])))
    if blank is not None:
        record["title_name"] = blank
    return record


@st.composite
def _out_of_range_cost_records(draw: st.DrawFn) -> dict[str, Any]:
    """Invalid: acquisition_cost_or_budget missing or out of range (R1.7/R1.8)."""
    kind = draw(st.sampled_from(["missing", "too_low", "too_high", "non_numeric"]))
    record: dict[str, Any] = {"title_name": draw(_title_names())}
    if kind == "missing":
        return record
    if kind == "too_low":
        record["acquisition_cost_or_budget"] = draw(
            st.decimals(
                min_value=Decimal("-1000"),
                max_value=Decimal("0.00"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            ).map(str)
        )
    elif kind == "too_high":
        record["acquisition_cost_or_budget"] = draw(
            st.decimals(
                min_value=MAX_ACQUISITION_COST + Decimal("0.01"),
                max_value=Decimal("9999999999.99"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            ).map(str)
        )
    else:  # non_numeric
        record["acquisition_cost_or_budget"] = draw(
            st.sampled_from(["abc", "N/A", "$12.00", "", "   "])
        )
    return record


@st.composite
def _bad_asset_type_records(draw: st.DrawFn) -> dict[str, Any]:
    """Invalid: asset_type present but outside the enum set (R1.8)."""
    bad = draw(
        st.text(min_size=1, max_size=20).filter(
            lambda s: s.strip() != "" and s.strip() not in ASSET_TYPES
        )
    )
    return {
        "title_name": draw(_title_names()),
        "acquisition_cost_or_budget": draw(_valid_cost_str()),
        "asset_type": bad,
    }


def _invalid_records() -> st.SearchStrategy[dict[str, Any]]:
    """Any single invalid record across the three rejection families."""
    return st.one_of(
        _missing_title_name_records(),
        _out_of_range_cost_records(),
        _bad_asset_type_records(),
    )


# --------------------------------------------------------------------------- #
# Property 1: Batch summary conservation (R1.1, R1.9, R1.10).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 1: Batch summary conservation
@given(
    records=st.lists(
        st.one_of(_valid_records(), _invalid_records()),
        min_size=0,
        max_size=15,
    )
)
@settings(max_examples=150)
async def test_batch_summary_conservation(records: list[dict[str, Any]]) -> None:
    """Validates: Requirements 1.1, 1.9, 1.10

    For any ingestion batch, the returned accepted_count plus rejected_count
    equals the total number of records submitted, the rejections list carries
    exactly one entry per rejected record, and exactly one title record exists
    per accepted record.
    """
    service, titles, trigger = _build_service()

    result = await service.ingest(
        payload=_json_payload(records),
        content_type="json",
        idempotency_key="",
    )

    total = len(records)
    # Conservation: accepted + rejected == total (R1.10).
    assert result["accepted_count"] + result["rejected_count"] == total
    assert result["accepted_count"] >= 0
    assert result["rejected_count"] >= 0
    # One rejection detail per rejected record (R1.9).
    assert len(result["rejections"]) == result["rejected_count"]
    # Exactly one persisted title per accepted record (R1.1), and one extraction
    # trigger per accepted record (R1.6).
    assert len(titles.created) == result["accepted_count"]
    assert len(trigger.calls) == result["accepted_count"]


# --------------------------------------------------------------------------- #
# Property 2: Mixed-batch partial acceptance (R1.7, R1.8).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 2: Mixed-batch partial acceptance
@given(
    valid=st.lists(_valid_records(), min_size=1, max_size=8),
    invalid=st.lists(_invalid_records(), min_size=1, max_size=8),
    seed=st.randoms(use_true_random=False),
)
@settings(max_examples=150)
async def test_mixed_batch_partial_acceptance(
    valid: list[dict[str, Any]],
    invalid: list[dict[str, Any]],
    seed: Any,
) -> None:
    """Validates: Requirements 1.7, 1.8

    For any batch mixing a known number of valid rows with a known number of
    invalid rows, every valid row is accepted and every invalid row is rejected
    with a RejectionDetail; processing continues across the whole batch so the
    counts match the known valid/invalid split exactly.
    """
    # Tag each record so we can assert the per-row verdict against its origin,
    # then interleave valid and invalid rows into one batch.
    tagged = [(rec, True) for rec in valid] + [(rec, False) for rec in invalid]
    seed.shuffle(tagged)
    records = [dict(rec) for rec, _ in tagged]
    expected_valid = len(valid)
    expected_invalid = len(invalid)

    service, titles, trigger = _build_service()

    result = await service.ingest(
        payload=_json_payload(records),
        content_type="json",
        idempotency_key="",
    )

    # The known split is reflected exactly in the summary (R1.7, R1.8).
    assert result["accepted_count"] == expected_valid
    assert result["rejected_count"] == expected_invalid
    assert len(titles.created) == expected_valid
    assert len(trigger.calls) == expected_valid

    # Every rejection points back at an invalid row with a populated detail.
    rejected_indexes = {r["row_index"] for r in result["rejections"]}
    assert len(result["rejections"]) == expected_invalid
    assert len(rejected_indexes) == expected_invalid
    for detail in result["rejections"]:
        is_valid_row = tagged[detail["row_index"]][1]
        assert is_valid_row is False
        assert detail["field"] in {
            "title_name",
            "acquisition_cost_or_budget",
            "asset_type",
        }
        assert detail["reason"]


# --------------------------------------------------------------------------- #
# Property 3: Unsupported format rejection (R1.4).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 3: Unsupported format rejection
@given(
    content_type=st.text(min_size=0, max_size=12).filter(
        lambda s: s.strip().lower() not in {"csv", "json", "pdf"}
    ),
    records=st.lists(_valid_records(), min_size=0, max_size=6),
)
@settings(max_examples=150)
async def test_unsupported_format_rejection(
    content_type: str,
    records: list[dict[str, Any]],
) -> None:
    """Validates: Requirements 1.4

    For any payload whose content type is not CSV, JSON, or PDF, the
    Ingestion_Service rejects the request with an UnsupportedFormatError and
    creates zero title records (and dispatches no extraction).
    """
    service, titles, trigger = _build_service()

    raised = False
    try:
        await service.ingest(
            payload=_json_payload(records),
            content_type=content_type,
            idempotency_key="",
        )
    except UnsupportedFormatError:
        raised = True

    assert raised, f"expected UnsupportedFormatError for content_type={content_type!r}"
    # Whole-request guard: no title created, no extraction dispatched (R1.4).
    assert titles.created == []
    assert trigger.calls == []
