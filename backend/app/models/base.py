"""Shared SQLAlchemy declarative base and common column/type helpers.

This module defines the single :class:`Base` that every ORM model inherits from
so that a single ``Base.metadata`` describes the full schema (used by Alembic's
``target_metadata`` and by the test suite to create tables).

Task 2.1 establishes the core tables; task 2.2 extends the same ``Base`` with the
expanded-requirement tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by all CineROI ORM models."""


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary-key column defaulting to ``gen_random_uuid()`` in Postgres."""
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


def created_at_column() -> Mapped[datetime]:
    """A ``TIMESTAMPTZ NOT NULL DEFAULT now()`` creation-timestamp column."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
