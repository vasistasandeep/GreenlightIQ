"""ORM model for the ``license_terms`` expanded table (R22).

Captures the contract structure for a title: license duration, exclusivity,
ordered windowing rules, holdbacks, and the milestone payment schedule used by
milestone-based payback computation (R22.2). ``license_duration_months`` must be
positive. Window-sum-vs-duration validation (R22.4) is enforced at the
application layer. The confidential deal-term fields (windowing rules,
holdbacks, milestone schedule) are encrypted at rest via
:class:`~app.core.encryption.EncryptedJSON` (R28.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedJSON
from app.models.base import Base, uuid_pk


class LicenseTerm(Base):
    """Licensing / windowing contract structure for a title (R22)."""

    __tablename__ = "license_terms"
    __table_args__ = (
        CheckConstraint(
            "license_duration_months > 0",
            name="ck_license_terms_duration_positive",
        ),
    )

    license_id: Mapped[uuid.UUID] = uuid_pk()
    title_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("titles.title_id", ondelete="CASCADE"),
        nullable=False,
    )
    license_duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    is_exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Deal terms are confidential and encrypted at rest (R28.1). Stored as
    # encrypted TEXT rather than JSONB because ciphertext is opaque to the
    # database; windowing-vs-duration validation (R22.4) runs in the app layer.
    windowing_rules: Mapped[list | dict] = mapped_column(EncryptedJSON, nullable=False)
    holdbacks: Mapped[list | dict | None] = mapped_column(EncryptedJSON, nullable=True)
    milestone_schedule: Mapped[list | dict] = mapped_column(
        EncryptedJSON, nullable=False
    )
