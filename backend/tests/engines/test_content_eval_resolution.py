"""End-to-end Content_Eval resolution through the real provider + engine.

# Feature: content-eval-model

These tests exercise the *production* resolution path: the
:class:`app.api.deps.ContentEvalValuationInputProvider` (task 13) resolving a
title's :class:`~app.engines.guardrails.ValuationInputs` and feeding them to the
real :class:`~app.engines.guardrails.Guardrails_Engine` (task 12 seam), so the
precedence, the churn<->LTV link, and the ``driver_explanations`` passthrough are
verified together against the verdict/scorecard they actually produce.

No database is used. The provider reads two collaborators lazily inside
``get_inputs`` -- ``TitleVersionRepository`` (the title's active
``source_snapshot``, read by BOTH the wrapped ``SnapshotValuationInputProvider``
and the content-eval provider) and ``ModelVersioningEngine.read_active`` (the
active ``model_versions`` row whose ``guardrail_params['content_eval']`` block
drives the FITTED path). We monkeypatch those two symbols at their source
modules with in-memory fakes, exactly the "in-memory fake / monkeypatched repo"
fixture style the sibling engine tests use (see
``tests/engines/test_churn_resolution.py``). The engine itself is wired with the
shared in-memory fakes from ``tests/engines/test_guardrails_properties.py`` --
USD-native title (no FX lookup), no genre/territories (identity weighting), and a
positive viewing-hours figure so the CPVH check never short-circuits the run.

The driver values the tests expect are recomputed straight from the pure domain
(``engagement.resolve_*`` / the churn<->LTV formula) rather than pinned to
literals, so a coefficient re-tune moves the assertion with the model instead of
silently drifting.

Validates: Requirements 1.4, 1.5, 1.6, 8.3; Properties 6, 12
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

import app.api.deps as deps
from app.api.deps import (
    ContentEvalValuationInputProvider,
    DEFAULT_BASE_RETAINED_COHORT_VALUE,
    SnapshotValuationInputProvider,
)
from app.domain import engagement as engmod
from app.domain import features as featmod
from app.engines.guardrails import Guardrails_Engine
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


# --------------------------------------------------------------------------- #
# In-memory fakes for the two collaborators the provider reads (no DB)
# --------------------------------------------------------------------------- #


@dataclass
class _FakeTitleVersion:
    """A ``title_versions`` row stand-in: only ``source_snapshot`` is read."""

    source_snapshot: dict[str, Any]
    is_active: bool = True


class _FakeTitleVersionRepository:
    """Returns one active :class:`_FakeTitleVersion` for any title id.

    Both ``SnapshotValuationInputProvider`` and
    ``ContentEvalValuationInputProvider`` construct this repo with the session
    and call :meth:`get_active`; the session is an inert sentinel here.
    """

    #: Set by the monkeypatch fixture so every construction shares one snapshot.
    snapshot: dict[str, Any] = {}

    def __init__(self, session: Any) -> None:
        self._session = session

    async def get_active(self, title_id: uuid.UUID) -> _FakeTitleVersion:
        return _FakeTitleVersion(source_snapshot=dict(type(self).snapshot))


@dataclass
class _FakeActiveModelVersion:
    """A ``model_versions`` row stand-in exposing ``guardrail_params`` JSONB."""

    model_version_id: uuid.UUID
    guardrail_params: dict[str, Any]


class _FakeModelVersioningEngine:
    """Stands in for ``ModelVersioningEngine``; only ``read_active`` is used.

    ``read_active`` returns a row whose ``guardrail_params`` carries (or omits) a
    ``content_eval`` block. ``active=None`` models "no active version at all" so
    ``parse_content_eval_params(None)`` yields the illustrative DEFAULTS (source
    DEFAULTS), the inert default-off path.
    """

    #: Set by the monkeypatch fixture.
    active: _FakeActiveModelVersion | None = None

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def read_active(self) -> _FakeActiveModelVersion | None:
        return type(self).active


class _FakeModelVersionRepository:
    """Inert: the fake ModelVersioningEngine never calls it (session sentinel)."""

    def __init__(self, session: Any) -> None:
        self._session = session


@pytest.fixture
def patch_provider_collaborators(monkeypatch: pytest.MonkeyPatch):
    """Patch the provider's lazily-imported repos/engine with the fakes.

    The provider imports these INSIDE ``get_inputs``
    (``from app.repositories.titles import TitleVersionRepository`` etc.), so the
    patch must land on the source modules, not on ``app.api.deps``. Returns a
    ``configure(snapshot, content_eval)`` callable the tests use to set the
    title's snapshot and the active version's ``content_eval`` block (``None``
    content_eval => no active version).
    """
    import app.engines.model_versioning as mvmod
    import app.repositories.model_versions as mvrepo
    import app.repositories.titles as titlesmod

    monkeypatch.setattr(
        titlesmod, "TitleVersionRepository", _FakeTitleVersionRepository
    )
    monkeypatch.setattr(
        mvrepo, "ModelVersionRepository", _FakeModelVersionRepository
    )
    monkeypatch.setattr(
        mvmod, "ModelVersioningEngine", _FakeModelVersioningEngine
    )

    def configure(
        *,
        snapshot: dict[str, Any],
        content_eval: dict[str, Any] | None,
    ) -> None:
        _FakeTitleVersionRepository.snapshot = dict(snapshot)
        if content_eval is None:
            _FakeModelVersioningEngine.active = None
        else:
            _FakeModelVersioningEngine.active = _FakeActiveModelVersion(
                model_version_id=uuid.uuid4(),
                guardrail_params={"content_eval": content_eval},
            )

    yield configure

    # Reset the class-level state so tests do not leak into one another.
    _FakeTitleVersionRepository.snapshot = {}
    _FakeModelVersioningEngine.active = None


# --------------------------------------------------------------------------- #
# Snapshot + content_eval builders
# --------------------------------------------------------------------------- #


def _snapshot(**overrides: Any) -> dict[str, Any]:
    """A source snapshot carrying the modeling fields the providers read.

    Defaults give benign LTV/CPM figures and OMIT ``watch_time_elasticity`` and
    ``ad_load_receptivity`` so the FITTED path can override them; a title genre /
    rating / runtime so the engagement models have features to work with.
    ``churn_reduction_pct`` is present (so the churn<->LTV link has a pct to use)
    and ``churn_reduction_value`` is present (so by default SUPPLIED-wins pins it,
    matching every seeded title) unless a test overrides/removes it.
    """
    base: dict[str, Any] = {
        "ltv": "100",
        "cpm": "10",
        "ad_impressions": "1000",
        "churn_reduction_value": "1",
        "churn_reduction_pct": "2.0",
        "monthly_margin": "1000",
        # Feature inputs for the engagement models.
        "genre": "drama",
        "content_format": "scripted-series",
        "runtime_minutes": "55",
        "normalized_rating": "0.80",
        "franchise_flag": True,
    }
    base.update(overrides)
    return base


def _content_eval_fitted(**overrides: Any) -> dict[str, Any]:
    """A fitted ``content_eval`` block (source MODEL_VERSION), link OFF by default.

    An empty ``viewing_hours`` / ``engagement`` map is fine: the nested parsers
    fall back to their illustrative defaults with their own source, but the
    OVERALL ``source`` is MODEL_VERSION because ``raw`` is a usable mapping -- so
    ``fitted_active`` is True and the FITTED drivers engage using the default
    (illustrative) coefficients. Tests that need specific coefficients pass them.
    """
    block: dict[str, Any] = {
        "version_label": "resolution-fit-1",
        "fit_dataset_version": "kpi-test",
        "dominant_label_type": "PROXY",
        "link_churn_to_ltv": False,
    }
    block.update(overrides)
    return block


# --------------------------------------------------------------------------- #
# Engine wiring (shared in-memory fakes + the REAL content-eval provider)
# --------------------------------------------------------------------------- #

_SESSION_SENTINEL = object()


def _build_engine(
    provider: Any,
    *,
    title: FakeTitle,
) -> tuple[Guardrails_Engine, uuid.UUID, FakeProjectionRepository, FakeAuditService]:
    """Wire the engine against the shared in-memory fakes and the given provider."""
    projections = FakeProjectionRepository()
    audit = FakeAuditService()
    engine = Guardrails_Engine(
        title_repository=FakeTitleRepository(title),
        projection_repository=projections,
        exchange_rate_repository=FakeExchangeRateRepository(),
        license_term_repository=FakeLicenseTermRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        model_versioning_engine=FakeVersioningEngine(),
        audit_service=audit,
        input_provider=provider,
    )
    return engine, title.title_id, projections, audit


def _content_eval_provider() -> ContentEvalValuationInputProvider:
    return ContentEvalValuationInputProvider(_SESSION_SENTINEL)


def _snapshot_provider() -> SnapshotValuationInputProvider:
    return SnapshotValuationInputProvider(_SESSION_SENTINEL)


# --------------------------------------------------------------------------- #
# Expected-driver recomputation straight from the pure domain
# --------------------------------------------------------------------------- #


def _expected_fitted_wte(snapshot: dict[str, Any], ce_block: dict[str, Any]) -> Decimal:
    """Recompute the FITTED Watch_Time_Elasticity the provider would resolve."""
    from app.domain import content_eval as cemod

    params = cemod.parse_content_eval_params(ce_block)
    features = featmod.derive_features(snapshot)
    result = engmod.resolve_watch_time_elasticity(
        snapshot.get("watch_time_elasticity"),
        features,
        params.watch_time_elasticity,
        params.watch_time_elasticity_source,
    )
    return result.watch_time_elasticity


def _expected_fitted_receptivity(
    snapshot: dict[str, Any], ce_block: dict[str, Any]
) -> Decimal:
    """Recompute the FITTED Ad_Load_Receptivity multiplier the provider resolves."""
    from app.domain import content_eval as cemod

    params = cemod.parse_content_eval_params(ce_block)
    features = featmod.derive_features(snapshot)
    result = engmod.resolve_ad_load_receptivity(
        snapshot.get("ad_load_receptivity"),
        features,
        params.ad_load_receptivity,
        params.ad_load_receptivity_source,
    )
    return result.ad_load_receptivity


# --------------------------------------------------------------------------- #
# 1. Identity (Property 12): default-off path is byte-identical to the snapshot
# --------------------------------------------------------------------------- #


async def test_identity_no_fitted_version_link_off_matches_snapshot_provider(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.4; Property 12

    With NO active fitted content_eval version and ``link_churn_to_ltv`` off (the
    seeded default), the resolved ValuationInputs are byte-identical to the
    wrapped SnapshotValuationInputProvider's, and the two providers drive an
    identical verdict + scorecard through the real engine. ``driver_explanations``
    stays ``None``, so the persisted explanation carries no ``content_eval`` key.
    """
    configure = patch_provider_collaborators
    snapshot = _snapshot()
    configure(snapshot=snapshot, content_eval=None)  # no active version

    title_id = uuid.uuid4()

    # The two providers resolve byte-identical inputs.
    snap_inputs = await _snapshot_provider().get_inputs(title_id)
    ce_inputs = await _content_eval_provider().get_inputs(title_id)
    assert ce_inputs == snap_inputs
    assert ce_inputs.driver_explanations is None

    # ...and an identical verdict/scorecard through the engine.
    ce_engine, _, ce_proj, _ = _build_engine(
        _content_eval_provider(), title=FakeTitle(title_id=title_id)
    )
    snap_engine, _, snap_proj, _ = _build_engine(
        _snapshot_provider(), title=FakeTitle(title_id=title_id)
    )
    ce_result = await ce_engine.evaluate(title_id)
    snap_result = await snap_engine.evaluate(title_id)

    assert ce_result["recommendation_status"] == snap_result["recommendation_status"]
    assert ce_result["ltv_to_cost_multiple"] == snap_result["ltv_to_cost_multiple"]
    assert ce_result["explanation"] == snap_result["explanation"]
    # No content_eval key leaks into the persisted explanation on the demo path.
    assert "content_eval" not in ce_proj.created["explanation"]
    assert "content_eval" not in snap_proj.created["explanation"]


# --------------------------------------------------------------------------- #
# 2. A fitted version overrides a driver and the verdict reacts
# --------------------------------------------------------------------------- #


async def test_fitted_watch_time_elasticity_override_moves_the_verdict(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.5; Property 6

    A fitted version with a large watch_time_elasticity intercept overrides the
    (unsupplied) elasticity. Because the advertising term is
    ``watch_time_elasticity * cpm * ad_impressions`` in the LTV numerator, a
    bigger elasticity raises LTV-to-Cost. We size cost so the DEFAULT elasticity
    breaches the LTV floor (3.2) but the FITTED elasticity clears it, so the
    guardrail verdict flips -- a model override reacting on the scorecard.
    """
    configure = patch_provider_collaborators

    # A fitted block whose WTE is driven high by a large intercept (clamped to the
    # WTE domain). The elasticity multiplies cpm*ad_impressions = 10*1000 = 10000.
    big_wte = {
        "intercept": "3.00",  # at WTE_MAX; dominates the additive sum
        "runtime_weight": "0",
        "serialization_lift": "0",
        "rating_weight": "0",
        "franchise_lift": "0",
        "min_value": "0.00",
        "max_value": "3.00",
        "genre_offsets": {},
        "genre_default": "0",
        "format_lifts": {},
        "format_default": "0",
    }
    ce_block = _content_eval_fitted(engagement={"watch_time_elasticity": big_wte})

    # Snapshot: unsupplied WTE (so FITTED engages), churn_reduction_value pinned
    # tiny so the subscription term is negligible and the ad term dominates.
    # ad term with default WTE (0.80) = 0.80*10000 = 8000; with fitted (3.00) =
    # 30000. Subscription term = 1*100 = 100. Choose cost so 8100/cost < 3.2 and
    # 30100/cost >= 3.2:  cost = 4000 -> default 8100/4000=2.025 (<3.2 breach),
    # fitted 30100/4000=7.525 (>=3.2 pass).
    snapshot = _snapshot(churn_reduction_value="1", ltv="100")
    snapshot.pop("watch_time_elasticity", None)
    cost = Decimal("4000.00")

    expected_wte = _expected_fitted_wte(snapshot, ce_block)
    assert expected_wte == Decimal("3.00")  # the override actually fires

    # Baseline (no fitted version): breaches LTV.
    configure(snapshot=snapshot, content_eval=None)
    base_title = FakeTitle(
        title_id=uuid.uuid4(), acquisition_cost_or_budget=cost
    )
    base_engine, base_id, _, _ = _build_engine(
        _content_eval_provider(), title=base_title
    )
    base_result = await base_engine.evaluate(base_id)
    base_ltv_check = _ltv_check(base_result["explanation"])
    assert base_ltv_check["breached"] is True

    # Fitted version active: the WTE override clears the LTV floor.
    configure(snapshot=snapshot, content_eval=ce_block)
    fit_title = FakeTitle(
        title_id=uuid.uuid4(), acquisition_cost_or_budget=cost
    )
    fit_engine, fit_id, fit_proj, _ = _build_engine(
        _content_eval_provider(), title=fit_title
    )
    fit_result = await fit_engine.evaluate(fit_id)
    fit_ltv_check = _ltv_check(fit_result["explanation"])

    assert fit_ltv_check["breached"] is False
    assert fit_result["ltv_to_cost_multiple"] > base_result["ltv_to_cost_multiple"]
    # The FITTED elasticity breakdown surfaced in the persisted explanation.
    content_eval = fit_proj.created["explanation"]["content_eval"]
    assert "watch_time_elasticity" in content_eval
    assert content_eval["watch_time_elasticity"]["method"] == "FITTED"
    assert content_eval["watch_time_elasticity"]["value"] == str(expected_wte)


async def test_fitted_ad_load_receptivity_scales_cpm(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.5; Property 6

    Ad_Load_Receptivity is a unit-centred multiplier that SCALES the configured
    CPM rather than emitting a dollar CPM. A fitted block that pushes receptivity
    above 1.0 raises the effective cpm, lifting the advertising term and thus
    LTV-to-Cost; the persisted breakdown records the base vs scaled cpm.
    """
    configure = patch_provider_collaborators

    # Receptivity driven to its ceiling (1.50) via a large genre offset, clamped.
    high_recept = {
        "centre": "1.00",
        "rating_weight": "0",
        "runtime_weight": "0",
        "franchise_lift": "0",
        "min_value": "0.50",
        "max_value": "1.50",
        "genre_offsets": {"drama": "0.50"},
        "genre_default": "0",
    }
    ce_block = _content_eval_fitted(
        engagement={"ad_load_receptivity": high_recept}
    )

    snapshot = _snapshot()
    snapshot.pop("ad_load_receptivity", None)

    expected_recept = _expected_fitted_receptivity(snapshot, ce_block)
    assert expected_recept == Decimal("1.50")  # clamped to the ceiling

    configure(snapshot=snapshot, content_eval=ce_block)
    title = FakeTitle(
        title_id=uuid.uuid4(), acquisition_cost_or_budget=Decimal("1000.00")
    )
    engine, title_id, proj, _ = _build_engine(_content_eval_provider(), title=title)
    result = await engine.evaluate(title_id)

    content_eval = proj.created["explanation"]["content_eval"]
    assert content_eval["ad_load_receptivity"]["method"] == "FITTED"
    assert content_eval["ad_load_receptivity"]["value"] == str(expected_recept)
    # base_cpm 10 scaled by 1.50 -> 15.00 recorded in the breakdown.
    assert content_eval["ad_load_receptivity"]["base_cpm"] == "10"
    assert content_eval["ad_load_receptivity"]["scaled_cpm"] == "15.00"


# --------------------------------------------------------------------------- #
# 3. Precedence: SUPPLIED > FITTED > FALLBACK
# --------------------------------------------------------------------------- #


async def test_supplied_watch_time_elasticity_beats_fitted(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.5, 8.3; Property 6

    SUPPLIED wins: when the snapshot carries a finite ``watch_time_elasticity``,
    even an active fitted version does NOT override it -- the resolved elasticity
    is the supplied value and no watch_time_elasticity breakdown is attached.
    """
    configure = patch_provider_collaborators

    big_wte = {
        "intercept": "3.00",
        "runtime_weight": "0",
        "serialization_lift": "0",
        "rating_weight": "0",
        "franchise_lift": "0",
        "min_value": "0.00",
        "max_value": "3.00",
        "genre_offsets": {},
        "genre_default": "0",
        "format_lifts": {},
        "format_default": "0",
    }
    ce_block = _content_eval_fitted(engagement={"watch_time_elasticity": big_wte})

    # SUPPLIED elasticity on the snapshot.
    supplied = Decimal("1.25")
    snapshot = _snapshot(watch_time_elasticity=str(supplied))
    configure(snapshot=snapshot, content_eval=ce_block)

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())
    # SUPPLIED value used exactly, NOT the fitted 3.00.
    assert inputs.watch_time_elasticity == supplied
    # No FITTED watch_time_elasticity breakdown recorded (SUPPLIED skips the model).
    if inputs.driver_explanations is not None:
        assert "watch_time_elasticity" not in inputs.driver_explanations


async def test_fitted_beats_fallback_when_unsupplied(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.5, 1.6, 8.3; Property 6

    FITTED beats FALLBACK: with no supplied elasticity and a fitted version
    active, the resolved elasticity is the model's value (not the snapshot
    placeholder default of 1), and the breakdown is recorded with method FITTED.
    """
    configure = patch_provider_collaborators

    big_wte = {
        "intercept": "2.50",
        "runtime_weight": "0",
        "serialization_lift": "0",
        "rating_weight": "0",
        "franchise_lift": "0",
        "min_value": "0.00",
        "max_value": "3.00",
        "genre_offsets": {},
        "genre_default": "0",
        "format_lifts": {},
        "format_default": "0",
    }
    ce_block = _content_eval_fitted(engagement={"watch_time_elasticity": big_wte})

    snapshot = _snapshot()
    snapshot.pop("watch_time_elasticity", None)  # unsupplied
    configure(snapshot=snapshot, content_eval=ce_block)

    expected = _expected_fitted_wte(snapshot, ce_block)
    assert expected == Decimal("2.50")

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())
    assert inputs.watch_time_elasticity == expected
    assert inputs.driver_explanations is not None
    assert inputs.driver_explanations["watch_time_elasticity"]["method"] == "FITTED"


async def test_fallback_when_no_fitted_version(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.6, 8.3; Property 6

    FALLBACK: with no supplied elasticity AND no active fitted version, the
    resolved elasticity is the snapshot placeholder default (1), unchanged, with
    no driver_explanations -- the FITTED path never engages without a version.
    """
    configure = patch_provider_collaborators
    snapshot = _snapshot()
    snapshot.pop("watch_time_elasticity", None)
    configure(snapshot=snapshot, content_eval=None)

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())
    # SnapshotValuationInputProvider defaults watch_time_elasticity to 1.
    assert inputs.watch_time_elasticity == Decimal("1")
    assert inputs.driver_explanations is None


# --------------------------------------------------------------------------- #
# 4. link_churn_to_ltv: churn propagates into the LTV numerator (opt-in)
# --------------------------------------------------------------------------- #


async def test_link_on_and_unsupplied_derives_churn_reduction_value(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.5, 1.6; Property 12

    With ``link_churn_to_ltv`` on AND no supplied ``churn_reduction_value``, the
    provider derives it from the modeled pct:
    ``Base_Retained_Cohort_Value * (churn_reduction_pct / 100)``. We use the
    default Base_Retained_Cohort_Value and assert the exact linked value flows
    into the LTV-to-Cost subscription term.
    """
    configure = patch_provider_collaborators

    ce_block = _content_eval_fitted(link_churn_to_ltv=True)
    # No churn_reduction_value supplied; pct present.
    snapshot = _snapshot(churn_reduction_pct="2.0")
    snapshot.pop("churn_reduction_value", None)
    configure(snapshot=snapshot, content_eval=ce_block)

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())

    expected = DEFAULT_BASE_RETAINED_COHORT_VALUE * (Decimal("2.0") / Decimal("100"))
    assert inputs.churn_reduction_value == expected  # 1,000,000 * 0.02 = 20,000


async def test_link_on_but_supplied_churn_reduction_value_unchanged(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 8.3; Property 6

    SUPPLIED still wins at the field level: with the link on BUT a
    ``churn_reduction_value`` present on the snapshot, the provider leaves it
    untouched -- the link never overwrites a supplied value (every seeded title
    carries one, so demo verdicts never move even with the toggle flipped).
    """
    configure = patch_provider_collaborators

    ce_block = _content_eval_fitted(link_churn_to_ltv=True)
    snapshot = _snapshot(churn_reduction_value="7777", churn_reduction_pct="2.0")
    configure(snapshot=snapshot, content_eval=ce_block)

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())
    assert inputs.churn_reduction_value == Decimal("7777")


async def test_link_off_preserves_snapshot_churn_reduction_value(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.6, 8.3; Property 12

    With the link OFF (the default) and no supplied churn_reduction_value, the
    provider does NOT derive one from the pct -- today's independent, snapshot-
    sourced churn_reduction_value behavior is preserved exactly (here the
    snapshot default of 0 when the field is absent).
    """
    configure = patch_provider_collaborators

    # A fitted version is active (so the provider does not short-circuit), but the
    # link is off; no churn_reduction_value supplied.
    ce_block = _content_eval_fitted(link_churn_to_ltv=False)
    snapshot = _snapshot(churn_reduction_pct="2.0")
    snapshot.pop("churn_reduction_value", None)
    configure(snapshot=snapshot, content_eval=ce_block)

    inputs = await _content_eval_provider().get_inputs(uuid.uuid4())
    # SnapshotValuationInputProvider defaults an absent churn_reduction_value to 0;
    # the link being off leaves that untouched (NOT the 20,000 the link would set).
    assert inputs.churn_reduction_value == Decimal("0")


# --------------------------------------------------------------------------- #
# 5. driver_explanations reaches the persisted explanation (end to end)
# --------------------------------------------------------------------------- #


async def test_driver_explanations_persisted_under_content_eval(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.4, 8.3; Property 6

    When a fitted version overrides a driver, the per-driver breakdown threads
    through the engine into the persisted projection under
    ``explanation["content_eval"]`` (the serializer ``_jsonable_explanation``
    attaches it during persistence, so it lives on the stored JSONB -- the
    explainability surface's source), carrying the honesty label type and the
    resolved value, end to end through the real provider and engine.
    """
    configure = patch_provider_collaborators

    ce_block = _content_eval_fitted(
        dominant_label_type="PROXY",
        engagement={
            "watch_time_elasticity": {
                "intercept": "1.50",
                "runtime_weight": "0",
                "serialization_lift": "0",
                "rating_weight": "0",
                "franchise_lift": "0",
                "min_value": "0.00",
                "max_value": "3.00",
                "genre_offsets": {},
                "genre_default": "0",
                "format_lifts": {},
                "format_default": "0",
            }
        },
    )
    snapshot = _snapshot()
    snapshot.pop("watch_time_elasticity", None)
    configure(snapshot=snapshot, content_eval=ce_block)

    title = FakeTitle(title_id=uuid.uuid4())
    engine, title_id, proj, _ = _build_engine(_content_eval_provider(), title=title)
    result = await engine.evaluate(title_id)

    # Attached to the persisted projection's serialized explanation (the raw
    # in-memory result["explanation"] is pre-serialization and has no content_eval
    # key; the serializer adds it on the way to JSONB, R5.2/R5.4/R8.2).
    assert "content_eval" not in result["explanation"]
    content_eval = proj.created["explanation"]["content_eval"]
    wte = content_eval["watch_time_elasticity"]
    assert wte["method"] == "FITTED"
    assert wte["label_type"] == "PROXY"
    assert wte["version_label"] == "resolution-fit-1"
    assert wte["value"] == str(_expected_fitted_wte(snapshot, ce_block))


async def test_driver_explanations_absent_when_no_fitted_version(
    patch_provider_collaborators,
) -> None:
    """Validates: Requirements 1.4, 1.6; Property 12

    With no fitted version active, no ``content_eval`` key appears in the
    persisted explanation at all -- the passthrough adds nothing on the demo path.
    """
    configure = patch_provider_collaborators
    configure(snapshot=_snapshot(), content_eval=None)

    title = FakeTitle(title_id=uuid.uuid4())
    engine, title_id, proj, _ = _build_engine(_content_eval_provider(), title=title)
    result = await engine.evaluate(title_id)

    assert "content_eval" not in result["explanation"]
    assert "content_eval" not in proj.created["explanation"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _ltv_check(explanation: dict[str, Any]) -> dict[str, Any]:
    """Extract the LTV_TO_COST check from an evaluate() explanation."""
    for check in explanation["checks"]:
        if check["name"] == "LTV_TO_COST":
            return check
    raise AssertionError("LTV_TO_COST check missing from explanation")
