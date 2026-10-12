"""Repository for ``subscriber_clusters`` (design R3, R3.1-R3.3).

Provides the pgvector cosine-similarity query the Vector_Search_Engine needs:
rank every subscriber cohort's ``preference_vector`` against a title's
Narrative_DNA using the ``<=>`` cosine-distance operator and return cohorts in
descending similarity order (ascending distance). Keeping the raw vector query
behind a repository keeps the engine thin and consistent with the rest of the
data-access layer.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.subscriber_cluster import SubscriberCluster
from app.repositories.base import BaseRepository


class SubscriberClusterRepository(BaseRepository[SubscriberCluster]):
    """Async access to the ``subscriber_clusters`` table (design R3)."""

    model = SubscriberCluster
    pk = SubscriberCluster.cluster_id

    async def rank_by_similarity(
        self, title_vector: list[float]
    ) -> list[tuple[SubscriberCluster, float]]:
        """Rank cohorts by cosine similarity to ``title_vector`` (R3.1, R3.2).

        Computes cosine similarity as ``1 - (preference_vector <=> title_vector)``
        with pgvector's ``<=>`` cosine-distance operator and orders the rows by
        ascending distance, i.e. **descending** similarity (R3.2). An empty table
        yields an empty list, which the engine maps to the ``NO_CLUSTERS`` status
        (R3.3).

        Args:
            title_vector: The title's 1536-dim Narrative_DNA embedding.

        Returns:
            ``(cluster, cosine_similarity)`` pairs ordered from most to least
            similar. ``cosine_similarity`` is a Python ``float`` in ``[-1.0,
            1.0]`` where ``1.0`` is identical direction.
        """
        distance = SubscriberCluster.preference_vector.cosine_distance(
            title_vector
        )
        similarity = (1 - distance).label("cosine_similarity")
        stmt = (
            select(SubscriberCluster, similarity)
            .order_by(distance.asc())
        )
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]
