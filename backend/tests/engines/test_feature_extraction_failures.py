"""Unit/integration tests for Feature_Extraction failure modes and atomic persistence.

Targets :meth:`app.engines.feature_extraction.FeatureExtractionEngine.extract`
and its persistence helpers, covering the four behaviours task 10.3 calls for:

* **R2.2** — a title with no non-empty source document raises
  :class:`~app.engines.feature_extraction.NoSourceContentError`, records a
  ``FAILED`` status row, and produces no ``SUCCESS`` row / vector.
* **R2.7** — when persisting the artifacts fails, the partial write is rolled
  back (SAVEPOINT), a ``FAILED`` status row is recorded, and
  :class:`~app.engines.feature_extraction.ExtractionPersistenceError` is raised.
* **R2.8** — when document parsing/embedding fails, a ``FAILED`` status row is
  recorded, any previously persisted vector for the ``title_id`` is left
  unchanged, and :class:`~app.engines.feature_extraction.DocumentParseError` is
  raised.
* **R2.6** — on success exactly one ``MetadataVector`` row is persisted carrying
  all four artifacts (Narrative_DNA, affective primary+secondary,
  talent_pedigree_score, production_scale_metric) in a single transaction.

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database**. They reuse the exact
fake-collaborator pattern established in
``tests/engines/test_feature_extraction_properties.py`` — a ``_FakeSession``
whose ``begin_nested()`` is an async SAVEPOINT surrogate, a
``_FakeMetadataVectorRepository``, and a ``_FakeModelVersioningEngine`` — and
extend it with fault-injecting variants where a failure mode must be forced.

These are example-based unit/integration tests, not property tests, so no
``Property-N`` tag is required.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from types import TracebackType

import pytest

from app.engines.feature_extraction import (
    EMOTIONAL_TRIGGERS,
    BaseEmbeddingProvider,
    DeterministicEmbeddingProvider,
    DocumentParseError,
    ExtractionPersistenceError,
    FeatureExtractionEngine,
    NoSourceContentError,
    SourceBundle,
)
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS, MetadataVector

_WEIGHT_SUM = Decimal("1.00")
_SCORE_MIN = Decimal("0.00")
_SCORE_MAX = Decimal("10.00")


# --------------------------------------------------------------------------- #
# In-memory collaborator fakes (no database) — mirrors the property-test file.
# --------------------------------------------------------------------------- #
@dataclass
class _FakeModelVersion:
    """A ``ModelVersion``-like weight carrier read by ``read_active`` (R12.2)."""

    model_version_id: uuid.UUID
    talent_pedigree_weight: Decimal
    narrative_trope_weight: Decimal


class _FakeModelVersioningEngine:
    """Stand-in for ``ModelVersioningEngine`` exposing only ``read_active``."""

    def __init__(self, active: _FakeModelVersion) -> None:
        self._active = active

    async def read_active(self) -> _FakeModelVersion:
        """Return the single active version supplying scorer weights."""
        return self._active


class _FakeNestedTransaction:
    """Async-context-manager surrogate for a SAVEPOINT (``begin_nested``).

    On a clean exit the pending adds are committed to the session's persisted
    store; on an exception they are discarded, mirroring the SAVEPOINT rollback
    ``_persist_atomically`` relies on for R2.7.
    """

    def __init__(self, session: "_FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> "_FakeNestedTransaction":
        self._session._begin_savepoint()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            self._session._commit_savepoint()
        else:
            self._session._rollback_savepoint()
        return False  # never suppress — the engine normalizes failures itself.


class _FakeSession:
    """A session stand-in supporting ``add``/``flush``/``begin_nested``.

    ``add`` stages a row inside the current SAVEPOINT; ``flush`` is a no-op.
    ``persisted`` holds the rows that survived their nested transaction so a
    test can inspect exactly what the engine would have written.
    """

    def __init__(self) -> None:
        self.persisted: list[MetadataVector] = []
        self._pending: list[MetadataVector] = []

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction(self)

    def add(self, instance: MetadataVector) -> None:
        self._pending.append(instance)

    async def flush(self) -> None:
        return None

    # -- SAVEPOINT lifecycle driven by _FakeNestedTransaction ------------- #
    def _begin_savepoint(self) -> None:
        self._pending = []

    def _commit_savepoint(self) -> None:
        self.persisted.extend(self._pending)
        self._pending = []

    def _rollback_savepoint(self) -> None:
        self._pending = []


class _FlushFailsOnSuccessSession(_FakeSession):
    """A ``_FakeSession`` whose ``flush`` raises while inserting the SUCCESS row.

    Forces the R2.7 persist-failure path: the artifact insert (the row whose
    ``extraction_status == 'SUCCESS'``) fails on ``flush``, which must trigger a
    SAVEPOINT rollback. The subsequent FAILED-marker insert is allowed through
    so the test can assert that the failure row survives.
    """

    def __init__(self) -> None:
        super().__init__()
        self.flush_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1
        # Only the artifact (SUCCESS) insert is poisoned; the FAILED marker row
        # that _record_failure writes afterwards must still be able to persist.
        for pending in self._pending:
            if pending.extraction_status == "SUCCESS":
                raise RuntimeError("simulated DB flush failure during artifact insert")
        return None


class _FakeMetadataVectorRepository:
    """In-memory fake of ``MetadataVectorRepository`` over a ``_FakeSession``."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def create(self, instance: MetadataVector) -> MetadataVector:
        self.session.add(instance)
        await self.session.flush()
        self.session.persisted.append(instance)
        return instance

    async def list_for_title(self, title_id: uuid.UUID) -> list[MetadataVector]:
        return [r for r in self.session.persisted if r.title_id == title_id]


class _RaisingEmbeddingProvider(BaseEmbeddingProvider):
    """An embedding provider whose ``embed`` always raises (forces R2.8)."""

    def embed(self, text: str) -> list[float]:
        raise ValueError("simulated embedding/parse failure")


class _WrongLengthEmbeddingProvider(BaseEmbeddingProvider):
    """An embedding provider returning a wrong-length vector (forces R2.8)."""

    def embed(self, text: str) -> list[float]:
        # One dimension short of the required 1536 — the engine must reject it.
        return [0.0] * (NARRATIVE_DNA_DIMENSIONS - 1)


class _OutOfRangeEmbeddingProvider(BaseEmbeddingProvider):
    """An embedding provider returning an out-of-range component (forces R2.8)."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * NARRATIVE_DNA_DIMENSIONS
        vector[0] = 2.0  # outside the closed interval [-1.0, 1.0] (R2.1).
        return vector


# --------------------------------------------------------------------------- #
# Builders.
# --------------------------------------------------------------------------- #
def _default_weights() -> _FakeModelVersion:
    """A valid active version with coupled weights summing to 1.00 (R12.2)."""
    return _FakeModelVersion(
        model_version_id=uuid.uuid4(),
        talent_pedigree_weight=Decimal("0.60"),
        narrative_trope_weight=Decimal("0.40"),
    )


def _build_engine(
    *,
    session: _FakeSession | None = None,
    embedding_provider: object | None = None,
) -> tuple[FeatureExtractionEngine, _FakeSession]:
    """Wire the engine against the in-memory fakes, allowing fault injection."""
    session = session if session is not None else _FakeSession()
    repository = _FakeMetadataVectorRepository(session)
    model_versioning = _FakeModelVersioningEngine(_default_weights())
    engine = FeatureExtractionEngine(
        session=session,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        embedding_provider=(
            embedding_provider
            if embedding_provider is not None
            else DeterministicEmbeddingProvider()
        ),  # type: ignore[arg-type]
        model_versioning=model_versioning,  # type: ignore[arg-type]
    )
    return engine, session


def _nonempty_sources() -> SourceBundle:
    """A source bundle with real content so the engine takes the success path."""
    return SourceBundle(logline="A heist thriller set on a sinking cruise ship.")


# --------------------------------------------------------------------------- #
# R2.2 — empty / whitespace source failure.
# --------------------------------------------------------------------------- #
async def test_empty_source_raises_and_records_failed_only() -> None:
    """R2.2: an empty source raises ``NoSourceContentError`` with only a FAILED row.

    A title with no non-empty source document must raise
    :class:`NoSourceContentError`, record exactly one ``FAILED`` extraction
    status row, and persist no ``SUCCESS`` row or usable vector.
    """
    engine, session = _build_engine()
    title_id = uuid.uuid4()
    model_version_id = uuid.uuid4()

    with pytest.raises(NoSourceContentError) as excinfo:
        await engine.extract(title_id, SourceBundle(), model_version_id)

    assert excinfo.value.title_id == title_id

    # Exactly one row, and it is a FAILED marker — no SUCCESS row / no vector.
    assert len(session.persisted) == 1
    row = session.persisted[0]
    assert row.extraction_status == "FAILED"
    assert row.title_id == title_id
    assert all(r.extraction_status != "SUCCESS" for r in session.persisted)
    # The marker carries no usable scalar scores.
    assert row.talent_pedigree_score is None
    assert row.production_scale_metric is None


async def test_whitespace_only_source_raises_and_records_failed() -> None:
    """R2.2: whitespace-only source fields count as no content and fail cleanly.

    A bundle whose only fields are whitespace must be treated as having no
    content: ``NoSourceContentError`` is raised and a ``FAILED`` row is recorded.
    """
    engine, session = _build_engine()
    title_id = uuid.uuid4()

    whitespace = SourceBundle(logline="   ", pitch_deck="\n\t", manifest_content="")
    with pytest.raises(NoSourceContentError):
        await engine.extract(title_id, whitespace, uuid.uuid4())

    assert len(session.persisted) == 1
    assert session.persisted[0].extraction_status == "FAILED"


# --------------------------------------------------------------------------- #
# R2.7 — persist-failure rollback.
# --------------------------------------------------------------------------- #
async def test_persist_failure_rolls_back_and_records_failed() -> None:
    """R2.7: a persist failure rolls back the partial write and records FAILED.

    When the artifact insert fails during ``flush``, the SAVEPOINT rollback must
    discard the partial ``SUCCESS`` write, a ``FAILED`` status row must be
    recorded in its place, and :class:`ExtractionPersistenceError` must be
    raised — leaving no half-written profile behind.
    """
    session = _FlushFailsOnSuccessSession()
    engine, session = _build_engine(session=session)
    title_id = uuid.uuid4()
    model_version_id = uuid.uuid4()

    with pytest.raises(ExtractionPersistenceError) as excinfo:
        await engine.extract(title_id, _nonempty_sources(), model_version_id)

    assert excinfo.value.title_id == title_id

    # The partial SUCCESS write was rolled back; only the FAILED marker survived.
    assert all(r.extraction_status != "SUCCESS" for r in session.persisted)
    failed_rows = [r for r in session.persisted if r.extraction_status == "FAILED"]
    assert len(failed_rows) == 1
    assert failed_rows[0].title_id == title_id
    # The engine did attempt the SUCCESS insert (so the rollback path was taken).
    assert session.flush_calls >= 1


# --------------------------------------------------------------------------- #
# R2.8 — parse-failure retain-prior.
# --------------------------------------------------------------------------- #
async def test_parse_failure_retains_prior_vector() -> None:
    """R2.8: a parse failure records FAILED and leaves a prior vector unchanged.

    When the embedding provider raises, the engine must raise
    :class:`DocumentParseError`, record a ``FAILED`` status row, and leave any
    previously persisted ``SUCCESS`` vector for the ``title_id`` untouched.
    """
    engine, session = _build_engine(embedding_provider=_RaisingEmbeddingProvider())
    title_id = uuid.uuid4()

    # Seed a prior SUCCESS row for the same title that must survive the failure.
    prior = MetadataVector(
        title_id=title_id,
        narrative_dna=[0.25] * NARRATIVE_DNA_DIMENSIONS,
        affective_primary=EMOTIONAL_TRIGGERS[0],
        affective_secondary=EMOTIONAL_TRIGGERS[1],
        talent_pedigree_score=Decimal("4.20"),
        production_scale_metric=Decimal("7.10"),
        model_version_id=uuid.uuid4(),
        extraction_status="SUCCESS",
    )
    session.persisted.append(prior)

    with pytest.raises(DocumentParseError) as excinfo:
        await engine.extract(title_id, _nonempty_sources(), uuid.uuid4())

    assert excinfo.value.title_id == title_id

    # The prior SUCCESS row is left exactly as it was (R2.8 retain-prior).
    success_rows = [r for r in session.persisted if r.extraction_status == "SUCCESS"]
    assert len(success_rows) == 1
    survivor = success_rows[0]
    assert survivor is prior
    assert survivor.talent_pedigree_score == Decimal("4.20")
    assert survivor.production_scale_metric == Decimal("7.10")
    assert survivor.narrative_dna == [0.25] * NARRATIVE_DNA_DIMENSIONS

    # A FAILED marker for the title was recorded alongside the untouched prior.
    failed_rows = [r for r in session.persisted if r.extraction_status == "FAILED"]
    assert len(failed_rows) == 1
    assert failed_rows[0].title_id == title_id


async def test_wrong_length_embedding_raises_parse_error() -> None:
    """R2.8: a wrong-length embedding is a parse failure recording FAILED.

    A provider returning a vector that is not 1536 dimensions must be rejected
    as a :class:`DocumentParseError`, with a ``FAILED`` row recorded and no
    ``SUCCESS`` row persisted.
    """
    engine, session = _build_engine(
        embedding_provider=_WrongLengthEmbeddingProvider()
    )
    title_id = uuid.uuid4()

    with pytest.raises(DocumentParseError):
        await engine.extract(title_id, _nonempty_sources(), uuid.uuid4())

    assert all(r.extraction_status != "SUCCESS" for r in session.persisted)
    assert any(r.extraction_status == "FAILED" for r in session.persisted)


async def test_out_of_range_embedding_raises_parse_error() -> None:
    """R2.8: an out-of-range embedding component is a parse failure.

    A provider returning a component outside ``[-1.0, 1.0]`` must be rejected as
    a :class:`DocumentParseError`, with a ``FAILED`` row recorded and no
    ``SUCCESS`` row persisted (the R2.1 range contract is enforced at R2.8).
    """
    engine, session = _build_engine(
        embedding_provider=_OutOfRangeEmbeddingProvider()
    )
    title_id = uuid.uuid4()

    with pytest.raises(DocumentParseError):
        await engine.extract(title_id, _nonempty_sources(), uuid.uuid4())

    assert all(r.extraction_status != "SUCCESS" for r in session.persisted)
    assert any(r.extraction_status == "FAILED" for r in session.persisted)


# --------------------------------------------------------------------------- #
# R2.6 — atomic four-artifact persistence.
# --------------------------------------------------------------------------- #
async def test_success_persists_single_row_with_all_four_artifacts() -> None:
    """R2.6: success persists exactly one row carrying all four artifacts.

    On the success path the engine must persist exactly one ``MetadataVector``
    row — in a single transaction — carrying all four extraction artifacts:
    the Narrative_DNA vector, the affective primary+secondary triggers, the
    talent_pedigree_score, and the production_scale_metric.
    """
    engine, session = _build_engine()
    title_id = uuid.uuid4()
    model_version_id = uuid.uuid4()

    output = await engine.extract(title_id, _nonempty_sources(), model_version_id)

    # Exactly one persisted row, and it is the SUCCESS profile (atomic insert).
    assert len(session.persisted) == 1
    row = session.persisted[0]
    assert row.extraction_status == "SUCCESS"
    assert row.title_id == title_id
    assert row.model_version_id == model_version_id

    # Artifact 1: Narrative_DNA — 1536 dims, all in range, matching the output.
    assert len(row.narrative_dna) == NARRATIVE_DNA_DIMENSIONS
    assert row.narrative_dna == output["narrative_dna"]
    assert all(-1.0 <= c <= 1.0 for c in row.narrative_dna)

    # Artifact 2: Affective tone — exactly one primary + one distinct secondary.
    assert row.affective_primary == output["affective_tone"]["primary"]
    assert row.affective_secondary == output["affective_tone"]["secondary"]
    assert row.affective_primary in EMOTIONAL_TRIGGERS
    assert row.affective_secondary in EMOTIONAL_TRIGGERS
    assert row.affective_primary != row.affective_secondary

    # Artifact 3 & 4: the two scalar scores, in range and matching the output.
    assert row.talent_pedigree_score is not None
    assert row.production_scale_metric is not None
    assert _SCORE_MIN <= row.talent_pedigree_score <= _SCORE_MAX
    assert _SCORE_MIN <= row.production_scale_metric <= _SCORE_MAX
    assert float(row.talent_pedigree_score) == output["talent_pedigree_score"]
    assert float(row.production_scale_metric) == output["production_scale_metric"]

    # No FAILED marker was written on the success path.
    assert all(r.extraction_status != "FAILED" for r in session.persisted)
