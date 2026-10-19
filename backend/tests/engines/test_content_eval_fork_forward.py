"""Calibration fork carries the ``content_eval`` params forward intact (Task 11).

The Content_Eval_System stores its params under
``model_versions.guardrail_params['content_eval']`` (JSONB, no migration). Those
params must survive a calibration fork unchanged: ``calibration.py`` forks a new
immutable version with ``guardrail_params=dict(active.guardrail_params)``, a
shallow dict copy that carries every guardrail sub-object -- including
``content_eval`` -- forward verbatim (design Component 9, R5.1/R5.3).

This test pins that behavior WITHOUT a live database, mirroring the in-memory
fake-engine approach of ``test_calibration_properties.py``. The controller only
calls ``read_active`` and ``create_version`` on its engine collaborator, so the
fake implements exactly those: ``read_active`` returns an active version whose
``guardrail_params`` includes a populated ``content_eval`` block, and
``create_version`` records the ``guardrail_params`` it was handed. We drive a
MAPE above the threshold so a fork actually happens, then assert the forked
``content_eval`` block is present, equal by value, and parses to the same
:class:`~app.domain.content_eval.ContentEvalParams` as the original -- i.e. the
fork preserved it intact.

Validates: Requirements 5.1, 5.3
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.security import UserContext, UserRole
from app.domain import content_eval as ce
from app.engines.calibration import Calibration_Controller


def _content_eval_block() -> dict:
    """A fully populated content_eval sub-object (link ON, non-default nested)."""
    return {
        "version_label": "churn-fit-7",
        "fit_dataset_version": "kpi-2024-02",
        "dominant_label_type": "SYNTHETIC",
        "link_churn_to_ltv": True,
        "viewing_hours": {
            "intercept": "7.0",
            "betas": {"normalized_rating": "0.55", "franchise_flag": "0.35"},
            "floor": "3",
            "objective": "wape_log",
        },
        "engagement": {
            "watch_time_elasticity": {
                "intercept": "0.75",
                "runtime_weight": "0.09",
                "serialization_lift": "0.13",
                "rating_weight": "0.28",
                "franchise_lift": "0.11",
                "min_value": "0.00",
                "max_value": "3.00",
            },
            "ad_load_receptivity": {
                "centre": "1.00",
                "rating_weight": "0.09",
                "runtime_weight": "0.05",
                "franchise_lift": "0.03",
                "min_value": "0.50",
                "max_value": "1.50",
            },
        },
    }


class _FakeModelVersion:
    """A ModelVersion-like active row exposing what the controller reads."""

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
    """In-memory fake: records the guardrail_params handed to ``create_version``."""

    def __init__(self, guardrail_params: dict[str, object]) -> None:
        self.active = _FakeModelVersion(
            Decimal("0.60"), Decimal("0.40"), guardrail_params
        )
        self.create_version_calls = 0
        self.last_create_kwargs: dict[str, object] | None = None

    async def read_active(self) -> _FakeModelVersion:
        return self.active

    async def create_version(
        self,
        *,
        talent_pedigree_weight: Decimal,
        narrative_trope_weight: Decimal,
        guardrail_params: dict[str, object],
    ) -> _FakeModelVersion:
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
    """Minimal ``AuditScorecardLike``: exposes only ``mape``."""

    def __init__(self, mape: Decimal | None) -> None:
        self._mape = mape

    @property
    def mape(self) -> Decimal | None:
        return self._mape


def _actor() -> UserContext:
    return UserContext(
        user_id=uuid.uuid4(),
        display_name="Test Analyst",
        role=UserRole.DATA_ANALYST,
    )


async def test_calibration_fork_copies_content_eval_forward_intact() -> None:
    """Validates: Requirements 5.1, 5.3

    A calibration fork (MAPE above threshold) must carry the ``content_eval``
    guardrail sub-object forward unchanged. We assert the forked guardrail_params
    contains ``content_eval``, that it is equal by value to the original, and that
    it parses to the same ContentEvalParams -- so the fork preserved it intact.
    """
    original_content_eval = _content_eval_block()
    guardrail_params: dict[str, object] = {
        "cpvh_ceiling_premium": "0.20",
        "content_eval": original_content_eval,
    }
    engine = _FakeModelVersioningEngine(guardrail_params)
    controller = Calibration_Controller(engine)

    # MAPE well above the 10% threshold forces a fork.
    result = await controller.evaluate_and_apply(
        _AuditScorecardStub(Decimal("25.00")), _actor()
    )

    assert result["adjustment_required"] is True
    assert engine.create_version_calls == 1

    forked = engine.last_create_kwargs
    assert forked is not None
    forked_params = forked["guardrail_params"]
    assert isinstance(forked_params, dict)

    # content_eval is carried forward and unchanged by value.
    assert "content_eval" in forked_params
    assert forked_params["content_eval"] == original_content_eval

    # ...and it parses to the identical structured params (link ON preserved).
    before = ce.parse_content_eval_params(original_content_eval)
    after = ce.parse_content_eval_params(forked_params["content_eval"])
    assert after == before
    assert after.link_churn_to_ltv is True
    assert after.source == "MODEL_VERSION"
    assert after.viewing_hours_source == "MODEL_VERSION"
    assert after.watch_time_elasticity_source == "MODEL_VERSION"
    assert after.ad_load_receptivity_source == "MODEL_VERSION"


async def test_fork_forward_survives_round_trip_through_dict_copy() -> None:
    """Validates: Requirements 5.1, 5.3

    The fork uses ``dict(active.guardrail_params)`` (a shallow copy). Confirm the
    copy the controller builds is a distinct dict object but references the same
    ``content_eval`` payload, so nothing is dropped or mutated in transit.
    """
    original_content_eval = _content_eval_block()
    guardrail_params: dict[str, object] = {"content_eval": original_content_eval}
    engine = _FakeModelVersioningEngine(guardrail_params)
    controller = Calibration_Controller(engine)

    await controller.evaluate_and_apply(_AuditScorecardStub(Decimal("30.00")), _actor())

    forked_params = engine.last_create_kwargs["guardrail_params"]  # type: ignore[index]
    # A distinct top-level dict (immutable fork, not the same object)...
    assert forked_params is not guardrail_params
    # ...carrying the content_eval block forward intact.
    assert forked_params["content_eval"] == original_content_eval
