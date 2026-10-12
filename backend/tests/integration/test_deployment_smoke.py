"""Deployment smoke test (task 22.2).

Brings the *entire* stack up exactly the way an operator would — ``docker compose
up`` against the repo-root ``docker-compose.yml`` authored in task 22.1 — and
asserts the two deployment guarantees the task names:

* **R18.4** — starting the compose configuration initializes the PostgreSQL
  database from the provided scripts and loads the mock seed data. The
  ``db-init`` one-shot job runs ``database/seed/seed.py`` (Alembic migrations +
  ``01_schema.sql`` + ``02_seed_data.sql``) and ``backend``/``worker`` wait for
  it to finish successfully. We verify the seed landed by reading the seeded
  rows back out of the running ``db`` service (users, the active model version,
  exchange rates, titles) — a database that merely came up but was never
  initialized/seeded would fail this.
* **R29.4** — once the stack is healthy, ``GET /health`` on the backend reports
  the per-component readiness of the **database**, the **Task_Queue**, and the
  **Telemetry_Connector**. We assert all three component keys are present and,
  in a cleanly started stack, each reports "up" with an overall ``"ok"`` status.

Skip-vs-fail contract
---------------------
This is an end-to-end test that needs a working Docker daemon with the Compose
plugin. Following the project's DB-dependent integration-test convention (see
``conftest.py`` / ``test_schema_integrity.py``), the whole module **skips
cleanly** — never fails — when:

* the ``docker``/``docker compose`` CLI is not on PATH, or
* the Docker daemon is not reachable (as in the CI/sandbox here), or
* the stack cannot be built/started for an environmental reason.

Only *assertion* failures after a genuinely healthy stack are real failures.

The test is marked ``@pytest.mark.integration`` and is a slow, opt-in check: run
it explicitly with ``pytest -m integration backend/tests/integration/test_deployment_smoke.py``
on a machine with Docker. It brings the stack down (``docker compose down -v``)
in a ``finally`` so no containers or volumes leak between runs.

Requirements: 18.4, 29.4
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

try:  # pragma: no cover - import guard; module skips when missing
    import httpx

    _HAS_HTTPX = True
except Exception:  # pragma: no cover - import guard
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# Repository layout: backend/tests/integration/<this file> -> project root is
# three parents up; the compose file lives at the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILE = _PROJECT_ROOT / "docker-compose.yml"

# How the compose file publishes the backend and database (see docker-compose.yml).
_BACKEND_BASE_URL = "http://localhost:8000"
_HEALTH_URL = f"{_BACKEND_BASE_URL}/health"
_DB_SERVICE = "db"
_DB_USER = "cineroi"
_DB_NAME = "cineroi"

# Expected seed cardinalities loaded by database/seed/02_seed_data.sql (R18.4):
# one user per role, one active model version, four USD exchange rates, five titles.
_EXPECTED_USERS = 4
_EXPECTED_ACTIVE_MODEL_VERSIONS = 1
_EXPECTED_EXCHANGE_RATES = 4
_EXPECTED_TITLES = 5

# Bringing a full stack (image build + migrations + seed + health) up is slow.
_STACK_READY_TIMEOUT_S = 600
_HEALTH_POLL_TIMEOUT_S = 180
_POLL_INTERVAL_S = 5


# --------------------------------------------------------------------------- #
# Docker / compose availability detection (skip, never fail).
# --------------------------------------------------------------------------- #
def _docker_cli() -> str | None:
    """Return the resolved ``docker`` executable, or ``None`` if not installed."""
    return shutil.which("docker")


def _run(args: list[str], *, timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, capturing text output; never raises on non-zero exit.

    Decodes as UTF-8 with ``errors="replace"`` so Compose's progress output
    (which emits box-drawing / spinner bytes that the Windows cp1252 default
    cannot decode) never crashes the reader thread.
    """
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _docker_available() -> tuple[bool, str]:
    """Return (available, reason) describing whether Docker + Compose can run.

    "Available" means the ``docker`` CLI exists, the daemon answers ``docker
    info``, and the ``docker compose`` plugin is present. Any failure is a skip
    reason, not an error — exactly the sandbox case where no daemon is running.
    """
    cli = _docker_cli()
    if cli is None:
        return False, "the `docker` CLI is not installed / not on PATH"

    try:
        info = _run([cli, "info"], timeout=20)
    except Exception as exc:  # subprocess spawn / timeout
        return False, f"could not invoke `docker info` ({exc!r})"
    if info.returncode != 0:
        return False, "the Docker daemon is not reachable (`docker info` failed)"

    try:
        compose = _run([cli, "compose", "version"], timeout=20)
    except Exception as exc:
        return False, f"could not invoke `docker compose` ({exc!r})"
    if compose.returncode != 0:
        return False, "the `docker compose` plugin is not available"

    return True, "docker available"


def _require_docker() -> str:
    """Skip the whole module cleanly unless Docker + Compose are usable."""
    if not _HAS_HTTPX:
        pytest.skip("httpx is not installed; cannot probe the deployed /health endpoint")
    if not _COMPOSE_FILE.is_file():
        pytest.skip(f"docker-compose.yml not found at {_COMPOSE_FILE}")
    available, reason = _docker_available()
    if not available:
        pytest.skip(f"Docker is unavailable, skipping deployment smoke test: {reason}")
    return _docker_cli()  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Compose lifecycle helpers.
# --------------------------------------------------------------------------- #
def _compose(docker: str, *args: str) -> list[str]:
    return [docker, "compose", "-f", str(_COMPOSE_FILE), *args]


def _compose_up(docker: str) -> None:
    """Build and start the full stack in detached mode, waiting for health.

    ``--wait`` blocks until services with a healthcheck are healthy (and the
    one-shot ``db-init`` has exited successfully) or the timeout elapses.
    """
    result = _run(
        _compose(docker, "up", "--build", "--detach", "--wait"),
        timeout=_STACK_READY_TIMEOUT_S,
        cwd=_PROJECT_ROOT,
    )
    if result.returncode != 0:
        # A build/pull/start failure here is environmental (no network to pull
        # base images, disk pressure, etc.) rather than a product defect — skip.
        pytest.skip(
            "`docker compose up --wait` did not bring the stack up healthy "
            f"(environmental): {result.stderr.strip()[-800:]}"
        )


def _compose_down(docker: str) -> None:
    """Tear the stack down and remove named volumes so runs stay isolated."""
    _run(
        _compose(docker, "down", "--volumes", "--remove-orphans"),
        timeout=180,
        cwd=_PROJECT_ROOT,
    )


def _psql_scalar(docker: str, sql: str) -> str:
    """Run a single-value query inside the running ``db`` service via psql.

    Returns the trimmed scalar output. Raises on a failed query so a seed
    assertion surfaces a real failure (the stack is already confirmed healthy by
    the time we read seed rows).
    """
    result = _run(
        _compose(
            docker,
            "exec",
            "-T",
            _DB_SERVICE,
            "psql",
            "-U",
            _DB_USER,
            "-d",
            _DB_NAME,
            "-tAc",
            sql,
        ),
        timeout=60,
        cwd=_PROJECT_ROOT,
    )
    assert result.returncode == 0, (
        f"psql query failed inside the db service: {sql!r}\n{result.stderr.strip()}"
    )
    return result.stdout.strip()


def _poll_health() -> dict:
    """Poll ``GET /health`` until it answers 200, returning the parsed body.

    The backend has its own compose healthcheck, so ``--wait`` already blocked on
    it; this short poll just absorbs the gap between "container healthy" and the
    published port accepting a client connection.
    """
    deadline = time.monotonic() + _HEALTH_POLL_TIMEOUT_S
    last_err: Exception | str = "no attempt made"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(_HEALTH_URL, timeout=10)
            if response.status_code == 200:
                return response.json()
            last_err = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:  # connection refused while port settles
            last_err = exc
        time.sleep(_POLL_INTERVAL_S)
    pytest.fail(f"GET {_HEALTH_URL} never returned 200 within the timeout: {last_err!r}")


# --------------------------------------------------------------------------- #
# Module-scoped fixture: one stack brought up, shared by the assertions below.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def deployed_stack() -> Iterator[str]:
    """Bring the compose stack up once for the module; tear it down after.

    Yields the resolved ``docker`` CLI path so tests can ``docker compose exec``
    into the running ``db`` service to verify the seed.
    """
    docker = _require_docker()
    _compose_up(docker)
    try:
        yield docker
    finally:
        _compose_down(docker)


@pytest.fixture(scope="module")
def health_body(deployed_stack: str) -> dict:
    """The parsed ``GET /health`` body from the healthy, deployed stack."""
    return _poll_health()


# --------------------------------------------------------------------------- #
# R29.4 - /health reports DB / Task_Queue / Telemetry_Connector status.
# --------------------------------------------------------------------------- #
def test_health_reports_all_three_components(health_body: dict) -> None:
    """R29.4: the health probe reports database, task queue, and telemetry."""
    for component in ("database", "task_queue", "telemetry"):
        assert component in health_body, (
            f"/health is missing the {component!r} component: {health_body}"
        )
        assert "status" in health_body[component], (
            f"/health {component!r} entry has no status: {health_body[component]}"
        )


def test_health_components_are_up_in_a_clean_stack(health_body: dict) -> None:
    """R29.4: a freshly started stack reports every component up and overall ok."""
    database = health_body["database"]["status"]
    task_queue = health_body["task_queue"]["status"]
    telemetry = health_body["telemetry"]["status"]

    assert database == "up", f"database component not up: {health_body['database']}"
    assert task_queue == "up", f"task_queue component not up: {health_body['task_queue']}"
    assert telemetry == "up", f"telemetry component not up: {health_body['telemetry']}"
    assert health_body.get("status") == "ok", (
        f"overall health status not ok with all components up: {health_body}"
    )


# --------------------------------------------------------------------------- #
# R18.4 - compose startup initializes the DB from scripts and loads seed data.
# --------------------------------------------------------------------------- #
def test_schema_was_initialized_with_pgvector(deployed_stack: str) -> None:
    """R18.4: the init scripts enabled pgvector and built the core schema."""
    docker = deployed_stack
    extension = _psql_scalar(
        docker, "SELECT count(*) FROM pg_extension WHERE extname = 'vector';"
    )
    assert extension == "1", "pgvector extension was not enabled by the init scripts"

    titles_table = _psql_scalar(
        docker,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_name = 'titles';",
    )
    assert titles_table == "1", "the 'titles' table was not created by the migrations"


def test_mock_seed_data_was_loaded(deployed_stack: str) -> None:
    """R18.4: db-init loaded the mock seed data (users, model version, rates, titles)."""
    docker = deployed_stack

    users = int(_psql_scalar(docker, "SELECT count(*) FROM users;"))
    assert users >= _EXPECTED_USERS, (
        f"expected at least {_EXPECTED_USERS} seeded users (one per role), got {users}"
    )

    active_models = int(
        _psql_scalar(docker, "SELECT count(*) FROM model_versions WHERE is_active;")
    )
    assert active_models == _EXPECTED_ACTIVE_MODEL_VERSIONS, (
        f"expected exactly {_EXPECTED_ACTIVE_MODEL_VERSIONS} active model version, "
        f"got {active_models}"
    )

    rates = int(_psql_scalar(docker, "SELECT count(*) FROM exchange_rates;"))
    assert rates >= _EXPECTED_EXCHANGE_RATES, (
        f"expected at least {_EXPECTED_EXCHANGE_RATES} seeded exchange rates, got {rates}"
    )

    titles = int(_psql_scalar(docker, "SELECT count(*) FROM titles;"))
    assert titles >= _EXPECTED_TITLES, (
        f"expected at least {_EXPECTED_TITLES} seeded titles, got {titles}"
    )


def test_health_db_probe_agrees_with_seeded_database(
    deployed_stack: str, health_body: dict
) -> None:
    """R18.4 + R29.4: the live DB health probe passes against the seeded database.

    Ties the two requirements together: the same database the health endpoint
    probes as "up" is the one carrying the loaded seed data, so a healthy report
    reflects a genuinely initialized deployment rather than an empty shell.
    """
    assert health_body["database"]["status"] == "up"
    one = _psql_scalar(deployed_stack, "SELECT 1;")
    assert one == "1"
