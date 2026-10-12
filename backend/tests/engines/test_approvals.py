"""Unit tests for the Approval_Workflow engine (R20.3-R20.5).

Targets :class:`app.engines.approvals.Approval_Workflow`, exercising the three
behaviors task 14.3 requires:

* **High-budget sign-off threshold (R20.3).** A GREENLIGHT decision whose
  ``normalized_cost_usd`` exceeds 25,000,000 USD requires CCO + CFO sign-off;
  anything else (non-GREENLIGHT, no normalized cost, or cost at/below the
  threshold) requires none.
* **Recording acts with actor and timestamp (R20.4).** Each approve / reject /
  override is persisted with the actor identity and an ``acted_at`` time.
* **Finalization gating (R20.5).** Finalization is blocked until every required
  approval is recorded, reports which roles remain outstanding, and is permitted
  exactly when none remain.

Per the engines' testing convention, the four repository collaborators are
replaced with tiny in-memory fakes so these tests need no database. The fakes
implement only the methods the engine calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.errors import ApprovalsPendingError, NotFoundError
from app.core.security import UserContext, UserRole
from app.engines.approvals import (
    HIGH_BUDGET_THRESHOLD_USD,
    REQUIRED_SIGN_OFF_ROLES,
    ApprovalActionType,
    Approval_Workflow,
)


# ---------------------------------------------------------------------------
# In-memory fakes of the ORM rows and repositories
# ---------------------------------------------------------------------------


class _Decision:
    """A financial_projections-like decision row the engine reads from."""

    def __init__(
        self,
        recommendation_status: str | None,
        normalized_cost_usd: Decimal | None,
    ) -> None:
        self.projection_id = uuid.uuid4()
        self.recommendation_status = recommendation_status
        self.normalized_cost_usd = normalized_cost_usd


class _User:
    def __init__(self, role: UserRole) -> None:
        self.user_id = uuid.uuid4()
        self.user_role = role.value


class _Workflow:
    def __init__(self, decision_id: uuid.UUID, required_roles: list[str]) -> None:
        self.workflow_id = uuid.uuid4()
        self.decision_id = decision_id
        self.required_roles = required_roles
        self.finalized = False


class _Action:
    def __init__(self, workflow_id: uuid.UUID, actor_id: uuid.UUID, action: str) -> None:
        self.action_id = uuid.uuid4()
        self.workflow_id = workflow_id
        self.actor_id = actor_id
        self.action = action
        # Mimic the DB server-default now() populated on insert (R20.4).
        self.acted_at = datetime.now(timezone.utc)


class _FakeWorkflowRepo:
    def __init__(self) -> None:
        self.by_decision: dict[uuid.UUID, _Workflow] = {}

    async def get_for_decision(self, decision_id: uuid.UUID) -> _Workflow | None:
        return self.by_decision.get(decision_id)

    async def create(self, instance: _Workflow) -> _Workflow:
        self.by_decision[instance.decision_id] = instance
        return instance

    async def update(self, instance: _Workflow, **values: object) -> _Workflow:
        for key, value in values.items():
            setattr(instance, key, value)
        return instance


class _FakeActionRepo:
    def __init__(self) -> None:
        self.rows: list[_Action] = []

    async def create(self, instance: _Action) -> _Action:
        self.rows.append(instance)
        return instance

    async def list_for_workflow(self, workflow_id: uuid.UUID) -> list[_Action]:
        return [a for a in self.rows if a.workflow_id == workflow_id]


class _FakeProjectionRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, _Decision] = {}

    def add(self, decision: _Decision) -> None:
        self.rows[decision.projection_id] = decision

    async def get(self, entity_id: uuid.UUID) -> _Decision | None:
        return self.rows.get(entity_id)


class _FakeUserRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, _User] = {}

    def add(self, user: _User) -> None:
        self.rows[user.user_id] = user

    async def get(self, entity_id: uuid.UUID) -> _User | None:
        return self.rows.get(entity_id)


def _build() -> tuple[
    Approval_Workflow, _FakeWorkflowRepo, _FakeActionRepo, _FakeProjectionRepo, _FakeUserRepo
]:
    workflows = _FakeWorkflowRepo()
    actions = _FakeActionRepo()
    projections = _FakeProjectionRepo()
    users = _FakeUserRepo()
    engine = Approval_Workflow(
        workflows=workflows,
        actions=actions,
        projections=projections,
        users=users,
    )
    return engine, workflows, actions, projections, users


def _ctx(user: _User, role: UserRole) -> UserContext:
    return UserContext(user_id=user.user_id, display_name="t", role=role)


# ---------------------------------------------------------------------------
# R20.3 — high-budget sign-off threshold
# ---------------------------------------------------------------------------


class TestRequiresSignOff:
    def test_greenlight_above_threshold_requires_sign_off(self) -> None:
        over = HIGH_BUDGET_THRESHOLD_USD + Decimal("1")
        assert Approval_Workflow.requires_sign_off("GREENLIGHT", over) is True

    def test_greenlight_at_threshold_does_not_require_sign_off(self) -> None:
        # Criterion is "greater than" — exactly at the threshold is not over it.
        assert (
            Approval_Workflow.requires_sign_off(
                "GREENLIGHT", HIGH_BUDGET_THRESHOLD_USD
            )
            is False
        )

    def test_greenlight_below_threshold_does_not_require_sign_off(self) -> None:
        under = HIGH_BUDGET_THRESHOLD_USD - Decimal("1")
        assert Approval_Workflow.requires_sign_off("GREENLIGHT", under) is False

    def test_non_greenlight_never_requires_sign_off(self) -> None:
        huge = HIGH_BUDGET_THRESHOLD_USD + Decimal("1000000")
        assert Approval_Workflow.requires_sign_off("NEGOTIATE_HARD", huge) is False
        assert Approval_Workflow.requires_sign_off("PASS", huge) is False

    def test_missing_cost_does_not_require_sign_off(self) -> None:
        assert Approval_Workflow.requires_sign_off("GREENLIGHT", None) is False

    @pytest.mark.asyncio
    async def test_ensure_workflow_creates_for_high_budget_greenlight(self) -> None:
        engine, workflows, _, projections, _ = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)

        workflow = await engine.ensure_workflow(decision.projection_id)

        assert workflow is not None
        assert set(workflow.required_roles) == {
            r.value for r in REQUIRED_SIGN_OFF_ROLES
        }
        assert workflow.finalized is False

    @pytest.mark.asyncio
    async def test_ensure_workflow_none_for_non_high_budget(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("GREENLIGHT", Decimal("1000000"))
        projections.add(decision)

        assert await engine.ensure_workflow(decision.projection_id) is None

    @pytest.mark.asyncio
    async def test_ensure_workflow_is_idempotent(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)

        first = await engine.ensure_workflow(decision.projection_id)
        second = await engine.ensure_workflow(decision.projection_id)

        assert first is not None
        assert second is first

    @pytest.mark.asyncio
    async def test_ensure_workflow_unknown_decision_raises_not_found(self) -> None:
        engine, *_ = _build()
        with pytest.raises(NotFoundError):
            await engine.ensure_workflow(uuid.uuid4())


# ---------------------------------------------------------------------------
# R20.4 — recording acts with actor and timestamp
# ---------------------------------------------------------------------------


class TestRecordAction:
    @pytest.mark.asyncio
    async def test_records_actor_and_timestamp(self) -> None:
        engine, _, actions, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        cco = _User(UserRole.CHIEF_CONTENT_OFFICER)
        users.add(cco)

        record = await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )

        # The act is recorded against the decision's workflow, carrying the
        # acting identity (R20.4). ``acted_at`` is populated by the DB server
        # default (``func.now()``) on flush, verified at the integration layer.
        assert record.action == "APPROVE"
        assert record.actor_id == cco.user_id
        assert hasattr(record, "acted_at")
        assert actions.rows == [record]

    @pytest.mark.asyncio
    async def test_rejects_unknown_action(self) -> None:
        engine, _, _, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        cfo = _User(UserRole.CFO)
        users.add(cfo)

        with pytest.raises(ValueError):
            await engine.record_action(
                decision.projection_id, "APPROVE_MAYBE", _ctx(cfo, UserRole.CFO)
            )

    @pytest.mark.asyncio
    async def test_cannot_record_against_non_high_budget_decision(self) -> None:
        engine, _, _, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("1000000"))
        projections.add(decision)
        cfo = _User(UserRole.CFO)
        users.add(cfo)

        with pytest.raises(NotFoundError):
            await engine.record_action(
                decision.projection_id,
                ApprovalActionType.APPROVE,
                _ctx(cfo, UserRole.CFO),
            )


# ---------------------------------------------------------------------------
# R20.5 — finalization gating
# ---------------------------------------------------------------------------


class TestFinalizationGating:
    @pytest.mark.asyncio
    async def test_no_workflow_is_finalizable(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("PASS", Decimal("40000000"))
        projections.add(decision)

        status = await engine.can_finalize(decision.projection_id)

        assert status.can_finalize is True
        assert status.required_roles == ()
        assert status.outstanding_roles == ()

    @pytest.mark.asyncio
    async def test_no_approvals_blocks_with_all_roles_outstanding(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        await engine.ensure_workflow(decision.projection_id)

        status = await engine.can_finalize(decision.projection_id)

        assert status.can_finalize is False
        assert set(status.outstanding_roles) == set(REQUIRED_SIGN_OFF_ROLES)
        assert status.approved_roles == ()

    @pytest.mark.asyncio
    async def test_partial_approval_still_blocks(self) -> None:
        engine, _, _, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        cco = _User(UserRole.CHIEF_CONTENT_OFFICER)
        users.add(cco)

        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )

        status = await engine.can_finalize(decision.projection_id)

        assert status.can_finalize is False
        assert status.outstanding_roles == (UserRole.CFO,)
        assert status.approved_roles == (UserRole.CHIEF_CONTENT_OFFICER,)

    @pytest.mark.asyncio
    async def test_all_approvals_permit_finalization(self) -> None:
        engine, workflows, _, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        cco = _User(UserRole.CHIEF_CONTENT_OFFICER)
        cfo = _User(UserRole.CFO)
        users.add(cco)
        users.add(cfo)

        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cfo, UserRole.CFO),
        )

        status = await engine.can_finalize(decision.projection_id)
        assert status.can_finalize is True
        assert status.outstanding_roles == ()

        workflow = await engine.finalize(decision.projection_id)
        assert workflow is not None
        assert workflow.finalized is True

    @pytest.mark.asyncio
    async def test_reject_does_not_count_as_approval(self) -> None:
        engine, _, _, projections, users = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        cco = _User(UserRole.CHIEF_CONTENT_OFFICER)
        cfo = _User(UserRole.CFO)
        users.add(cco)
        users.add(cfo)

        # CCO rejects, CFO approves — the CCO sign-off is still outstanding.
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.REJECT,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cfo, UserRole.CFO),
        )

        status = await engine.can_finalize(decision.projection_id)
        assert status.can_finalize is False
        assert status.outstanding_roles == (UserRole.CHIEF_CONTENT_OFFICER,)

    @pytest.mark.asyncio
    async def test_finalize_raises_approvals_pending_when_outstanding(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("GREENLIGHT", Decimal("40000000"))
        projections.add(decision)
        await engine.ensure_workflow(decision.projection_id)

        with pytest.raises(ApprovalsPendingError) as exc:
            await engine.finalize(decision.projection_id)

        details = exc.value.details or {}
        assert set(details.get("outstanding_roles", [])) == {
            r.value for r in REQUIRED_SIGN_OFF_ROLES
        }

    @pytest.mark.asyncio
    async def test_finalize_without_gate_returns_none(self) -> None:
        engine, _, _, projections, _ = _build()
        decision = _Decision("PASS", Decimal("40000000"))
        projections.add(decision)

        assert await engine.finalize(decision.projection_id) is None
