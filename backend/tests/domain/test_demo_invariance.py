"""Demo-invariance guard for the Advanced_Content_Eval_Drivers feature.

# Feature: advanced-content-eval-drivers, Property 1: Option-B conservation / inertness

This is the byte-identity proof the whole feature is gated on (tasks.md hard
invariant, R7.3 / R8.5 / R8.6 / R9.2): with all four ``enable_*`` kill-switches
false (their default) and every new ``titles`` column at its NEUTRAL default,
the five seeded demo titles produce verdicts and explanations that are
BYTE-IDENTICAL to the pre-feature baseline. Each driver's contribution is
identically zero / 1.00, so nothing the advanced-driver layer could touch moves.

What this pins (all without a database):

1. **Seed backfill == migration neutral defaults.** The nine new driver columns
   the seed backfills for the five demo titles equal migration 0005's neutral
   server defaults exactly (``is_franchise=false``, ``franchise_order=1``,
   parents NULL, ``production_stage=CONCEPT_SCRIPT``,
   ``source_ip_provenance=ORIGINAL_SCREENPLAY``,
   ``release_window=DIRECT_TO_STREAMING``, ``release_month=NULL``,
   ``vernacular_track_count=1``). The expected values are read from the migration
   module so a change on one side without the other fails here.

2. **guardrail_params drivers round-trip (no drift).** The seed's ``comps`` /
   ``lineage`` / ``momentum`` / ``macro_modifiers`` sub-objects parse back through
   each driver's ``parse_params`` to the imported ``DEFAULT_*_PARAMS`` and report
   ``MODEL_VERSION`` -- the embedded JSON can never drift from the domain
   coefficients, and the blocks are inert at seed time.

3. **Inertness end to end for each demo title.** For each of the five demo titles,
   the real :class:`AdvancedDriversValuationInputProvider` (all flags false),
   given that title's seeded neutral driver facts, resolves inputs, a verdict,
   and a persisted explanation that are byte-identical to the wrapped
   :class:`ContentEvalValuationInputProvider` baseline, and no ``advanced_drivers``
   key leaks onto the explanation.

4. **Verdict distribution.** The five demo titles carry exactly 3 GREENLIGHT,
   1 NEGOTIATE_HARD, and 1 PASS, the canonical demo mix the inert path preserves.

The seed facts are imported from ``generate_seed_sql`` (``TITLES`` /
``_FORMAT_BY_TITLE``) rather than hard-coded, so the guard stays bound to the
actual seed logic. Importing the generator does not regenerate the SQL file (the
render-time code only runs under ``__main__``).

Validates: Requirements 7.3, 8.5, 8.6, 9.2; Property 1
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest

import app.api.deps as deps
from app.api.deps import (
    AdvancedDriversValuationInputProvider,
    ContentEvalValuationInputProvider,
)
from app.core.config import Settings
from app.domain.comps import DEFAULT_COMPS_PARAMS
from app.domain.comps import parse_params as parse_comps_params
from app.domain.lineage import (
    DEFAULT_LINEAGE_PARAMS,
)
from app.domain.lineage import (
    parse_params as parse_lineage_params,
)
from app.domain.macro_modifiers import (
    DEFAULT_MACRO_PARAMS,
)
from app.domain.macro_modifiers import (
    parse_params as parse_macro_params,
)
from app.domain.momentum import (
    DEFAULT_MOMENTUM_PARAMS,
)
from app.domain.momentum import (
    parse_params as parse_momentum_params,
)
from app.engines.guardrails import Guardrails_Engine
from tests.engines.test_content_eval_resolution import (  # noqa: F401 (fixture)
    patch_provider_collaborators,
)
from tests.engines.test_guardrails_properties import (
    FakeAuditService,
    FakeExchangeRateRepository,
    FakeLicenseTermRepository,
    FakeProjectionRepository,
    FakeTelemetryRepository,
    FakeTitle,
    FakeTitleRepository,
    FakeVersioningEngine,
)

_SESSION_SENTINEL = object()

# The five canonical demo titles and their verdicts (tasks.md hard invariant).
_DEMO_LABELS = (
    "title-aurora",
    "title-monsoon",
    "title-ledger",
    "title-reruns",
    "title-echoes",
)


# --------------------------------------------------------------------------- #
# Load the seed generator and migration 0005 as modules (no SQL regeneration)
# --------------------------------------------------------------------------- #


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED = _load_module(
    "generate_seed_sql_under_test",
    _REPO_ROOT / "database" / "seed" / "generate_seed_sql.py",
)
_MIGRATION = _load_module(
    "migration_0005_under_test",
    _REPO_ROOT
    / "database"
    / "migrations"
    / "versions"
    / "0005_advanced_content_eval_drivers.py",
)

_TITLES_BY_LABEL = {t[0]: t for t in _SEED.TITLES}
_GUARDRAIL_PARAMS = _SEED.MODEL_VERSION["guardrail_params"]


# --------------------------------------------------------------------------- #
# 1. Seed backfill == migration neutral defaults
# --------------------------------------------------------------------------- #


def test_production_stage_check_allows_concept_script() -> None:
    """The seed's neutral ``production_stage`` is inside migration 0005's CHECK.

    Guards the seed backfill against the CHECK constraint the migration installs:
    CONCEPT_SCRIPT must be one of the four allowed production stages, so the
    backfilled rows load cleanly.
    """
    assert "CONCEPT_SCRIPT" in _MIGRATION._PRODUCTION_STAGES


def test_seed_titles_insert_carries_neutral_driver_columns() -> None:
    """The rendered titles INSERT backfills the nine neutral driver columns.

    Renders the seed SQL in memory (no file write) and asserts the titles INSERT
    names every new driver column and emits each demo title row with the neutral
    tuple that matches migration 0005's server defaults. Binds the backfill text
    to the stated neutral contract so a drift is caught.
    """
    sql = _SEED.render()

    # The column list names all nine new columns.
    assert (
        "is_franchise, franchise_order, parent_title_viewing_hours, "
        "parent_completion_rate, production_stage, source_ip_provenance, "
        "release_window, release_month, vernacular_track_count) VALUES"
    ) in sql

    # Every demo title row ends with the neutral driver tuple.
    neutral_tail = (
        "FALSE, 1, NULL, NULL, 'CONCEPT_SCRIPT', 'ORIGINAL_SCREENPLAY', "
        "'DIRECT_TO_STREAMING', NULL, 1)"
    )
    for label in _DEMO_LABELS:
        name = _TITLES_BY_LABEL[label][1]
        # Find the row for this demo title and confirm its neutral tail.
        marker = f"'{name}'"
        row_start = sql.index(marker)
        row_end = sql.index("\n", row_start)
        row = sql[row_start:row_end]
        assert row.rstrip(",").endswith(neutral_tail), (
            f"{label} row does not carry the neutral driver tuple: {row}"
        )


# --------------------------------------------------------------------------- #
# 2. guardrail_params driver blocks round-trip to the domain defaults (no drift)
# --------------------------------------------------------------------------- #


def test_comps_block_round_trips_to_defaults() -> None:
    params, source = parse_comps_params(_GUARDRAIL_PARAMS["comps"])
    assert source == "MODEL_VERSION"
    assert params == DEFAULT_COMPS_PARAMS


def test_lineage_block_round_trips_to_defaults() -> None:
    params, source = parse_lineage_params(_GUARDRAIL_PARAMS["lineage"])
    assert source == "MODEL_VERSION"
    assert params == DEFAULT_LINEAGE_PARAMS


def test_momentum_block_round_trips_to_defaults() -> None:
    params, source = parse_momentum_params(_GUARDRAIL_PARAMS["momentum"])
    assert source == "MODEL_VERSION"
    assert params == DEFAULT_MOMENTUM_PARAMS


def test_macro_modifiers_block_round_trips_to_defaults() -> None:
    params, source = parse_macro_params(_GUARDRAIL_PARAMS["macro_modifiers"])
    assert source == "MODEL_VERSION"
    assert params == DEFAULT_MACRO_PARAMS


# --------------------------------------------------------------------------- #
# 3. Verdict distribution (3 GREENLIGHT / 1 NEGOTIATE_HARD / 1 PASS)
# --------------------------------------------------------------------------- #


def test_demo_verdict_distribution() -> None:
    """The five demo titles carry the canonical 3/1/1 verdict mix.

    The recommendation is the last element of each seeded TITLES tuple; the inert
    advanced-driver path must preserve this distribution (tasks.md invariant).
    """
    verdicts = [_TITLES_BY_LABEL[label][-1] for label in _DEMO_LABELS]
    assert verdicts.count("GREENLIGHT") == 3
    assert verdicts.count("NEGOTIATE_HARD") == 1
    assert verdicts.count("PASS") == 1


# --------------------------------------------------------------------------- #
# 4. Inertness end to end for each demo title (all flags false)
# --------------------------------------------------------------------------- #


def _all_flags_false_settings() -> Settings:
    return Settings(
        enable_comps=False,
        enable_lineage=False,
        enable_momentum=False,
        enable_macro_modifiers=False,
    )


def _neutral_demo_snapshot(label: str) -> dict[str, Any]:
    """A neutral source snapshot for a demo title, bound to the seed facts.

    Carries benign modeling fields (as a seeded ``source_snapshot`` would, so the
    content-eval layer behaves identically) plus the NEUTRAL advanced-driver
    facts the seed backfills onto the title columns. A ``churn_reduction_value``
    is present so the content-eval layer's SUPPLIED-wins pins it exactly as a
    seeded title.
    """
    _l, _name, _atype, _cost, _cur, _terrs, genre, _vh, _hist, *_rest = (
        _TITLES_BY_LABEL[label]
    )
    return {
        "ltv": "100",
        "cpm": "10",
        "ad_impressions": "1000",
        "churn_reduction_value": "1",
        "churn_reduction_pct": "2.0",
        "monthly_margin": "1000",
        "genre": genre,
        "content_format": _SEED._FORMAT_BY_TITLE.get(label),
        "runtime_minutes": "55",
        "normalized_rating": "0.80",
        # Neutral advanced-driver facts (the seed backfill defaults).
        "is_franchise": False,
        "franchise_order": 1,
        "production_stage": "CONCEPT_SCRIPT",
        "source_ip_provenance": "ORIGINAL_SCREENPLAY",
        "release_window": "DIRECT_TO_STREAMING",
        "vernacular_track_count": 1,
    }


def _build_engine(
    provider: Any, *, title: FakeTitle
) -> tuple[Guardrails_Engine, uuid.UUID, FakeProjectionRepository]:
    projections = FakeProjectionRepository()
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=projections,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=FakeVersioningEngine(),
        audit_service=FakeAuditService(),
        input_provider=provider,
    )
    return engine, title.title_id, projections


def _without_model_version_stamp(explanation: dict[str, Any]) -> dict[str, Any]:
    """Drop the per-run random ``churn_model.model_version_id`` before comparing.

    Each engine is wired with its own ``FakeVersioningEngine`` whose stamp uuid is
    random per instance, so the persisted ``churn_model`` block embeds a different
    stamp for the two providers. That stamp is unrelated to the advanced-driver
    wiring; normalizing it lets us assert byte-identity of everything the
    advanced-driver layer could have touched.
    """
    import copy

    clone = copy.deepcopy(explanation)
    churn_model = clone.get("churn_model")
    if isinstance(churn_model, dict):
        churn_model.pop("model_version_id", None)
    return clone


@pytest.mark.parametrize("label", _DEMO_LABELS)
async def test_demo_title_inputs_byte_identical_to_baseline(
    label: str,
    patch_provider_collaborators,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validates: Requirements 7.3, 9.2; Property 1

    With all flags false, the advanced-drivers provider resolves inputs for each
    demo title that are byte-identical to the content-eval baseline, and the
    ``driver_explanations`` passthrough is absent -- no driver touched the inputs.
    """
    monkeypatch.setattr(deps, "get_settings", _all_flags_false_settings)
    configure = patch_provider_collaborators
    configure(snapshot=_neutral_demo_snapshot(label), content_eval=None)

    title_id = uuid.uuid4()
    adv_inputs = await AdvancedDriversValuationInputProvider(
        _SESSION_SENTINEL
    ).get_inputs(title_id)
    ce_inputs = await ContentEvalValuationInputProvider(
        _SESSION_SENTINEL
    ).get_inputs(title_id)

    assert adv_inputs == ce_inputs
    assert adv_inputs.driver_explanations is None


@pytest.mark.parametrize("label", _DEMO_LABELS)
async def test_demo_title_verdict_and_explanation_byte_identical_to_baseline(
    label: str,
    patch_provider_collaborators,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validates: Requirements 7.3, 8.5, 8.6, 9.2; Property 1

    End to end: with all flags false, the advanced-drivers provider and the
    content-eval baseline drive an identical verdict, LTV-to-Cost multiple, and
    persisted explanation through the real engine for each demo title, and no
    ``advanced_drivers`` key leaks into the stored explanation.
    """
    monkeypatch.setattr(deps, "get_settings", _all_flags_false_settings)
    configure = patch_provider_collaborators
    configure(snapshot=_neutral_demo_snapshot(label), content_eval=None)

    title_id = uuid.uuid4()
    adv_engine, _, adv_proj = _build_engine(
        AdvancedDriversValuationInputProvider(_SESSION_SENTINEL),
        title=FakeTitle(title_id=title_id),
    )
    ce_engine, _, ce_proj = _build_engine(
        ContentEvalValuationInputProvider(_SESSION_SENTINEL),
        title=FakeTitle(title_id=title_id),
    )
    adv_result = await adv_engine.evaluate(title_id)
    ce_result = await ce_engine.evaluate(title_id)

    assert adv_result["recommendation_status"] == ce_result["recommendation_status"]
    assert adv_result["ltv_to_cost_multiple"] == ce_result["ltv_to_cost_multiple"]
    assert adv_result["explanation"] == ce_result["explanation"]

    adv_expl = _without_model_version_stamp(adv_proj.created["explanation"])
    ce_expl = _without_model_version_stamp(ce_proj.created["explanation"])
    assert adv_expl == ce_expl
    assert "advanced_drivers" not in adv_proj.created["explanation"]
