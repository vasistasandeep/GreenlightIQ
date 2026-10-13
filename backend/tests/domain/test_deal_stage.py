"""Tests for the pure deal-stage lifecycle state machine.

Targets ``app.domain.deal_stage``: the allowed-transition matrix, the validator,
and the helpers the API relies on. Mixes explicit example cases for the key
transitions with hypothesis properties that pin the state machine's invariants.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.deal_stage import (
    ALLOWED_TRANSITIONS,
    INITIAL_STAGE,
    TERMINAL_STAGES,
    DealStage,
    IllegalStageTransition,
    allowed_next_stages,
    coerce_stage,
    is_transition_allowed,
    validate_transition,
)

_stages = st.sampled_from(list(DealStage))


class TestExamples:
    def test_initial_stage_is_screening(self) -> None:
        assert INITIAL_STAGE is DealStage.SCREENING

    def test_forward_progression_is_allowed(self) -> None:
        assert is_transition_allowed(DealStage.SCREENING, DealStage.EVALUATED)
        assert is_transition_allowed(DealStage.EVALUATED, DealStage.IN_NEGOTIATION)
        assert is_transition_allowed(DealStage.IN_NEGOTIATION, DealStage.APPROVED)
        assert is_transition_allowed(DealStage.APPROVED, DealStage.CLOSED_WON)

    def test_any_live_stage_can_be_passed(self) -> None:
        for stage in (
            DealStage.SCREENING,
            DealStage.EVALUATED,
            DealStage.IN_NEGOTIATION,
            DealStage.APPROVED,
        ):
            assert is_transition_allowed(stage, DealStage.PASSED)

    def test_approved_may_close_won_or_lost(self) -> None:
        assert is_transition_allowed(DealStage.APPROVED, DealStage.CLOSED_WON)
        assert is_transition_allowed(DealStage.APPROVED, DealStage.CLOSED_LOST)

    def test_cannot_skip_stages(self) -> None:
        assert not is_transition_allowed(DealStage.SCREENING, DealStage.APPROVED)
        assert not is_transition_allowed(DealStage.SCREENING, DealStage.CLOSED_WON)
        assert not is_transition_allowed(DealStage.EVALUATED, DealStage.CLOSED_WON)

    def test_cannot_move_backwards(self) -> None:
        assert not is_transition_allowed(DealStage.EVALUATED, DealStage.SCREENING)
        assert not is_transition_allowed(DealStage.APPROVED, DealStage.IN_NEGOTIATION)

    def test_validate_transition_raises_on_illegal_move(self) -> None:
        with pytest.raises(IllegalStageTransition) as exc:
            validate_transition(DealStage.SCREENING, DealStage.CLOSED_WON)
        assert exc.value.from_stage is DealStage.SCREENING
        assert exc.value.to_stage is DealStage.CLOSED_WON

    def test_validate_transition_returns_target_on_legal_move(self) -> None:
        assert (
            validate_transition(DealStage.SCREENING, DealStage.EVALUATED)
            is DealStage.EVALUATED
        )

    def test_coerce_none_defaults_to_initial(self) -> None:
        assert coerce_stage(None) is INITIAL_STAGE

    def test_coerce_string_and_enum(self) -> None:
        assert coerce_stage("APPROVED") is DealStage.APPROVED
        assert coerce_stage(DealStage.APPROVED) is DealStage.APPROVED

    def test_coerce_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            coerce_stage("NONSENSE")


class TestProperties:
    @given(_stages)
    def test_terminal_stages_have_no_outgoing_transitions(self, stage: DealStage) -> None:
        if stage in TERMINAL_STAGES:
            assert allowed_next_stages(stage) == []

    @given(_stages)
    def test_no_stage_transitions_to_itself(self, stage: DealStage) -> None:
        assert not is_transition_allowed(stage, stage)

    @given(_stages, _stages)
    def test_validate_matches_is_allowed(
        self, current: DealStage, target: DealStage
    ) -> None:
        if is_transition_allowed(current, target):
            assert validate_transition(current, target) is target
        else:
            with pytest.raises(IllegalStageTransition):
                validate_transition(current, target)

    @given(_stages)
    def test_allowed_next_stages_are_exactly_the_matrix_entry(
        self, stage: DealStage
    ) -> None:
        assert set(allowed_next_stages(stage)) == ALLOWED_TRANSITIONS[stage]

    @given(_stages)
    def test_every_stage_has_a_matrix_entry(self, stage: DealStage) -> None:
        assert stage in ALLOWED_TRANSITIONS