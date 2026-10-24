"""Repository for ``metadata_vectors`` (R17.2, R17.6).

Stores the extracted Narrative_DNA embedding and affective/pedigree scores for a
title. Foreign key on ``title_id`` enforces referential integrity (R17.2).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.financial_projection import FinancialProjection
from app.models.metadata_vector import MetadataVector
from app.models.title import Title
from app.repositories.base import BaseRepository

logger = get_logger(__name__)

# Default Budget_Band half-width: a candidate comp's normalized-USD cost must
# fall within [0.65 * cost, 1.35 * cost] (+/-35%) of the query title's cost
# (R1.2). Resolved in the seam (the band bounds are passed in already in USD).
BUDGET_BAND_LOW = Decimal("0.65")
BUDGET_BAND_HIGH = Decimal("1.35")

# Post-dedup truncation count over SUCCESS rows only (R1.3). The <k shrink and
# the zero-comp intercept fallback (R1.5) are decided by the pure comps module
# from the realized count this method returns.
COMPS_K = 5


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


class CompCandidate:
    """A budget-band comp retrieved for the Comps_Engine (Driver A).

    A plain value object carrying exactly what ``app.domain.comps`` needs to
    compute the empirical anchor: the comp's identity, the ascending pgvector
    cosine *distance* to the query title (so a smaller value is a closer comp,
    matching the ``(cosine, title_id asc)`` tie-break the pure module expects),
    its projected viewing hours (the ``H_comps`` source), and its latest
    churn-mitigation percentage (the ``C_comps`` source).

    ``comp_viewing_hours`` / ``comp_churn_pct`` are ``None`` when the underlying
    column is NULL (no projection yet, or no projected hours); the pure comps
    module skips a ``None`` entry per-metric rather than dropping the comp.
    """

    __slots__ = (
        "title_id",
        "title_name",
        "genre_tag",
        "cosine_distance",
        "comp_viewing_hours",
        "comp_churn_pct",
    )

    def __init__(
        self,
        title_id: uuid.UUID,
        title_name: str,
        genre_tag: str | None,
        cosine_distance: float,
        comp_viewing_hours: Decimal | None,
        comp_churn_pct: Decimal | None,
    ) -> None:
        self.title_id = title_id
        self.title_name = title_name
        self.genre_tag = genre_tag
        self.cosine_distance = cosine_distance
        self.comp_viewing_hours = comp_viewing_hours
        self.comp_churn_pct = comp_churn_pct


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

    async def rank_comps_within_band(
        self,
        query_vector: list[float],
        query_title_id: uuid.UUID,
        query_asset_type: str,
        cost_usd_low: Decimal,
        cost_usd_high: Decimal,
        normalize_cost: Callable[[Decimal, str], Awaitable[Decimal | None]],
        k: int = COMPS_K,
    ) -> list[CompCandidate]:
        """Retrieve the ``k`` nearest historical comps within the Budget_Band (R1.1-R1.6).

        The pgvector I/O seam for Driver A. Ranks historical titles by
        Narrative_DNA cosine *distance* to ``query_vector`` ascending (R1.1),
        restricted to historical titles of the same ``asset_type`` whose
        extraction succeeded (R1.2, R1.6), excluding the query title itself, and
        keeps only comps whose own normalized-USD cost falls inside the
        Budget_Band ``[cost_usd_low, cost_usd_high]`` (R1.2). It does **not**
        widen the band: it shrinks the realized ``k`` instead (the pure comps
        module decides the ``<k`` shrink / zero-comp intercept fallback from the
        count this returns, R1.5).

        Mirrors ``rank_similar_titles``' SUCCESS-only selection, correlated
        newest-``financial_projections``-row subquery, and dedup-to-closest-row
        patterns:

        - ``extraction_status = 'SUCCESS'`` excludes the FAILED zero-vector
          marker (``[0.0] * 1536``) and NULL markers, so a meaningless cosine
          distance can never enter the comp set and corrupt the anchor (R1.6).
          The realized ``k`` therefore counts SUCCESS rows only.
        - ``comp_viewing_hours`` = ``titles.projected_viewing_hours`` (the
          ``H_comps`` source); ``comp_churn_pct`` = the comp's newest
          ``financial_projections.churn_reduction_pct`` via a correlated
          scalar subquery (``ORDER BY created_at DESC LIMIT 1``), the only
          resolvable churn source (there is no churn column on ``titles``).
        - ``ORDER BY cos_dist ASC, title_id ASC`` is the deterministic
          tie-break equal-distance comps resolve by (R1.4), matching the
          ``(cosine, title_id asc)`` ordering ``app.domain.comps`` expects.
        - The DB ``LIMIT`` is widened to absorb duplicate vectors per title and
          band-excluded rows; dedup to the single closest SUCCESS row per title
          and the Budget_Band membership check run in Python, then the list is
          truncated to ``k``.

        Budget_Band normalization is an **async FX seam**: ``normalize_cost``
        converts a candidate's native ``(acquisition_cost_or_budget,
        native_currency)`` to normalized USD (the ``cost_usd_low`` /
        ``cost_usd_high`` bounds are already in USD). A candidate whose cost
        cannot be normalized (FX unavailable) is skipped and logged at WARNING,
        rather than being treated as in- or out-of-band; this is non-fatal (the
        caller falls back to the intercept when no comps survive).

        Args:
            query_vector: The query title's 1536-dim Narrative_DNA embedding.
            query_title_id: The query title's id, excluded from the results.
            query_asset_type: The query title's ``asset_type``; comps must match.
            cost_usd_low: Lower Budget_Band bound in normalized USD (inclusive).
            cost_usd_high: Upper Budget_Band bound in normalized USD (inclusive).
            normalize_cost: Async callable mapping ``(native_cost, currency)`` to
                a normalized-USD ``Decimal``, or ``None`` when FX is unavailable.
            k: Post-dedup truncation count over SUCCESS rows (default 5).

        Returns:
            ``CompCandidate`` value objects ordered closest-first (ascending
            cosine distance, ties by ascending ``title_id``), at most ``k``
            long. An empty list when no eligible comp exists (caller falls back
            to the DETERMINISTIC_FALLBACK intercept).
        """
        distance = MetadataVector.narrative_dna.cosine_distance(
            query_vector
        ).label("cos_dist")

        latest_churn = (
            select(FinancialProjection.churn_reduction_pct)
            .where(FinancialProjection.title_id == Title.title_id)
            .order_by(FinancialProjection.created_at.desc())
            .limit(1)
            .correlate(Title)
            .scalar_subquery()
            .label("comp_churn_pct")
        )

        # Order by the derived cosine-distance expression (not the bare ``<=>``)
        # so the planner does an exact sequential scan at demo data volumes,
        # where the IVFFlat ANN index returns zero candidates - same rationale
        # as ``rank_similar_titles``. The deterministic ``title_id ASC`` second
        # key gives the equal-distance tie-break the pure comps module relies on.
        stmt = (
            select(
                Title.title_id,
                Title.title_name,
                Title.genre_tag,
                Title.acquisition_cost_or_budget,
                Title.native_currency,
                Title.projected_viewing_hours,
                latest_churn,
                distance,
            )
            .join(Title, Title.title_id == MetadataVector.title_id)
            .where(
                Title.is_historical.is_(True),
                Title.title_id != query_title_id,
                Title.asset_type == query_asset_type,
                MetadataVector.extraction_status == "SUCCESS",
            )
            .order_by(distance.asc(), Title.title_id.asc())
            .limit(k * 5)
        )
        result = await self.session.execute(stmt)

        seen: set[uuid.UUID] = set()
        comps: list[CompCandidate] = []
        for row in result.all():
            comp_id = row[0]
            # Dedup multiple SUCCESS vectors per title to the single closest
            # row. Rows are already ordered by ascending distance, so the first
            # row seen for a title is its closest.
            if comp_id in seen:
                continue

            # Cost (and thus Budget_Band membership) is a per-title property, so
            # record the title as seen before the band / FX checks: every vector
            # row for this title shares the same cost and resolves the same way,
            # and marking it here avoids a redundant FX call on a duplicate.
            seen.add(comp_id)

            native_cost = row[3]
            native_currency = row[4]
            comp_cost_usd = await normalize_cost(native_cost, native_currency)
            if comp_cost_usd is None:
                logger.warning(
                    "comps.band.fx_unavailable",
                    title_id=str(comp_id),
                    native_currency=native_currency,
                )
                continue
            # Never widen the band: a candidate outside [low, high] is excluded.
            if comp_cost_usd < cost_usd_low or comp_cost_usd > cost_usd_high:
                continue

            comps.append(
                CompCandidate(
                    title_id=comp_id,
                    title_name=row[1],
                    genre_tag=row[2],
                    cosine_distance=float(row[7]),
                    comp_viewing_hours=row[5],
                    comp_churn_pct=row[6],
                )
            )
            if len(comps) >= k:
                break
        return comps