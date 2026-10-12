"""ORM model for the ``audit_log`` expanded table (R25.1, R25.2).

Records an immutable, append-only trail of state-changing actions with the
actor, timestamp, action, and before/after values (R25.1). Append-only is
enforced in the database by revoking UPDATE/DELETE and installing a
mutation-blocking trigger (see migration 0002); this ORM model is insert-only by
convention. ``model_version_id`` associates a valuation entry with the model
version active at the time (R25.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AuditLog(Base):
    """An append-only audit trail entry (R25.1, R25.2)."""

    __tablename__ = "audit_log"

    audit_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("model_versions.model_version_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
