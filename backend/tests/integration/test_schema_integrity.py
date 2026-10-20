"""Schema-integrity integration tests (task 2.4).

Verifies the shipped Alembic schema against a real PostgreSQL 16 + pgvector
instance:

* UUID primary keys are generated server-side (R17.1).
* Foreign keys on ``title_id`` are enforced (R17.2).
* ``asset_type`` / ``recommendation_status`` enum CHECKs and the
  ``acquisition_cost_or_budget`` range CHECK reject invalid values (R17.4,
  R17.5).
* ``metadata_vectors.narrative_dna`` stores and round-trips a VECTOR(1536)
  and rejects wrong-dimension vectors (R17.6).
* The exactly-one-active partial unique indexes on ``model_versions`` and
  ``title_versions`` are enforced (R24.4 / R26.1).
* The ``audit_log`` append-only trigger blocks UPDATE and DELETE (R25.2).

All tests are marked ``@pytest.mark.integration`` and skip cleanly when no
database is available (see ``conftest.py``).

Requirements: 17.1, 17.2, 17.4, 17.5, 17.6, 25.2
"""

from __future__ import annotations

import uuid

import pytest

try:  # pragma: no cover - import guard; conftest skips when missing
    import psycopg
    from psycopg import errors as pg_errors
    from psycopg.types.json import Json

    _HAS_PSYCOPG = True
except Exception:  # pragma: no cover - import guard
    psycopg = None  # type: ignore[assignment]
    pg_errors = None  # type: ignore[assignment]
    Json = None  # type: ignore[assignment]
    _HAS_PSYCOPG = False

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Helpers for seeding FK prerequisites.
# --------------------------------------------------------------------------- #
def _vector_literal(values: list[float]) -> str:
    """Render a pgvector literal (``[v1,v2,...]``) for raw SQL binding."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _insert_title(
    conn: "psycopg.Connection",
    *,
    asset_type: str = "ORIGINAL_FILM",
    acquisition_cost: str = "1000000.00",
    native_currency: str = "USD",
    territories: list[str] | None = None,
) -> uuid.UUID:
    """Insert a minimal valid ``titles`` row and return its generated id."""
    territories = territories if territories is not None else ["US"]
    row = conn.execute(
        """
        INSERT INTO titles
            (title_name, asset_type, acquisition_cost_or_budget,
             native_currency, target_territories)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING title_id
        """,
        ("Test Title", asset_type, acquisition_cost, native_currency,
         Json(territories)),
    ).fetchone()
    return row[0]


def _insert_model_version(conn: "psycopg.Connection", *, active: bool = False) -> uuid.UUID:
    """Insert a valid ``model_versions`` row (weights sum to 1.00)."""
    row = conn.execute(
        """
        INSERT INTO model_versions
            (talent_pedigree_weight, narrative_trope_weight,
             guardrail_params, is_active)
        VALUES (%s, %s, %s, %s)
        RETURNING model_version_id
        """,
        ("0.60", "0.40", Json({"cpvh_ceiling": 0.18}), active),
    ).fetchone()
    return row[0]


# --------------------------------------------------------------------------- #
# R17.1 - UUID primary keys
# --------------------------------------------------------------------------- #
def test_titles_uuid_primary_key_is_server_generated(conn: "psycopg.Connection") -> None:
    """R17.1: titles.title_id is a server-generated UUID primary key."""
    title_id = _insert_title(conn)
    assert isinstance(title_id, uuid.UUID)

    # Primary-key column type is ``uuid``.
    col_type = conn.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = 'titles' AND column_name = 'title_id'
        """
    ).fetchone()[0]
    assert col_type == "uuid"

    # And it is the declared primary key.
    pk = conn.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a
            ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = 'titles'::regclass AND i.indisprimary
        """
    ).fetchall()
    assert [r[0] for r in pk] == ["title_id"]


def test_distinct_rows_get_distinct_uuids(conn: "psycopg.Connection") -> None:
    """R17.1: each inserted row receives its own unique UUID."""
    first = _insert_title(conn)
    second = _insert_title(conn)
    assert first != second


# --------------------------------------------------------------------------- #
# R17.2 - foreign key enforcement on title_id
# --------------------------------------------------------------------------- #
def test_metadata_vectors_fk_rejects_unknown_title(conn: "psycopg.Connection") -> None:
    """R17.2: inserting a metadata_vectors row for a missing title fails."""
    bogus_title = uuid.uuid4()
    with pytest.raises(pg_errors.ForeignKeyViolation):
        conn.execute(
            """
            INSERT INTO metadata_vectors
                (title_id, narrative_dna, affective_primary, affective_secondary)
            VALUES (%s, %s, %s, %s)
            """,
            (bogus_title, _vector_literal([0.0] * 1536), "JOY", "AWE"),
        )
    conn.rollback()


def test_financial_projections_fk_rejects_unknown_title(conn: "psycopg.Connection") -> None:
    """R17.2: financial_projections requires an existing title_id."""
    model_version = _insert_model_version(conn)
    bogus_title = uuid.uuid4()
    with pytest.raises(pg_errors.ForeignKeyViolation):
        conn.execute(
            """
            INSERT INTO financial_projections (title_id, model_version_id)
            VALUES (%s, %s)
            """,
            (bogus_title, model_version),
        )
    conn.rollback()


def test_historical_ground_truth_fk_rejects_unknown_title(
    conn: "psycopg.Connection",
) -> None:
    """R17.2: historical_ground_truth requires an existing title_id."""
    bogus_title = uuid.uuid4()
    with pytest.raises(pg_errors.ForeignKeyViolation):
        conn.execute(
            """
            INSERT INTO historical_ground_truth (title_id, metric_name, actual_value)
            VALUES (%s, %s, %s)
            """,
            (bogus_title, "viewing_hours", "100"),
        )
    conn.rollback()


def test_fk_accepts_existing_title(conn: "psycopg.Connection") -> None:
    """R17.2: a child row with a valid title_id is accepted."""
    title_id = _insert_title(conn)
    conn.execute(
        """
        INSERT INTO metadata_vectors
            (title_id, narrative_dna, affective_primary, affective_secondary)
        VALUES (%s, %s, %s, %s)
        """,
        (title_id, _vector_literal([0.0] * 1536), "JOY", "AWE"),
    )
    count = conn.execute(
        "SELECT count(*) FROM metadata_vectors WHERE title_id = %s", (title_id,)
    ).fetchone()[0]
    assert count == 1
    conn.rollback()


# --------------------------------------------------------------------------- #
# R17.4 - asset_type enum CHECK + acquisition_cost range CHECK
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "asset_type",
    ["ORIGINAL_SERIES", "ORIGINAL_FILM", "LICENSED_LIBRARY", "CO_PRODUCTION"],
)
def test_asset_type_accepts_enumerated_values(
    conn: "psycopg.Connection", asset_type: str
) -> None:
    """R17.4: every value in the enumerated set is accepted."""
    title_id = _insert_title(conn, asset_type=asset_type)
    assert isinstance(title_id, uuid.UUID)
    conn.rollback()


def test_asset_type_rejects_unknown_value(conn: "psycopg.Connection") -> None:
    """R17.4: an off-enum asset_type violates the CHECK constraint."""
    with pytest.raises(pg_errors.CheckViolation):
        _insert_title(conn, asset_type="DOCUMENTARY")
    conn.rollback()


def test_acquisition_cost_rejects_zero(conn: "psycopg.Connection") -> None:
    """R17.4 (range CHECK): acquisition cost must be > 0 (>= 0.01)."""
    with pytest.raises(pg_errors.CheckViolation):
        _insert_title(conn, acquisition_cost="0.00")
    conn.rollback()


def test_acquisition_cost_rejects_above_upper_bound(conn: "psycopg.Connection") -> None:
    """R17.4 (range CHECK): acquisition cost above the ceiling is rejected."""
    with pytest.raises((pg_errors.CheckViolation, pg_errors.NumericValueOutOfRange)):
        _insert_title(conn, acquisition_cost="1000000000.00")
    conn.rollback()


def test_acquisition_cost_accepts_boundary(conn: "psycopg.Connection") -> None:
    """R17.4 (range CHECK): the exact lower boundary 0.01 is accepted."""
    title_id = _insert_title(conn, acquisition_cost="0.01")
    assert isinstance(title_id, uuid.UUID)
    conn.rollback()


# --------------------------------------------------------------------------- #
# R17.5 - recommendation_status enum CHECK
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "status", ["GREENLIGHT", "NEGOTIATE_HARD", "PASS"]
)
def test_recommendation_status_accepts_enumerated_values(
    conn: "psycopg.Connection", status: str
) -> None:
    """R17.5: each enumerated recommendation_status value is accepted."""
    title_id = _insert_title(conn)
    model_version = _insert_model_version(conn)
    conn.execute(
        """
        INSERT INTO financial_projections
            (title_id, model_version_id, recommendation_status)
        VALUES (%s, %s, %s)
        """,
        (title_id, model_version, status),
    )
    conn.rollback()


def test_recommendation_status_rejects_unknown_value(conn: "psycopg.Connection") -> None:
    """R17.5: an off-enum recommendation_status violates the CHECK."""
    title_id = _insert_title(conn)
    model_version = _insert_model_version(conn)
    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(
            """
            INSERT INTO financial_projections
                (title_id, model_version_id, recommendation_status)
            VALUES (%s, %s, %s)
            """,
            (title_id, model_version, "MAYBE"),
        )
    conn.rollback()


# --------------------------------------------------------------------------- #
# R17.6 - VECTOR(1536) storage
# --------------------------------------------------------------------------- #
def test_pgvector_extension_enabled(conn: "psycopg.Connection") -> None:
    """R17.6: the pgvector extension is installed."""
    row = conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    assert row is not None


def test_narrative_dna_stores_and_roundtrips_1536_dims(
    conn: "psycopg.Connection",
) -> None:
    """R17.6: a 1536-dim vector is stored and read back with full dimensionality."""
    title_id = _insert_title(conn)
    values = [round(i / 1536, 6) for i in range(1536)]
    conn.execute(
        """
        INSERT INTO metadata_vectors
            (title_id, narrative_dna, affective_primary, affective_secondary)
        VALUES (%s, %s, %s, %s)
        """,
        (title_id, _vector_literal(values), "JOY", "AWE"),
    )
    stored = conn.execute(
        """
        SELECT vector_dims(narrative_dna)
        FROM metadata_vectors WHERE title_id = %s
        """,
        (title_id,),
    ).fetchone()[0]
    assert stored == 1536
    conn.rollback()


def test_narrative_dna_rejects_wrong_dimension(conn: "psycopg.Connection") -> None:
    """R17.6: a vector with the wrong dimension count is rejected."""
    title_id = _insert_title(conn)
    with pytest.raises(psycopg.errors.DataError):
        conn.execute(
            """
            INSERT INTO metadata_vectors
                (title_id, narrative_dna, affective_primary, affective_secondary)
            VALUES (%s, %s, %s, %s)
            """,
            (title_id, _vector_literal([0.1, 0.2, 0.3]), "JOY", "AWE"),
        )
    conn.rollback()


# --------------------------------------------------------------------------- #
# Exactly-one-active partial unique indexes (R26.1 / R24.4)
# --------------------------------------------------------------------------- #
def test_model_versions_allows_single_active(conn: "psycopg.Connection") -> None:
    """One active model version is permitted; many inactive ones coexist."""
    # Neutralize any pre-existing active row (seed/migration or a prior committing
    # test) inside this test's own transaction, which is rolled back at the end,
    # so the global one-active partial-unique index reflects only this test.
    conn.execute("UPDATE model_versions SET is_active = FALSE WHERE is_active")
    mv_active = _insert_model_version(conn, active=True)
    mv_i1 = _insert_model_version(conn, active=False)
    mv_i2 = _insert_model_version(conn, active=False)
    # Scope the assertion to the rows THIS test created so pre-existing active
    # rows (migration/seed or a prior committing test) do not perturb the count.
    active_count = conn.execute(
        "SELECT count(*) FROM model_versions "
        "WHERE is_active AND model_version_id = ANY(%s)",
        ([mv_active, mv_i1, mv_i2],),
    ).fetchone()[0]
    assert active_count == 1
    conn.rollback()


def test_model_versions_rejects_two_active(conn: "psycopg.Connection") -> None:
    """The partial unique index blocks a second active model version."""
    conn.execute("UPDATE model_versions SET is_active = FALSE WHERE is_active")
    _insert_model_version(conn, active=True)
    with pytest.raises(pg_errors.UniqueViolation):
        _insert_model_version(conn, active=True)
    conn.rollback()


def test_title_versions_rejects_two_active_per_title(
    conn: "psycopg.Connection",
) -> None:
    """The partial unique index blocks two active versions of one title."""
    title_id = _insert_title(conn)
    conn.execute(
        """
        INSERT INTO title_versions
            (title_id, version_number, source_snapshot, is_active)
        VALUES (%s, %s, %s, %s)
        """,
        (title_id, 1, Json({"v": 1}), True),
    )
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(
            """
            INSERT INTO title_versions
                (title_id, version_number, source_snapshot, is_active)
            VALUES (%s, %s, %s, %s)
            """,
            (title_id, 2, Json({"v": 2}), True),
        )
    conn.rollback()


def test_title_versions_allows_active_per_distinct_title(
    conn: "psycopg.Connection",
) -> None:
    """Each distinct title may independently have one active version."""
    title_a = _insert_title(conn)
    title_b = _insert_title(conn)
    for title_id in (title_a, title_b):
        conn.execute(
            """
            INSERT INTO title_versions
                (title_id, version_number, source_snapshot, is_active)
            VALUES (%s, %s, %s, %s)
            """,
            (title_id, 1, Json({"v": 1}), True),
        )
    active_count = conn.execute(
        "SELECT count(*) FROM title_versions "
        "WHERE is_active AND title_id = ANY(%s)",
        ([title_a, title_b],),
    ).fetchone()[0]
    assert active_count == 2
    conn.rollback()


# --------------------------------------------------------------------------- #
# R25.2 - audit_log append-only trigger (UPDATE / DELETE blocked)
# --------------------------------------------------------------------------- #
def _insert_audit_entry(conn: "psycopg.Connection") -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO audit_log (subject_id, action, before_value, after_value)
        VALUES (%s, %s, %s, %s)
        RETURNING audit_id
        """,
        (uuid.uuid4(), "VALUATION", Json({"x": 1}), Json({"x": 2})),
    ).fetchone()
    return row[0]


def test_audit_log_insert_is_allowed(conn: "psycopg.Connection") -> None:
    """R25.2: appending (INSERT) to the audit log is permitted."""
    audit_id = _insert_audit_entry(conn)
    assert isinstance(audit_id, uuid.UUID)
    conn.rollback()


def test_audit_log_update_is_blocked(conn: "psycopg.Connection") -> None:
    """R25.2: the append-only trigger blocks UPDATE on audit_log."""
    audit_id = _insert_audit_entry(conn)
    with pytest.raises(pg_errors.RaiseException):
        conn.execute(
            "UPDATE audit_log SET action = %s WHERE audit_id = %s",
            ("TAMPERED", audit_id),
        )
    conn.rollback()


def test_audit_log_delete_is_blocked(conn: "psycopg.Connection") -> None:
    """R25.2: the append-only trigger blocks DELETE on audit_log."""
    audit_id = _insert_audit_entry(conn)
    with pytest.raises(pg_errors.RaiseException):
        conn.execute("DELETE FROM audit_log WHERE audit_id = %s", (audit_id,))
    conn.rollback()
