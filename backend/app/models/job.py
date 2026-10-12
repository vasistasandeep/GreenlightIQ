"""ORM model for the ``jobs`` expanded table (R23.2-R23.5, R27.1, R29.3).

Represents an asynchronous unit of work dispatched to the Task_Queue. ``status``
is constrained to the Job_Status enum and drives the PENDING -> PROCESSING ->
COMPLETED|FAILED lifecycle (R23.3). ``idempotency_key`` is unique so a replayed
submission returns the stored result rather than re-running (R27.1).
``dead_lettered`` marks jobs that exhausted retries (R29.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk

JOB_STATUSES = ("PENDING", "PROCESSING", "COMPLETED", "FAILED")


class Job(Base):
    """An asynchronous background job tracked through its lifecycle (R23)."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_jobs_status",
        ),
    )

    job_id: Mapped[uuid.UUID] = uuid_pk()
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()
