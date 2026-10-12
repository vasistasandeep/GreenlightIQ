"""ORM model for the ``sessions`` expanded table (R19.2, R19.4).

A session is bound to a user identity on SSO login (R19.2). ``last_activity_at``
drives the 30-minute idle-expiry check (R19.4); ``revoked`` supports explicit
invalidation (R19.6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class Session(Base):
    """An authenticated user session with idle-expiry tracking (R19.2, R19.4)."""

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(nullable=False, server_default="false")
