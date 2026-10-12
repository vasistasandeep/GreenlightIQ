"""ORM model for the ``users`` expanded table (R20.1, R19).

A user is an authenticated principal mapped from an SSO subject. Each user holds
exactly one role from the enumerated set (R20.1) and a JSONB list of authorized
territories used for confidential-record / field scoping (R28.2). The PII
``display_name`` is encrypted at rest via :class:`~app.core.encryption.EncryptedString`
(R28.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.models.base import Base, created_at_column, uuid_pk

USER_ROLES = (
    "DATA_ANALYST",
    "CONTENT_BUYER",
    "CHIEF_CONTENT_OFFICER",
    "CFO",
)


class User(Base):
    """An authenticated principal with exactly one role (R20.1)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("external_subject", name="uq_users_external_subject"),
        CheckConstraint(
            "user_role IN ('DATA_ANALYST', 'CONTENT_BUYER', "
            "'CHIEF_CONTENT_OFFICER', 'CFO')",
            name="ck_users_user_role",
        ),
    )

    user_id: Mapped[uuid.UUID] = uuid_pk()
    external_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII encrypted at rest (R28.1). ``external_subject`` stays plaintext because
    # it is a unique SSO-lookup key (Fernet ciphertext is non-deterministic and
    # cannot support equality lookups or UNIQUE enforcement).
    display_name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    user_role: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_territories: Mapped[list | dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = created_at_column()
