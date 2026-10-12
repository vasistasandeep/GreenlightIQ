"""Unit tests for the Ingestion_Service CSV row-limit boundary (R1.5).

Targets :meth:`app.engines.ingestion.IngestionService.ingest` with
``content_type="csv"`` and the :data:`~app.engines.ingestion.MAX_CSV_ROWS`
whole-request guard. Per R1.5, a CSV manifest with *more than* 10,000 data rows
is rejected whole — :class:`~app.core.errors.RowLimitExceededError` is raised and
*no* title record is created — while a manifest of exactly 10,000 data rows is
accepted and processed normally.

Two concrete examples pin the boundary (design testing strategy: "Row-limit
boundary at exactly 10,000 and 10,001 rows (R1.5)"):

* **Exactly 10,000 data rows** (header + 10,000 valid rows) is ACCEPTED: no
  :class:`RowLimitExceededError` is raised and the returned
  :class:`~app.engines.ingestion.IngestionResult` conserves the batch
  (``accepted_count + rejected_count == 10_000``, R1.10).
* **10,001 data rows** is REJECTED whole: :class:`RowLimitExceededError` is
  raised and the service creates zero title records (R1.5).

These are example-based unit tests (not property tests), so no ``Property-N``
tag is used. They run with **no database**: every injected collaborator is an
in-memory fake whose operations are O(1) per row, so even the 10,000-row case
completes quickly. The row-limit guard fires during CSV parsing (before any
persistence), so the fakes exist mainly to let the accepted-path reach a
summary; the ``extraction_trigger`` is left ``None`` (a no-op).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.errors import RowLimitExceededError
from app.engines.ingestion import MAX_CSV_ROWS, IngestionService
from app.models.job import Job
from app.models.license_term import LicenseTerm
from app.models.title import Title
from app.models.title_version import TitleVersion


# --------------------------------------------------------------------------- #
# In-memory collaborator fakes (no database).
#
# The real schema assigns UUID primary keys via a Postgres ``gen_random_uuid()``
# server default, populated on flush. The engine reads ``title.title_id`` and
# ``version.title_version_id`` immediately after ``create``, so each fake's
# ``create`` assigns the PK to mirror that server-default behaviour. Every
# operation is O(1) so the 10,000-row accepted path stays fast.
# --------------------------------------------------------------------------- #
class _FakeSession:
    """Session stand-in exposing only the async ``flush`` the engine calls."""

    async def flush(self) -> None:
        return None


class _FakeTitleRepository:
    """In-memory fake of ``TitleRepository`` (``create`` / ``get``)."""

    def __init__(self) -> None:
        self.created: list[Title] = []
        self._by_id: dict[uuid.UUID, Title] = {}

    async def create(self, instance: Title) -> Title:
        # Mirror the server-default PK assignment so the engine can read it.
        if instance.title_id is None:
            instance.title_id = uuid.uuid4()
        self.created.append(instance)
        self._by_id[instance.title_id] = instance
        return instance

    async def get(self, entity_id: uuid.UUID) -> Title | None:
        return self._by_id.get(entity_id)


class _FakeTitleVersionRepository:
    """In-memory fake of ``TitleVersionRepository`` with O(1) version lookups.

    Tracks the latest version number and the active version *per title* in dicts
    so ``latest_version_number`` / ``get_active`` stay O(1) regardless of batch
    size (every accepted row in a fresh batch creates a brand-new title, so these
    are trivially small, but the structure keeps the accepted path cheap).
    """

    def __init__(self) -> None:
        self.created: list[TitleVersion] = []
        self._latest: dict[uuid.UUID, int] = {}
        self._active: dict[uuid.UUID, TitleVersion] = {}

    async def latest_version_number(self, title_id: uuid.UUID) -> int:
        return self._latest.get(title_id, 0)

    async def get_active(self, title_id: uuid.UUID) -> TitleVersion | None:
        return self._active.get(title_id)

    async def create(self, instance: TitleVersion) -> TitleVersion:
        if instance.title_version_id is None:
            instance.title_version_id = uuid.uuid4()
        self.created.append(instance)
        self._latest[instance.title_id] = instance.version_number
        if instance.is_active:
            self._active[instance.title_id] = instance
        return instance

    async def update(self, instance: TitleVersion, **values: Any) -> TitleVersion:
        for key, value in values.items():
            setattr(instance, key, value)
        if instance.is_active:
            self._active[instance.title_id] = instance
        elif self._active.get(instance.title_id) is instance:
            del self._active[instance.title_id]
        return instance


class _FakeJobRepository:
    """In-memory fake of ``JobRepository``.

    ``get_by_idempotency_key`` always returns ``None`` (no prior replay), and
    ``create`` assigns the job PK and records the row so the accepted-path result
    can carry a ``job_id``.
    """

    def __init__(self) -> None:
        self.created: list[Job] = []

    async def get_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        return None

    async def create(self, instance: Job) -> Job:
        if instance.job_id is None:
            instance.job_id = uuid.uuid4()
        self.created.append(instance)
        return instance


class _FakeLicenseTermRepository:
    """In-memory fake of ``LicenseTermRepository`` (``create`` only)."""

    def __init__(self) -> None:
        self.created: list[LicenseTerm] = []

    async def create(self, instance: LicenseTerm) -> LicenseTerm:
        self.created.append(instance)
        return instance


class _FakeMetadataVectorRepository:
    """Stand-in for ``MetadataVectorRepository`` (unused by the ingest path)."""

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, instance: Any) -> Any:
        self.created.append(instance)
        return instance


@dataclass
class _Collaborators:
    """Bundle of the injected fakes so a test can assert against each one."""

    session: _FakeSession = field(default_factory=_FakeSession)
    titles: _FakeTitleRepository = field(default_factory=_FakeTitleRepository)
    versions: _FakeTitleVersionRepository = field(
        default_factory=_FakeTitleVersionRepository
    )
    jobs: _FakeJobRepository = field(default_factory=_FakeJobRepository)
    licenses: _FakeLicenseTermRepository = field(
        default_factory=_FakeLicenseTermRepository
    )
    vectors: _FakeMetadataVectorRepository = field(
        default_factory=_FakeMetadataVectorRepository
    )


def _build_service() -> tuple[IngestionService, _Collaborators]:
    """Wire an ``IngestionService`` against fresh in-memory fakes.

    ``extraction_trigger`` is left ``None`` (a no-op per R1.6), so the accepted
    path exercises persistence against the fakes without a live pipeline.
    """
    deps = _Collaborators()
    service = IngestionService(
        session=deps.session,  # type: ignore[arg-type]
        title_repository=deps.titles,  # type: ignore[arg-type]
        title_version_repository=deps.versions,  # type: ignore[arg-type]
        job_repository=deps.jobs,  # type: ignore[arg-type]
        license_term_repository=deps.licenses,  # type: ignore[arg-type]
        metadata_vector_repository=deps.vectors,  # type: ignore[arg-type]
    )
    return service, deps


def _csv_with_rows(data_rows: int) -> bytes:
    """Build a CSV payload with a header and ``data_rows`` minimal-valid rows.

    Each data row carries only the required fields — ``title_name`` and an
    in-range ``acquisition_cost_or_budget`` (R1.7, R1.8) — so every row validates
    and the only thing under test is the whole-request row-count guard (R1.5).
    The text is assembled directly (not via ``csv.writer``) to keep constructing
    a 10,000+ row manifest cheap.
    """
    header = "title_name,acquisition_cost_or_budget\n"
    body = "".join(f"Title {i},1000.00\n" for i in range(data_rows))
    return (header + body).encode("utf-8")


# --------------------------------------------------------------------------- #
# R1.5 — exactly 10,000 rows is accepted (boundary, inclusive).
# --------------------------------------------------------------------------- #
async def test_exactly_max_rows_is_accepted() -> None:
    """R1.5: a CSV of exactly 10,000 data rows is accepted, not row-limited.

    ``MAX_CSV_ROWS`` is the inclusive ceiling: a manifest with exactly that many
    valid data rows must NOT raise :class:`RowLimitExceededError`. The returned
    summary conserves the batch (``accepted_count + rejected_count == 10_000``,
    R1.10) and, since every row is minimal-valid, all 10,000 are accepted.
    """
    service, deps = _build_service()
    payload = _csv_with_rows(MAX_CSV_ROWS)

    result = await service.ingest(
        payload=payload,
        content_type="csv",
        idempotency_key="boundary-exactly-max",
    )

    # Batch is conserved and fully accepted (R1.10).
    assert result["accepted_count"] + result["rejected_count"] == MAX_CSV_ROWS
    assert result["accepted_count"] == MAX_CSV_ROWS
    assert result["rejected_count"] == 0
    assert result["rejections"] == []
    # Processing really happened: one title per accepted row was created.
    assert len(deps.titles.created) == MAX_CSV_ROWS
    assert len(deps.versions.created) == MAX_CSV_ROWS
    # A completed job summary was recorded.
    assert result["job_id"]
    assert len(deps.jobs.created) == 1


# --------------------------------------------------------------------------- #
# R1.5 — 10,001 rows is rejected whole, with no titles created.
# --------------------------------------------------------------------------- #
async def test_one_over_max_rows_is_rejected_whole() -> None:
    """R1.5: a CSV of 10,001 data rows is rejected whole with no titles created.

    One row beyond :data:`MAX_CSV_ROWS` trips the whole-request guard:
    :class:`RowLimitExceededError` is raised and the service creates NO title
    records (nor versions, nor a job) — the entire batch is refused.
    """
    service, deps = _build_service()
    payload = _csv_with_rows(MAX_CSV_ROWS + 1)

    with pytest.raises(RowLimitExceededError):
        await service.ingest(
            payload=payload,
            content_type="csv",
            idempotency_key="boundary-one-over-max",
        )

    # Whole-request rejection: nothing was persisted (R1.5).
    assert deps.titles.created == []
    assert deps.versions.created == []
    assert deps.jobs.created == []
    assert deps.licenses.created == []
