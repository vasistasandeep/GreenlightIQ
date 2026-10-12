"""Async database access layer (repositories) for CineROI AI (task 6.1).

Each repository wraps a single ORM model and receives an injected
:class:`~sqlalchemy.ext.asyncio.AsyncSession`. Shared CRUD and the
optimistic-lock-aware :meth:`BaseRepository.update_with_version` live in
:mod:`app.repositories.base`; ``titles`` and ``financial_projections`` use that
path to reject stale ``row_version`` updates with
:class:`OptimisticLockError` (mapped to ``409 STALE_VERSION``, R27.2).

The async engine/session factory lives in :mod:`app.core.db`; importing this
package does not open a database connection (R17.2, R27.2).
"""

from __future__ import annotations

from app.repositories.approvals import (
    ApprovalActionRepository,
    ApprovalWorkflowRepository,
)
from app.repositories.audit_log import AuditLogRepository
from app.repositories.base import BaseRepository, OptimisticLockError
from app.repositories.exchange_rates import ExchangeRateRepository
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.ground_truth import GroundTruthRepository
from app.repositories.jobs import JobRepository
from app.repositories.license_terms import LicenseTermRepository
from app.repositories.metadata_vectors import MetadataVectorRepository
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.subscriber_clusters import SubscriberClusterRepository
from app.repositories.telemetry import TelemetryRepository
from app.repositories.titles import TitleRepository, TitleVersionRepository
from app.repositories.users import SessionRepository, UserRepository

__all__ = [
    "ApprovalActionRepository",
    "ApprovalWorkflowRepository",
    "AuditLogRepository",
    "BaseRepository",
    "ExchangeRateRepository",
    "FinancialProjectionRepository",
    "GroundTruthRepository",
    "JobRepository",
    "LicenseTermRepository",
    "MetadataVectorRepository",
    "ModelVersionRepository",
    "OptimisticLockError",
    "SessionRepository",
    "SubscriberClusterRepository",
    "TelemetryRepository",
    "TitleRepository",
    "TitleVersionRepository",
    "UserRepository",
]
