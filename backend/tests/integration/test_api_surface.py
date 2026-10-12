"""DB-backed integration tests for the REST API surface (task 16.3).

Where ``tests/api/test_core_routers.py`` and ``tests/api/test_support_routers.py``
pin each router's HTTP contract with *in-memory* fakes (task 16.1 / 16.2), this
module drives the same endpoints through FastAPI's :class:`TestClient` against a
**real** PostgreSQL 16 + pgvector database provisioned by ``conftest.py`` (via
testcontainers or an externally supplied ``CINEROI_DATABASE_URL`` /
``TEST_DATABASE_URL``). The whole module skips cleanly when no database is
available, matching the project's DB-dependent integration-test convention
(see ``test_optimistic_lock.py`` / ``test_auth_flows.py``).

The app's request-scoped DB dependency (:func:`app.core.db.get_db_session`) and
the health router's session factory (:func:`app.core.db.get_sessionmaker`) are
both repointed at a dedicated async engine bound to the *same migrated* database
the sync conftest fixture provisioned, so every request reads and writes the
exact production schema. Auth is overridden with a seeded
:class:`~app.core.security.UserContext` (no SSO/IdP needed) and the Task_Queue
dispatcher with a recording double (no broker needed) — the only two seams a
true end-to-end request would otherwise require external infrastructure for.

Surface exercised against real persistence (task 16.3):

* **202 dispatch + job polling (R23.2, R23.4).** ``POST /titles/ingest`` persists
  a real ``jobs`` row and returns ``202`` with its id; ``GET /jobs/{id}`` then
  reads that same row back and reports its status.
* **Partial-batch 200 (R23.4).** A completed ingest job carrying a mixed
  accepted/rejected summary is polled and returned ``200`` with the per-row
  rejection detail intact.
* **Valuation not-found mapping (R9.3, R10.3).** ``POST /valuation/calculate`` and
  ``GET /valuation/{title_id}`` map an unknown title to ``404 TITLE_NOT_FOUND``
  through the real repository lookups.
* **Approval gating (R20.5).** A high-budget GREENLIGHT decision reports it cannot
  be finalized via ``GET /decisions/{id}/finalization`` while executive sign-offs
  are outstanding; after a CCO and a CFO each record a real ``POST
  /decisions/{id}/approve`` act, the report flips to finalizable with no
  outstanding roles — the gate opening only once every required sign-off is
  persisted.
* **Conflict gating 409 (R29.5).** ``POST /jobs/{id}/retry`` on a job that is not
  dead-lettered is rejected ``409 CONFLICT`` so an operator cannot re-run a
  healthy job — a reachable conflict on the async-job surface.
* **Calibration-apply flow (R12/R16.3).** ``POST /calibration/apply`` audits a
  historical title against its persisted projection + ground truth and reports
  the calibration outcome, committing the unit of work.
* **Health reporting (R29.4).** ``GET /health`` reports per-component DB / queue /
  telemetry status with the live DB probe hitting the provisioned database.

Requirements: 9.3, 10.3, 20.5, 23.2, 23.4, 29.4
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import pytest

try:  # pragma: no cover - import guard; conftest skips when missing
    import psycopg  # noqa: F401

    _HAS_PSYCOPG = True
except Exception:  # pragma: no cover - import guard
    psycopg = None  # type: ignore[assignment]
    _HAS_PSYCOPG = False

try:  # pragma: no cover - import guard
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    _HAS_SQLALCHEMY_ASYNC = True
except Exception:  # pragma: no cover - import guard
    AsyncSession = None  # type: ignore[assignment,misc]
    async_sessionmaker = None  # type: ignore[assignment]
    create_async_engine = None  # type: ignore[assignment]
    _HAS_SQLALCHEMY_ASYNC = False

from fastapi.testclient import TestClient

from app.api import deps
from app.core import db as core_db
from app.core.security import UserContext, UserRole
from app.main import create_app
from app.models.financial_projection import FinancialProjection
from app.models.historical_ground_truth import HistoricalGroundTruth
from app.models.job import Job
from app.models.model_version import ModelVersion
from app.models.title import Title
from app.models.user import User

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# URL / engine fixtures (mirrors the other integration modules' conventions).
# --------------------------------------------------------------------------- #
def _psycopg_url_to_async_sqlalchemy(url: str) -> str:
    """Convert a raw psycopg/libpq URL into an async SQLAlchemy URL.

    The conftest ``postgres_url`` fixture yields a ``postgresql://...`` libpq
    string; SQLAlchemy's async engine needs the ``postgresql+psycopg://`` driver
    prefix (psycopg 3 supports async natively).
    """
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session", autouse=True)
def _configure_encryption_key() -> Iterator[None]:
    """Provision a Fernet key so encrypted columns round-trip through the DB.

    ``users.display_name`` is an :class:`~app.core.encryption.EncryptedString`
    (PII encrypted at rest, R28.1); the approval-gating scenario seeds executive
    users whose ``display_name`` must round-trip. Configure a real key for the
    test process and reset the cached settings/encryptor so the ciphertext
    round-trips through the real database (same approach as ``test_auth_flows``).
    """
    from cryptography.fernet import Fernet

    from app.core import encryption

    previous = os.environ.get("CINEROI_ENCRYPTION_KEY")
    os.environ["CINEROI_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")
    from app.core.config import get_settings

    get_settings.cache_clear()
    encryption._build_encryptor.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CINEROI_ENCRYPTION_KEY", None)
        else:
            os.environ["CINEROI_ENCRYPTION_KEY"] = previous
        get_settings.cache_clear()
        encryption._build_encryptor.cache_clear()


@pytest.fixture()
async def async_engine(postgres_url: str):
    """Yield a dedicated async engine bound to the provisioned test database."""
    if not _HAS_SQLALCHEMY_ASYNC:  # pragma: no cover - env guard
        pytest.skip("async SQLAlchemy is not available; cannot run async DB test")

    async_url = _psycopg_url_to_async_sqlalchemy(postgres_url)
    engine = create_async_engine(async_url, future=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
def session_factory(async_engine) -> "async_sessionmaker[AsyncSession]":
    """An async sessionmaker bound to the provisioned test database."""
    return async_sessionmaker(
        bind=async_engine, expire_on_commit=False, autoflush=False
    )


class _RecordingDispatcher:
    """A Task_Queue dispatcher double that records calls instead of enqueuing.

    A real request would hand the heavy per-row work to a Celery broker; the test
    asserts *that* a job was dispatched (and persisted) without a running worker.
    """

    def __init__(self) -> None:
        self.ingest_calls: list[tuple[uuid.UUID, bytes, str, str]] = []
        self.backtest_calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def dispatch_ingest(
        self,
        job_id: uuid.UUID,
        payload: bytes,
        content_type: str,
        idempotency_key: str,
    ) -> None:
        self.ingest_calls.append((job_id, payload, content_type, idempotency_key))

    def dispatch_backtest(self, job_id: uuid.UUID, title_id: uuid.UUID) -> None:
        self.backtest_calls.append((job_id, title_id))


ANALYST = UserContext(
    user_id=uuid.uuid4(),
    display_name="Ana Analyst",
    role=UserRole.DATA_ANALYST,
    authorized_territories=(),
)
CFO = UserContext(
    user_id=uuid.uuid4(),
    display_name="Fin Officer",
    role=UserRole.CFO,
    authorized_territories=(),
)


@pytest.fixture()
def dispatcher() -> _RecordingDispatcher:
    return _RecordingDispatcher()


@pytest.fixture()
def make_client(
    session_factory: "async_sessionmaker[AsyncSession]",
    async_engine,
    dispatcher: _RecordingDispatcher,
    monkeypatch: pytest.MonkeyPatch,
):
    """Return a factory building a TestClient wired to the real test database.

    Repoints both the request-scoped session dependency and the health router's
    process-global session factory at the provisioned engine, overrides auth with
    a seeded actor, and swaps the Task_Queue dispatcher for the recording double.
    The caller selects which :class:`UserContext` the request authenticates as.
    """
    # The health router calls app.core.db.get_sessionmaker() directly (not via a
    # dependency), so point the process-global factory at the test engine for the
    # live DB probe. Restored automatically by monkeypatch on teardown.
    monkeypatch.setattr(core_db, "get_sessionmaker", lambda: session_factory)

    def _build(user: UserContext = ANALYST) -> TestClient:
        app = create_app()

        async def _db_session() -> AsyncIterator["AsyncSession"]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[deps.get_db_session] = _db_session
        app.dependency_overrides[core_db.get_db_session] = _db_session
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_task_dispatcher] = lambda: dispatcher
        return TestClient(app, raise_server_exceptions=True)

    return _build


# --------------------------------------------------------------------------- #
# Seeding helpers (real rows in the provisioned database).
# --------------------------------------------------------------------------- #
async def _seed_active_model_version(
    factory: "async_sessionmaker[AsyncSession]",
) -> uuid.UUID:
    """Persist (deactivating any prior) a single active model version.

    Guardrail/calibration code resolves "the active model version" to stamp
    valuations and fork calibrated versions; the partial unique index allows only
    one active row, so deactivate any existing active version first.
    """
    from sqlalchemy import update

    async with factory() as session:
        await session.execute(
            update(ModelVersion)
            .where(ModelVersion.is_active.is_(True))
            .values(is_active=False)
        )
        mv = ModelVersion(
            talent_pedigree_weight=Decimal("0.50"),
            narrative_trope_weight=Decimal("0.50"),
            guardrail_params={"cpvh_floor": "0.18"},
            is_active=True,
        )
        session.add(mv)
        await session.commit()
        return mv.model_version_id


async def _seed_title(
    factory: "async_sessionmaker[AsyncSession]",
    *,
    is_historical: bool = False,
) -> uuid.UUID:
    """Persist a minimal valid ``titles`` row and return its id."""
    async with factory() as session:
        title = Title(
            title_name=f"API Surface Title {uuid.uuid4().hex[:8]}",
            asset_type="ORIGINAL_FILM",
            acquisition_cost_or_budget=Decimal("1000000.00"),
            native_currency="USD",
            target_territories=["US"],
            genre_tag="DRAMA",
            is_historical=is_historical,
        )
        session.add(title)
        await session.commit()
        return title.title_id


async def _seed_projection(
    factory: "async_sessionmaker[AsyncSession]",
    *,
    title_id: uuid.UUID,
    model_version_id: uuid.UUID,
    recommendation_status: str,
    normalized_cost_usd: Decimal,
    calculated_cpvh: Decimal | None = Decimal("0.0500"),
) -> uuid.UUID:
    """Persist a ``financial_projections`` row (the "decision") and return its id."""
    async with factory() as session:
        projection = FinancialProjection(
            title_id=title_id,
            model_version_id=model_version_id,
            calculated_cpvh=calculated_cpvh,
            ltv_to_cost_multiple=Decimal("3.5000"),
            churn_reduction_pct=Decimal("2.00"),
            payback_horizon_months=8,
            recommendation_status=recommendation_status,
            normalized_cost_usd=normalized_cost_usd,
            explanation={"checks": []},
        )
        session.add(projection)
        await session.commit()
        return projection.projection_id


async def _seed_user(
    factory: "async_sessionmaker[AsyncSession]", *, role: UserRole
) -> uuid.UUID:
    """Persist a ``users`` row with the given role; return its id."""
    async with factory() as session:
        user = User(
            external_subject=f"idp|{uuid.uuid4()}",
            display_name=f"{role.value} Exec",
            user_role=role.value,
            authorized_territories=[],
        )
        session.add(user)
        await session.commit()
        return user.user_id


# --------------------------------------------------------------------------- #
# R23.2 / R23.4 - 202 dispatch, then poll the persisted job.
# --------------------------------------------------------------------------- #
async def test_ingest_dispatches_202_and_job_is_pollable(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
    dispatcher: _RecordingDispatcher,
) -> None:
    """R23.2 + R23.4: ingest returns 202 with a persisted job id that polls back.

    ``POST /titles/ingest`` writes a real ``PENDING`` ``jobs`` row and dispatches
    the heavy work (recorded by the double), returning ``202`` with the job id.
    ``GET /jobs/{id}`` then reads that *same* persisted row back and reports its
    status — proving the dispatch handshake round-trips through the real DB.
    """
    client = make_client(ANALYST)

    resp = client.post(
        "/api/v1/titles/ingest",
        content=b"title_name,acquisition_cost_or_budget\nFoo,1000.00\n",
        headers={"Content-Type": "text/csv", "Idempotency-Key": f"k-{uuid.uuid4()}"},
    )
    assert resp.status_code == 202
    body = resp.json()
    job_id = uuid.UUID(body["job_id"])
    assert body["status"] == "PENDING"
    assert len(dispatcher.ingest_calls) == 1
    assert dispatcher.ingest_calls[0][0] == job_id

    # The job must be independently readable from the database.
    async with session_factory() as session:
        stored = await session.get(Job, job_id)
        assert stored is not None
        assert stored.job_type == "ingest_batch"
        assert stored.status == "PENDING"

    # And pollable through the API, reporting the persisted status (R23.4).
    poll = client.get(f"/api/v1/jobs/{job_id}")
    assert poll.status_code == 200
    polled = poll.json()
    assert polled["job_id"] == str(job_id)
    assert polled["status"] == "PENDING"


async def test_poll_unknown_job_maps_to_404(make_client) -> None:
    """R23.4: polling a job id with no row maps to the 404 envelope."""
    client = make_client(ANALYST)
    resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# R23.4 - partial-batch result surfaced on poll (200).
# --------------------------------------------------------------------------- #
async def test_poll_completed_partial_batch_returns_200_with_rejections(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R23.4: a completed mixed-outcome ingest job polls back 200 with its summary.

    Seeds a COMPLETED ingest ``jobs`` row whose ``result`` carries a partial batch
    (some accepted, some rejected). ``GET /jobs/{id}`` returns ``200`` and the
    stored accepted/rejected counts and the per-row rejection detail round-trip
    through JSONB unchanged.
    """
    async with session_factory() as session:
        job = Job(
            job_type="ingest_batch",
            status="COMPLETED",
            idempotency_key=f"partial-{uuid.uuid4()}",
            result={
                "accepted_count": 2,
                "rejected_count": 1,
                "rejections": [
                    {
                        "row_index": 3,
                        "field": "acquisition_cost_or_budget",
                        "reason": "acquisition_cost_or_budget is required.",
                    }
                ],
            },
        )
        session.add(job)
        await session.commit()
        job_id = job.job_id

    client = make_client(ANALYST)
    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["result"]["accepted_count"] == 2
    assert body["result"]["rejected_count"] == 1
    assert body["result"]["rejections"][0]["row_index"] == 3
    assert body["result"]["rejections"][0]["field"] == "acquisition_cost_or_budget"


# --------------------------------------------------------------------------- #
# R9.3 / R10.3 - valuation not-found mapping against the real repositories.
# --------------------------------------------------------------------------- #
async def test_calculate_valuation_unknown_title_maps_to_404(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R9.3: calculating a valuation for a nonexistent title maps to 404.

    An active model version is seeded so the engine wiring is complete; the
    unknown ``title_id`` fails the real title lookup inside the Guardrails_Engine
    and surfaces ``404 TITLE_NOT_FOUND`` through the envelope.
    """
    await _seed_active_model_version(session_factory)

    client = make_client(ANALYST)
    resp = client.post(
        "/api/v1/valuation/calculate",
        json={"title_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TITLE_NOT_FOUND"


async def test_get_valuation_unknown_title_maps_to_404(make_client) -> None:
    """R10.3: retrieving a scorecard for a nonexistent title maps to 404."""
    client = make_client(ANALYST)
    resp = client.get(f"/api/v1/valuation/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TITLE_NOT_FOUND"


async def test_get_valuation_title_without_projection_maps_to_404(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R10.3: a persisted title with no computed valuation still maps to 404.

    The title exists but has no ``financial_projections`` row yet, so the
    scorecard retrieval reports ``404 TITLE_NOT_FOUND`` — distinguishing "no
    title" from "no valuation" only in the message, both via the same envelope.
    """
    title_id = await _seed_title(session_factory)
    client = make_client(ANALYST)
    resp = client.get(f"/api/v1/valuation/{title_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TITLE_NOT_FOUND"


# --------------------------------------------------------------------------- #
# R20.5 - approval finalization gating (409 until sign-offs present).
# --------------------------------------------------------------------------- #
async def test_high_budget_finalization_gated_until_sign_offs_recorded(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R20.5: finalization gating flips from blocked to clear as sign-offs land.

    Seeds a GREENLIGHT decision whose normalized cost exceeds the high-budget
    threshold. ``GET /decisions/{id}/finalization`` first reports it cannot be
    finalized with both executive roles outstanding. A CCO then a CFO each record
    a real ``POST /decisions/{id}/approve`` act (authenticated as the seeded
    executive users whose roles the workflow resolves); the report flips to
    ``can_finalize = True`` with no outstanding roles only once *both* required
    sign-offs are persisted — proving the gate is enforced over real persistence.
    """
    model_version_id = await _seed_active_model_version(session_factory)
    title_id = await _seed_title(session_factory)
    decision_id = await _seed_projection(
        session_factory,
        title_id=title_id,
        model_version_id=model_version_id,
        recommendation_status="GREENLIGHT",
        normalized_cost_usd=Decimal("40000000.00"),  # > 25M threshold (R20.3)
    )

    # Executive principals whose user rows carry the roles the workflow resolves.
    cco_id = await _seed_user(session_factory, role=UserRole.CHIEF_CONTENT_OFFICER)
    cfo_id = await _seed_user(session_factory, role=UserRole.CFO)
    cco = UserContext(
        user_id=cco_id,
        display_name="Cora CCO",
        role=UserRole.CHIEF_CONTENT_OFFICER,
        authorized_territories=(),
    )
    cfo = UserContext(
        user_id=cfo_id,
        display_name="Fin CFO",
        role=UserRole.CFO,
        authorized_territories=(),
    )

    cfo_client = make_client(cfo)

    # Before any sign-off: gated, both executive roles outstanding (R20.5).
    report = cfo_client.get(f"/api/v1/decisions/{decision_id}/finalization")
    assert report.status_code == 200
    rbody = report.json()
    assert rbody["can_finalize"] is False
    assert set(rbody["outstanding_roles"]) == {"CHIEF_CONTENT_OFFICER", "CFO"}
    assert set(rbody["required_roles"]) == {"CHIEF_CONTENT_OFFICER", "CFO"}

    # First sign-off (CCO) recorded via the real approve endpoint (R20.4).
    cco_approve = make_client(cco).post(f"/api/v1/decisions/{decision_id}/approve")
    assert cco_approve.status_code == 200
    assert cco_approve.json()["action"] == "APPROVE"

    # Still gated: CFO sign-off outstanding (R20.5).
    partial = cfo_client.get(f"/api/v1/decisions/{decision_id}/finalization")
    assert partial.status_code == 200
    assert partial.json()["can_finalize"] is False
    assert partial.json()["outstanding_roles"] == ["CFO"]
    assert partial.json()["approved_roles"] == ["CHIEF_CONTENT_OFFICER"]

    # Second sign-off (CFO) recorded; the gate now opens (R20.5).
    cfo_approve = cfo_client.post(f"/api/v1/decisions/{decision_id}/approve")
    assert cfo_approve.status_code == 200

    cleared = cfo_client.get(f"/api/v1/decisions/{decision_id}/finalization")
    assert cleared.status_code == 200
    assert cleared.json()["can_finalize"] is True
    assert cleared.json()["outstanding_roles"] == []


async def test_approve_unknown_decision_maps_to_404(make_client) -> None:
    """R20.4/R20.5: an approve act against a nonexistent decision maps to 404."""
    client = make_client(CFO)
    resp = client.post(f"/api/v1/decisions/{uuid.uuid4()}/approve")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# R29.5 - conflict gating: retry of a non-dead-lettered job is 409.
# --------------------------------------------------------------------------- #
async def test_retry_non_dead_lettered_job_conflicts_409(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R29.5: retrying a job that is not dead-lettered is rejected 409 CONFLICT.

    Only a dead-lettered job may be re-dispatched; a healthy COMPLETED job polled
    from the real DB cannot be retried, so ``POST /jobs/{id}/retry`` maps to
    ``409 CONFLICT`` through the envelope — guarding against re-running good work.
    """
    async with session_factory() as session:
        job = Job(
            job_type="run_backtest_audit",
            status="COMPLETED",
            idempotency_key=f"healthy-{uuid.uuid4()}",
            dead_lettered=False,
        )
        session.add(job)
        await session.commit()
        job_id = job.job_id

    client = make_client(ANALYST)
    resp = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


# --------------------------------------------------------------------------- #
# R12 / R16.3 - calibration-apply flow against a real audit.
# --------------------------------------------------------------------------- #
async def test_calibration_apply_low_mape_reports_no_adjustment(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R12.5 / R16.3: calibration-apply audits a historical title and reports no change.

    Seeds a historical title with a persisted projection and matching ground
    truth whose actual equals the prediction (MAPE = 0%, within the 10%
    threshold). ``POST /calibration/apply`` runs the real audit → calibrate flow
    and reports ``adjustment_required = False`` with no new model version — the
    active weights left untouched (R12.5), exercising the full endpoint wiring and
    commit against the real database.
    """
    model_version_id = await _seed_active_model_version(session_factory)
    title_id = await _seed_title(session_factory, is_historical=True)
    await _seed_projection(
        session_factory,
        title_id=title_id,
        model_version_id=model_version_id,
        recommendation_status="GREENLIGHT",
        normalized_cost_usd=Decimal("1000000.00"),
        calculated_cpvh=Decimal("0.0500"),
    )
    # Ground truth whose actual matches the predicted CPVH -> MAPE 0%.
    async with session_factory() as session:
        session.add(
            HistoricalGroundTruth(
                title_id=title_id,
                metric_name="cpvh",
                actual_value=Decimal("0.0500"),
            )
        )
        await session.commit()

    client = make_client(CFO)
    resp = client.post(
        "/api/v1/calibration/apply",
        json={"title_id": str(title_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["adjustment_required"] is False
    assert body["new_model_version_id"] is None
    assert Decimal(str(body["mape"])) == Decimal("0.00")


async def test_calibration_apply_unauthorized_role_rejected(
    make_client,
    session_factory: "async_sessionmaker[AsyncSession]",
) -> None:
    """R20.1: a role outside the calibrate grant is rejected before any audit.

    CONTENT_BUYER is not permitted :class:`Operation.CALIBRATE`; the RBAC check
    runs first, so the request is rejected ``403`` through the envelope without
    touching the backtest/calibration flow.
    """
    buyer = UserContext(
        user_id=uuid.uuid4(),
        display_name="Bea Buyer",
        role=UserRole.CONTENT_BUYER,
        authorized_territories=(),
    )
    client = make_client(buyer)
    resp = client.post(
        "/api/v1/calibration/apply",
        json={"title_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] in {"FORBIDDEN", "FORBIDDEN_OVERRIDE"}


# --------------------------------------------------------------------------- #
# R29.4 - aggregate health probe with the live DB probe hitting the test DB.
# --------------------------------------------------------------------------- #
async def test_health_reports_component_statuses_with_live_db(make_client) -> None:
    """R29.4: /health reports per-component status with the DB probe up.

    With the health router's session factory pointed at the provisioned database,
    the DB probe's ``SELECT 1`` succeeds and ``database`` reports ``up``; the
    queue/telemetry components still report their own status independently and the
    top-level status is the aggregate (``ok`` iff all up).
    """
    client = make_client(ANALYST)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["database"]["status"] == "up"
    for component in ("database", "task_queue", "telemetry"):
        assert body[component]["status"] in {"up", "down"}
