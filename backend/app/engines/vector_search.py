"""Vector_Search_Engine: subscriber-preference similarity matching (R3).

Ranks a title's persisted Narrative_DNA embedding against subscriber cluster
*preference* vectors using pgvector cosine similarity and returns the cohorts
ordered from best to worst audience fit:

- Loads the title's 1536-dim Narrative_DNA from ``metadata_vectors`` and computes
  cosine similarity against every row in ``subscriber_clusters`` using pgvector's
  ``<=>`` cosine-distance operator; similarity is ``1 - distance`` (R3.1).
- Returns results ranked in **descending** order of cosine similarity, i.e.
  ascending cosine distance (R3.2).
- When no subscriber cluster preference vectors exist, returns an empty result
  set carrying a ``NO_CLUSTERS`` status so callers can distinguish "no reference
  clusters available" from "clusters exist but none matched" (R3.3).

The engine is a thin orchestration layer over the repository data-access layer;
it receives an injected :class:`~sqlalchemy.ext.asyncio.AsyncSession` and does
not open a database connection on import. The actual ``<=>`` ranking query lives
in :class:`~app.repositories.subscriber_clusters.SubscriberClusterRepository`.
"""

from __future__ import annotations

import uuid
from typing import Literal, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.metadata_vectors import MetadataVectorRepository
from app.repositories.subscriber_clusters import SubscriberClusterRepository

#: Status when a non-empty ranking was produced against existing clusters.
STATUS_OK: Literal["OK"] = "OK"
#: Status when no subscriber cluster preference vectors exist (R3.3).
STATUS_NO_CLUSTERS: Literal["NO_CLUSTERS"] = "NO_CLUSTERS"


class SimilarityResult(TypedDict):
    """One subscriber-cluster similarity row (design R3).

    Attributes:
        cluster_id: The subscriber cohort the similarity was computed against.
        cosine_similarity: Cosine similarity to the title's Narrative_DNA,
            ``1 - cosine_distance``; higher means closer audience fit.
        status: ``"OK"`` for a ranked match, or ``"NO_CLUSTERS"`` on the status
            sentinel returned when no reference clusters exist (R3.3).
    """

    cluster_id: uuid.UUID
    cosine_similarity: float
    status: Literal["OK", "NO_CLUSTERS"]


class VectorSearchEngine:
    """Cosine-similarity matcher against subscriber cluster vectors (R3).

    Wraps :class:`MetadataVectorRepository` (to load the title's Narrative_DNA)
    and :class:`SubscriberClusterRepository` (to run the pgvector ``<=>`` cosine
    ranking). Construction never touches the database — the injected session is
    used lazily when :meth:`match` executes a statement.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.metadata_vectors = MetadataVectorRepository(session)
        self.subscriber_clusters = SubscriberClusterRepository(session)

    async def match(self, title_id: uuid.UUID) -> list[SimilarityResult]:
        """Rank subscriber clusters by similarity to a title's Narrative_DNA.

        Loads the title's persisted Narrative_DNA vector, then computes cosine
        similarity against every subscriber cluster preference vector with
        pgvector and returns the matches ordered by descending similarity
        (R3.1, R3.2).

        Args:
            title_id: The title whose Narrative_DNA drives the match. The title
                must have a persisted ``metadata_vectors`` row (R3.1).

        Returns:
            A list of :class:`SimilarityResult` ordered from most to least
            similar. When no subscriber cluster preference vectors exist, a
            single-element list is returned whose one entry carries the
            ``NO_CLUSTERS`` status, a nil ``cluster_id``, and a ``0.0``
            similarity, signalling that no reference clusters are available
            (R3.3). A title with no persisted Narrative_DNA likewise yields the
            ``NO_CLUSTERS`` sentinel because there is nothing to match against.
        """
        title_vector = await self._load_title_vector(title_id)
        if title_vector is None:
            return [self._no_clusters_result()]

        ranked = await self.subscriber_clusters.rank_by_similarity(title_vector)
        if not ranked:
            # No subscriber cluster preference vectors exist (R3.3).
            return [self._no_clusters_result()]

        return [
            SimilarityResult(
                cluster_id=cluster.cluster_id,
                cosine_similarity=similarity,
                status=STATUS_OK,
            )
            for cluster, similarity in ranked
        ]

    async def _load_title_vector(
        self, title_id: uuid.UUID
    ) -> list[float] | None:
        """Return the title's persisted Narrative_DNA embedding, or ``None``.

        Uses the most recently recorded metadata vector for the title. Returns
        ``None`` when the title has no persisted Narrative_DNA, so :meth:`match`
        can fall back to the ``NO_CLUSTERS`` sentinel.
        """
        vectors = await self.metadata_vectors.list_for_title(title_id)
        if not vectors:
            return None
        # Prefer the newest extraction when more than one exists.
        latest = max(vectors, key=lambda v: v.created_at)
        narrative_dna = latest.narrative_dna
        if narrative_dna is None:
            return None
        return list(narrative_dna)

    @staticmethod
    def _no_clusters_result() -> SimilarityResult:
        """Build the ``NO_CLUSTERS`` status sentinel result (R3.3)."""
        return SimilarityResult(
            cluster_id=uuid.UUID(int=0),
            cosine_similarity=0.0,
            status=STATUS_NO_CLUSTERS,
        )
