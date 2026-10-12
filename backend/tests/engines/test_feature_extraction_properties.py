"""Property-based tests for the Feature_Extraction engine (R2).

Targets :class:`app.engines.feature_extraction.FeatureExtractionEngine.extract`
and the artifact builders it orchestrates
(:class:`~app.engines.feature_extraction.DeterministicEmbeddingProvider`,
``_build_affective_tone`` and the scalar scorers), exercising the end-to-end
``extract`` path so the *persisted* shape is covered as well as the returned
:class:`~app.engines.feature_extraction.ExtractionOutput`.

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database**. Three stand-ins
reproduce exactly the collaborator contract ``extract`` relies on:

* :class:`_FakeSession` — a session stand-in whose ``begin_nested()`` is an async
  context manager (SAVEPOINT surrogate) and whose ``add`` / ``flush`` capture the
  inserted :class:`~app.models.metadata_vector.MetadataVector` rows in memory, so
  ``_persist_atomically`` runs without a real DB and the persisted row is
  inspectable.
* :class:`_FakeMetadataVectorRepository` — mirrors the repository contract the
  engine is constructed with (``create`` appends; ``list_for_title`` reads back
  the rows the session captured), matching ``MetadataVectorRepository``.
* :class:`_FakeModelVersioningEngine` — ``read_active`` returns a
  ``ModelVersion``-like object whose ``talent_pedigree_weight`` and
  ``narrative_trope_weight`` always sum to exactly ``1.00`` (the R12.2 CHECK), so
  the scalar scorers resolve real weights.

Covers design Property 4 (Narrative DNA vector shape, R2.1), Property 5
(Affective tone cardinality, R2.3) and Property 6 (Extraction score bounds,
R2.4/R2.5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from types import TracebackType

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.feature_extraction import (
    EMOTIONAL_TRIGGERS,
    DeterministicEmbeddingProvider,
    FeatureExtractionEngine,
    SourceBundle,
)
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS, MetadataVector

_WEIGHT_SUM = Decimal("1.00")
_SCORE_MIN = Decimal("0.00")
_SCORE_MAX = Decimal("10.00")
_SCORE_QUANTUM = Decimal("0.01")


# --------------------------------------------------------------------------- #
# In-memory collaborator fakes (no database).
# --------------------------------------------------------------------------- #
@dataclass
class _FakeModelVersion:
    """A ``ModelVersion``-like weight carrier read by ``read_active``.

    Only the two coupled feature weights the engine's scorers consume are
    modelled; both lie in ``[0.00, 1.00]`` and sum to exactly ``1.00`` (R12.2).
    """

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

    On a clean exit the captured adds are committed to the session's persisted
    store; on an exception the pending adds are discarded, mirroring the
    SAVEPOINT rollback ``_persist_atomically`` relies on for R2.7.
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

    ``add`` stages a row inside the current SAVEPOINT; ``flush`` is a no-op
    (there is no DB round-trip to force). ``persisted`` holds the rows that
    survived their nested transaction, so a test can inspect exactly what the
    engine would have written.
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


class _FakeMetadataVectorRepository:
    """In-memory fake of ``MetadataVectorRepository`` over a ``_FakeSession``.

    ``create`` appends a row (matching the base repository's add+flush) and
    ``list_for_title`` reads back the rows captured for a title — covering the
    repository contract the engine is constructed with even though ``extract``
    persists via the session directly.
    """

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def create(self, instance: MetadataVector) -> MetadataVector:
        self.session.add(instance)
        await self.session.flush()
        self.session.persisted.append(instance)
        return instance

    async def list_for_title(self, title_id: uuid.UUID) -> list[MetadataVector]:
        return [r for r in self.session.persisted if r.title_id == title_id]


# --------------------------------------------------------------------------- #
# Strategies.
# --------------------------------------------------------------------------- #
def _coupled_weights() -> st.SearchStrategy[tuple[Decimal, Decimal]]:
    """A (talent, narrative) weight pair in [0.00, 1.00] summing to 1.00 (R12.2)."""
    return st.decimals(
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ).map(lambda t: (t, _WEIGHT_SUM - t))


def _nonempty_text() -> st.SearchStrategy[str]:
    """Text guaranteed to carry at least one non-whitespace character."""
    return st.text(min_size=1, max_size=400).filter(lambda s: s.strip() != "")


def _source_bundles() -> st.SearchStrategy[SourceBundle]:
    """A ``SourceBundle`` with at least one non-empty source field (R2.1).

    Any field may be ``None`` or blank, but at least one of logline / pitch deck
    / manifest carries real text so the bundle always ``has_content()`` and the
    engine takes the success path.
    """
    optional = st.one_of(st.none(), st.just(""), _nonempty_text())
    return st.builds(
        SourceBundle,
        logline=optional,
        pitch_deck=optional,
        manifest_content=optional,
    ).filter(lambda b: b.has_content())


def _build_engine(
    weights: tuple[Decimal, Decimal],
) -> tuple[FeatureExtractionEngine, _FakeSession]:
    """Wire the engine against the in-memory fakes for a given weight pair."""
    talent, narrative = weights
    session = _FakeSession()
    repository = _FakeMetadataVectorRepository(session)
    model_versioning = _FakeModelVersioningEngine(
        _FakeModelVersion(
            model_version_id=uuid.uuid4(),
            talent_pedigree_weight=talent,
            narrative_trope_weight=narrative,
        )
    )
    engine = FeatureExtractionEngine(
        session=session,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        embedding_provider=DeterministicEmbeddingProvider(),
        model_versioning=model_versioning,  # type: ignore[arg-type]
    )
    return engine, session


def _assert_two_dp(value: Decimal) -> None:
    """Assert ``value`` is quantised to exactly two decimal places (R2.4/R2.5)."""
    assert value == value.quantize(_SCORE_QUANTUM), (
        f"score {value} is not rounded to 2 decimal places."
    )


# --------------------------------------------------------------------------- #
# Property 4: Narrative DNA vector shape (R2.1).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 4: Narrative DNA vector shape
@given(sources=_source_bundles(), weights=_coupled_weights())
@settings(max_examples=150)
async def test_narrative_dna_shape_and_range(
    sources: SourceBundle,
    weights: tuple[Decimal, Decimal],
) -> None:
    """Validates: Requirements 2.1

    For any title with at least one non-empty source document, the generated
    Narrative_DNA vector has exactly 1536 dimensions and every component lies in
    the closed interval [-1.0, 1.0] — in both the returned output and the
    persisted row.
    """
    engine, session = _build_engine(weights)
    title_id = uuid.uuid4()
    model_version_id = uuid.uuid4()

    output = await engine.extract(title_id, sources, model_version_id)

    vector = output["narrative_dna"]
    assert len(vector) == NARRATIVE_DNA_DIMENSIONS == 1536
    for component in vector:
        assert isinstance(component, float)
        assert -1.0 <= component <= 1.0

    # The persisted SUCCESS row carries the same in-range 1536-dim vector (R2.6).
    assert len(session.persisted) == 1
    stored = session.persisted[0]
    assert stored.extraction_status == "SUCCESS"
    assert len(stored.narrative_dna) == NARRATIVE_DNA_DIMENSIONS
    for component in stored.narrative_dna:
        assert -1.0 <= component <= 1.0


# --------------------------------------------------------------------------- #
# Property 5: Affective tone cardinality (R2.3).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 5: Affective tone cardinality
@given(sources=_source_bundles(), weights=_coupled_weights())
@settings(max_examples=150)
async def test_affective_tone_cardinality(
    sources: SourceBundle,
    weights: tuple[Decimal, Decimal],
) -> None:
    """Validates: Requirements 2.3

    For any processed title the Affective_Tone_Score names exactly one primary
    and one secondary trigger, both members of the predefined trigger set, and
    the primary is always distinct from the secondary.
    """
    engine, session = _build_engine(weights)
    title_id = uuid.uuid4()

    output = await engine.extract(title_id, sources, uuid.uuid4())
    tone = output["affective_tone"]

    # Exactly the two keys, each a predefined trigger, and distinct (R2.3).
    assert set(tone.keys()) == {"primary", "secondary"}
    assert tone["primary"] in EMOTIONAL_TRIGGERS
    assert tone["secondary"] in EMOTIONAL_TRIGGERS
    assert tone["primary"] != tone["secondary"]

    # The persisted row reflects the same single primary/secondary pair (R2.6).
    stored = session.persisted[0]
    assert stored.affective_primary == tone["primary"]
    assert stored.affective_secondary == tone["secondary"]
    assert stored.affective_primary != stored.affective_secondary


# --------------------------------------------------------------------------- #
# Property 6: Extraction score bounds (R2.4, R2.5).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 6: Extraction score bounds
@given(sources=_source_bundles(), weights=_coupled_weights())
@settings(max_examples=150)
async def test_extraction_score_bounds(
    sources: SourceBundle,
    weights: tuple[Decimal, Decimal],
) -> None:
    """Validates: Requirements 2.4, 2.5

    For any processed title, talent_pedigree_score and production_scale_metric
    each lie within [0.0, 10.0] and are rounded to exactly 2 decimal places —
    for every active weight set (which always sums to 1.00).
    """
    engine, session = _build_engine(weights)
    title_id = uuid.uuid4()

    output = await engine.extract(title_id, sources, uuid.uuid4())

    talent = output["talent_pedigree_score"]
    production = output["production_scale_metric"]
    assert 0.0 <= talent <= 10.0
    assert 0.0 <= production <= 10.0

    # Decimal view of the persisted scores: in-range and quantised to 2 dp.
    stored = session.persisted[0]
    for score in (stored.talent_pedigree_score, stored.production_scale_metric):
        assert score is not None
        assert _SCORE_MIN <= score <= _SCORE_MAX
        _assert_two_dp(score)
