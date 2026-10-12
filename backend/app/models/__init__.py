"""SQLAlchemy ORM models for CineROI AI.

Importing this package registers every model with the shared ``Base.metadata``
so that Alembic (``target_metadata``) and the test suite see the full schema.
Task 2.1 adds the core tables; task 2.2 extends the same ``Base`` with the
expanded-requirement tables below.
"""

from __future__ import annotations

from app.models.approval import (
    APPROVAL_ACTIONS,
    ApprovalAction,
    ApprovalWorkflow,
)
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.exchange_rate import ExchangeRate
from app.models.financial_projection import (
    RECOMMENDATION_STATUSES,
    FinancialProjection,
)
from app.models.historical_ground_truth import HistoricalGroundTruth
from app.models.job import JOB_STATUSES, Job
from app.models.license_term import LicenseTerm
from app.models.market_telemetry_cache import MarketTelemetryCache
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS, MetadataVector
from app.models.model_version import ModelVersion
from app.models.session import Session
from app.models.subscriber_cluster import SubscriberCluster
from app.models.title import ASSET_TYPES, Title
from app.models.title_version import TitleVersion
from app.models.user import USER_ROLES, User

__all__ = [
    "APPROVAL_ACTIONS",
    "ASSET_TYPES",
    "ApprovalAction",
    "ApprovalWorkflow",
    "AuditLog",
    "Base",
    "ExchangeRate",
    "FinancialProjection",
    "HistoricalGroundTruth",
    "JOB_STATUSES",
    "Job",
    "LicenseTerm",
    "MarketTelemetryCache",
    "MetadataVector",
    "ModelVersion",
    "NARRATIVE_DNA_DIMENSIONS",
    "RECOMMENDATION_STATUSES",
    "Session",
    "SubscriberCluster",
    "Title",
    "TitleVersion",
    "USER_ROLES",
    "User",
]
