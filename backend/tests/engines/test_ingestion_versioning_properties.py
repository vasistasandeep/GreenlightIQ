"""Property-based tests for Ingestion_Service idempotency + title versioning.

Targets :class:`app.engines.ingestion.IngestionService.ingest` and the two
behaviours it orchestrates across the injected repositories:

* **Idempotent replay (R27.1):** an ingest carrying an ``idempotency_key`` that
  already has a stored ``jobs`` row returns the *stored* ``IngestionResult``
  unchanged and creates no new title / version / job rows (design Property 33).
* **Versioning immutability + increment (R24.1-R24.4):** a submission carrying an
  existing ``title_id`` appends a child version whose ``version_number`` is one
  greater than the prior maximum, that new version becomes the single active one,
  and all prior versions are left byte-for-byte unchanged (design Property 32).

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), the service is wired against in-memory fakes for every
injected collaborator. The fakes faithfully reproduce the contracts the service
relies on:

* The job fake stores jobs keyed by ``idempotency_key``; ``get_by_idempotency_key``
  returns the prior job whose ``result`` is set, so a second ingest with the same
  key replays it (R27.1).
* The title / title-version fakes assign a UUID on ``create`` (the real schema
  populates ids via a server default on flush, which an in-memory fake must stand
  in for), track versions per title, increment ``latest_version_number``, expose
  the single active version via ``get_active``, and manage the ``is_active`` flag
  through ``update`` — mirroring the partial unique "one active per title" index
  (R24.4).

No extraction trigger is injected (``None``), so the service is exercised without
a live pipeline; ``model_version_id`` is irrelevant to these two properties.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.ingestion import IngestionService


# --------------------------------------------------------------------------- #
# In-memory fakes for the injected collaborators
# --------------------------------------------------------------------------- #


class FakeSession:
    """A no-op stand-in for the owning AsyncSession.

    The service ``flush``es (never ``commit``s) and relies on the repositories —
    not the session — to assign primary keys, so ``flush`` is a no-op here. The
    repository fakes below assign ids on ``create`` to mimic the real server
    default populating on flush.
    """

    async def flush(self) -> None:  # pragma: no cover - trivial
        return None


class FakeJobRepository:
    """Stores jobs keyed by idempotency key to drive idempotent replay (R27.1).

    ``get_by_idempotency_key`` returns the previously stored job (whose ``result``
    is set) so the service replays its stored :class:`IngestionResult` rather than
    reprocessing. ``create`` assigns a ``job_id`` (standing in for the DB server
    default) and indexes the row by its key.
    """

    def __init__(self) -> None:
        self.jobs: list[Any] = []
        self._by_key: dict[str, Any] = {}

    async def get_by_idempotency_key(self, idempotency_key: str) -> Any | None:
        return self._by_key.get(idempotency_key)

    async def create(self, job: Any) -> Any:
        if getattr(job, "job_id", None) is None:
            job.job_id = uuid.uuid4()
        self.jobs.append(job)
        if job.idempotency_key:
            self._by_key[job.idempotency_key] = job
        return job


@dataclass
class _TitleRow:
    """Minimal mutable stand-in for a persisted ``titles`` row."""

    title_id: uuid.UUID | None = None
    active_version_id: uuid.UUID | None = None
    # The service sets a number of columns on the ORM object; capture them so a
    # snapshot/compare sees any accidental mutation of an existing title.
    attrs: dict[str, Any] = field(default_factory=dict)


class FakeTitleRepository:
    """In-memory ``titles`` store that assigns an id on create (R17.1)."""

    def __init__(self) -> None:
        self.titles: dict[uuid.UUID, Any] = {}

    async def get(self, title_id: uuid.UUID) -> Any | None:
        return self.titles.get(title_id)

    async def create(self, title: Any) -> Any:
        if getattr(title, "title_id", None) is None:
            title.title_id = uuid.uuid4()
        self.titles[title.title_id] = title
        return title

    async def update(self, title: Any, **values: Any) -> Any:
        for key, value in values.items():
            setattr(title, key, value)
        return title


class FakeTitleVersionRepository:
    """In-memory ``title_versions`` store enforcing one-active-per-title (R24).

    Tracks every version per title in insertion order. ``latest_version_number``
    returns the current maximum (0 when none), ``get_active`` returns the single
    row flagged active, and ``update`` toggles the ``is_active`` flag — together
    reproducing the partial unique "one active per title" index (R24.4) that the
    service relies on when it deactivates the prior active version before
    inserting the new one.
    """

    def __init__(self) -> None:
        self.versions: list[Any] = []

    def _for_title(self, title_id: uuid.UUID) -> list[Any]:
        return [v for v in self.versions if v.title_id == title_id]

    async def latest_version_number(self, title_id: uuid.UUID) -> int:
        numbers = [v.version_number for v in self._for_title(title_id)]
        return max(numbers, default=0)

    async def get_active(self, title_id: uuid.UUID) -> Any | None:
        for version in self._for_title(title_id):
            if version.is_active:
                return version
        return None

    async def create(self, version: Any) -> Any:
        if getattr(version, "title_version_id", None) is None:
            version.title_version_id = uuid.uuid4()
        self.versions.append(version)
        return version

    async def update(self, version: Any, **values: Any) -> Any:
        for key, value in values.items():
            setattr(version, key, value)
        return version


class FakeLicenseTermRepository:
    """Captures license rows; not central to these two properties."""

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, row: Any) -> Any:
        self.created.append(row)
        return row


class FakeMetadataVectorRepository:
    """Unused by ingestion persistence; present only to satisfy injection."""


def _build_service() -> tuple[
    IngestionService,
    FakeTitleRepository,
    FakeTitleVersionRepository,
    FakeJobRepository,
]:
    """Wire the service against in-memory fakes (no extraction trigger)."""
    titles = FakeTitleRepository()
    versions = FakeTitleVersionRepository()
    jobs = FakeJobRepository()
    service = IngestionService(
        session=FakeSession(),  # type: ignore[arg-type]
        title_repository=titles,  # type: ignore[arg-type]
        title_version_repository=versions,  # type: ignore[arg-type]
        job_repository=jobs,  # type: ignore[arg-type]
        license_term_repository=FakeLicenseTermRepository(),  # type: ignore[arg-type]
        metadata_vector_repository=FakeMetadataVectorRepository(),  # type: ignore[arg-type]
    )
    return service, titles, versions, jobs


# --------------------------------------------------------------------------- #
# Generators: valid JSON records
# --------------------------------------------------------------------------- #

_ASSET_TYPES = ["ORIGINAL_SERIES", "ORIGINAL_FILM", "LICENSED_LIBRARY", "CO_PRODUCTION"]

# Non-empty, non-blank title names so the record passes required-field validation.
_title_name = st.text(min_size=1, max_size=40).map(lambda s: s.strip()).filter(bool)

# Acquisition cost strictly inside the inclusive [0.01, 999999999.99] range so the
# record always validates and is accepted (R1.8).
_cost = st.integers(min_value=1, max_value=5_000_000).map(lambda n: f"{n}.00")


@st.composite
def _valid_record(draw: Any, *, title_id: str | None = None) -> dict[str, Any]:
    """A single JSON record that always passes per-row validation (R1.1, R1.8)."""
    record: dict[str, Any] = {
        "title_name": draw(_title_name),
        "acquisition_cost_or_budget": draw(_cost),
        "asset_type": draw(st.sampled_from(_ASSET_TYPES)),
        "native_currency": draw(st.sampled_from(["USD", "EUR", "GBP", "INR"])),
    }
    if title_id is not None:
        record["title_id"] = title_id
    return record


def _json_payload(records: list[dict[str, Any]]) -> bytes:
    """Encode a list of records as a JSON ingest payload (array form, R1.2)."""
    return json.dumps(records).encode("utf-8")


def _snapshot_versions(versions: FakeTitleVersionRepository) -> dict[uuid.UUID, dict[str, Any]]:
    """Deep snapshot every version's observable state, keyed by version id."""
    return {
        v.title_version_id: {
            "title_id": v.title_id,
            "version_number": v.version_number,
            "is_active": v.is_active,
            "source_snapshot": copy.deepcopy(v.source_snapshot),
        }
        for v in versions.versions
    }


# --------------------------------------------------------------------------- #
# Property 33: Idempotent ingestion replay (R27.1)
# --------------------------------------------------------------------------- #


# Feature: cineroi-ai, Property 33: Idempotent ingestion replay
@given(
    records=st.lists(_valid_record(), min_size=1, max_size=6),
    idempotency_key=st.text(min_size=1, max_size=24).filter(lambda s: s.strip() != ""),
)
@settings(max_examples=120, deadline=None)
async def test_idempotent_replay_returns_stored_result_without_duplicates(
    records: list[dict[str, Any]], idempotency_key: str
) -> None:
    """Validates: Requirements 27.1

    Ingesting the same payload twice under the same idempotency key returns the
    identical :class:`IngestionResult` the second time and creates no new title,
    version, or job rows on replay. The first call's repository state is
    snapshotted and asserted unchanged after the replay.
    """
    service, titles, versions, jobs = _build_service()
    payload = _json_payload(records)

    first = await service.ingest(payload, "json", idempotency_key)

    # Snapshot repository state after the first (processing) call.
    titles_after_first = dict(titles.titles)
    versions_after_first = _snapshot_versions(versions)
    jobs_after_first = list(jobs.jobs)

    second = await service.ingest(payload, "json", idempotency_key)

    # The replay returns the identical stored result (R27.1).
    assert second == first
    assert second["job_id"] == first["job_id"]

    # No duplicate records: titles, versions, and jobs are all unchanged.
    assert dict(titles.titles) == titles_after_first
    assert _snapshot_versions(versions) == versions_after_first
    assert list(jobs.jobs) == jobs_after_first
    assert len(jobs.jobs) == 1
    # Exactly one version per accepted record was created on the first pass only.
    assert len(versions.versions) == len(records)


# --------------------------------------------------------------------------- #
# Property 32: Title versioning immutability and increment (R24.1-R24.4)
# --------------------------------------------------------------------------- #


# Feature: cineroi-ai, Property 32: Title versioning immutability and increment
@given(
    seed_record=_valid_record(),
    follow_up_records=st.lists(_valid_record(), min_size=1, max_size=5),
)
@settings(max_examples=120, deadline=None)
async def test_versioning_appends_incrementing_active_version_leaving_priors_untouched(
    seed_record: dict[str, Any], follow_up_records: list[dict[str, Any]]
) -> None:
    """Validates: Requirements 24.1, 24.2, 24.3, 24.4

    Seeding a brand-new title creates version 1 (active). Each subsequent
    submission carrying that ``title_id`` appends a child version whose
    ``version_number`` is one greater than the prior maximum (R24.1, R24.2),
    becomes the single active version (R24.4), and leaves every prior version's
    stored state unchanged (R24.3).
    """
    service, titles, versions, _jobs = _build_service()

    # Seed a new title (no title_id) -> version 1, active.
    seed_result = await service.ingest(
        _json_payload([seed_record]), "json", f"seed-{uuid.uuid4()}"
    )
    assert seed_result["accepted_count"] == 1
    assert len(versions.versions) == 1
    title_id = versions.versions[0].title_id
    assert versions.versions[0].version_number == 1
    assert versions.versions[0].is_active is True

    title_id_str = str(title_id)

    for step, record in enumerate(follow_up_records, start=1):
        expected_version_number = step + 1  # seed was 1

        # Snapshot all prior versions' observable state before this submission.
        priors = _snapshot_versions(versions)
        prior_ids = set(priors)

        versioned_record = dict(record)
        versioned_record["title_id"] = title_id_str
        result = await service.ingest(
            _json_payload([versioned_record]), "json", f"v-{uuid.uuid4()}"
        )
        assert result["accepted_count"] == 1

        title_versions = [v for v in versions.versions if v.title_id == title_id]
        new_versions = [v for v in title_versions if v.title_version_id not in prior_ids]

        # Exactly one new child version was appended (R24.1).
        assert len(new_versions) == 1
        new_version = new_versions[0]

        # Its version_number is the prior maximum + 1 (R24.2).
        assert new_version.version_number == expected_version_number

        # Exactly one active version exists for the title, and it is the new one
        # (R24.4): single active, repointed to the latest submission.
        active = [v for v in title_versions if v.is_active]
        assert len(active) == 1
        assert active[0].title_version_id == new_version.title_version_id

        # The title row points at the new active version (R24.4).
        title = titles.titles[title_id]
        assert title.active_version_id == new_version.title_version_id

        # Every prior version is unchanged except that the formerly-active one is
        # now inactive; its number and immutable source snapshot never change
        # (R24.3). No prior version's source_snapshot or version_number mutates.
        for version in title_versions:
            if version.title_version_id in prior_ids:
                before = priors[version.title_version_id]
                assert version.version_number == before["version_number"]
                assert version.source_snapshot == before["source_snapshot"]
                assert version.title_id == before["title_id"]
                # No prior version remains active after a newer one supersedes it.
                assert version.is_active is False
