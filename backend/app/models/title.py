"""ORM model for the ``titles`` core table (R17.1, R17.3, R17.4).

A title is the central entity in CineROI: a candidate for acquisition that is
profiled, valued, and (optionally) backtested. Primary key is a UUID (R17.1),
``asset_type`` is constrained to the enumerated set (R17.4), ``target_territories``
is stored as JSONB country codes (R17.3), and ``acquisition_cost_or_budget`` is
range-checked (R1.8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk

ASSET_TYPES = ("ORIGINAL_SERIES", "ORIGINAL_FILM", "LICENSED_LIBRARY", "CO_PRODUCTION")


class Title(Base):
    """A candidate content title in the acquisition pipeline."""

    __tablename__ = "titles"
    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('ORIGINAL_SERIES', 'ORIGINAL_FILM', "
            "'LICENSED_LIBRARY', 'CO_PRODUCTION')",
            name="ck_titles_asset_type",
        ),
        CheckConstraint(
            "acquisition_cost_or_budget BETWEEN 0.01 AND 999999999.99",
            name="ck_titles_acquisition_cost_range",
        ),
    )

    title_id: Mapped[uuid.UUID] = uuid_pk()
    title_name: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    acquisition_cost_or_budget: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_territories: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    genre_tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    projected_viewing_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2), nullable=True
    )
    is_historical: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    # FK -> title_versions wired in task 2.2 (R24.4). Circular with
    # title_versions.title_id, so emitted via a separate ALTER (use_alter).
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey(
            "title_versions.title_version_id",
            use_alter=True,
            name="fk_titles_active_version_id",
        ),
        nullable=True,
    )
    row_version: Mapped[int] = mapped_column(nullable=False, server_default="0")
    # FK -> users wired in task 2.2.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.user_id", name="fk_titles_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = created_at_column()
