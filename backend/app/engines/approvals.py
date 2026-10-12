"""Approval_Workflow: multi-tier executive sign-off on high-value decisions (R20.3-R20.5).

High-budget greenlights are too consequential to be finalized by a single
actor. This engine implements the governance gate the design calls for: a
GREENLIGHT decision whose *normalized* acquisition cost exceeds the high-budget
threshold requires sign-off from both a CHIEF_CONTENT_OFFICER and a CFO before
it may be finalized (R20.3), every approve / reject / override act is recorded
with its actor and a timestamp (R20.4), and finalization is blocked — reporting
exactly which approvals remain — until all required sign-offs are present (R20.5).

Threshold is defined in base currency (R20 ↔ R21)
-------------------------------------------------
Per the design's cross-cutting decision, the 25,000,000 threshold in R20.3 is
interpreted as **25,000,000 USD (Base_Currency)**. The workflow compares a
decision's ``normalized_cost_usd`` — the USD value the currency layer produced
during valuation (R21.2) — against the threshold, never a native-currency
figure. A ₹2.4B INR acquisition and a €27M EUR acquisition are judged by the
same base-currency yardstick. A decision with no normalized cost yet, or whose
cost is at or below the threshold, or whose recommendation is not GREENLIGHT,
needs no multi-tier sign-off.

Required roles and how approvals are counted
--------------------------------------------
A high-budget GREENLIGHT requires the two executive roles
:data:`REQUIRED_SIGN_OFF_ROLES` = {CHIEF_CONTENT_OFFICER, CFO}. The workflow row
persists this set in ``required_roles``. Sign-off is counted from the recorded
APPROVE actions: an action's actor's role (resolved from ``users``) satisfies the
corresponding required role. REJECT and OVERRIDE acts are recorded for the audit
trail (R20.4) but do not count toward satisfying a required approval — only an
explicit APPROVE does. A required role is *outstanding* until at least one
APPROVE from an actor holding that role is on record.

Statelessness and persistence
------------------------------
Like the other engines, this one owns no persistence of its own: it reads and
writes exclusively through injected repositories
(:class:`~app.repositories.approvals.ApprovalWorkflowRepository`,
:class:`~app.repositories.approvals.ApprovalActionRepository`,
:class:`~app.repositories.financial_projections.FinancialProjectionRepository`,
and :class:`~app.repositories.users.UserRepository`). Repository methods flush
rather than commit, so the surrounding request/task unit-of-work controls the
transaction boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ApprovalsPendingError, NotFoundError
from app.core.security import UserContext, UserRole
from app.models.approval import ApprovalAction, ApprovalWorkflow
from app.repositories.approvals import (
    ApprovalActionRepository,
    ApprovalWorkflowRepository,
)
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.users import UserRepository

__all__ = [
    "HIGH_BUDGET_THRESHOLD_USD",
    "REQUIRED_SIGN_OFF_ROLES",
    "GREENLIGHT_STATUS",
    "ApprovalActionType",
    "FinalizationStatus",
    "Approval_Workflow",
]


#: The high-budget sign-off threshold, in Base_Currency (USD). A GREENLIGHT
#: decision whose ``normalized_cost_usd`` is *strictly greater* than this amount
#: requires executive multi-tier sign-off (R20.3). The comparison is strict
#: (``>``), matching "greater than 25000000" in the acceptance criterion.
HIGH_BUDGET_THRESHOLD_USD: Decimal = Decimal("25000000")

#: Recommendation status that triggers the high-budget approval gate (R20.3).
GREENLIGHT_STATUS = "GREENLIGHT"

#: The roles whose sign-off a high-budget GREENLIGHT requires (R20.3). Ordered
#: for deterministic reporting of outstanding approvals.
REQUIRED_SIGN_OFF_ROLES: tuple[UserRole, ...] = (
    UserRole.CHIEF_CONTENT_OFFICER,
    UserRole.CFO,
)


class ApprovalActionType(str):
    """The recordable sign-off act kinds, mirroring the DB CHECK constraint.

    Kept as plain string constants (the ORM column is TEXT with a CHECK on these
    values) so callers may pass the string directly; :meth:`Approval_Workflow.
    record_action` validates against this set.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    OVERRIDE = "OVERRIDE"


_VALID_ACTIONS: frozenset[str] = frozenset(
    {ApprovalActionType.APPROVE, ApprovalActionType.REJECT, ApprovalActionType.OVERRIDE}
)


@dataclass(frozen=True)
class FinalizationStatus:
    """The result of evaluating whether a decision may be finalized (R20.5).

    Attributes:
        can_finalize: ``True`` only when no required approval remains
            outstanding. A decision that needs no sign-off at all (not a
            high-budget GREENLIGHT, or no workflow) is finalizable.
        required_roles: The roles whose sign-off the decision requires. Empty
            when the decision does not need multi-tier sign-off.
        outstanding_roles: The required roles that have not yet recorded an
            APPROVE. Empty exactly when :attr:`can_finalize` is ``True``.
        approved_roles: The required roles that have recorded an APPROVE.
    """

    can_finalize: bool
    required_roles: tuple[UserRole, ...]
    outstanding_roles: tuple[UserRole, ...]
    approved_roles: tuple[UserRole, ...]


class Approval_Workflow:
    """Govern executive sign-off and finalization of high-budget decisions (R20.3-R20.5).

    The workflow is stateless beyond its injected repositories; construct it per
    request/unit-of-work with repositories bound to the active session.
    """

    def __init__(
        self,
        *,
        workflows: ApprovalWorkflowRepository,
        actions: ApprovalActionRepository,
        projections: FinancialProjectionRepository,
        users: UserRepository,
    ) -> None:
        """Bind the workflow to its persistence collaborators.

        Args:
            workflows: Repository for ``approval_workflows`` rows.
            actions: Repository for ``approval_actions`` rows.
            projections: Repository for ``financial_projections`` (the decisions
                being governed), used to read the recommendation status and
                normalized cost that determine whether sign-off is required.
            users: Repository for ``users``, used to resolve each action actor's
                role when counting approvals.
        """
        self._workflows = workflows
        self._actions = actions
        self._projections = projections
        self._users = users

    # -- threshold logic (R20.3) ------------------------------------------- #

    @staticmethod
    def requires_sign_off(
        recommendation_status: str | None, normalized_cost_usd: Decimal | None
    ) -> bool:
        """Whether a decision needs high-budget multi-tier sign-off (R20.3).

        Pure predicate: sign-off is required only for a GREENLIGHT recommendation
        whose normalized (base-currency, USD) cost is strictly greater than
        :data:`HIGH_BUDGET_THRESHOLD_USD`. A missing status/cost, a non-GREENLIGHT
        status, or a cost at or below the threshold needs no sign-off.

        Args:
            recommendation_status: The decision's recommendation status.
            normalized_cost_usd: The decision's cost normalized to USD (R21.2),
                or ``None`` when not yet normalized.

        Returns:
            ``True`` when CCO + CFO sign-off is required, else ``False``.
        """
        if recommendation_status != GREENLIGHT_STATUS:
            return False
        if normalized_cost_usd is None:
            return False
        return normalized_cost_usd > HIGH_BUDGET_THRESHOLD_USD

    async def ensure_workflow(
        self, decision_id: uuid.UUID
    ) -> ApprovalWorkflow | None:
        """Create (if needed) and return the sign-off workflow for a decision (R20.3).

        Reads the decision's recommendation status and normalized cost; when the
        decision is a high-budget GREENLIGHT and no workflow yet exists, creates
        one whose ``required_roles`` is :data:`REQUIRED_SIGN_OFF_ROLES`. Returns
        ``None`` when the decision does not require sign-off (and no workflow
        exists), so callers can treat "no workflow" as "no gate."

        Idempotent: if a workflow already exists for the decision it is returned
        unchanged rather than duplicated.

        Raises:
            NotFoundError: The referenced decision does not exist.
        """
        existing = await self._workflows.get_for_decision(decision_id)
        if existing is not None:
            return existing

        decision = await self._projections.get(decision_id)
        if decision is None:
            raise NotFoundError(
                "The referenced decision was not found.",
                details={"decision_id": str(decision_id)},
            )

        if not self.requires_sign_off(
            decision.recommendation_status, decision.normalized_cost_usd
        ):
            return None

        workflow = ApprovalWorkflow(
            decision_id=decision_id,
            required_roles=[role.value for role in REQUIRED_SIGN_OFF_ROLES],
            finalized=False,
        )
        return await self._workflows.create(workflow)

    # -- recording acts (R20.4) -------------------------------------------- #

    async def record_action(
        self,
        decision_id: uuid.UUID,
        action: str,
        actor: UserContext,
    ) -> ApprovalAction:
        """Record an approve / reject / override act with actor and timestamp (R20.4).

        Ensures a workflow exists for the decision (creating one for a
        high-budget GREENLIGHT if necessary) and appends an
        :class:`~app.models.approval.ApprovalAction` capturing the acting
        identity (``actor_id``) and the time of the act (``acted_at``, defaulted
        by the database to ``now()``).

        Args:
            decision_id: The decision the act applies to.
            action: One of ``APPROVE`` / ``REJECT`` / ``OVERRIDE``.
            actor: The authenticated principal performing the act.

        Returns:
            The persisted action row (with its server-assigned ``acted_at``).

        Raises:
            ValueError: ``action`` is not one of the recordable act kinds.
            NotFoundError: The decision does not exist, or does not require a
                sign-off workflow (nothing to record an act against).
        """
        if action not in _VALID_ACTIONS:
            raise ValueError(
                f"Unknown approval action {action!r}; "
                f"expected one of {sorted(_VALID_ACTIONS)}."
            )

        workflow = await self.ensure_workflow(decision_id)
        if workflow is None:
            raise NotFoundError(
                "No approval workflow exists for this decision; it does not "
                "require multi-tier sign-off.",
                details={"decision_id": str(decision_id)},
            )

        record = ApprovalAction(
            workflow_id=workflow.workflow_id,
            actor_id=actor.user_id,
            action=action,
        )
        return await self._actions.create(record)

    # -- finalization gating (R20.5) --------------------------------------- #

    async def can_finalize(self, decision_id: uuid.UUID) -> FinalizationStatus:
        """Report whether a decision may be finalized and which approvals remain (R20.5).

        A decision with no sign-off workflow (not a high-budget GREENLIGHT) is
        finalizable with no required or outstanding roles. For a governed
        decision, the required roles are read from the workflow; a role counts as
        approved when at least one recorded APPROVE act was performed by an actor
        holding that role. Finalization is permitted if and only if no required
        role remains outstanding.

        Args:
            decision_id: The decision to evaluate.

        Returns:
            A :class:`FinalizationStatus` describing the gate.
        """
        workflow = await self._workflows.get_for_decision(decision_id)
        if workflow is None:
            # No governance gate: nothing to sign off, so finalization is allowed.
            return FinalizationStatus(
                can_finalize=True,
                required_roles=(),
                outstanding_roles=(),
                approved_roles=(),
            )

        required = self._parse_required_roles(workflow.required_roles)
        approved = await self._approved_roles(workflow.workflow_id)

        approved_required = tuple(r for r in required if r in approved)
        outstanding = tuple(r for r in required if r not in approved)

        return FinalizationStatus(
            can_finalize=not outstanding,
            required_roles=required,
            outstanding_roles=outstanding,
            approved_roles=approved_required,
        )

    async def finalize(self, decision_id: uuid.UUID) -> ApprovalWorkflow | None:
        """Finalize a decision, enforcing the sign-off gate (R20.5).

        If the decision requires sign-off and any required approval remains
        outstanding, raises :class:`~app.core.errors.ApprovalsPendingError`
        (mapped to ``409 APPROVALS_PENDING``) carrying the outstanding roles.
        When all required approvals are present the workflow's ``finalized`` flag
        is set and the updated row is returned. A decision with no governance gate
        requires no finalization step and returns ``None``.

        Args:
            decision_id: The decision to finalize.

        Returns:
            The finalized workflow row, or ``None`` when the decision has no gate.

        Raises:
            ApprovalsPendingError: Required approvals remain outstanding (R20.5).
        """
        status = await self.can_finalize(decision_id)
        if not status.required_roles:
            # No gate — nothing to finalize at the approval layer.
            return None

        if not status.can_finalize:
            raise ApprovalsPendingError(
                details={
                    "decision_id": str(decision_id),
                    "outstanding_roles": [r.value for r in status.outstanding_roles],
                    "required_roles": [r.value for r in status.required_roles],
                    "approved_roles": [r.value for r in status.approved_roles],
                },
            )

        workflow = await self._workflows.get_for_decision(decision_id)
        assert workflow is not None  # guaranteed by required_roles being non-empty
        return await self._workflows.update(workflow, finalized=True)

    # -- helpers ----------------------------------------------------------- #

    async def _approved_roles(self, workflow_id: uuid.UUID) -> frozenset[UserRole]:
        """Resolve the set of roles that have recorded an APPROVE for a workflow.

        Only APPROVE acts count toward satisfying a required sign-off; REJECT and
        OVERRIDE are recorded for the audit trail but do not approve. Each
        approving action's actor is resolved to its role via the users
        repository; unknown or role-less actors are ignored.
        """
        actions = await self._actions.list_for_workflow(workflow_id)
        roles: set[UserRole] = set()
        for act in actions:
            if act.action != ApprovalActionType.APPROVE:
                continue
            if act.actor_id is None:
                continue
            user = await self._users.get(act.actor_id)
            if user is None:
                continue
            try:
                roles.add(UserRole(user.user_role))
            except ValueError:
                # An actor carrying a role outside the enum cannot satisfy a
                # required sign-off; skip rather than fail the gate evaluation.
                continue
        return frozenset(roles)

    @staticmethod
    def _parse_required_roles(raw: object) -> tuple[UserRole, ...]:
        """Coerce the stored ``required_roles`` JSON into an ordered role tuple.

        The column stores a JSON list of role names (e.g.
        ``["CHIEF_CONTENT_OFFICER", "CFO"]``). Names are mapped back to
        :class:`UserRole`, preserving stored order and dropping any unknown
        entry (defensive against hand-edited rows).
        """
        if not isinstance(raw, (list, tuple)):
            return ()
        result: list[UserRole] = []
        for name in raw:
            try:
                result.append(UserRole(name))
            except ValueError:
                continue
        return tuple(result)
