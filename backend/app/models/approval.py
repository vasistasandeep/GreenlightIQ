"""ORM models for the approval workflow (R20.3-R20.5).

``approval_workflows`` governs a high-budget GREENLIGHT decision, listing the
roles whose sign-off is required (e.g. CHIEF_CONTENT_OFFICER + CFO) and whether
the decision has been finalized (R20.5). ``approval_actions`` records each
approve / reject / override act with its actor and timestamp (R20.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

APPROVAL_ACTIONS = ("APPROVE", "REJECT", "OVERRIDE")


class ApprovalWorkflow(Base):
    """Multi-tier sign-off state for a high-budget decision (R20.3, R20.5)."""

    __tablename__ = "approval_workflows"

    workflow_id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("financial_projections.projection_id", ondelete="CASCADE"),
        nullable=False,
    )
    required_roles: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    finalized: Mapped[bool] = mapped_column(nullable=False, server_default="false")


class ApprovalAction(Base):
    """A single approve / reject / override act by a user (R20.4)."""

    __tablename__ = "approval_actions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('APPROVE', 'REJECT', 'OVERRIDE')",
            name="ck_approval_actions_action",
        ),
    )

    action_id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("approval_workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    acted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
