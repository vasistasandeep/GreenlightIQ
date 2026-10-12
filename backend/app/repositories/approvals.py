"""Repositories for ``approval_workflows`` and ``approval_actions`` (R20.3-R20.5).

A workflow governs a high-budget GREENLIGHT decision and lists the required
sign-off roles; actions record each approve / reject / override act (R20.4). The
workflow repository resolves the workflow for a decision and its recorded
actions so the service layer can determine whether outstanding approvals remain
(R20.5).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.approval import ApprovalAction, ApprovalWorkflow
from app.repositories.base import BaseRepository


class ApprovalWorkflowRepository(BaseRepository[ApprovalWorkflow]):
    """Async access to the ``approval_workflows`` table (R20.3, R20.5)."""

    model = ApprovalWorkflow
    pk = ApprovalWorkflow.workflow_id

    async def get_for_decision(
        self, decision_id: uuid.UUID
    ) -> ApprovalWorkflow | None:
        """Return the workflow governing a financial-projection decision."""
        stmt = select(ApprovalWorkflow).where(
            ApprovalWorkflow.decision_id == decision_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class ApprovalActionRepository(BaseRepository[ApprovalAction]):
    """Async access to the ``approval_actions`` table (R20.4)."""

    model = ApprovalAction
    pk = ApprovalAction.action_id

    async def list_for_workflow(
        self, workflow_id: uuid.UUID
    ) -> list[ApprovalAction]:
        """Return every recorded action for a workflow, oldest first."""
        stmt = (
            select(ApprovalAction)
            .where(ApprovalAction.workflow_id == workflow_id)
            .order_by(ApprovalAction.acted_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
