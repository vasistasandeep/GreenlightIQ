"""Pure domain state machine for the acquisition deal-stage lifecycle.

A title moves through a human-managed acquisition pipeline that is orthogonal to
the AI's ``recommendation_status``: the AI advises, the buyer drives the deal.
The lifecycle is:

    SCREENING -> EVALUATED -> IN_NEGOTIATION -> APPROVED -> CLOSED_WON
                                                        \\-> CLOSED_LOST
    (and most live stages may be abandoned to PASSED)

This module is pure: it enumerates the stages, encodes the allowed transitions,
and validates a proposed move. It performs no I/O and holds no state, so it is
exhaustively unit-testable and reusable by the API layer and any future worker.
"""

from __future__ import annotations

from enum import Enum


class DealStage(str, Enum):
    """A title's position in the human acquisition pipeline."""

    SCREENING = "SCREENING"
    EVALUATED = "EVALUATED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    APPROVED = "APPROVED"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"
    PASSED = "PASSED"


#: The stage every title starts in when first ingested.
INITIAL_STAGE: DealStage = DealStage.SCREENING

#: Terminal stages: a deal that has reached one of these cannot move again.
TERMINAL_STAGES: frozenset[DealStage] = frozenset(
    {DealStage.CLOSED_WON, DealStage.CLOSED_LOST, DealStage.PASSED}
)

#: The forward progression through the live pipeline.
_FORWARD: dict[DealStage, DealStage] = {
    DealStage.SCREENING: DealStage.EVALUATED,
    DealStage.EVALUATED: DealStage.IN_NEGOTIATION,
    DealStage.IN_NEGOTIATION: DealStage.APPROVED,
    DealStage.APPROVED: DealStage.CLOSED_WON,
}

#: Allowed transitions out of each stage (R-governance): one step forward along
#: the pipeline, plus an abandon-to-PASSED escape hatch from any live stage, plus
#: the APPROVED -> CLOSED_LOST path (a deal can fall through after approval).
#: Terminal stages have no outgoing transitions.
ALLOWED_TRANSITIONS: dict[DealStage, frozenset[DealStage]] = {
    DealStage.SCREENING: frozenset({DealStage.EVALUATED, DealStage.PASSED}),
    DealStage.EVALUATED: frozenset({DealStage.IN_NEGOTIATION, DealStage.PASSED}),
    DealStage.IN_NEGOTIATION: frozenset({DealStage.APPROVED, DealStage.PASSED}),
    DealStage.APPROVED: frozenset(
        {DealStage.CLOSED_WON, DealStage.CLOSED_LOST, DealStage.PASSED}
    ),
    DealStage.CLOSED_WON: frozenset(),
    DealStage.CLOSED_LOST: frozenset(),
    DealStage.PASSED: frozenset(),
}


class IllegalStageTransition(ValueError):
    """Raised when a proposed deal-stage transition is not allowed."""

    def __init__(self, from_stage: DealStage, to_stage: DealStage) -> None:
        self.from_stage = from_stage
        self.to_stage = to_stage
        super().__init__(
            f"Cannot move a deal from {from_stage.value} to {to_stage.value}."
        )


def coerce_stage(value: str | DealStage | None) -> DealStage:
    """Coerce a raw value to a :class:`DealStage`, defaulting to the initial stage.

    A ``None`` (e.g. a title persisted before the column existed) maps to
    :data:`INITIAL_STAGE`. An unrecognized string raises ``ValueError``.
    """
    if value is None:
        return INITIAL_STAGE
    if isinstance(value, DealStage):
        return value
    return DealStage(value)


def allowed_next_stages(current: DealStage) -> list[DealStage]:
    """Return the stages ``current`` may transition to, in a stable order."""
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    # Stable, enum-declaration order so the UI lists options predictably.
    return [stage for stage in DealStage if stage in allowed]


def is_transition_allowed(current: DealStage, target: DealStage) -> bool:
    """Return True when moving from ``current`` to ``target`` is permitted."""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: DealStage, target: DealStage) -> DealStage:
    """Validate a transition, returning ``target`` or raising on an illegal move.

    A no-op (``current == target``) is rejected as an illegal transition: callers
    should not record a stage change that does not change the stage.
    """
    if not is_transition_allowed(current, target):
        raise IllegalStageTransition(current, target)
    return target


#: Human-friendly labels for the UI (kept here so backend and docs agree).
STAGE_LABELS: dict[DealStage, str] = {
    DealStage.SCREENING: "Screening",
    DealStage.EVALUATED: "Evaluated",
    DealStage.IN_NEGOTIATION: "In Negotiation",
    DealStage.APPROVED: "Approved",
    DealStage.CLOSED_WON: "Closed - Won",
    DealStage.CLOSED_LOST: "Closed - Lost",
    DealStage.PASSED: "Passed",
}


__all__ = [
    "DealStage",
    "INITIAL_STAGE",
    "TERMINAL_STAGES",
    "ALLOWED_TRANSITIONS",
    "IllegalStageTransition",
    "coerce_stage",
    "allowed_next_stages",
    "is_transition_allowed",
    "validate_transition",
    "STAGE_LABELS",
]