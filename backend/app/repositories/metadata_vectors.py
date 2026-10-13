"""Repository for ``metadata_vectors`` (R17.2, R17.6).

Stores the extracted Narrative_DNA embedding and affective/pedigree scores for a
title. Foreign key on ``title_id`` enforces referential integrity (R17.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.financial_projection import FinancialProjection
from app.models.metadata_vector import MetadataVector
from app.models.title import Title
from app.repositories.base import BaseRepository


class SimilarTitle:
    """A nearest-neighbour title ranked by Narrative_DNA cosine similarity.

    A plain value object (not an ORM row) carrying just the fields the comps
    surface needs: the neighbour's id/name/genre, its latest recommendation (if
    it has a computed valuation), and the cosine similarity to the query title.
    """

    __slots__ = (
        "title_id",
        "title_name",
        "genre_tag",
        "recommendation_status",
        "cosine_similarity",
    )

    def __init__(
        self,
        title_id: uuid.UUID,
        title_name: str,
        genre_tag: str | None,
        recommendation_status: str | None,
        cosine_similarity: float,
    ) -> None:
        self.title_id = title_id
        self.title_name = title_name
        self.genre_tag = genre_tag
        self.recommendation_status = recommendation_status
        self.cosine_similarity = cosine_similarity


class MetadataVectorRepository(BaseRepository[MetadataVector]):
    """Async access to the ``metadata_vectors`` table."""

    model = MetadataVector
    pk = MetadataVector.metadata_id

    async def list_for_title(
        self, title_id: uuid.UUID
    ) -> list[MetadataVector]:
        """Return all metadata vectors recorded for a title."""
        stmt = select(MetadataVector).where(
            MetadataVector.title_id == title_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_title_version(
        self, title_version_id: uuid.UUID
    ) -> MetadataVector | None:
        """Return the metadata vector tied to a specific title version (R24.3)."""
        stmt = select(MetadataVector).where(
            MetadataVector.title_version_id == title_version_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def rank_similar_titles(
        self,
        title_vector: list[float],
        exclude_title_id: uuid.UUID,
        limit: int = 3,
    ) -> list[SimilarTitle]:
        """Rank other titles by Narrative_DNA cosine similarity to ``title_vector``.

        Mirrors ``SubscriberClusterRepository.rank_by_similarity`` but ranks
        title-to-title instead of title-to-cohort: it computes cosine similarity
        as ``1 - (narrative_dna <=> title_vector)`` with pgvector's ``<=>``
        operator, joins ``titles`` for the display name/genre, excludes the query
        title itself, and returns the ``limit`` most similar neighbours
        (descending similarity / ascending distance).

        Each neighbour's latest recommendation is resolved with a correlated
        scalar subquery over ``financial_projections`` (newest row by
        ``created_at``), so a title with no computed valuation yet simply yields
        ``recommendation_status = None`` rather than being dropped.

        Args:
            title_vector: The query title's 1536-dim Narrative_DNA embedding.
            exclude_title_id: The query title's id, excluded from the results.
            limit: Maximum number of neighbours to return (default 3).

        Returns:
            ``SimilarTitle`` value objects ordered most-to-least similar. An empty
            list when no other title has a stored embedding.
        """
        distance = MetadataVector.narrative_dna.cosine_distance(title_vector)
        similarity = (1 - distance).label("cosine_similarity")

        latest_recommendation = (
            select(FinancialProjection.recommendation_status)
            .where(FinancialProjection.title_id == Title.title_id)
            .order_by(FinancialProjection.created_at.desc())
            .limit(1)
            .correlate(Title)
            .scalar_subquery()
            .label("recommendation_status")
        )

        # Order by the *computed* ``1 - distance`` similarity expression, not the
        # bare ``<=>`` distance. Ordering by the bare operator makes the planner
        # pick the IVFFlat ANN index, which at demo data volumes (a handful of
        # rows) has near-empty inverted lists and returns ZERO candidates for the
        # probed lists. Ordering by the derived expression forces an exact
        # sequential scan - correct exhaustive nearest-neighbour at this scale.
        #
        # A title can carry several metadata_vectors rows (re-extractions), so we
        # dedup to the single closest row per neighbour in Python before
        # truncating to ``limit``; the DB ``limit`` is widened to absorb
        # duplicates without a second round trip.
        stmt = (
            select(
                Title.title_id,
                Title.title_name,
                Title.genre_tag,
                latest_recommendation,
                similarity,
            )
            .join(Title, Title.title_id == MetadataVector.title_id)
            .where(MetadataVector.title_id != exclude_title_id)
            .order_by(similarity.desc())
            .limit(limit * 5)
        )
        result = await self.session.execute(stmt)
        seen: set[uuid.UUID] = set()
        comps: list[SimilarTitle] = []
        for row in result.all():
            neighbour_id = row[0]
            if neighbour_id in seen:
                continue
            seen.add(neighbour_id)
            comps.append(
                SimilarTitle(
                    title_id=neighbour_id,
                    title_name=row[1],
                    genre_tag=row[2],
                    recommendation_status=row[3],
                    cosine_similarity=float(row[4]),
                )
            )
            if len(comps) >= limit:
                break
        return comps