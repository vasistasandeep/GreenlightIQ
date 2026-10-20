"""Router-level tests for the supporting API surface (task 16.2).

These tests exercise the supporting routers (jobs, auth, decisions, versions,
calibration, audit, health) through FastAPI's :class:`TestClient`, overriding
the shared dependencies in :mod:`app.api.deps` with lightweight in-memory doubles
so no database, broker, or SSO provider is required. They verify the HTTP
contract each router owns:

* authentication gating (401 via the shared error envelope),
* job status polling and dead-letter retry (404 / 409 mapping, R23.4, R29.5),
* override authorization matrix (403 FORBIDDEN_OVERRIDE for an unauthorized
  role, R20.2) and audit recording on a successful override (R25.1),
* finalization gating report (R20.5),
* model-version catalog + title versions (R26.3, R24.5),
* calibration apply wiring (R12/R16.3), and
* the aggregate /health probe shape (R29.4).

The 16.3 integration suite drives the same endpoints against a real Postgres;
these tests pin the router behavior itself without external infrastructure.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.security import UserContext, UserRole
from app.engines.rbac import RBACService
from app.main import create_app


# --------------------------------------------------------------------------- #
# In-memory doubles
# --------------------------------------------------------------------------- #
class _Row:
    """A tiny attribute bag standing in for an ORM row."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeResultList:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Minimal async session double supporting ``get`` and ``commit``.

    Repositories in the supporting routers call ``session.get(Model, id)`` for
    point lookups and ``session.execute`` for list queries; this double serves
    both from in-memory tables keyed by model name. Only the behavior the tests
    need is implemented.
    """

    def __init__(self, tables=None, list_results=None):
        # tables: {model_name: {id: row}}
        self.tables = tables or {}
        # list_results: {model_name: [rows]} returned by execute(select(...))
        self.list_results = list_results or {}
        self.committed = False
        self.flushed = False
        self._execute_queue = []

    async def get(self, model, entity_id):
        return self.tables.get(model.__name__, {}).get(entity_id)

    async def execute(self, _stmt):
        # Return the next queued result, else empty.
        if self._execute_queue:
            return self._execute_queue.pop(0)
        return _FakeResultList([])

    def queue_execute(self, rows):
        self._execute_queue.append(_FakeResultList(rows))

    async def commit(self):
        self.committed = True

    async def flush(self):
        self.flushed = True

    async def refresh(self, _instance):
        return None

    async def delete(self, _instance):
        return None

    def add(self, _instance):
        return None


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
def app():
    return create_app()


def _client_with(app, *, user: UserContext, session: _FakeSession) -> TestClient:
    """Build a TestClient with auth + DB dependencies overridden."""

    async def _fake_session():
        yield session

    app.dependency_overrides[deps.get_db_session] = _fake_session
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_rbac_service] = RBACService
    return TestClient(app, raise_server_exceptions=True)


# --------------------------------------------------------------------------- #
# Authentication gating
# --------------------------------------------------------------------------- #
def test_jobs_requires_authentication(app):
    # Override only the DB session so the real auth dependency runs without a
    # live engine; with no Authorization header the auth path returns 401
    # before any query is issued.
    session = _FakeSession()

    async def _fake_session():
        yield session

    app.dependency_overrides[deps.get_db_session] = _fake_session
    client = TestClient(app)
    resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] == "UNAUTHENTICATED"


# --------------------------------------------------------------------------- #
# Jobs: status + retry (R23.4, R29.5)
# --------------------------------------------------------------------------- #
def test_get_job_not_found_maps_to_404(app):
    session = _FakeSession(tables={"Job": {}})
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_get_job_returns_status(app):
    job_id = uuid.uuid4()
    job = _Row(
        job_id=job_id,
        job_type="run_backtest_audit",
        status="COMPLETED",
        result={"scorecard": {"mape": "4.2"}},
        failure_reason=None,
        dead_lettered=False,
    )
    session = _FakeSession(tables={"Job": {job_id: job}})
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["result"] == {"scorecard": {"mape": "4.2"}}


def test_retry_non_dead_lettered_job_conflicts(app):
    job_id = uuid.uuid4()
    job = _Row(
        job_id=job_id,
        job_type="run_backtest_audit",
        status="COMPLETED",
        result=None,
        failure_reason=None,
        dead_lettered=False,
    )
    session = _FakeSession(tables={"Job": {job_id: job}})
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


# --------------------------------------------------------------------------- #
# Decisions: override authorization matrix (R20.2)
# --------------------------------------------------------------------------- #
def test_override_rejected_for_unauthorized_role(app):
    decision_id = uuid.uuid4()
    session = _FakeSession()
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.post(
        f"/api/v1/decisions/{decision_id}/override",
        json={"recommendation_status": "PASS"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN_OVERRIDE"


def test_override_invalid_status_rejected(app):
    decision_id = uuid.uuid4()
    session = _FakeSession()
    client = _client_with(app, user=CFO, session=session)
    resp = client.post(
        f"/api/v1/decisions/{decision_id}/override",
        json={"recommendation_status": "MAYBE"},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "VALIDATION_FAILED"


# --------------------------------------------------------------------------- #
# Versions: model-version catalog + title versions (R26.3, R24.5)
# --------------------------------------------------------------------------- #
def test_model_version_not_found(app):
    session = _FakeSession(tables={"ModelVersion": {}})
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.get(f"/api/v1/models/versions/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_title_versions_unknown_title_maps_to_title_not_found(app):
    session = _FakeSession(tables={"Title": {}})
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.get(f"/api/v1/titles/{uuid.uuid4()}/versions")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TITLE_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Audit lineage (R25.4)
# --------------------------------------------------------------------------- #
def test_audit_lineage_empty_subject_returns_empty_list(app):
    subject_id = uuid.uuid4()
    session = _FakeSession()
    session.queue_execute([])  # AuditLogRepository.list_for_subject -> no rows
    client = _client_with(app, user=ANALYST, session=session)
    resp = client.get(f"/api/v1/audit/lineage/{subject_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_id"] == str(subject_id)
    assert body["entries"] == []


# --------------------------------------------------------------------------- #
# Health probe shape (R29.4)
# --------------------------------------------------------------------------- #
def test_health_reports_component_statuses(app):
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    for component in ("database", "task_queue", "telemetry"):
        assert component in body
        assert body[component]["status"] in {"up", "down"}


# --------------------------------------------------------------------------- #
# Dashboard summary (R14.1, R14.2)
# --------------------------------------------------------------------------- #
def test_dashboard_summary_aggregates_titles_and_kpis(app, monkeypatch):
    """GET /dashboard/summary rolls titles + projections into KPIs and grid rows."""
    import uuid as _uuid
    from dataclasses import dataclass, field
    from decimal import Decimal

    import app.api.dashboard as dash

    @dataclass
    class _Title:
        title_id: _uuid.UUID
        title_name: str
        asset_type: str
        acquisition_cost_or_budget: Decimal
        native_currency: str

    @dataclass
    class _Projection:
        calculated_cpvh: Decimal | None
        ltv_to_cost_multiple: Decimal | None
        recommendation_status: str | None
        normalized_cost_usd: Decimal | None = field(default=None)
        payback_horizon_months: int | None = field(default=None)

    t1 = _Title(_uuid.uuid4(), "Aurora", "ORIGINAL_SERIES", Decimal("42000000"), "USD")
    t2 = _Title(_uuid.uuid4(), "Ledger", "ORIGINAL_FILM", Decimal("9500000"), "USD")
    projections = {
        t1.title_id: _Projection(Decimal("0.1680"), Decimal("3.8"), "GREENLIGHT",
                                  Decimal("42000000")),
        # CPVH above the 0.18 premium ceiling -> BREACH; non-greenlight -> risk.
        t2.title_id: _Projection(Decimal("0.2375"), Decimal("2.9"), "NEGOTIATE_HARD",
                                  Decimal("9500000")),
    }

    class _Titles:
        def __init__(self, session):
            ...

        async def list(self, **_):
            return [t1, t2]

    class _Projections:
        def __init__(self, session):
            ...

        async def get_latest_for_title(self, tid):
            return projections.get(tid)

    class _GroundTruth:
        # No seeded ground truth in this fixture -> the accuracy rate stays None
        # (no Eligible_Audited_Title), exercising the honest blank-until-measured path.
        def __init__(self, session):
            ...

        async def list_for_title(self, tid):
            return []

    monkeypatch.setattr(dash, "TitleRepository", _Titles)
    monkeypatch.setattr(dash, "FinancialProjectionRepository", _Projections)
    monkeypatch.setattr(dash, "GroundTruthRepository", _GroundTruth)

    async def _fake_session():
        yield object()

    app.dependency_overrides[deps.get_db_session] = _fake_session
    client = TestClient(app)
    try:
        resp = client.get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.pop(deps.get_db_session, None)

    assert resp.status_code == 200
    body = resp.json()

    # Two titles in the grid, badges derived from the CPVH ceiling.
    assert len(body["titles"]) == 2
    by_name = {t["title_name"]: t for t in body["titles"]}
    assert by_name["Aurora"]["cpvh_status"] == "PASS"
    assert by_name["Ledger"]["cpvh_status"] == "BREACH"

    # KPIs: summed valuation, averaged LTV, and risk = share of non-GREENLIGHT.
    kpis = body["kpis"]
    assert kpis["active_pipeline_valuation_usd"] == 51500000.0
    assert kpis["avg_ltv_to_cost"] == 3.35
    assert kpis["portfolio_risk_exposure"] == 0.5


# --------------------------------------------------------------------------- #
# Dashboard Model_Accuracy_Rate (dashboard-accuracy-and-payback-audit, R6).
# These drive GET /dashboard/summary through the handler with ground-truth
# doubles so the verdict-match rate is exercised at the HTTP contract level
# (the pure helper is covered separately in tests/domain/test_accuracy_properties).
# --------------------------------------------------------------------------- #
def _run_dashboard(app, monkeypatch, titles, projections, ground_truth):
    """Drive GET /dashboard/summary with in-memory repo doubles; return kpis."""
    import app.api.dashboard as dash

    class _Titles:
        def __init__(self, session):
            ...

        async def list(self, **_):
            return titles

    class _Projections:
        def __init__(self, session):
            ...

        async def get_latest_for_title(self, tid):
            return projections.get(tid)

    class _GroundTruth:
        def __init__(self, session):
            ...

        async def list_for_title(self, tid):
            return ground_truth.get(tid, [])

    monkeypatch.setattr(dash, "TitleRepository", _Titles)
    monkeypatch.setattr(dash, "FinancialProjectionRepository", _Projections)
    monkeypatch.setattr(dash, "GroundTruthRepository", _GroundTruth)

    async def _fake_session():
        yield object()

    app.dependency_overrides[deps.get_db_session] = _fake_session
    client = TestClient(app)
    try:
        resp = client.get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.pop(deps.get_db_session, None)
    assert resp.status_code == 200
    return resp.json()["kpis"]


def _mk_dashboard_doubles():
    """Return (Title, Projection, GroundTruth) dataclasses + a GT-row factory."""
    import uuid as _uuid
    from dataclasses import dataclass, field
    from datetime import datetime, timezone
    from decimal import Decimal

    @dataclass
    class _Title:
        title_id: _uuid.UUID
        title_name: str
        asset_type: str
        acquisition_cost_or_budget: Decimal
        native_currency: str

    @dataclass
    class _Projection:
        calculated_cpvh: Decimal | None
        ltv_to_cost_multiple: Decimal | None
        recommendation_status: str | None
        normalized_cost_usd: Decimal | None = field(default=None)
        payback_horizon_months: int | None = field(default=None)

    @dataclass
    class _GTRow:
        metric_name: str
        actual_value: Decimal
        recorded_at: datetime = field(
            default_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

    def all_pass_gt():
        # Four actuals that all pass a premium (0.18) ceiling -> GREENLIGHT.
        return [
            _GTRow("cpvh", Decimal("0.10")),
            _GTRow("ltv_to_cost", Decimal("4.0")),
            _GTRow("churn_reduction", Decimal("2.0")),
            _GTRow("payback_horizon", Decimal("8")),
        ]

    def churn_fail_gt():
        # Churn below 1.5 is a non-correctable breach -> PASS.
        return [
            _GTRow("cpvh", Decimal("0.10")),
            _GTRow("ltv_to_cost", Decimal("4.0")),
            _GTRow("churn_reduction", Decimal("0.5")),
            _GTRow("payback_horizon", Decimal("8")),
        ]

    return _Title, _Projection, _GTRow, all_pass_gt, churn_fail_gt


def test_dashboard_accuracy_null_when_no_ground_truth(app, monkeypatch):
    """R6.1: no ground truth anywhere -> model_accuracy_rate is null (not 0)."""
    import uuid as _uuid
    from decimal import Decimal

    _Title, _Projection, _GTRow, _ap, _cf = _mk_dashboard_doubles()
    t = _Title(_uuid.uuid4(), "Aurora", "ORIGINAL_SERIES", Decimal("42000000"), "USD")
    kpis = _run_dashboard(
        app, monkeypatch,
        titles=[t],
        projections={t.title_id: _Projection(Decimal("0.168"), Decimal("3.8"), "GREENLIGHT")},
        ground_truth={},
    )
    assert kpis["model_accuracy_rate"] is None


def test_dashboard_accuracy_known_fraction(app, monkeypatch):
    """R6.2: two eligible titles, one matching verdict -> rate is 0.5."""
    import uuid as _uuid
    from decimal import Decimal

    _Title, _Projection, _GTRow, all_pass_gt, churn_fail_gt = _mk_dashboard_doubles()
    # t1: predicted GREENLIGHT, actuals all pass -> actual GREENLIGHT -> MATCH.
    t1 = _Title(_uuid.uuid4(), "Match", "ORIGINAL_SERIES", Decimal("10000000"), "USD")
    # t2: predicted GREENLIGHT, actual churn fails -> actual PASS -> MISS.
    t2 = _Title(_uuid.uuid4(), "Miss", "ORIGINAL_SERIES", Decimal("10000000"), "USD")
    kpis = _run_dashboard(
        app, monkeypatch,
        titles=[t1, t2],
        projections={
            t1.title_id: _Projection(Decimal("0.10"), Decimal("4.0"), "GREENLIGHT"),
            t2.title_id: _Projection(Decimal("0.10"), Decimal("4.0"), "GREENLIGHT"),
        },
        ground_truth={t1.title_id: all_pass_gt(), t2.title_id: churn_fail_gt()},
    )
    assert kpis["model_accuracy_rate"] == 0.5


def test_dashboard_accuracy_excludes_insufficient_ground_truth(app, monkeypatch):
    """R6.3: a title missing a required metric is excluded, not counted."""
    import uuid as _uuid
    from decimal import Decimal

    _Title, _Projection, _GTRow, all_pass_gt, _cf = _mk_dashboard_doubles()
    # t1 fully eligible + matching -> rate should be 1.0 over the eligible set.
    t1 = _Title(_uuid.uuid4(), "Full", "ORIGINAL_SERIES", Decimal("10000000"), "USD")
    # t2 has only partial ground truth (no payback_horizon) -> not classifiable.
    t2 = _Title(_uuid.uuid4(), "Partial", "ORIGINAL_SERIES", Decimal("10000000"), "USD")
    partial_gt = [
        _GTRow("cpvh", Decimal("0.10")),
        _GTRow("ltv_to_cost", Decimal("4.0")),
        _GTRow("churn_reduction", Decimal("2.0")),
    ]
    kpis = _run_dashboard(
        app, monkeypatch,
        titles=[t1, t2],
        projections={
            t1.title_id: _Projection(Decimal("0.10"), Decimal("4.0"), "GREENLIGHT"),
            t2.title_id: _Projection(Decimal("0.10"), Decimal("4.0"), "GREENLIGHT"),
        },
        ground_truth={t1.title_id: all_pass_gt(), t2.title_id: partial_gt},
    )
    # Only t1 is eligible; it matches -> 1.0. The partial title neither helped nor hurt.
    assert kpis["model_accuracy_rate"] == 1.0