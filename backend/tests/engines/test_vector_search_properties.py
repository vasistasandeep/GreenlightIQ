"""Property-based and unit tests for the Vector_Search_Engine (R3).

Targets :meth:`app.engines.vector_search.VectorSearchEngine.match` and the
status sentinels ``STATUS_OK`` / ``STATUS_NO_CLUSTERS`` it returns. The engine
is a thin orchestration layer: it loads a title's Narrative_DNA from the
metadata-vector repository and delegates the pgvector ``<=>`` cosine ranking to
:meth:`SubscriberClusterRepository.rank_by_similarity`, which returns
``(cluster, similarity)`` pairs ordered **descending** by cosine similarity.

Per the design's testing strategy ("engine orchestration tested via in-memory
repository fakes"), these tests run with **no database**. Two stand-ins
reproduce the collaborator contracts ``match`` relies on:

* :class:`_FakeMetadataVectorRepository` — ``list_for_title`` returns the
  metadata-vector rows recorded for a title, each carrying a ``narrative_dna``
  list and a ``created_at`` so the engine's "newest wins" selection is exercised.
* :class:`_FakeSubscriberClusterRepository` — ``rank_by_similarity`` computes
  cosine similarity in pure Python against a fixed set of cluster preference
  vectors and returns the pairs sorted **descending** by similarity, mirroring
  the pgvector query contract. The computation is deterministic so a test can
  independently predict the ordering.

The real :class:`VectorSearchEngine` is constructed with a stand-in session and
its ``metadata_vectors`` / ``subscriber_clusters`` attributes are swapped for the
fakes — matching how production wires the repositories in ``__init__``.

Covers design Property 7 (Similarity ranking order, R3.1/R3.2) and the
example-based NO_CLUSTERS cases (R3.3): no clusters exist, and a title with no
persisted Narrative_DNA.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.vector_search import (
    STATUS_NO_CLUSTERS,
    STATUS_OK,
    VectorSearchEngine,
)

_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# In-memory collaborator stand-ins (no database).
# --------------------------------------------------------------------------- #
@dataclass
class _FakeMetadataVector:
    """A ``MetadataVector``-like row carrying the two fields ``match`` reads."""

    narrative_dna: list[float] | None
    created_at: datetime


@dataclass
class _FakeCluster:
    """A ``SubscriberCluster``-like row: an id and its preference vector."""

    cluster_id: uuid.UUID
    preference_vector: list[float]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Mirrors pgvector's ``1 - (a <=> b)``. Returns ``0.0`` for a zero-magnitude
    vector so the fake stays total (pgvector treats the undefined case as a
    distance of 1, i.e. similarity 0).
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class _FakeMetadataVectorRepository:
    """In-memory fake of ``MetadataVectorRepository.list_for_title``."""

    def __init__(self, rows_by_title: dict[uuid.UUID, list[_FakeMetadataVector]]) -> None:
        self._rows_by_title = rows_by_title

    async def list_for_title(self, title_id: uuid.UUID) -> list[_FakeMetadataVector]:
        return list(self._rows_by_title.get(title_id, []))


class _FakeSubscriberClusterRepository:
    """In-memory fake of ``SubscriberClusterRepository.rank_by_similarity``.

    Computes cosine similarity in Python against the configured cluster set and
    returns ``(cluster, similarity)`` pairs ordered **descending** by similarity,
    exactly as the pgvector ``<=>`` query (ascending distance) would (R3.1, R3.2).
    """

    def __init__(self, clusters: list[_FakeCluster]) -> None:
        self._clusters = clusters

    async def rank_by_similarity(
        self, title_vector: list[float]
    ) -> list[tuple[_FakeCluster, float]]:
        scored = [
            (cluster, _cosine_similarity(cluster.preference_vector, title_vector))
            for cluster in self._clusters
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


@dataclass
class _StandInSession:
    """A placeholder passed to the engine; the fakes replace the repositories."""

    marker: str = field(default="no-db")


def _build_engine(
    *,
    metadata_rows: dict[uuid.UUID, list[_FakeMetadataVector]],
    clusters: list[_FakeCluster],
) -> VectorSearchEngine:
    """Construct the real engine and swap in the in-memory repository fakes."""
    engine = VectorSearchEngine(session=_StandInSession())  # type: ignore[arg-type]
    engine.metadata_vectors = _FakeMetadataVectorRepository(metadata_rows)  # type: ignore[assignment]
    engine.subscriber_clusters = _FakeSubscriberClusterRepository(clusters)  # type: ignore[assignment]
    return engine


# --------------------------------------------------------------------------- #
# Strategies.
# --------------------------------------------------------------------------- #
def _finite_floats() -> st.SearchStrategy[float]:
    """Bounded, finite float components for small test vectors."""
    return st.floats(
        min_value=-1.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    )


def _vectors(dim: int) -> st.SearchStrategy[list[float]]:
    """A fixed-length vector whose magnitude is non-zero (defined cosine)."""
    return st.lists(_finite_floats(), min_size=dim, max_size=dim).filter(
        lambda v: any(abs(x) > 1e-6 for x in v)
    )


@st.composite
def _ranking_scenarios(draw: st.DrawFn) -> tuple[list[float], list[list[float]]]:
    """A title vector plus a small set of cluster preference vectors.

    All vectors share the same dimension (2-5) and are non-degenerate, so cosine
    similarity is well defined for every pair.
    """
    dim = draw(st.integers(min_value=2, max_value=5))
    title_vector = draw(_vectors(dim))
    cluster_vectors = draw(st.lists(_vectors(dim), min_size=1, max_size=6))
    return title_vector, cluster_vectors


# --------------------------------------------------------------------------- #
# Property 7: Similarity ranking order (R3.1, R3.2).
# --------------------------------------------------------------------------- #
# Feature: cineroi-ai, Property 7: Similarity ranking order
@given(scenario=_ranking_scenarios())
@settings(max_examples=150)
async def test_similarity_ranking_order(
    scenario: tuple[list[float], list[list[float]]],
) -> None:
    """Validates: Requirements 3.1, 3.2

    For any set of subscriber cluster preference vectors, ``match`` returns an
    all-OK result list whose cosine similarities are non-increasing, and whose
    ordering matches an independent descending sort of the computed similarities.
    """
    title_vector, cluster_vectors = scenario
    clusters = [_FakeCluster(uuid.uuid4(), vec) for vec in cluster_vectors]
    title_id = uuid.uuid4()
    engine = _build_engine(
        metadata_rows={
            title_id: [_FakeMetadataVector(narrative_dna=title_vector, created_at=_EPOCH)]
        },
        clusters=clusters,
    )

    results = await engine.match(title_id)

    # One result per cluster, each a ranked OK match (not the sentinel).
    assert len(results) == len(clusters)
    assert all(r["status"] == STATUS_OK for r in results)

    similarities = [r["cosine_similarity"] for r in results]

    # (a) The returned similarities are non-increasing (descending rank, R3.2).
    for earlier, later in zip(similarities, similarities[1:]):
        assert earlier >= later

    # (b) The ordering matches an independent descending sort of the per-cluster
    #     similarities computed from the title vector (R3.1).
    expected = sorted(
        (_cosine_similarity(c.preference_vector, title_vector) for c in clusters),
        reverse=True,
    )
    assert similarities == expected


# --------------------------------------------------------------------------- #
# Property 7 companion: "newest metadata vector wins" ordering input (R3.1).
# --------------------------------------------------------------------------- #
async def test_match_uses_latest_metadata_vector() -> None:
    """Validates: Requirements 3.1

    When a title has several metadata vectors, the match is driven by the most
    recently created Narrative_DNA (the engine's "newest wins" selection), so the
    ranking reflects that vector's similarities.
    """
    old_vector = [1.0, 0.0]
    new_vector = [0.0, 1.0]
    title_id = uuid.uuid4()
    # Cluster aligned with the NEW vector should rank first.
    aligned_with_new = _FakeCluster(uuid.uuid4(), [0.0, 1.0])
    aligned_with_old = _FakeCluster(uuid.uuid4(), [1.0, 0.0])

    engine = _build_engine(
        metadata_rows={
            title_id: [
                _FakeMetadataVector(narrative_dna=old_vector, created_at=_EPOCH),
                _FakeMetadataVector(
                    narrative_dna=new_vector, created_at=_EPOCH + timedelta(days=1)
                ),
            ]
        },
        clusters=[aligned_with_old, aligned_with_new],
    )

    results = await engine.match(title_id)

    assert [r["cluster_id"] for r in results] == [
        aligned_with_new.cluster_id,
        aligned_with_old.cluster_id,
    ]
    assert results[0]["cosine_similarity"] > results[1]["cosine_similarity"]


# --------------------------------------------------------------------------- #
# Example-based: NO_CLUSTERS status sentinel (R3.3).
# --------------------------------------------------------------------------- #
async def test_match_returns_no_clusters_sentinel_when_no_clusters_exist() -> None:
    """Validates: Requirements 3.3

    When no subscriber cluster preference vectors exist, ``match`` returns a
    single-element result whose entry carries the NO_CLUSTERS status, the nil
    cluster id, and a 0.0 similarity.
    """
    title_id = uuid.uuid4()
    engine = _build_engine(
        metadata_rows={
            title_id: [_FakeMetadataVector(narrative_dna=[0.1, 0.2, 0.3], created_at=_EPOCH)]
        },
        clusters=[],  # empty cluster set
    )

    results = await engine.match(title_id)

    assert len(results) == 1
    only = results[0]
    assert only["status"] == STATUS_NO_CLUSTERS
    assert only["cluster_id"] == uuid.UUID(int=0)
    assert only["cosine_similarity"] == 0.0


async def test_match_returns_no_clusters_sentinel_when_title_has_no_metadata_vector() -> None:
    """Validates: Requirements 3.3

    A title with no persisted Narrative_DNA has nothing to match against, so
    ``match`` falls back to the NO_CLUSTERS sentinel even when clusters exist.
    """
    title_id = uuid.uuid4()
    clusters = [_FakeCluster(uuid.uuid4(), [1.0, 0.0, 0.0])]
    engine = _build_engine(metadata_rows={}, clusters=clusters)

    results = await engine.match(title_id)

    assert len(results) == 1
    assert results[0]["status"] == STATUS_NO_CLUSTERS
    assert results[0]["cluster_id"] == uuid.UUID(int=0)
    assert results[0]["cosine_similarity"] == 0.0


async def test_match_returns_no_clusters_sentinel_when_metadata_vector_dna_is_none() -> None:
    """Validates: Requirements 3.3

    A metadata-vector row whose Narrative_DNA is ``None`` is treated like having
    no vector, yielding the NO_CLUSTERS sentinel.
    """
    title_id = uuid.uuid4()
    clusters = [_FakeCluster(uuid.uuid4(), [1.0, 0.0, 0.0])]
    engine = _build_engine(
        metadata_rows={
            title_id: [_FakeMetadataVector(narrative_dna=None, created_at=_EPOCH)]
        },
        clusters=clusters,
    )

    results = await engine.match(title_id)

    assert len(results) == 1
    assert results[0]["status"] == STATUS_NO_CLUSTERS
