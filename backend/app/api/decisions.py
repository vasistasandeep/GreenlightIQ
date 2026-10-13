"""Decisions router: recommendation override and approval workflow (R20.2, R20.4, R20.5).

Exposes the decision-governance endpoints from the design's "Added endpoints":

* ``POST /decisions/{id}/override`` — override a title's ``Recommendation_Status``.
  Permitted only for CONTENT_BUYER / CHIEF_CONTENT_OFFICER / CFO (R20.2); an
  unauthorized role is rejected with ``403 FORBIDDEN_OVERRIDE``. Every override
  is recorded in the append-only audit trail with its before/after value (R25.1).
* ``POST /decisions/{id}/approve`` and ``/reject`` — record an executive sign-off
  act with actor and timestamp against the decision's approval workflow (R20.4).
* ``GET /decisions/{id}/finalization`` — report whether the decision may be
  finalized and which required approvals remain outstanding (R20.5).

The ``{id}`` path parameter is a ``financial_projections.projection_id`` (the
"decision"). RBAC is enforced via :class:`~app.engines.rbac.RBACService`, the
sign-off state machine via :class:`~app.engines.approvals.Approval_Workflow`, and
override attribution via :class:`~app.engines.audit.AuditLogService`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_audit_service,
    get_current_user,
    get_rbac_service,
)
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import UserContext, UserRole
from app.engines.approvals import Approval_Workflow, ApprovalActionType
from app.engines.audit import AuditLogService
from app.engines.rbac import Operation, RBACService
from app.repositories.approvals import (
    ApprovalActionRepository,
    ApprovalWorkflowRepository,
)
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.users import UserRepository

router = APIRouter(prefix="/decisions", tags=["decisions"])

_RECOMMENDATION_STATUSES = frozenset({"GREENLIGHT", "NEGOTIATE_HARD", "PASS"})


class OverrideRequest(BaseModel):
    """A recommendation override request (R20.2)."""

    recommendation_status: str = Field(
        description="New status: GREENLIGHT | NEGOTIATE_HARD | PASS."
    )
    justification: str | None = Field(
        default=None, description="Optional free-text rationale recorded in audit."
    )


class OverrideResponse(BaseModel):
    """The result of an override, echoing the applied status."""

    decision_id: uuid.UUID
    previous_status: str | None
    recommendation_status: str


class ActionResponse(BaseModel):
    """Confirmation that an approval action was recorded (R20.4)."""

    decision_id: uuid.UUID
    action: str
    actor_id: uuid.UUID
    acted_at: str | None = None


class FinalizationResponse(BaseModel):
    """Finalization gating report for a decision (R20.5)."""

    decision_id: uuid.UUID
    can_finalize: bool
    required_roles: list[str] = Field(default_factory=list)
    outstanding_roles: list[str] = Field(default_factory=list)
    approved_roles: list[str] = Field(default_factory=list)


def _workflow(session: AsyncSession) -> Approval_Workflow:
    """Build an :class:`Approval_Workflow` bound to the request session."""
    return Approval_Workflow(
        workflows=ApprovalWorkflowRepository(session),
        actions=ApprovalActionRepository(session),
        projections=FinancialProjectionRepository(session),
        users=UserRepository(session),
    )


async def _require_decision(
    projections: FinancialProjectionRepository, decision_id: uuid.UUID
):
    """Load a decision (financial projection) or raise ``404 NOT_FOUND``."""
    decision = await projections.get(decision_id)
    if decision is None:
        raise NotFoundError(
            "The requested decision was not found.",
            details={"decision_id": str(decision_id)},
        )
    return decision


@router.post("/{decision_id}/override", response_model=OverrideResponse)
async def override_recommendation(
    decision_id: uuid.UUID,
    body: OverrideRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: UserContext = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac_service),
    audit: AuditLogService = Depends(get_audit_service),
) -> OverrideResponse:
    """Override a decision's recommendation, gated to decision-making roles (R20.2).

    Only CONTENT_BUYER / CHIEF_CONTENT_OFFICER / CFO may override; any other role
    is rejected with ``403 FORBIDDEN_OVERRIDE`` by the RBAC check. The override is
    persisted and an append-only audit entry capturing the before/after status and
    the acting identity is recorded (R25.1).
    """
    # Authorize first so an unauthorized attempt never touches the record (R20.2).
    rbac.authorize(actor, Operation.OVERRIDE, resource=decision_id)

    new_status = body.recommendation_status
    if new_status not in _RECOMMENDATION_STATUSES:
        raise ValidationFailedError(
            "Unknown recommendation status.",
            details={
                "recommendation_status": new_status,
                "allowed": sorted(_RECOMMENDATION_STATUSES),
            },
        )

    projections = FinancialProjectionRepository(session)
    decision = await _require_decision(projections, decision_id)
    previous = decision.recommendation_status

    await projections.update(decision, recommendation_status=new_status)
    await audit.record(
        actor=actor.user_id,
        action="override",
        before={"recommendation_status": previous},
        after={"recommendation_status": new_status},
        subject_id=decision_id,
    )
    await session.commit()

    return OverrideResponse(
        decision_id=decision_id,
        previous_status=previous,
        recommendation_status=new_status,
    )


@router.post("/{decision_id}/approve", response_model=ActionResponse)
async def approve_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    actor: UserContext = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac_service),
) -> ActionResponse:
    """Record an executive APPROVE sign-off for a decision (R20.4)."""
    return await _record_action(
        decision_id,
        ApprovalActionType.APPROVE,
        Operation.APPROVE,
        session,
        actor,
        rbac,
    )


@router.post("/{decision_id}/reject", response_model=ActionResponse)
async def reject_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    actor: UserContext = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac_service),
) -> ActionResponse:
    """Record an executive REJECT sign-off for a decision (R20.4)."""
    return await _record_action(
        decision_id,
        ApprovalActionType.REJECT,
        Operation.REJECT,
        session,
        actor,
        rbac,
    )


async def _record_action(
    decision_id: uuid.UUID,
    action: str,
    operation: Operation,
    session: AsyncSession,
    actor: UserContext,
    rbac: RBACService,
) -> ActionResponse:
    """Authorize and persist an approve/reject act with actor + timestamp (R20.4)."""
    rbac.authorize(actor, operation, resource=decision_id)

    projections = FinancialProjectionRepository(session)
    await _require_decision(projections, decision_id)

    workflow = _workflow(session)
    recorded = await workflow.record_action(decision_id, action, actor)
    await session.commit()

    return ActionResponse(
        decision_id=decision_id,
        action=action,
        actor_id=actor.user_id,
        acted_at=recorded.acted_at.isoformat() if recorded.acted_at else None,
    )


@router.get("/{decision_id}/finalization", response_model=FinalizationResponse)
async def finalization_status(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> FinalizationResponse:
    """Report finalization gating and outstanding approvals for a decision (R20.5).

    A decision with no sign-off gate (not a high-budget GREENLIGHT) reports
    ``can_finalize = True`` with empty role lists; a governed decision reports the
    required roles and exactly which remain outstanding so the sign-off UI can
    surface what is still owed.
    """
    projections = FinancialProjectionRepository(session)
    await _require_decision(projections, decision_id)

    workflow = _workflow(session)
    # Materialize the sign-off workflow for a qualifying (high-budget GREENLIGHT)
    # decision so its required roles surface on first view, rather than appearing
    # only after the first approval is recorded (R20.3, R20.5).
    await workflow.ensure_workflow(decision_id)
    outcome = await workflow.can_finalize(decision_id)
    await session.commit()
    return FinalizationResponse(
        decision_id=decision_id,
        can_finalize=outcome.can_finalize,
        required_roles=[r.value for r in outcome.required_roles],
        outstanding_roles=[r.value for r in outcome.outstanding_roles],
        approved_roles=[r.value for r in outcome.approved_roles],
    )


class DemoSignOffRequest(BaseModel):
    """Dev/demo-only request to record an executive sign-off as a given role."""

    role: str = Field(
        description="Executive role to sign off as: CHIEF_CONTENT_OFFICER | CFO.",
    )


_DEMO_SIGN_OFF_ROLES = frozenset(
    {UserRole.CHIEF_CONTENT_OFFICER.value, UserRole.CFO.value}
)


@router.post("/{decision_id}/demo-sign-off", response_model=ActionResponse)
async def demo_sign_off(
    decision_id: uuid.UUID,
    body: DemoSignOffRequest,
    session: AsyncSession = Depends(get_db_session),
    _actor: UserContext = Depends(get_current_user),
) -> ActionResponse:
    """Record an APPROVE on behalf of a seeded executive role (DEV/DEMO ONLY).

    A high-budget GREENLIGHT requires sign-off from two distinct roles
    (CHIEF_CONTENT_OFFICER and CFO), but a demo session is a single identity, so
    it cannot clear a two-role gate on its own. This endpoint lets the demo
    attribute an approval to the seeded user actually holding the requested role,
    so the sign-off flow can complete end-to-end.

    It is hard-blocked outside dev/demo: enabled only when the demo auth bypass is
    on AND the environment is not production, mirroring the auth-bypass guard. In
    production it responds ``404`` so the route is effectively absent.
    """
    settings = get_settings()
    if not (settings.demo_auth_bypass and not settings.is_production):
        raise NotFoundError(
            "The requested resource was not found.",
            details={"decision_id": str(decision_id)},
        )

    if body.role not in _DEMO_SIGN_OFF_ROLES:
        raise ValidationFailedError(
            "role must be CHIEF_CONTENT_OFFICER or CFO.",
            details={"role": body.role},
        )

    # Attribute the approval to a seeded user who actually holds the role, so the
    # workflow's role-based approval counting (which resolves actor -> role)
    # recognizes it.
    users = UserRepository(session)
    role_holder = await users.get_by_role(body.role)
    if role_holder is None:
        raise NotFoundError(
            "No seeded user holds the requested role.",
            details={"role": body.role},
        )

    signer = UserContext(
        user_id=role_holder.user_id,
        display_name=role_holder.display_name,
        role=UserRole(role_holder.user_role),
    )

    projections = FinancialProjectionRepository(session)
    await _require_decision(projections, decision_id)

    workflow = _workflow(session)
    recorded = await workflow.record_action(
        decision_id, ApprovalActionType.APPROVE, signer
    )
    await session.commit()

    return ActionResponse(
        decision_id=decision_id,
        action=ApprovalActionType.APPROVE,
        actor_id=signer.user_id,
        acted_at=recorded.acted_at.isoformat() if recorded.acted_at else None,
    )
