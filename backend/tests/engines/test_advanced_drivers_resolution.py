"""End-to-end Advanced_Content_Eval_Drivers resolution + the inertness proof.

# Feature: advanced-content-eval-drivers

These tests exercise the *production* wiring path for task 10: the
:class:`app.api.deps.AdvancedDriversValuationInputProvider` resolving a title's
:class:`~app.engines.guardrails.ValuationInputs` behind the four per-driver
kill-switches and feeding them to the real
:class:`~app.engines.guardrails.Guardrails_Engine`, so the flag gating, the
``advanced_drivers`` passthrough, and the precedence are verified against the
verdict/scorecard they actually produce.

The headline property is INERTNESS (R7.2, R7.3): with all four flags false (the
default) the resolved inputs, the verdict, and the persisted explanation are
BYTE-IDENTICAL to the pre-feature baseline (the wrapped content-eval provider),
so the seeded demo and every existing test stay untouched until a driver is
explicitly enabled. The other tests flip each flag on independently to show its
driver flows through and reacts, and show a SUPPLIED value still wins over an
enabled driver (``SUPPLIED > FITTED > DETERMINISTIC_FALLBACK``).

No database is used. The provider reads two collaborators lazily inside
``get_inputs`` -- ``TitleVersionRepository`` (the active ``source_snapshot``) and
``ModelVersioningEngine.read_active`` (the content-eval layer's active version).
We reuse the in-memory fakes / monkeypatch fixture from
``tests/engines/test_content_eval_resolution.py`` and the shared engine fakes
from ``tests/engines/test_guardrails_properties.py``. The four flags are
controlled by monkeypatching ``app.api.deps.get_settings`` with a per-test
``Settings`` instance so the ``lru_cache``d global is never mutated.

Validates: Requirements 7.2, 7.4, 7.5, 9.1, 9.3; Properties 1, 5
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

import app.api.deps as deps
from app.api.deps import (
    AdvancedDriversValuationInputProvider,
    ContentEvalValuationInputProvider,
)
from app.core.config import Settings
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


# --------------------------------------------------------------------------- #
# Flag control + snapshot / engine helpers
# --------------------------------------------------------------------------- #


def _settings(**flags: bool) -> Settings:
    """Build a Settings instance with the four driver flags set as requested."""
    return Settings(
        enable_comps=flags.get("enable_comps", False),
        enable_lineage=flags.get("enable_lineage", False),
        enable_momentum=flags.get("enable_momentum", False),
        enable_macro_modifiers=flags.get("enable_macro_modifiers", False),
    )


@pytest.fixture
def set_flags(monkeypatch: pytest.MonkeyPatch):
    """Return a callable that patches ``deps.get_settings`` with chosen flags.

    The provider calls ``get_settings()`` (imported into ``app.api.deps``), so the
    patch lands on that symbol; the real ``lru_cache``d global is never touched.
    """

    def _apply(**flags: bool) -> None:
        settings = _settings(**flags)
        monkeypatch.setattr(deps, "get_settings", lambda: settings)

    return _apply


def _snapshot(**overrides: Any) -> dict[str, Any]:
    """A source snapshot carrying benign modeling fields + neutral driver facts.

    Mirrors the content-eval resolution snapshot (so the wrapped provider behaves
    the same), plus the neutral advanced-driver columns a demo title carries:
    non-franchise, CONCEPT_SCRIPT, ORIGINAL_SCREENPLAY, DIRECT_TO_STREAMING, no
    release month, single vernacular track. A ``churn_reduction_value`` is present
    so the content-eval layer's SUPPLIED-wins pins it exactly as a seeded title.
    """
    base: dict[str, Any] = {
        "ltv": "100",
        "cpm": "10",
        "ad_impressions": "1000",
        "churn_reduction_value": "1",
        "churn_reduction_pct": "2.0",
        "monthly_margin": "1000",
        "genre": "drama",
        "content_format": "scripted-series",
        "runtime_minutes": "55",
        "normalized_rating": "0.80",
        # Neutral advanced-driver facts (byte-identical demo defaults).
        "is_franchise": False,
        "franchise_order": 1,
        "production_stage": "CONCEPT_SCRIPT",
        "source_ip_provenance": "ORIGINAL_SCREENPLAY",
        "release_window": "DIRECT_TO_STREAMING",
        "vernacular_track_count": 1,
    }
    base.update(overrides)
    return base


def _advanced_provider() -> AdvancedDriversValuationInputProvider:
    return AdvancedDriversValuationInputProvider(_SESSION_SENTINEL)


def _content_eval_provider() -> ContentEvalValuationInputProvider:
    return ContentEvalValuationInputProvider(_SESSION_SENTINEL)


def _without_model_version_stamp(explanation: dict[str, Any]) -> dict[str, Any]:
    """Copy ``explanation`` with the per-run ``churn_model.model_version_id`` dropped.

    Each engine is wired with its own ``FakeVersioningEngine`` whose stamp uuid is
    random per instance, so the persisted ``churn_model`` block embeds a different
    ``model_version_id`` for the two providers. That stamp is unrelated to the
    provider wiring under test; normalizing it lets us assert byte-identity of
    everything the advanced-driver layer could have touched.
    """
    import copy

    clone = copy.deepcopy(explanation)
    churn_model = clone.get("churn_model")
    if isinstance(churn_model, dict):
        churn_model.pop("model_version_id", None)
    return clone


def _build_engine(
    provider: Any, *, title: FakeTitle
) -> tuple[Guardrails_Engine, uuid.UUID, FakeProjectionRepository]:
    """Wire the engine against the shared in-memory fakes and the given provider."""
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


# --------------------------------------------------------------------------- #
# 1. INERTNESS (R7.2/R7.3, Property 1/5): all flags false == pre-feature baseline
# --------------------------------------------------------------------------- #


async def test_all_flags_false_inputs_byte_identical_to_content_eval(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.2, 7.3; Property 1

    With every flag false, the advanced-drivers provider resolves inputs that are
    byte-identical (equal, including ``driver_explanations is None``) to the
    wrapped content-eval provider's -- no driver touches ``ValuationInputs``.
    """
    configure = patch_provider_collaborators
    set_flags()  # all false
    snapshot = _snapshot()
    configure(snapshot=snapshot, content_eval=None)

    title_id = uuid.uuid4()
    adv_inputs = await _advanced_provider().get_inputs(title_id)
    ce_inputs = await _content_eval_provider().get_inputs(title_id)

    assert adv_inputs == ce_inputs
    assert adv_inputs.driver_explanations is None


async def test_all_flags_false_verdict_and_explanation_byte_identical(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.2, 7.3, 9.1; Property 1

    The inertness guarantee holds end to end: the advanced-drivers provider and
    the content-eval provider drive an identical verdict, LTV-to-Cost multiple,
    and persisted explanation through the real engine, and no ``advanced_drivers``
    key leaks into the stored explanation.
    """
    configure = patch_provider_collaborators
    set_flags()  # all false
    configure(snapshot=_snapshot(), content_eval=None)

    title_id = uuid.uuid4()

    adv_engine, _, adv_proj = _build_engine(
        _advanced_provider(), title=FakeTitle(title_id=title_id)
    )
    ce_engine, _, ce_proj = _build_engine(
        _content_eval_provider(), title=FakeTitle(title_id=title_id)
    )
    adv_result = await adv_engine.evaluate(title_id)
    ce_result = await ce_engine.evaluate(title_id)

    assert adv_result["recommendation_status"] == ce_result["recommendation_status"]
    assert adv_result["ltv_to_cost_multiple"] == ce_result["ltv_to_cost_multiple"]
    assert adv_result["explanation"] == ce_result["explanation"]

    # The persisted explanations match too, apart from the per-engine random
    # model-version stamp (each FakeVersioningEngine mints its own uuid; it is not
    # a product of the provider wiring). Normalize it before comparing.
    adv_expl = _without_model_version_stamp(adv_proj.created["explanation"])
    ce_expl = _without_model_version_stamp(ce_proj.created["explanation"])
    assert adv_expl == ce_expl
    # No advanced-driver / content-eval passthrough leaks onto the demo path.
    assert "advanced_drivers" not in adv_proj.created["explanation"]
    assert "content_eval" not in adv_proj.created["explanation"]


async def test_all_flags_false_even_with_rich_driver_facts(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.2; Property 1, 5

    Inertness does NOT depend on the facts being neutral: even when the snapshot
    carries rich, non-neutral driver facts (a 3rd franchise entry, an
    acquisition-ready stage with buzz, a premium IP / theatrical window / four
    vernacular tracks), every flag being false means the provider still returns
    the content-eval inputs byte-identical with no ``advanced_drivers`` block.
    """
    configure = patch_provider_collaborators
    set_flags()  # all false
    rich = _snapshot(
        is_franchise=True,
        franchise_order=3,
        parent_title_viewing_hours="5000",
        parent_completion_rate="0.80",
        production_stage="ACQUISITION_READY",
        v_trailer="1.8",
        e_ratio="0.9",
        s_velocity="1.9",
        source_ip_provenance="TRUE_CRIME_IP",
        release_window="THEATRICAL_60D_PLUS",
        release_month=12,
        vernacular_track_count=4,
    )
    configure(snapshot=rich, content_eval=None)

    title_id = uuid.uuid4()
    adv_inputs = await _advanced_provider().get_inputs(title_id)
    ce_inputs = await _content_eval_provider().get_inputs(title_id)

    assert adv_inputs == ce_inputs
    assert adv_inputs.driver_explanations is None


# --------------------------------------------------------------------------- #
# 2. Each flag toggled on independently flows its driver through
# --------------------------------------------------------------------------- #


async def test_enable_comps_surfaces_anchor(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.3

    With only ``enable_comps`` on and a non-empty comp set pre-resolved on the
    snapshot, the provider surfaces the Comps anchor (``H_comps`` / ``C_comps`` /
    dispersion / realized_k) and the ``base_hours_override`` / ``base_churn_
    override`` seeds under ``driver_explanations['advanced_drivers']['comps']``.
    No other driver appears (flags are independent).
    """
    configure = patch_provider_collaborators
    set_flags(enable_comps=True)
    snapshot = _snapshot(
        comps={
            "viewing_hours": ["2600", "2900", "3100", "3400", "4200"],
            "churn_pct": ["1.60", "1.80", "1.90", "2.10", "2.30"],
            "title_ids": [1, 2, 3, 4, 5],
        }
    )
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    advanced = inputs.driver_explanations["advanced_drivers"]
    assert set(advanced) == {"comps"}

    comps = advanced["comps"]
    # Median of the 5 viewing-hours values -> 3100; median churn -> 1.90.
    assert comps["h_comps"] == "3100"
    assert comps["c_comps"] == "1.90"
    assert comps["base_hours_override"] == "3100"
    assert comps["base_churn_override"] == "1.90"
    assert comps["realized_k"] == 5
    assert comps["use_intercept_fallback"] is False
    # IQR = ((3400+4200)/2) - ((2600+2900)/2) = 3800 - 2750 = 1050.
    assert comps["dispersion_iqr"] == "1050"


async def test_enable_comps_empty_comp_set_no_anchor(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.3

    With ``enable_comps`` on but an EMPTY comp set, the driver records the
    intercept-fallback signal and surfaces NO ``base_hours_override`` /
    ``base_churn_override`` -- Driver A is a no-op on the anchor, honoring the
    zero-comp fallback to the viewing-hours constant intercept.
    """
    configure = patch_provider_collaborators
    set_flags(enable_comps=True)
    configure(snapshot=_snapshot(), content_eval=None)  # no comps sub-object

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    comps = inputs.driver_explanations["advanced_drivers"]["comps"]
    assert comps["use_intercept_fallback"] is True
    assert comps["realized_k"] == 0
    assert "base_hours_override" not in comps
    assert "base_churn_override" not in comps


async def test_enable_lineage_surfaces_floor_and_credit(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.3

    With only ``enable_lineage`` on and a 2nd franchise entry with valid parent
    data, the provider surfaces an active Franchise_Floor and the
    ``delta_C_franchise`` credit (2nd entry -> +0.20).
    """
    configure = patch_provider_collaborators
    set_flags(enable_lineage=True)
    snapshot = _snapshot(
        is_franchise=True,
        franchise_order=2,
        parent_title_viewing_hours="5000",
        parent_completion_rate="0.80",
    )
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    advanced = inputs.driver_explanations["advanced_drivers"]
    assert set(advanced) == {"lineage"}

    lineage = advanced["lineage"]
    assert lineage["is_active"] is True
    # delta_C = clamp(0.15 + 0.05 * min(2-1, 6), 0.15, 0.45) = 0.20.
    assert lineage["delta_c_franchise"] == "0.20"
    # Franchise_Floor = 5000 * (0.55 + 0.35 * 0.80) = 5000 * 0.83 = 4150.00.
    assert Decimal(lineage["franchise_floor"]) == Decimal("4150.00")


async def test_enable_lineage_non_franchise_inactive(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4; Property 5

    With ``enable_lineage`` on but a non-franchise title, the driver is inactive:
    zero floor, zero credit -- it leaves the base prediction unchanged.
    """
    configure = patch_provider_collaborators
    set_flags(enable_lineage=True)
    configure(snapshot=_snapshot(), content_eval=None)  # non-franchise default

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    lineage = inputs.driver_explanations["advanced_drivers"]["lineage"]
    assert lineage["is_active"] is False
    assert lineage["franchise_floor"] == "0"
    assert lineage["delta_c_franchise"] == "0.00"


async def test_enable_momentum_stage_excluded_is_neutral(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4; Property 5

    With ``enable_momentum`` on and a CONCEPT_SCRIPT title, the driver is
    STAGE_EXCLUDED and its multiplier is forced to the neutral 1.00 (an
    unproduced pitch is never penalized), bounds serialize as ``[1.00,1.50]``.
    """
    configure = patch_provider_collaborators
    set_flags(enable_momentum=True)
    configure(snapshot=_snapshot(), content_eval=None)  # CONCEPT_SCRIPT default

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    momentum = inputs.driver_explanations["advanced_drivers"]["momentum"]
    assert momentum["stage_excluded"] is True
    assert momentum["reason"] == "STAGE_EXCLUDED"
    assert momentum["value"] == "1.00"
    assert momentum["bounds"] == "[1.00,1.50]"


async def test_enable_momentum_active_stage_lifts(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.3

    With ``enable_momentum`` on and an ACQUISITION_READY title with fresh buzz,
    the multiplier composes above the neutral baseline, within [1.00, 1.50].
    """
    configure = patch_provider_collaborators
    set_flags(enable_momentum=True)
    snapshot = _snapshot(
        production_stage="ACQUISITION_READY",
        v_trailer="1.5",
        e_ratio="0.8",
        s_velocity="1.6",
        telemetry_source_available=True,
    )
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    momentum = inputs.driver_explanations["advanced_drivers"]["momentum"]
    assert momentum["stage_excluded"] is False
    assert momentum["reason"] == "ACTIVE"
    value = Decimal(momentum["value"])
    assert Decimal("1.00") < value <= Decimal("1.50")


async def test_enable_macro_modifiers_surfaces_multipliers(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.3

    With only ``enable_macro_modifiers`` on and premium descriptors, the provider
    surfaces each clamped multiplier and their product.
    """
    configure = patch_provider_collaborators
    set_flags(enable_macro_modifiers=True)
    snapshot = _snapshot(
        source_ip_provenance="BESTSELLER_BOOK",
        release_window="THEATRICAL_30D",
        release_month=12,
        vernacular_track_count=2,
    )
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    advanced = inputs.driver_explanations["advanced_drivers"]
    assert set(advanced) == {"macro_modifiers"}

    macro = advanced["macro_modifiers"]
    assert macro["source_ip_multiplier"] == "1.20"  # BESTSELLER_BOOK
    assert macro["release_window_multiplier"] == "1.25"  # THEATRICAL_30D
    assert macro["calendar_seasonality_multiplier"] == "1.30"  # December
    assert macro["vernacular_tam_multiplier"] == "1.40"  # 2 tracks


async def test_flags_are_independent(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4

    Enabling two flags surfaces exactly those two driver blocks and no others --
    the four kill-switches are independent.
    """
    configure = patch_provider_collaborators
    set_flags(enable_comps=True, enable_macro_modifiers=True)
    snapshot = _snapshot(
        comps={
            "viewing_hours": ["3000"],
            "churn_pct": ["2.00"],
            "title_ids": [7],
        }
    )
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _advanced_provider().get_inputs(uuid.uuid4())
    advanced = inputs.driver_explanations["advanced_drivers"]
    assert set(advanced) == {"comps", "macro_modifiers"}


async def test_advanced_drivers_threaded_into_persisted_explanation(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.4, 9.1

    When a driver is enabled, the ``advanced_drivers`` block threads through the
    engine into the persisted projection explanation (end to end), while the
    verdict itself is still governed by the untouched thresholds / recommendation.
    """
    configure = patch_provider_collaborators
    set_flags(enable_lineage=True)
    snapshot = _snapshot(
        is_franchise=True,
        franchise_order=2,
        parent_title_viewing_hours="5000",
        parent_completion_rate="0.80",
    )
    configure(snapshot=snapshot, content_eval=None)

    title = FakeTitle(title_id=uuid.uuid4())
    engine, title_id, proj = _build_engine(_advanced_provider(), title=title)
    await engine.evaluate(title_id)

    # The engine attaches driver_explanations under the "content_eval" key of the
    # persisted explanation (the existing passthrough); the advanced_drivers block
    # rides along inside it.
    content_eval = proj.created["explanation"]["content_eval"]
    assert "advanced_drivers" in content_eval
    assert content_eval["advanced_drivers"]["lineage"]["is_active"] is True


# --------------------------------------------------------------------------- #
# 3. Precedence: a SUPPLIED value wins over an enabled driver
# --------------------------------------------------------------------------- #


async def test_supplied_churn_pct_wins_over_enabled_comps(
    patch_provider_collaborators,  # noqa: F811
    set_flags,
) -> None:
    """Validates: Requirements 7.5, 9.3; Property 1

    SUPPLIED > FITTED > DETERMINISTIC_FALLBACK holds regardless of flag state:
    with ``enable_comps`` on (surfacing a DETERMINISTIC_FALLBACK ``C_comps``
    churn anchor), a SUPPLIED ``churn_reduction_pct`` on the snapshot still wins
    at the field level -- the engine's churn resolution short-circuits on the
    supplied value, so the resolved churn equals the supplied value exactly, not
    the comps anchor.
    """
    configure = patch_provider_collaborators
    set_flags(enable_comps=True)
    supplied_pct = Decimal("2.0")
    snapshot = _snapshot(
        churn_reduction_pct=str(supplied_pct),
        comps={
            "viewing_hours": ["3000", "3000", "3000"],
            "churn_pct": ["4.50", "4.50", "4.50"],  # anchor differs from supplied
            "title_ids": [1, 2, 3],
        },
    )
    configure(snapshot=snapshot, content_eval=None)

    title = FakeTitle(title_id=uuid.uuid4())
    engine, title_id, _ = _build_engine(_advanced_provider(), title=title)
    result = await engine.evaluate(title_id)

    # The SUPPLIED churn pct wins; the comps C_comps (4.50) does NOT override it.
    assert result["churn_reduction_pct"] == supplied_pct

    # The inputs still carry the SUPPLIED value on the field, and the comps anchor
    # is only surfaced on the explanation (never mutating the SUPPLIED field).
    inputs = await _advanced_provider().get_inputs(title_id)
    assert inputs.churn_reduction_pct == supplied_pct
    comps = inputs.driver_explanations["advanced_drivers"]["comps"]
    assert comps["base_churn_override"] == "4.50"
