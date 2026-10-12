"""Property-based tests for the Calibration_Controller (R12 ↔ R26).

Targets :meth:`app.engines.calibration.Calibration_Controller.evaluate_and_apply`
and its no-op branch: when a backtest audit's MAPE is at or below the 10%
threshold (or is ``None`` because no metrics were eligible, R11.8), the
controller must report that no adjustment is required and leave the active
feature-extraction weights untouched — crucially, it must NEVER fork a new
model version in that case (R12.5).

Per the design's testing strategy, the controller's one collaborator — the
:class:`~app.engines.model_versioning.ModelVersioningEngine` — is replaced with
an **in-memory fake**, so these tests run with no database. The controller only
calls two methods on the engine (``read_active`` and ``create_version``), so the
fake implements exactly those: ``read_active`` returns a ModelVersion-like
object whose coupled weights sum to ``1.00``, and ``create_version`` records
that it was invoked and returns a new-version-like object carrying a fresh id.
The audit input is a tiny stub exposing only ``.mape`` (the structural
``AuditScorecardLike`` contract).

Covers design Property 20 (Calibration no-op below threshold), validating
Requirement 12.5. A positive-control test (MAPE clearly above threshold) is
included so the no-op assertions are not vacuous: it confirms the same fakes do
drive ``create_version`` when calibration IS required.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.security import UserContext, UserRole
from app.engines.calibration import MAPE_THRESHOLD, Calibration_Controller

# The active weights the fake engine reports. They sum to exactly 1.00 (R12.2)
# and are the baseline the no-op branch must leave unchanged.
_ACTIVE_TALENT = Decimal("0.60")
_ACTIVE_NARRATIVE = Decimal("0.40")


class _FakeModelVersion:
    """A ModelVersion-like active row for the fake engine to return.

    Exposes only the attributes :class:`Calibration_Controller` reads from the
    active version: the two coupled feature weights and the guardrail params.
    Its ``model_version_id`` lets the positive control assert a distinct new id.
    """

    def __init__(
        self,
        talent_pedigree_weight: Decimal,
        narrative_trope_weight: Decimal,
        guardrail_params: dict[str, object],
    ) -> None:
        self.model_version_id = uuid.uuid4()
        self.talent_pedigree_weight = talent_pedigree_weight
        self.narrative_trope_weight = narrative_trope_weight
        self.guardrail_params = guardrail_params


class _FakeModelVersioningEngine:
    """In-memory fake of the collaborator the controller depends on (R26).

    Implements the two methods the controller calls: ``read_active`` returns a
    stable active :class:`_FakeModelVersion` (weights summing to 1.00), and
    ``create_version`` records every invocation and returns a brand-new
    version-like object with a fresh id. The ``create_version_calls`` counter is
    the no-op witness — it must remain ``0`` on the sub-threshold branch (R12.5).
    """

    def __init__(
        self,
        talent_pedigree_weight: Decimal = _ACTIVE_TALENT,
        narrative_trope_weight: Decimal = _ACTIVE_NARRATIVE,
    ) -> None:
        self.active = _FakeModelVersion(
            talent_pedigree_weight,
            narrative_trope_weight,
            {"cpvh_ceiling_premium": "0.20"},
        )
        self.create_version_calls = 0
        self.last_create_kwargs: dict[str, object] | None = None

    async def read_active(self) -> _FakeModelVersion:
        """Return the single active model version (never ``None`` here)."""
        return self.active

    async def create_version(
        self,
        *,
        talent_pedigree_weight: Decimal,
        narrative_trope_weight: Decimal,
        guardrail_params: dict[str, object],
    ) -> _FakeModelVersion:
        """Record the fork and return a new active version with a fresh id."""
        self.create_version_calls += 1
        self.last_create_kwargs = {
            "talent_pedigree_weight": talent_pedigree_weight,
            "narrative_trope_weight": narrative_trope_weight,
            "guardrail_params": guardrail_params,
        }
        return _FakeModelVersion(
            talent_pedigree_weight, narrative_trope_weight, guardrail_params
        )


class _AuditScorecardStub:
    """Minimal ``AuditScorecardLike``: exposes only ``mape`` (R11.8)."""

    def __init__(self, mape: Decimal | None) -> None:
        self._mape = mape

    @property
    def mape(self) -> Decimal | None:
        return self._mape


def _actor() -> UserContext:
    """A throwaway actor; the fork itself is actor-agnostic."""
    return UserContext(
        user_id=uuid.uuid4(),
        display_name="Test Analyst",
        role=UserRole.DATA_ANALYST,
    )


# MAPE values at or below the 10% threshold, drawn at the 2-decimal precision the
# scorecard reports (R11.5), spanning the whole [0, 10] no-op band. ``None`` is
# included explicitly as the "no eligible metrics" case (R11.8) that must also
# be a no-op.
_sub_threshold_mape = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0.00"),
        max_value=MAPE_THRESHOLD,  # 10 — inclusive upper bound (R12.5).
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)


# Feature: cineroi-ai, Property 20: Calibration no-op below threshold
@given(mape=_sub_threshold_mape)
@settings(max_examples=200)
async def test_no_adjustment_at_or_below_threshold(mape: Decimal | None) -> None:
    """Validates: Requirements 12.5

    For any audit with MAPE of 10 percent or less (and for a ``None`` MAPE), the
    controller reports no adjustment is required — ``adjustment_required`` is
    ``False`` with ``new_model_version_id`` and ``offsets`` both ``None`` — and
    it NEVER forks a new model version, so the active weights are left unchanged.
    """
    engine = _FakeModelVersioningEngine()
    controller = Calibration_Controller(engine)

    before_talent = engine.active.talent_pedigree_weight
    before_narrative = engine.active.narrative_trope_weight

    result = await controller.evaluate_and_apply(_AuditScorecardStub(mape), _actor())

    # The no-op result shape (R12.5).
    assert result["adjustment_required"] is False
    assert result["new_model_version_id"] is None
    assert result["offsets"] is None

    # The witness: no version was ever created on the sub-threshold branch.
    assert engine.create_version_calls == 0

    # The active weights are untouched (identity preserved, R12.5).
    assert engine.active.talent_pedigree_weight == before_talent
    assert engine.active.narrative_trope_weight == before_narrative


# Positive control: ensures the no-op test above is not vacuous by proving the
# same fakes DO drive a fork when MAPE clearly exceeds the threshold (R12.3).
async def test_positive_control_above_threshold_creates_version() -> None:
    """Validates: Requirements 12.5 (non-vacuity for the no-op property)

    With a MAPE well above 10 percent the controller applies a calibration:
    ``adjustment_required`` is ``True``, a new model-version id is returned, and
    ``create_version`` WAS invoked exactly once. This guards against a controller
    (or test) that could pass the no-op property simply by never calibrating.
    """
    engine = _FakeModelVersioningEngine()
    controller = Calibration_Controller(engine)

    result = await controller.evaluate_and_apply(
        _AuditScorecardStub(Decimal("25.00")), _actor()
    )

    assert result["adjustment_required"] is True
    assert result["new_model_version_id"] is not None
    assert result["offsets"] is not None
    assert engine.create_version_calls == 1
