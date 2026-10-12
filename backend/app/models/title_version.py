"""ORM model for the ``title_versions`` expanded table (R24).

Each ingestion of a title creates an immutable versioned snapshot with an
incrementing ``version_number`` (R24.2). ``(title_id, version_number)`` is
unique, and a partial unique index enforces exactly one active version per
title (R24.4). The ``source_snapshot`` (which can carry unreleased-script
material) is encrypted at rest via
:class:`~app.core.encryption.EncryptedJSON` (R28.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedJSON
from app.models.base import Base, created_at_column, uuid_pk


class TitleVersion(Base):
    """An immutable versioned snapshot of a title's source data (R24)."""

    __tablename__ = "title_versions"
    __table_args__ = (
        UniqueConstraint(
            "title_id", "version_number", name="uq_title_versions_title_version"
        ),
        # Exactly one active version per title (R24.4).
        Index(
            "uq_title_versions_one_active_per_title",
            "title_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    title_version_id: Mapped[uuid.UUID] = uuid_pk()
    title_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("titles.title_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Unreleased-script / submitted source data is confidential and encrypted at
    # rest (R28.1); stored as encrypted TEXT since ciphertext is opaque to JSONB.
    source_snapshot: Mapped[dict] = mapped_column(EncryptedJSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at_column()
