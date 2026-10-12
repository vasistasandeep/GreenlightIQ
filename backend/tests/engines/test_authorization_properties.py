"""Property-based tests for the authorization and approval matrix (R20, R28).

Targets the two engines that govern *who may do what* and *which high-value
decisions may be finalized*:

* :class:`app.engines.rbac.RBACService` — operation-level authorization
  (override gating, R20.2) and confidential-record/field scoping by role and
  authorized territory (R28.2, R28.4). The service is pure, so these properties
  drive it directly with generated :class:`~app.core.security.UserContext`
  actors and plain record mappings.
* :class:`app.engines.approvals.Approval_Workflow` — the high-budget sign-off
  threshold in base currency (R20.3) and finalization gating (R20.5). Following
  the engines' testing convention (see ``tests/engines/test_approvals.py`` and
  ``test_model_versioning_properties.py``), the workflow's four repository
  collaborators are replaced with tiny in-memory fakes so the properties need no
  database. The fakes implement only the methods the engine calls and mirror the
  server-side behaviour the engine relies on (generated ids, append-only action
  list, role resolution via the users repo).

Covers design Property 26 (high-budget approval threshold in base currency),
Property 27 (finalization gating), Property 28 (override authorization matrix),
and Property 29 (confidential access scoping), validating Requirements 20.2,
20.3, 20.5, 28.2, and 28.4. Each property runs at least 100 generated examples.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import (
    ApprovalsPendingError,
    ForbiddenError,
    ForbiddenOverrideError,
)
from app.core.security import UserContext, UserRole
from app.engines.approvals import (
    HIGH_BUDGET_THRESHOLD_USD,
    REQUIRED_SIGN_OFF_ROLES,
    ApprovalActionType,
    Approval_Workflow,
    GREENLIGHT_STATUS,
)
from app.engines.rbac import (
    CONFIDENTIAL_ACCESS_ROLES,
    OVERRIDE_ROLES,
    TERRITORY_UNRESTRICTED_ROLES,
    WITHHELD_FIELDS_KEY,
    Operation,
    RBACService,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_ROLES = tuple(UserRole)

#: A pool of territory identifiers the generators draw from. Kept small so the
#: "record territory is / is not in the actor's authorized set" branch is
#: actually exercised in both directions across examples.
_TERRITORIES = ("US", "GB", "IN", "EU", "JP", "BR")

#: Recommendation statuses a decision may carry. Includes GREENLIGHT (the only
#: one that can gate on budget) plus the non-greenlight statuses that must never
#: require sign-off, and ``None`` for a not-yet-decided projection.
_STATUSES = (GREENLIGHT_STATUS, "NEGOTIATE_HARD", "PASS", None)


def _roles() -> st.SearchStrategy[UserRole]:
    return st.sampled_from(_ROLES)


def _territory_sets() -> st.SearchStrategy[tuple[str, ...]]:
    """Generate an actor's authorized-territory tuple (possibly empty)."""
    return st.lists(
        st.sampled_from(_TERRITORIES), min_size=0, max_size=len(_TERRITORIES), unique=True
    ).map(tuple)


def _user_context() -> st.SearchStrategy[UserContext]:
    """Generate an authenticated actor with one role and a territory set."""
    return st.builds(
        lambda role, territories: UserContext(
            user_id=uuid.uuid4(),
            display_name="generated-actor",
            role=role,
            authorized_territories=territories,
        ),
        role=_roles(),
        territories=_territory_sets(),
    )


def _normalized_costs() -> st.SearchStrategy[Decimal | None]:
    """Costs that straddle the high-budget threshold, plus ``None``.

    Values are drawn across and around :data:`HIGH_BUDGET_THRESHOLD_USD` so both
    sides of the strict ``>`` boundary — and the exact boundary itself — are
    generated, together with the not-yet-normalized ``None`` case.
    """
    threshold = HIGH_BUDGET_THRESHOLD_USD
    around = st.sampled_from(
        [
            threshold - Decimal("1"),
            threshold,
            threshold + Decimal("1"),
            Decimal("0"),
        ]
    )
    span = st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("100000000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    )
    return st.one_of(st.none(), around, span)


# ===========================================================================
# Property 28 — Override authorization matrix (RBAC_Service, R20.2)
# ===========================================================================


# Feature: cineroi-ai, Property 28: Override authorization matrix
@given(actor=_user_context())
@settings(max_examples=200)
def test_override_authorized_iff_role_is_decision_maker(actor: UserContext) -> None:
    """Validates: Requirements 20.2

    An attempt to override a Recommendation_Status succeeds if and only if the
    actor's role is one of {CONTENT_BUYER, CHIEF_CONTENT_OFFICER, CFO}; any other
    role is rejected with an authorization error. ``authorize`` and the boolean
    ``can`` predicate agree, and the authorized set is exactly OVERRIDE_ROLES.
    """
    rbac = RBACService()
    allowed = actor.role in OVERRIDE_ROLES

    # The permission predicate must match the matrix exactly (iff).
    assert rbac.can(actor, Operation.OVERRIDE) is allowed

    if allowed:
        # A permitted role authorizes without raising.
        rbac.authorize(actor, Operation.OVERRIDE)
    else:
        # A non-decision-maker (DATA_ANALYST) is rejected with the specific
        # override-authorization error (a ForbiddenError subclass, R20.2).
        with pytest.raises(ForbiddenOverrideError) as exc:
            rbac.authorize(actor, Operation.OVERRIDE)
        details = exc.value.details or {}
        assert details.get("role") == actor.role.value
        assert details.get("operation") == Operation.OVERRIDE.value


# Feature: cineroi-ai, Property 28: Override authorization matrix
@given(actor=_user_context())
@settings(max_examples=200)
def test_override_matrix_is_exactly_the_three_decision_roles(
    actor: UserContext,
) -> None:
    """Validates: Requirements 20.2

    The override-authorized set is precisely {CONTENT_BUYER,
    CHIEF_CONTENT_OFFICER, CFO}: DATA_ANALYST is denied and the three decision
    roles are allowed, with no other outcome possible. Passing the operation as
    its string value yields the same decision as the enum member.
    """
    rbac = RBACService()
    decision_roles = {
        UserRole.CONTENT_BUYER,
        UserRole.CHIEF_CONTENT_OFFICER,
        UserRole.CFO,
    }

    # The engine's declared OVERRIDE_ROLES must be exactly the design's set.
    assert set(OVERRIDE_ROLES) == decision_roles

    expected = actor.role in decision_roles
    # Enum and string spellings of the operation agree (interface symmetry).
    assert rbac.can(actor, Operation.OVERRIDE) is expected
    assert rbac.can(actor, "override") is expected

    if not expected:
        with pytest.raises(ForbiddenError):
            rbac.authorize(actor, "override")


# ===========================================================================
# Property 29 — Confidential access scoping (RBAC_Service, R28.2, R28.4)
# ===========================================================================


def _expected_confidential_access(actor: UserContext, territory: str | None) -> bool:
    """Oracle for R28.2: whether ``actor`` may see confidential data here.

    Independently re-derives the policy rather than calling the engine, so the
    property compares the engine against the specification, not against itself:

    * the role must be cleared for confidential data at all; and
    * either the record is not territory-bound (``territory is None``), or the
      role is territory-unrestricted (executive), or the record's territory is
      among the actor's authorized territories.
    """
    if actor.role not in CONFIDENTIAL_ACCESS_ROLES:
        return False
    if territory is None or actor.role in TERRITORY_UNRESTRICTED_ROLES:
        return True
    return territory in set(actor.authorized_territories)


# Feature: cineroi-ai, Property 29: Confidential access scoping
@given(
    actor=_user_context(),
    territory=st.one_of(st.none(), st.sampled_from(_TERRITORIES)),
)
@settings(max_examples=200)
def test_confidential_access_granted_iff_role_and_territory_authorized(
    actor: UserContext, territory: str | None
) -> None:
    """Validates: Requirements 28.2, 28.4

    Confidential access is granted if and only if the actor's role AND territory
    are authorized for the record: a role lacking confidential clearance is never
    granted; an executive role is granted regardless of territory; a
    territory-bound confidential role is granted only when the record's territory
    is in its authorized set (or the record is not territory-bound).
    """
    rbac = RBACService()
    expected = _expected_confidential_access(actor, territory)
    assert rbac.can_access_confidential(actor, territory) is expected


# Feature: cineroi-ai, Property 29: Confidential access scoping
@given(
    actor=_user_context(),
    territory=st.one_of(st.none(), st.sampled_from(_TERRITORIES)),
    public_value=st.integers(),
    secret_value=st.text(min_size=0, max_size=12),
    deal_value=st.integers(),
)
@settings(max_examples=200)
def test_scope_record_withholds_confidential_fields_with_indication(
    actor: UserContext,
    territory: str | None,
    public_value: int,
    secret_value: str,
    deal_value: int,
) -> None:
    """Validates: Requirements 28.2, 28.4

    When the actor is authorized, every field (confidential included) is
    returned unchanged and no withheld-indication is present. When the actor is
    NOT authorized, each confidential field is removed from the result and listed
    under the withheld-fields indication (R28.4), while non-confidential fields
    are always returned. The scoping never mutates the source record.
    """
    rbac = RBACService()
    confidential_fields = ("secret_script", "deal_terms")
    record = {
        "title": "public-title",
        "public_rating": public_value,
        "secret_script": secret_value,
        "deal_terms": deal_value,
    }
    source_snapshot = dict(record)

    scoped = rbac.scope_record(
        actor,
        record,
        confidential_fields=confidential_fields,
        territory=territory,
    )

    # The source mapping is never mutated (a copy is returned).
    assert record == source_snapshot

    # Non-confidential fields are always present and unchanged.
    assert scoped["title"] == "public-title"
    assert scoped["public_rating"] == public_value

    authorized = _expected_confidential_access(actor, territory)
    if authorized:
        # Authorized: confidential fields returned verbatim, no indication.
        assert scoped["secret_script"] == secret_value
        assert scoped["deal_terms"] == deal_value
        assert WITHHELD_FIELDS_KEY not in scoped
    else:
        # Unauthorized: confidential fields withheld with an explicit indication
        # (R28.4) — not silently dropped.
        assert "secret_script" not in scoped
        assert "deal_terms" not in scoped
        assert scoped[WITHHELD_FIELDS_KEY] == sorted(confidential_fields)


# Feature: cineroi-ai, Property 29: Confidential access scoping
@given(actor=_user_context(), territory=st.one_of(st.none(), st.sampled_from(_TERRITORIES)))
@settings(max_examples=150)
def test_scope_record_with_no_confidential_fields_returns_everything(
    actor: UserContext, territory: str | None
) -> None:
    """Validates: Requirements 28.4

    A record that declares no confidential fields is returned in full to any
    authenticated actor with no withheld-indication, regardless of role or
    territory — there is nothing to scope.
    """
    rbac = RBACService()
    record = {"title": "t", "rating": 7}

    scoped = rbac.scope_record(
        actor, record, confidential_fields=(), territory=territory
    )

    assert scoped == record
    assert WITHHELD_FIELDS_KEY not in scoped


# ===========================================================================
# In-memory fakes for the Approval_Workflow repositories
# ===========================================================================


class _Decision:
    """A ``financial_projections``-like row the workflow reads from."""

    def __init__(
        self, recommendation_status: str | None, normalized_cost_usd: Decimal | None
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


# ===========================================================================
# Property 26 — High-budget approval threshold in base currency (R20.3)
# ===========================================================================


# Feature: cineroi-ai, Property 26: High-budget approval threshold in base currency
@given(status=st.sampled_from(_STATUSES), cost=_normalized_costs())
@settings(max_examples=200)
def test_sign_off_required_iff_greenlight_above_threshold(
    status: str | None, cost: Decimal | None
) -> None:
    """Validates: Requirements 20.3

    Dual sign-off is required if and only if the decision is a GREENLIGHT whose
    ``normalized_cost_usd`` strictly exceeds the base-currency threshold
    (25,000,000 USD). Any non-GREENLIGHT status, a missing cost, or a cost at or
    below the threshold requires no sign-off. The comparison uses the normalized
    base-currency value, never a native-currency figure.
    """
    expected = (
        status == GREENLIGHT_STATUS
        and cost is not None
        and cost > HIGH_BUDGET_THRESHOLD_USD
    )
    assert Approval_Workflow.requires_sign_off(status, cost) is expected


# Feature: cineroi-ai, Property 26: High-budget approval threshold in base currency
@given(status=st.sampled_from(_STATUSES), cost=_normalized_costs())
@settings(max_examples=200)
async def test_ensure_workflow_creates_gate_exactly_when_sign_off_required(
    status: str | None, cost: Decimal | None
) -> None:
    """Validates: Requirements 20.3

    ``ensure_workflow`` materializes a sign-off workflow — requiring both
    CHIEF_CONTENT_OFFICER and CFO — exactly when the decision needs sign-off, and
    returns ``None`` (no gate) otherwise, consistent with the pure
    ``requires_sign_off`` predicate.
    """
    engine, _, _, projections, _ = _build()
    decision = _Decision(status, cost)
    projections.add(decision)

    workflow = await engine.ensure_workflow(decision.projection_id)
    required = Approval_Workflow.requires_sign_off(status, cost)

    if required:
        assert workflow is not None
        assert set(workflow.required_roles) == {r.value for r in REQUIRED_SIGN_OFF_ROLES}
        assert workflow.finalized is False
    else:
        assert workflow is None


# ===========================================================================
# Property 27 — Finalization gating (R20.5)
# ===========================================================================


# Feature: cineroi-ai, Property 27: Finalization gating
@given(
    approve_cco=st.booleans(),
    approve_cfo=st.booleans(),
    cco_also_rejects=st.booleans(),
)
@settings(max_examples=200)
async def test_finalization_permitted_iff_no_outstanding_approval(
    approve_cco: bool, approve_cfo: bool, cco_also_rejects: bool
) -> None:
    """Validates: Requirements 20.5

    For a high-budget GREENLIGHT governed by a sign-off workflow, finalization is
    permitted if and only if no required approval remains outstanding — i.e. both
    the CCO and the CFO have each recorded an APPROVE. Partial or absent approvals
    block finalization and the outstanding set is exactly the required roles that
    have not approved. REJECT acts never count toward satisfying a sign-off.
    """
    engine, _, _, projections, users = _build()
    decision = _Decision(GREENLIGHT_STATUS, HIGH_BUDGET_THRESHOLD_USD + Decimal("1"))
    projections.add(decision)
    cco = _User(UserRole.CHIEF_CONTENT_OFFICER)
    cfo = _User(UserRole.CFO)
    users.add(cco)
    users.add(cfo)

    # Materialize the governance gate up front: a high-budget GREENLIGHT is
    # governed whether or not any action has been recorded yet, so the "no
    # approvals at all" case must still block finalization (R20.5).
    await engine.ensure_workflow(decision.projection_id)

    if cco_also_rejects:
        # A reject is recorded for the audit trail but must not approve (R20.4).
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.REJECT,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )
    if approve_cco:
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cco, UserRole.CHIEF_CONTENT_OFFICER),
        )
    if approve_cfo:
        await engine.record_action(
            decision.projection_id,
            ApprovalActionType.APPROVE,
            _ctx(cfo, UserRole.CFO),
        )

    status = await engine.can_finalize(decision.projection_id)

    expected_outstanding: set[UserRole] = set()
    if not approve_cco:
        expected_outstanding.add(UserRole.CHIEF_CONTENT_OFFICER)
    if not approve_cfo:
        expected_outstanding.add(UserRole.CFO)

    # Finalization is permitted iff nothing is outstanding (the iff of R20.5).
    assert status.can_finalize is (not expected_outstanding)
    assert set(status.outstanding_roles) == expected_outstanding
    assert set(status.required_roles) == set(REQUIRED_SIGN_OFF_ROLES)

    if status.can_finalize:
        workflow = await engine.finalize(decision.projection_id)
        assert workflow is not None
        assert workflow.finalized is True
    else:
        with pytest.raises(ApprovalsPendingError):
            await engine.finalize(decision.projection_id)


# Feature: cineroi-ai, Property 27: Finalization gating
@given(status=st.sampled_from(["NEGOTIATE_HARD", "PASS"]), cost=_normalized_costs())
@settings(max_examples=150)
async def test_ungated_decision_is_always_finalizable(
    status: str, cost: Decimal | None
) -> None:
    """Validates: Requirements 20.5

    A decision that is not a high-budget GREENLIGHT has no sign-off gate, so no
    approval is ever outstanding and finalization is permitted unconditionally
    (with empty required and outstanding sets).
    """
    engine, _, _, projections, _ = _build()
    decision = _Decision(status, cost)
    projections.add(decision)

    result = await engine.can_finalize(decision.projection_id)

    assert result.can_finalize is True
    assert result.required_roles == ()
    assert result.outstanding_roles == ()
    # Finalizing an ungated decision is a no-op at the approval layer.
    assert await engine.finalize(decision.projection_id) is None
