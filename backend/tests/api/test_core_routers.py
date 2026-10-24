"""Integration tests for the core REST API routers (task 16.1).

These tests exercise the full HTTP surface of the documented core endpoints via
FastAPI's :class:`~starlette.testclient.TestClient`, with the auth / RBAC and the
engine/dispatch dependencies overridden by in-memory fakes. They verify, through
real routing and the shared error-envelope handlers:

* ``POST /titles/ingest`` returns ``202`` with a ``job_id``, honors the
  idempotency header, and rejects unsupported formats (415) and oversized CSVs
  (422) through the envelope (R1, R23.2, R27.1).
* ``POST /valuation/calculate`` returns the recommendation + explanation and maps
  a missing title to ``404`` (R9.2, R9.3, R30.4).
* ``GET /valuation/{title_id}`` returns the full scorecard and maps missing data
  to ``404`` (R10, R10.3).
* ``POST /backtest/audit`` returns the audit scorecard (R11.6).
* ``GET /market/telemetry`` returns the cached snapshot (R13.3).
* Unauthenticated requests are rejected with the ``401`` envelope (R19.3).
* RBAC denies an under-privileged role with the ``403`` envelope (R20).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.errors import TitleNotFoundError
from app.core.security import UserContext, UserRole
from app.domain.churn import ChurnContribution, ChurnResult
from app.main import create_app


# A small CALCULATED churn detail used by the FakeGuardrailsEngine canned result
# so POST /valuation/calculate can surface a churn_model object (R7.3). The
# breakdown carries the six feature keys plus a bounds-adjustment entry; the keys
# and points mirror the domain's calculate_churn_mitigation output shape.
def _canned_churn_detail() -> ChurnResult:
    breakdown = (
        ChurnContribution("base_platform_rate", "Base Platform Rate", None, None, Decimal("0.15")),
        ChurnContribution("asset_cadence", "Asset Cadence", Decimal("0.35"), None, Decimal("0.35")),
        ChurnContribution(
            "talent_pedigree_contribution",
            "Talent Pedigree Contribution",
            Decimal("8.50"),
            Decimal("0.09"),
            Decimal("0.77"),
        ),
        ChurnContribution(
            "production_scale_contribution",
            "Production Scale Contribution",
            Decimal("9.00"),
            Decimal("0.03"),
            Decimal("0.27"),
        ),
        ChurnContribution(
            "exclusivity_lift", "Exclusivity Lift", Decimal("1"), Decimal("0.25"), Decimal("0.25")
        ),
        ChurnContribution(
            "market_telemetry_heat",
            "Market Telemetry Heat",
            Decimal("65.00"),
            Decimal("0.005"),
            Decimal("0.33"),
        ),
    )
    return ChurnResult(
        churn_reduction_pct=Decimal("2.00"),
        method="CALCULATED",
        is_borderline=False,
        breakdown=breakdown,
        missing_features=(),
        params_source="MODEL_VERSION",
        unclamped=Decimal("2.12"),
    )


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _analyst() -> UserContext:
    return UserContext(
        user_id=uuid.uuid4(),
        display_name="Test Analyst",
        role=UserRole.DATA_ANALYST,
        authorized_territories=(),
    )


class FakeDispatcher:
    """Records dispatched tasks instead of enqueuing them on a broker."""

    def __init__(self) -> None:
        self.ingest_calls: list[tuple[uuid.UUID, bytes, str, str]] = []
        self.backtest_calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def dispatch_ingest(
        self, job_id: uuid.UUID, payload: bytes, content_type: str, idempotency_key: str
    ) -> None:
        self.ingest_calls.append((job_id, payload, content_type, idempotency_key))

    def dispatch_backtest(self, job_id: uuid.UUID, title_id: uuid.UUID) -> None:
        self.backtest_calls.append((job_id, title_id))


@dataclass
class FakeJob:
    job_id: uuid.UUID
    job_type: str
    status: str
    idempotency_key: str | None = None
    requested_by: uuid.UUID | None = None
    result: dict | None = None


class FakeJobRepository:
    """In-memory ``jobs`` repository keyed by idempotency key."""

    def __init__(self) -> None:
        self.by_key: dict[str, FakeJob] = {}
        self.created: list[FakeJob] = []

    async def get_by_idempotency_key(self, idempotency_key: str) -> FakeJob | None:
        return self.by_key.get(idempotency_key)

    async def create(self, job: Any) -> Any:
        job.job_id = job.job_id or uuid.uuid4()
        self.created.append(job)
        if job.idempotency_key:
            self.by_key[job.idempotency_key] = job
        return job


class FakeSession:
    """A no-op async session; engines are overridden so it is never queried."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeGuardrailsEngine:
    """Returns a canned valuation result or raises TitleNotFoundError."""

    def __init__(self, *, known_title: uuid.UUID | None = None) -> None:
        self._known = known_title

    async def evaluate(
        self, title_id: uuid.UUID, model_version_id: Any = None, *, actor: Any = None
    ) -> dict[str, Any]:
        if self._known is not None and title_id != self._known:
            raise TitleNotFoundError(
                "no title", details={"title_id": str(title_id)}
            )
        return {
            "title_id": title_id,
            "calculated_cpvh": Decimal("0.0400"),
            "ltv_to_cost_multiple": Decimal("3.5000"),
            "churn_reduction_pct": Decimal("2.00"),
            "payback_horizon_months": 8,
            "recommendation_status": "GREENLIGHT",
            "normalized_cost_usd": Decimal("1000.00"),
            "exchange_rate_id": None,
            "model_version_id": uuid.uuid4(),
            "explanation": {
                "checks": [
                    {
                        "name": "CPVH",
                        "computed_value": Decimal("0.0400"),
                        "threshold": Decimal("0.18"),
                        "passed": True,
                        "breached": False,
                        "shortfall_magnitude": None,
                        "correctable": None,
                    }
                ],
                "dominant_factor": None,
                "unclassifiable": False,
            },
            # calculable-churn-model (R7.3): the resolved churn detail the
            # calculate route serializes into explanation["churn_model"]. The
            # in-memory explanation above intentionally omits churn_model (the
            # engine attaches it only on the persist path), so the route must
            # derive it from this.
            "churn_detail": _canned_churn_detail(),
        }


class _FakeSession:
    """Minimal session stub exposing the commit() the audit handler calls."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeBacktestingModule:
    def __init__(self) -> None:
        self.persisted: list[dict] = []
        # The audit handler commits the persisted ground truth through the
        # module's session; mirror the real module's attribute here.
        self.session = _FakeSession()

    async def persist_ground_truth(self, record: dict) -> uuid.UUID:
        self.persisted.append(record)
        return record["title_id"]

    async def audit(self, title_id: uuid.UUID) -> dict[str, Any]:
        return {
            "title_id": title_id,
            "metrics": [
                {
                    "metric": "cpvh",
                    "predicted": Decimal("0.0400"),
                    "actual": Decimal("0.0500"),
                    "excluded": False,
                }
            ],
            "mape": Decimal("25.00"),
            "no_eligible_metrics": False,
        }


@dataclass
class FakeSnapshot:
    genre_tag: str
    territory: str
    social_sentiment_index: Decimal | None = Decimal("1.20")
    chart_velocity_score: Decimal | None = Decimal("0.80")
    licensing_inflation_multiplier: Decimal | None = Decimal("1.05")
    source_available: bool = True
    found: bool = True


class FakeTelemetryConnector:
    async def get_telemetry(self, genre: str, territory: str) -> FakeSnapshot:
        return FakeSnapshot(genre_tag=genre, territory=territory)


# --------------------------------------------------------------------------- #
# App + client fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


@pytest.fixture()
def guardrails() -> FakeGuardrailsEngine:
    return FakeGuardrailsEngine()


@pytest.fixture()
def backtesting() -> FakeBacktestingModule:
    return FakeBacktestingModule()


@pytest.fixture()
def jobs_repo() -> FakeJobRepository:
    return FakeJobRepository()


@pytest.fixture()
def client(
    dispatcher: FakeDispatcher,
    guardrails: FakeGuardrailsEngine,
    backtesting: FakeBacktestingModule,
    jobs_repo: FakeJobRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    app = create_app()

    # Authenticated as a DATA_ANALYST by default (satisfies INGEST/VALUATION).
    app.dependency_overrides[deps.get_current_user] = _analyst
    app.dependency_overrides[deps.get_db_session] = lambda: FakeSession()
    app.dependency_overrides[deps.get_task_dispatcher] = lambda: dispatcher
    app.dependency_overrides[deps.get_guardrails_engine] = lambda: guardrails
    app.dependency_overrides[deps.get_backtesting_module] = lambda: backtesting
    app.dependency_overrides[deps.get_telemetry_connector] = (
        lambda: FakeTelemetryConnector()
    )

    # The titles router builds its JobRepository directly from the session; patch
    # the class the router imported so it uses the in-memory fake.
    import app.api.titles as titles_mod

    monkeypatch.setattr(titles_mod, "JobRepository", lambda session: jobs_repo)

    return TestClient(app)


# --------------------------------------------------------------------------- #
# POST /titles/ingest
# --------------------------------------------------------------------------- #


def test_ingest_returns_202_and_dispatches(
    client: TestClient, dispatcher: FakeDispatcher
) -> None:
    resp = client.post(
        "/api/v1/titles/ingest",
        content=b"title_name,acquisition_cost_or_budget\nFoo,1000.00\n",
        headers={"Content-Type": "text/csv", "Idempotency-Key": "key-1"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "PENDING"
    assert uuid.UUID(body["job_id"])
    assert len(dispatcher.ingest_calls) == 1
    assert dispatcher.ingest_calls[0][2] == "csv"
    assert dispatcher.ingest_calls[0][3] == "key-1"


def test_ingest_idempotent_replay_echoes_stored_job(
    client: TestClient, jobs_repo: FakeJobRepository, dispatcher: FakeDispatcher
) -> None:
    stored = FakeJob(
        job_id=uuid.uuid4(),
        job_type="ingest_batch",
        status="COMPLETED",
        idempotency_key="dup",
        result={
            "accepted_count": 2,
            "rejected_count": 1,
            "rejections": [{"row_index": 3, "field": "title_name", "reason": "required"}],
        },
    )
    jobs_repo.by_key["dup"] = stored

    resp = client.post(
        "/api/v1/titles/ingest",
        content=b"title_name,acquisition_cost_or_budget\nFoo,1000.00\n",
        headers={"Content-Type": "text/csv", "Idempotency-Key": "dup"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == str(stored.job_id)
    assert body["status"] == "COMPLETED"
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 1
    assert body["rejections"][0]["row_index"] == 3
    # A replay must NOT re-dispatch the heavy work.
    assert dispatcher.ingest_calls == []


def test_ingest_rejects_unsupported_format_with_415_envelope(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/titles/ingest",
        content=b"<xml/>",
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error_code"] == "UNSUPPORTED_FORMAT"
    assert "message" in body


def test_ingest_rejects_oversized_csv_with_422_envelope(client: TestClient) -> None:
    header = "title_name,acquisition_cost_or_budget\n"
    rows = "".join(f"T{i},1000.00\n" for i in range(10_001))
    resp = client.post(
        "/api/v1/titles/ingest",
        content=(header + rows).encode(),
        headers={"Content-Type": "text/csv"},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "ROW_LIMIT_EXCEEDED"


# --------------------------------------------------------------------------- #
# POST /valuation/calculate
# --------------------------------------------------------------------------- #


def test_calculate_returns_recommendation_and_explanation(client: TestClient) -> None:
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/valuation/calculate",
        json={"title_id": str(title_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_id"] == str(title_id)
    assert body["recommendation_status"] == "GREENLIGHT"
    assert body["explanation"]["checks"][0]["name"] == "CPVH"
    assert body["calculated_cpvh"] is not None


def test_calculate_missing_title_maps_to_404(
    client: TestClient, guardrails: FakeGuardrailsEngine
) -> None:
    guardrails._known = uuid.uuid4()  # any other id raises TitleNotFoundError
    resp = client.post(
        "/api/v1/valuation/calculate",
        json={"title_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TITLE_NOT_FOUND"


def test_calculate_includes_churn_model(client: TestClient) -> None:
    """POST /valuation/calculate surfaces churn_model from the resolved detail (R7.3)."""
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/valuation/calculate",
        json={"title_id": str(title_id)},
    )
    assert resp.status_code == 200
    churn_model = resp.json()["explanation"]["churn_model"]
    assert churn_model["churn_method"] == "CALCULATED"
    assert churn_model["is_borderline"] is False
    assert churn_model["params_source"] == "MODEL_VERSION"
    assert churn_model["missing_features"] == []
    breakdown = churn_model["churn_breakdown"]
    # The six feature keys ride along as decimal strings (JSONB round-trip shape).
    assert breakdown["base_platform_rate"] == "0.15"
    assert breakdown["asset_cadence"] == "0.35"
    assert breakdown["talent_pedigree_contribution"] == "0.77"
    assert breakdown["production_scale_contribution"] == "0.27"
    assert breakdown["exclusivity_lift"] == "0.25"
    assert breakdown["market_telemetry_heat"] == "0.33"


# --------------------------------------------------------------------------- #
# GET /valuation/{title_id}
# --------------------------------------------------------------------------- #


def test_get_valuation_returns_scorecard(client: TestClient) -> None:
    title_id = uuid.uuid4()

    @dataclass
    class FakeTitle:
        title_id: uuid.UUID

    @dataclass
    class FakeProjection:
        calculated_cpvh: Decimal = Decimal("0.0400")
        ltv_to_cost_multiple: Decimal = Decimal("3.5000")
        churn_reduction_pct: Decimal = Decimal("2.00")
        payback_horizon_months: int = 8
        recommendation_status: str = "GREENLIGHT"
        normalized_cost_usd: Decimal = Decimal("1000.00")
        model_version_id: uuid.UUID = field(default_factory=uuid.uuid4)
        explanation: dict | None = field(default_factory=lambda: {"checks": []})

    @dataclass
    class FakeVector:
        affective_primary: str = "JOY"
        affective_secondary: str = "ANTICIPATION"
        talent_pedigree_score: Decimal = Decimal("7.50")
        production_scale_metric: Decimal = Decimal("8.00")
        narrative_dna: list = field(default_factory=lambda: [0.0] * 1536)
        extraction_status: str = "SUCCESS"
        created_at: datetime = field(
            default_factory=lambda: datetime.now(timezone.utc)
        )

    import app.api.valuation as val_mod

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return FakeTitle(title_id=title_id) if tid == title_id else None

    class _Projections:
        def __init__(self, session: Any) -> None: ...

        async def get_latest_for_title(self, tid: uuid.UUID) -> Any:
            return FakeProjection()

    class _Vectors:
        def __init__(self, session: Any) -> None: ...

        async def list_for_title(self, tid: uuid.UUID) -> list[Any]:
            return [FakeVector()]

    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    val_mod.FinancialProjectionRepository = _Projections  # type: ignore[assignment]
    val_mod.MetadataVectorRepository = _Vectors  # type: ignore[assignment]

    try:
        resp = client.get(f"/api/v1/valuation/{title_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title_id"] == str(title_id)
        assert body["recommendation_status"] == "GREENLIGHT"
        assert body["metadata_breakdown"]["narrative_dna_dimensions"] == 1536
        assert body["metadata_breakdown"]["affective_primary"] == "JOY"
    finally:
        # Restore patched classes to avoid leaking into other tests.
        import app.repositories.financial_projections as fp
        import app.repositories.metadata_vectors as mv
        import app.repositories.titles as tr

        val_mod.TitleRepository = tr.TitleRepository
        val_mod.FinancialProjectionRepository = fp.FinancialProjectionRepository
        val_mod.MetadataVectorRepository = mv.MetadataVectorRepository


def _patch_valuation_get(title_id: uuid.UUID, explanation: dict | None):
    """Patch the GET /valuation repositories with in-memory fakes.

    Returns the valuation module so the caller can restore the real repository
    classes in a finally block. The stored projection carries ``explanation``
    verbatim, exercising the GET passthrough (no engine re-run).
    """
    import app.api.valuation as val_mod

    @dataclass
    class FakeTitle:
        title_id: uuid.UUID

    @dataclass
    class FakeProjection:
        calculated_cpvh: Decimal = Decimal("0.0400")
        ltv_to_cost_multiple: Decimal = Decimal("3.5000")
        churn_reduction_pct: Decimal = Decimal("2.00")
        payback_horizon_months: int = 8
        recommendation_status: str = "GREENLIGHT"
        normalized_cost_usd: Decimal = Decimal("1000.00")
        model_version_id: uuid.UUID = field(default_factory=uuid.uuid4)
        explanation: dict | None = field(default_factory=lambda: explanation)

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return FakeTitle(title_id=title_id) if tid == title_id else None

    class _Projections:
        def __init__(self, session: Any) -> None: ...

        async def get_latest_for_title(self, tid: uuid.UUID) -> Any:
            return FakeProjection()

    class _Vectors:
        def __init__(self, session: Any) -> None: ...

        async def list_for_title(self, tid: uuid.UUID) -> list[Any]:
            return []

    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    val_mod.FinancialProjectionRepository = _Projections  # type: ignore[assignment]
    val_mod.MetadataVectorRepository = _Vectors  # type: ignore[assignment]
    return val_mod


def _restore_valuation_repos() -> None:
    import app.api.valuation as val_mod
    import app.repositories.financial_projections as fp
    import app.repositories.metadata_vectors as mv
    import app.repositories.titles as tr

    val_mod.TitleRepository = tr.TitleRepository
    val_mod.FinancialProjectionRepository = fp.FinancialProjectionRepository
    val_mod.MetadataVectorRepository = mv.MetadataVectorRepository


def test_get_valuation_passthrough_churn_model(client: TestClient) -> None:
    """GET passes a persisted churn_model through unchanged, no re-run (R7.3)."""
    title_id = uuid.uuid4()
    stored_churn_model = {
        "churn_method": "CALCULATED",
        "is_borderline": True,
        "params_source": "MODEL_VERSION",
        "model_version_id": str(uuid.uuid4()),
        "missing_features": ["telemetry_heat"],
        "churn_breakdown": {
            "base_platform_rate": "0.15",
            "asset_cadence": "0.35",
            "talent_pedigree_contribution": "0.77",
            "production_scale_contribution": "0.27",
            "exclusivity_lift": "0.25",
            "market_telemetry_heat": "0.00",
        },
    }
    _patch_valuation_get(
        title_id, {"checks": [], "churn_model": stored_churn_model}
    )
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}")
        assert resp.status_code == 200
        assert resp.json()["explanation"]["churn_model"] == stored_churn_model
    finally:
        _restore_valuation_repos()


def test_get_valuation_without_churn_model_still_serializes(client: TestClient) -> None:
    """A stored explanation lacking churn_model serializes fine; key is absent (R7.6)."""
    title_id = uuid.uuid4()
    _patch_valuation_get(title_id, {"checks": []})
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}")
        assert resp.status_code == 200
        explanation = resp.json()["explanation"]
        assert explanation == {"checks": []}
        assert "churn_model" not in explanation
    finally:
        _restore_valuation_repos()


def test_get_valuation_missing_title_maps_to_404(client: TestClient) -> None:
    import app.api.valuation as val_mod

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return None

    original = val_mod.TitleRepository
    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    try:
        resp = client.get(f"/api/v1/valuation/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TITLE_NOT_FOUND"
    finally:
        val_mod.TitleRepository = original


# --------------------------------------------------------------------------- #
# GET /valuation/{title_id}/comps
# --------------------------------------------------------------------------- #


def test_get_comps_returns_top_neighbours(client: TestClient) -> None:
    title_id = uuid.uuid4()
    neighbour_a = uuid.uuid4()
    neighbour_b = uuid.uuid4()

    @dataclass
    class FakeTitle:
        title_id: uuid.UUID

    @dataclass
    class FakeVector:
        narrative_dna: list = field(default_factory=lambda: [0.1] * 1536)
        created_at: datetime = field(
            default_factory=lambda: datetime.now(timezone.utc)
        )

    import app.api.valuation as val_mod
    import app.repositories.metadata_vectors as mv

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return FakeTitle(title_id=title_id) if tid == title_id else None

    class _Vectors:
        def __init__(self, session: Any) -> None: ...

        async def list_for_title(self, tid: uuid.UUID) -> list[Any]:
            return [FakeVector()]

        async def rank_similar_titles(
            self, title_vector: list, exclude_title_id: uuid.UUID, limit: int = 3
        ) -> list[Any]:
            assert exclude_title_id == title_id
            return [
                mv.SimilarTitle(
                    title_id=neighbour_a,
                    title_name="Neighbour A",
                    genre_tag="DRAMA",
                    recommendation_status="GREENLIGHT",
                    cosine_similarity=0.9123,
                ),
                mv.SimilarTitle(
                    title_id=neighbour_b,
                    title_name="Neighbour B",
                    genre_tag="THRILLER",
                    recommendation_status=None,
                    cosine_similarity=0.8011,
                ),
            ]

    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    val_mod.MetadataVectorRepository = _Vectors  # type: ignore[assignment]
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}/comps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert body["title_id"] == str(title_id)
        assert len(body["comps"]) == 2
        first = body["comps"][0]
        assert first["title_id"] == str(neighbour_a)
        assert first["title_name"] == "Neighbour A"
        assert first["recommendation_status"] == "GREENLIGHT"
        assert first["cosine_similarity"] == 0.9123
        # A neighbour without a computed valuation surfaces a null status.
        assert body["comps"][1]["recommendation_status"] is None
    finally:
        import app.repositories.titles as tr

        val_mod.TitleRepository = tr.TitleRepository
        val_mod.MetadataVectorRepository = mv.MetadataVectorRepository


def test_get_comps_no_embedding_returns_found_false(client: TestClient) -> None:
    title_id = uuid.uuid4()

    @dataclass
    class FakeTitle:
        title_id: uuid.UUID

    import app.api.valuation as val_mod
    import app.repositories.metadata_vectors as mv

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return FakeTitle(title_id=title_id)

    class _Vectors:
        def __init__(self, session: Any) -> None: ...

        async def list_for_title(self, tid: uuid.UUID) -> list[Any]:
            return []

    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    val_mod.MetadataVectorRepository = _Vectors  # type: ignore[assignment]
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}/comps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is False
        assert body["comps"] == []
    finally:
        import app.repositories.titles as tr

        val_mod.TitleRepository = tr.TitleRepository
        val_mod.MetadataVectorRepository = mv.MetadataVectorRepository


def test_get_comps_missing_title_maps_to_404(client: TestClient) -> None:
    import app.api.valuation as val_mod

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return None

    original = val_mod.TitleRepository
    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    try:
        resp = client.get(f"/api/v1/valuation/{uuid.uuid4()}/comps")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TITLE_NOT_FOUND"
    finally:
        val_mod.TitleRepository = original


# --------------------------------------------------------------------------- #
# GET /valuation/{title_id}/comps - Comps_Engine anchor (Driver A, task 15)
# --------------------------------------------------------------------------- #


@dataclass
class _AnchorTitle:
    """A USD-native historical title with the fields the anchor seam reads."""

    title_id: uuid.UUID
    asset_type: str = "ORIGINAL_FILM"
    acquisition_cost_or_budget: Decimal = Decimal("1000000.00")
    native_currency: str = "USD"


def _install_comps_fakes(
    title_id: uuid.UUID,
    neighbour_id: uuid.UUID,
    *,
    candidates: list[Any] | None,
):
    """Patch the valuation router's repositories for an anchor test.

    ``candidates`` is the list ``rank_comps_within_band`` returns; ``None`` means
    the method is never expected to be called (enable_comps off). Returns the
    (restore) teardown callable.
    """
    import app.api.valuation as val_mod
    import app.repositories.metadata_vectors as mv

    @dataclass
    class FakeVector:
        narrative_dna: list = field(default_factory=lambda: [0.1] * 1536)
        created_at: datetime = field(
            default_factory=lambda: datetime.now(timezone.utc)
        )

    class _Titles:
        def __init__(self, session: Any) -> None: ...

        async def get(self, tid: uuid.UUID) -> Any:
            return _AnchorTitle(title_id=title_id) if tid == title_id else None

    class _Vectors:
        def __init__(self, session: Any) -> None: ...

        async def list_for_title(self, tid: uuid.UUID) -> list[Any]:
            return [FakeVector()]

        async def rank_similar_titles(
            self, title_vector: list, exclude_title_id: uuid.UUID, limit: int = 3
        ) -> list[Any]:
            return [
                mv.SimilarTitle(
                    title_id=neighbour_id,
                    title_name="Neighbour A",
                    genre_tag="DRAMA",
                    recommendation_status="GREENLIGHT",
                    cosine_similarity=0.9123,
                )
            ]

        async def rank_comps_within_band(self, **kwargs: Any) -> list[Any]:
            assert candidates is not None, (
                "rank_comps_within_band must not be called when enable_comps is off"
            )
            return candidates

    orig_titles = val_mod.TitleRepository
    orig_vectors = val_mod.MetadataVectorRepository
    val_mod.TitleRepository = _Titles  # type: ignore[assignment]
    val_mod.MetadataVectorRepository = _Vectors  # type: ignore[assignment]

    def _restore() -> None:
        val_mod.TitleRepository = orig_titles
        val_mod.MetadataVectorRepository = orig_vectors

    return _restore


def test_get_comps_anchor_present_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable_comps on + a non-empty comp set surfaces the Comps anchor fields."""
    import app.api.valuation as val_mod
    import app.repositories.metadata_vectors as mv
    from app.core.config import Settings

    title_id = uuid.uuid4()
    neighbour_id = uuid.uuid4()
    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    comp_c = uuid.uuid4()

    # Three in-band comps -> median hours = 3100, median churn = 1.90.
    candidates = [
        mv.CompCandidate(
            title_id=comp_a,
            title_name="Comp A",
            genre_tag="DRAMA",
            cosine_distance=0.10,
            comp_viewing_hours=Decimal("2800"),
            comp_churn_pct=Decimal("1.80"),
        ),
        mv.CompCandidate(
            title_id=comp_b,
            title_name="Comp B",
            genre_tag="DRAMA",
            cosine_distance=0.20,
            comp_viewing_hours=Decimal("3100"),
            comp_churn_pct=Decimal("1.90"),
        ),
        mv.CompCandidate(
            title_id=comp_c,
            title_name="Comp C",
            genre_tag="DRAMA",
            cosine_distance=0.30,
            comp_viewing_hours=Decimal("3400"),
            comp_churn_pct=Decimal("2.00"),
        ),
    ]

    monkeypatch.setattr(
        val_mod, "get_settings", lambda: Settings(enable_comps=True)
    )
    restore = _install_comps_fakes(title_id, neighbour_id, candidates=candidates)
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}/comps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        # Decimals serialize as JSON strings.
        assert Decimal(body["h_comps"]) == Decimal("3100")
        assert Decimal(body["c_comps"]) == Decimal("1.90")
        assert Decimal(body["dispersion_iqr"]) == Decimal("600")
        assert body["realized_k"] == 3
        assert body["comp_title_ids"] == [str(comp_a), str(comp_b), str(comp_c)]
        # Each listed comp also carries the anchor.
        first = body["comps"][0]
        assert Decimal(first["h_comps"]) == Decimal("3100")
        assert first["realized_k"] == 3
    finally:
        restore()


def test_get_comps_anchor_absent_when_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable_comps off keeps the surface backward-compatible: anchor absent."""
    import app.api.valuation as val_mod
    from app.core.config import Settings

    title_id = uuid.uuid4()
    neighbour_id = uuid.uuid4()

    monkeypatch.setattr(
        val_mod, "get_settings", lambda: Settings(enable_comps=False)
    )
    # candidates=None asserts rank_comps_within_band is never called off-flag.
    restore = _install_comps_fakes(title_id, neighbour_id, candidates=None)
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}/comps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert body["h_comps"] is None
        assert body["c_comps"] is None
        assert body["dispersion_iqr"] is None
        assert body["realized_k"] is None
        assert body["comp_title_ids"] is None
        # Existing Top-3 surface unchanged; comp carries no anchor.
        assert body["comps"][0]["h_comps"] is None
    finally:
        restore()


def test_get_comps_anchor_absent_when_no_eligible_comps(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable_comps on but zero eligible comps -> intercept fallback, anchor absent."""
    import app.api.valuation as val_mod
    from app.core.config import Settings

    title_id = uuid.uuid4()
    neighbour_id = uuid.uuid4()

    monkeypatch.setattr(
        val_mod, "get_settings", lambda: Settings(enable_comps=True)
    )
    restore = _install_comps_fakes(title_id, neighbour_id, candidates=[])
    try:
        resp = client.get(f"/api/v1/valuation/{title_id}/comps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert body["h_comps"] is None
        assert body["realized_k"] is None
        assert body["comps"][0]["h_comps"] is None
    finally:
        restore()


# --------------------------------------------------------------------------- #
# Deal-stage lifecycle: GET/PATCH /titles/{id}/deal-stage
# --------------------------------------------------------------------------- #


def _buyer() -> UserContext:
    """A CONTENT_BUYER - a role permitted the OVERRIDE operation."""
    return UserContext(
        user_id=uuid.uuid4(),
        display_name="Test Buyer",
        role=UserRole.CONTENT_BUYER,
        authorized_territories=(),
    )


class _FakeAuditService:
    """Captures audit.record(...) calls without touching a session."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def _patch_titles_repo(title_id: uuid.UUID, stage: str):
    """Patch TitleRepository on the titles module with an in-memory fake.

    Returns the fake instance so a test can read back the stored deal_stage.
    """
    import app.api.titles as titles_mod

    @dataclass
    class FakeTitle:
        title_id: uuid.UUID
        deal_stage: str

    class _Repo:
        instance: Any = None

        def __init__(self, session: Any) -> None:
            self.title = FakeTitle(title_id=title_id, deal_stage=stage)
            _Repo.instance = self

        async def get(self, tid: uuid.UUID) -> Any:
            return self.title if tid == title_id else None

        async def update(self, instance: Any, **values: Any) -> Any:
            for key, value in values.items():
                setattr(instance, key, value)
            return instance

    titles_mod.TitleRepository = _Repo  # type: ignore[assignment]
    return titles_mod, _Repo


def test_get_deal_stage_returns_stage_and_allowed_moves(client: TestClient) -> None:
    title_id = uuid.uuid4()
    titles_mod, repo = _patch_titles_repo(title_id, "EVALUATED")
    try:
        resp = client.get(f"/api/v1/titles/{title_id}/deal-stage")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deal_stage"] == "EVALUATED"
        assert body["allowed_next_stages"] == ["IN_NEGOTIATION", "PASSED"]
    finally:
        import app.repositories.titles as tr

        titles_mod.TitleRepository = tr.TitleRepository


def test_get_deal_stage_missing_title_maps_to_404(client: TestClient) -> None:
    titles_mod, _repo = _patch_titles_repo(uuid.uuid4(), "SCREENING")
    try:
        resp = client.get(f"/api/v1/titles/{uuid.uuid4()}/deal-stage")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TITLE_NOT_FOUND"
    finally:
        import app.repositories.titles as tr

        titles_mod.TitleRepository = tr.TitleRepository


def test_patch_deal_stage_advances_on_legal_transition() -> None:
    title_id = uuid.uuid4()
    app = create_app()
    audit = _FakeAuditService()
    app.dependency_overrides[deps.get_current_user] = _buyer
    app.dependency_overrides[deps.get_db_session] = lambda: FakeSession()
    app.dependency_overrides[deps.get_audit_service] = lambda: audit
    titles_mod, repo = _patch_titles_repo(title_id, "EVALUATED")
    try:
        resp = TestClient(app).patch(
            f"/api/v1/titles/{title_id}/deal-stage",
            json={"deal_stage": "IN_NEGOTIATION"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["deal_stage"] == "IN_NEGOTIATION"
        assert body["allowed_next_stages"] == ["APPROVED", "PASSED"]
        # The transition was persisted and audited.
        assert repo.instance.title.deal_stage == "IN_NEGOTIATION"
        assert len(audit.records) == 1
        assert audit.records[0]["before"] == {"deal_stage": "EVALUATED"}
        assert audit.records[0]["after"] == {"deal_stage": "IN_NEGOTIATION"}
    finally:
        import app.repositories.titles as tr

        titles_mod.TitleRepository = tr.TitleRepository


def test_patch_deal_stage_rejects_illegal_transition_with_422() -> None:
    title_id = uuid.uuid4()
    app = create_app()
    audit = _FakeAuditService()
    app.dependency_overrides[deps.get_current_user] = _buyer
    app.dependency_overrides[deps.get_db_session] = lambda: FakeSession()
    app.dependency_overrides[deps.get_audit_service] = lambda: audit
    titles_mod, repo = _patch_titles_repo(title_id, "SCREENING")
    try:
        resp = TestClient(app).patch(
            f"/api/v1/titles/{title_id}/deal-stage",
            json={"deal_stage": "CLOSED_WON"},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "VALIDATION_FAILED"
        # Nothing was persisted or audited on a rejected move.
        assert repo.instance.title.deal_stage == "SCREENING"
        assert audit.records == []
    finally:
        import app.repositories.titles as tr

        titles_mod.TitleRepository = tr.TitleRepository


def test_patch_deal_stage_denies_unauthorized_role_with_403() -> None:
    # The default DATA_ANALYST is not permitted the OVERRIDE operation.
    title_id = uuid.uuid4()
    titles_mod, _repo = _patch_titles_repo(title_id, "EVALUATED")
    try:
        resp = client_fixture_patch(title_id)
        assert resp.status_code == 403
    finally:
        import app.repositories.titles as tr

        titles_mod.TitleRepository = tr.TitleRepository


def client_fixture_patch(title_id: uuid.UUID):
    """PATCH as the default DATA_ANALYST (no OVERRIDE) to assert the 403 gate."""
    app = create_app()
    app.dependency_overrides[deps.get_current_user] = _analyst
    app.dependency_overrides[deps.get_db_session] = lambda: FakeSession()
    app.dependency_overrides[deps.get_audit_service] = lambda: _FakeAuditService()
    return TestClient(app).patch(
        f"/api/v1/titles/{title_id}/deal-stage",
        json={"deal_stage": "IN_NEGOTIATION"},
    )


# --------------------------------------------------------------------------- #
# POST /backtest/audit
# --------------------------------------------------------------------------- #


def test_backtest_audit_returns_scorecard(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "metrics": [{"metric_name": "cpvh", "actual_value": 0.05}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_id"] == str(title_id)
    assert body["mape"] == "25.00"
    assert body["metrics"][0]["metric"] == "cpvh"
    assert len(backtesting.persisted) == 1
    # The handler must durably commit the ground truth so a later request (e.g.
    # calibration, which re-audits the title in its own session) can read it.
    assert backtesting.session.commits == 1


def test_backtest_accepts_actual_churn_alias(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    # The optional top-level actual_churn_reduction_pct is persisted as the
    # "churn_reduction" ground-truth metric even when no metrics list is sent
    # (R11.1). The churn alias alone satisfies the "at least one metric" rule.
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "actual_churn_reduction_pct": "1.80",
        },
    )
    assert resp.status_code == 200
    assert len(backtesting.persisted) == 1
    persisted_metrics = backtesting.persisted[0]["metrics"]
    churn = [m for m in persisted_metrics if m["metric_name"] == "churn_reduction"]
    assert len(churn) == 1
    assert Decimal(str(churn[0]["actual_value"])) == Decimal("1.80")


def test_backtest_accepts_churn_alias_alongside_metrics(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    # Both a metrics list and the churn alias may be present; the alias adds one
    # churn entry in addition to the caller-supplied metrics (R11.1, R11.2).
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={
            "title_id": str(title_id),
            "metrics": [{"metric_name": "cpvh", "actual_value": 0.05}],
            "actual_churn_reduction_pct": "1.80",
        },
    )
    assert resp.status_code == 200
    persisted_metrics = backtesting.persisted[0]["metrics"]
    names = {m["metric_name"] for m in persisted_metrics}
    assert names == {"cpvh", "churn_reduction"}


def test_backtest_requires_at_least_one_metric(
    client: TestClient, backtesting: FakeBacktestingModule
) -> None:
    # Neither a metrics list nor the churn alias: nothing to audit, rejected 422
    # via the model validator before the handler runs, persisting nothing (R11.2).
    title_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/backtest/audit",
        json={"title_id": str(title_id)},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "VALIDATION_FAILED"
    assert backtesting.persisted == []


# --------------------------------------------------------------------------- #
# GET /market/telemetry
# --------------------------------------------------------------------------- #


def test_market_telemetry_returns_snapshot(client: TestClient) -> None:
    resp = client.get("/api/v1/market/telemetry?genre=DRAMA&territory=US")
    assert resp.status_code == 200
    body = resp.json()
    assert body["genre_tag"] == "DRAMA"
    assert body["territory"] == "US"
    assert body["source_available"] is True
    assert body["found"] is True


# --------------------------------------------------------------------------- #
# Auth / RBAC envelope behavior
# --------------------------------------------------------------------------- #


def test_unauthenticated_request_rejected_with_401() -> None:
    # A client with NO auth override exercises the real get_current_user, which
    # rejects a request with no credential as 401 UNAUTHENTICATED (R19.3).
    app = create_app()
    # Override only the DB session (so no real engine is created) and leave the
    # real get_current_user in place. With no credential it rejects before any
    # repository is queried.
    app.dependency_overrides[deps.get_db_session] = lambda: FakeSession()
    app.dependency_overrides[deps.get_telemetry_connector] = (
        lambda: FakeTelemetryConnector()
    )
    with TestClient(app) as unauth_client:
        resp = unauth_client.get("/api/v1/market/telemetry?genre=DRAMA&territory=US")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


def test_rbac_denies_insufficient_role_with_403() -> None:
    # DATA_ANALYST is not permitted the OVERRIDE operation; but all core
    # endpoints allow DATA_ANALYST. Verify the RBAC path by forcing a role that
    # the VALUATION operation still permits is pointless; instead assert the
    # authorize() denial envelope through a direct dependency check.
    from app.core.errors import ForbiddenError
    from app.engines.rbac import Operation, RBACService

    rbac = RBACService()
    actor = _analyst()
    with pytest.raises(ForbiddenError) as exc:
        rbac.authorize(actor, Operation.OVERRIDE)
    assert exc.value.error_code in {"FORBIDDEN_OVERRIDE", "FORBIDDEN"}
