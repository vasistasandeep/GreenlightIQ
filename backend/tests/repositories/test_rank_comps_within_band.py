"""DB-less unit tests for ``MetadataVectorRepository.rank_comps_within_band``.

The budget-band comps retrieval is the pgvector I/O seam for Driver A
(advanced-content-eval-drivers, R1.1-R1.6). These tests run without a database:
a fake session compiles the statement (so the SQL stays valid) and returns
canned rows in the deterministic ``(cos_dist ASC, title_id ASC)`` order the real
query emits, letting us assert the Python-side behaviour of the method - the
Budget_Band membership check via the async FX seam, the SUCCESS-only /
historical / asset-type filtering (modelled by which rows the query returns),
dedup to the closest row per title, the normalized-USD band, and the ``k``
truncation - independently of Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects import postgresql

from app.repositories.metadata_vectors import (
    COMPS_K,
    CompCandidate,
    MetadataVectorRepository,
)


class _FakeResult:
    """Mimics the subset of a SQLAlchemy Result the method reads: ``all()``."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeSession:
    """Captures and compiles the statement, then returns canned rows.

    Compiling against the Postgres dialect forces the WHERE / ORDER BY / LIMIT
    and the pgvector cosine-distance expression to render, so a malformed query
    is caught here rather than only against a live database.
    """

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.compiled_sql: str | None = None

    async def execute(self, stmt: Any) -> _FakeResult:
        self.compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))
        return _FakeResult(self._rows)


def _row(
    title_id: uuid.UUID,
    *,
    name: str,
    genre: str | None,
    native_cost: Decimal,
    currency: str,
    hours: Decimal | None,
    churn: Decimal | None,
    cos_dist: float,
) -> tuple[Any, ...]:
    """Build a row shaped like the method's SELECT column list."""
    return (
        title_id,
        name,
        genre,
        native_cost,
        currency,
        hours,
        churn,
        cos_dist,
    )


def _usd_identity() -> Any:
    """An FX seam that treats every native cost as already-USD (rate 1.0)."""

    async def normalize(cost: Decimal, currency: str) -> Decimal | None:
        return cost

    return normalize


# Deterministic ids: ordering ``title_id ASC`` is exercised by the equal-distance
# tie-break test, so the literal byte ordering of these UUIDs matters there.
ID_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ID_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
ID_C = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
ID_D = uuid.UUID("00000000-0000-0000-0000-0000000000d4")
ID_E = uuid.UUID("00000000-0000-0000-0000-0000000000e5")
ID_F = uuid.UUID("00000000-0000-0000-0000-0000000000f6")
QUERY_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")


async def test_returns_in_band_comps_in_distance_order() -> None:
    """In-band comps come back closest-first with their H/C anchor sources."""
    rows = [
        _row(ID_A, name="A", genre="Drama", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.80"),
             cos_dist=0.10),
        _row(ID_B, name="B", genre="Drama", native_cost=Decimal("120"),
             currency="USD", hours=Decimal("2500.00"), churn=Decimal("2.10"),
             cos_dist=0.25),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert [c.title_id for c in comps] == [ID_A, ID_B]
    assert all(isinstance(c, CompCandidate) for c in comps)
    assert comps[0].comp_viewing_hours == Decimal("2000.00")
    assert comps[0].comp_churn_pct == Decimal("1.80")
    assert comps[0].cosine_distance == 0.10
    # Closest-first: distances are non-decreasing.
    assert comps[0].cosine_distance <= comps[1].cosine_distance


async def test_compiled_sql_has_band_asset_historical_success_filters() -> None:
    """The emitted SQL carries the SUCCESS / historical / asset-type filters."""
    session = _FakeSession([])
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_SERIES",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    sql = (session.compiled_sql or "").lower()
    assert "is_historical" in sql
    assert "asset_type" in sql
    assert "extraction_status" in sql
    assert "financial_projections" in sql  # the correlated churn subquery
    assert "projected_viewing_hours" in sql
    # Deterministic tie-break ordering: distance first, then title_id.
    assert "order by" in sql
    assert "title_id" in sql


async def test_out_of_band_candidates_are_excluded_not_widened() -> None:
    """A comp whose normalized-USD cost is outside the band is dropped.

    The band is never widened to backfill: an out-of-band candidate is simply
    excluded, shrinking the realized set.
    """
    rows = [
        _row(ID_A, name="TooCheap", genre="Drama", native_cost=Decimal("50"),
             currency="USD", hours=Decimal("1000.00"), churn=Decimal("1.00"),
             cos_dist=0.05),
        _row(ID_B, name="InBand", genre="Drama", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.10),
        _row(ID_C, name="TooDear", genre="Drama", native_cost=Decimal("200"),
             currency="USD", hours=Decimal("3000.00"), churn=Decimal("2.00"),
             cos_dist=0.20),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert [c.title_id for c in comps] == [ID_B]


async def test_normalized_usd_band_from_fx_seam() -> None:
    """Band membership uses the normalized-USD cost from the FX seam.

    A candidate priced at 9000 INR is out-of-band on its native number but
    in-band once normalized at 0.012 USD/INR (= 108 USD) within [65, 135].
    """
    rows = [
        _row(ID_A, name="InrComp", genre="Drama", native_cost=Decimal("9000"),
             currency="INR", hours=Decimal("2200.00"), churn=Decimal("1.90"),
             cos_dist=0.08),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    async def fx(cost: Decimal, currency: str) -> Decimal | None:
        rate = Decimal("0.012") if currency == "INR" else Decimal("1")
        return cost * rate

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=fx,
    )

    assert [c.title_id for c in comps] == [ID_A]
    assert comps[0].comp_viewing_hours == Decimal("2200.00")


async def test_fx_unavailable_candidate_is_skipped_non_fatal() -> None:
    """A candidate whose cost cannot be normalized is skipped, not fatal."""
    rows = [
        _row(ID_A, name="NoRate", genre="Drama", native_cost=Decimal("100"),
             currency="XYZ", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.05),
        _row(ID_B, name="InBand", genre="Drama", native_cost=Decimal("110"),
             currency="USD", hours=Decimal("2100.00"), churn=Decimal("1.70"),
             cos_dist=0.12),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    async def fx(cost: Decimal, currency: str) -> Decimal | None:
        return None if currency == "XYZ" else cost

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=fx,
    )

    assert [c.title_id for c in comps] == [ID_B]


async def test_dedups_multiple_vectors_to_closest_row_per_title() -> None:
    """Several SUCCESS vectors for one title collapse to its closest row.

    Rows arrive ordered by ascending distance, so the first row seen for a title
    is its closest; later duplicate rows for the same title are ignored.
    """
    rows = [
        _row(ID_A, name="A", genre="Drama", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.80"),
             cos_dist=0.10),
        _row(ID_A, name="A", genre="Drama", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.80"),
             cos_dist=0.40),
        _row(ID_B, name="B", genre="Drama", native_cost=Decimal("120"),
             currency="USD", hours=Decimal("2500.00"), churn=Decimal("2.10"),
             cos_dist=0.30),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert [c.title_id for c in comps] == [ID_A, ID_B]
    # The kept A row is the closest (0.10), not the later duplicate (0.40).
    assert comps[0].cosine_distance == 0.10


async def test_truncates_to_k() -> None:
    """At most ``k`` comps are returned even when more are in-band."""
    rows = [
        _row(ID_A, name="A", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.01),
        _row(ID_B, name="B", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.02),
        _row(ID_C, name="C", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.03),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
        k=2,
    )

    assert len(comps) == 2
    assert [c.title_id for c in comps] == [ID_A, ID_B]


async def test_equal_distance_ties_preserve_query_order() -> None:
    """Equal-distance comps are returned in the query's ``title_id ASC`` order.

    The DB applies the ``cos_dist ASC, title_id ASC`` tie-break; the method
    preserves that order, so equal-distance comps come back by ascending id.
    """
    rows = [
        _row(ID_A, name="A", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.20),
        _row(ID_B, name="B", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=Decimal("2000.00"), churn=Decimal("1.50"),
             cos_dist=0.20),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert [c.title_id for c in comps] == [ID_A, ID_B]


async def test_zero_comps_when_none_in_band() -> None:
    """No in-band comp yields an empty list (caller falls back to intercept)."""
    rows = [
        _row(ID_A, name="TooDear", genre="D", native_cost=Decimal("500"),
             currency="USD", hours=Decimal("4000.00"), churn=Decimal("2.50"),
             cos_dist=0.05),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert comps == []


async def test_default_k_is_five() -> None:
    """The default post-dedup truncation count is 5 (R1.3)."""
    assert COMPS_K == 5


async def test_null_hours_and_churn_pass_through_as_none() -> None:
    """A NULL projected-hours / churn column surfaces as ``None`` (skip rule).

    The comp is still returned - the pure comps module skips a ``None`` entry
    per-metric rather than dropping the comp from the set.
    """
    rows = [
        _row(ID_A, name="NoProjection", genre="D", native_cost=Decimal("100"),
             currency="USD", hours=None, churn=None, cos_dist=0.05),
    ]
    session = _FakeSession(rows)
    repo = MetadataVectorRepository(session)  # type: ignore[arg-type]

    comps = await repo.rank_comps_within_band(
        query_vector=[0.0] * 4,
        query_title_id=QUERY_ID,
        query_asset_type="ORIGINAL_FILM",
        cost_usd_low=Decimal("65"),
        cost_usd_high=Decimal("135"),
        normalize_cost=_usd_identity(),
    )

    assert len(comps) == 1
    assert comps[0].comp_viewing_hours is None
    assert comps[0].comp_churn_pct is None
