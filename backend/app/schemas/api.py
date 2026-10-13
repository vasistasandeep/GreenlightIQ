"""Pydantic request/response schemas for the core REST API (task 16.1).

These models define the wire contract for the documented core endpoints
(``POST /titles/ingest``, ``POST /valuation/calculate``,
``GET /valuation/{title_id}``, ``POST /backtest/audit``,
``GET /market/telemetry``). They are deliberately thin: domain validation and
computation live in the engines; these schemas only shape and validate the
request envelope and serialize engine results into stable JSON.

Monetary and ratio values produced by the engines are :class:`~decimal.Decimal`;
Pydantic serializes them losslessly as JSON numbers/strings. The explanation
payload (R30.4) is passed through as an already-structured mapping built by the
Guardrails_Engine.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# POST /titles/ingest
# --------------------------------------------------------------------------- #


class RejectionItem(BaseModel):
    """One rejected row in an ingestion summary (R1.7, R1.8)."""

    row_index: int = Field(..., description="Zero-based index of the rejected row.")
    field: str = Field(..., description="The field that failed validation.")
    reason: str = Field(..., description="Human-readable rejection reason.")


class IngestAcceptedResponse(BaseModel):
    """The ``202 Accepted`` body for a dispatched ingestion batch (R1, R23.2).

    The heavy per-row work runs asynchronously in the Task_Queue; the client
    polls ``GET /jobs/{job_id}`` for the terminal result. When the request is an
    idempotent replay of a already-completed batch, the stored accepted/rejected
    summary is echoed inline alongside the original ``job_id`` (R27.1).
    """

    job_id: uuid.UUID = Field(..., description="Identifier of the dispatched ingestion job.")
    status: str = Field(..., description="Current job status (PENDING for a freshly dispatched batch).")
    accepted_count: int | None = Field(
        default=None,
        description="Accepted-row count; present only for a completed/replayed batch.",
    )
    rejected_count: int | None = Field(
        default=None,
        description="Rejected-row count; present only for a completed/replayed batch.",
    )
    rejections: list[RejectionItem] | None = Field(
        default=None,
        description="Per-row rejection details; present only for a completed/replayed batch.",
    )


# --------------------------------------------------------------------------- #
# POST /valuation/calculate  and  GET /valuation/{title_id}
# --------------------------------------------------------------------------- #


class ValuationCalculateRequest(BaseModel):
    """Request body for a single-title valuation (R9.1).

    Carries the title to evaluate and, optionally, an explicit model-version
    stamp used to reproduce a historical valuation (R26.2, R26.3). When omitted
    the active model version is used.
    """

    title_id: uuid.UUID = Field(..., description="The title to evaluate.")
    model_version_id: uuid.UUID | None = Field(
        default=None,
        description="Optional explicit model-version stamp; defaults to the active version.",
    )


class ValuationSummaryResponse(BaseModel):
    """The compact valuation result returned by ``POST /valuation/calculate`` (R9.2, R30.4).

    Mirrors the documented core contract: the computed CPVH, the LTV-to-cost
    multiple, the final recommendation, and the structured explanation consumed
    by the explainability surface (R30.4). ``calculated_cpvh`` is ``null`` when
    projected viewing hours are zero (R4.5).
    """

    title_id: uuid.UUID
    calculated_cpvh: Decimal | None
    ltv_to_cost_multiple: Decimal | None
    recommendation_status: str
    explanation: dict[str, Any]


class MetadataBreakdown(BaseModel):
    """The extracted metadata profile surfaced in the full scorecard (R10, R15.1).

    A projection of the title's ``metadata_vectors`` row: the affective tone
    triggers and the talent-pedigree / production-scale scores. The 1536-dim
    Narrative_DNA embedding itself is summarized by its dimension count rather
    than serialized in full.
    """

    affective_primary: str | None = None
    affective_secondary: str | None = None
    talent_pedigree_score: Decimal | None = None
    production_scale_metric: Decimal | None = None
    narrative_dna_dimensions: int | None = Field(
        default=None,
        description="Length of the stored Narrative_DNA embedding, if present.",
    )
    extraction_status: str | None = None


class CounterProposalLeverOut(BaseModel):
    """A plain-language negotiation lever keyed to a breached guardrail (R3)."""

    name: str
    correctable: bool | None = None
    message: str


class LtvAttributionOut(BaseModel):
    """The LTV-to-Cost numerator decomposition (R6). Decimals serialize as strings."""

    subscription_value: Decimal | None = None
    advertising_value: Decimal | None = None
    total_modeled_value: Decimal | None = None
    normalized_cost_usd: Decimal | None = None
    multiple: Decimal | None = None


class ChurnCohortOut(BaseModel):
    """Absolute churn-cohort figures (R8). ``derived`` flags a modeled figure."""

    churn_reduction_pct: Decimal | None = None
    modeled_cohort_size: Decimal | None = None
    retained_subscribers: Decimal | None = None
    derived: bool = True


class ValuationScorecardResponse(BaseModel):
    """The full valuation scorecard returned by ``GET /valuation/{title_id}`` (R10, R30.4).

    Extends the compact summary with the remaining persisted guardrail outputs,
    the model-version stamp, and the metadata-vector breakdown (R10.1, R10.2).
    """

    title_id: uuid.UUID
    calculated_cpvh: Decimal | None
    ltv_to_cost_multiple: Decimal | None
    churn_reduction_pct: Decimal | None
    payback_horizon_months: int | None
    recommendation_status: str | None
    normalized_cost_usd: Decimal | None
    model_version_id: uuid.UUID | None
    explanation: dict[str, Any] | None
    metadata_breakdown: MetadataBreakdown | None
    # Deal Decision Support (R4, R6, R8). Decimals serialize as JSON strings.
    target_purchase_ceiling_usd: Decimal | None = None
    implied_discount_pct: Decimal | None = None
    counter_proposal_levers: list[CounterProposalLeverOut] = Field(default_factory=list)
    ltv_attribution: LtvAttributionOut | None = None
    churn_cohort: ChurnCohortOut | None = None


class TitleCompOut(BaseModel):
    """One nearest-neighbour title in the Top-3 comps surface (R2.6, R17.6).

    A comp is the result of a title-to-title Narrative_DNA cosine-similarity
    lookup over ``metadata_vectors``. ``cosine_similarity`` is in ``[-1.0, 1.0]``
    (1.0 == identical direction); ``recommendation_status`` is ``null`` when the
    neighbour has no computed valuation yet.
    """

    title_id: uuid.UUID
    title_name: str
    genre_tag: str | None = None
    recommendation_status: str | None = None
    cosine_similarity: float


class ComparableTitlesResponse(BaseModel):
    """The ``GET /valuation/{title_id}/comps`` payload (R2.6).

    ``found`` is false when the query title has no stored embedding (comps cannot
    be computed); ``comps`` is then empty. An empty ``comps`` with ``found`` true
    means the title has an embedding but no other title does yet.
    """

    title_id: uuid.UUID
    found: bool
    comps: list[TitleCompOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# POST /backtest/audit
# --------------------------------------------------------------------------- #


class GroundTruthMetricInput(BaseModel):
    """One observed actual-outcome metric in a ground-truth submission (R11.1)."""

    metric_name: str = Field(..., description="The audited metric (e.g. 'cpvh').")
    actual_value: Any = Field(..., description="The observed actual value; must be numeric (R11.2).")


class BacktestAuditRequest(BaseModel):
    """Request body for a backtest audit submission (R11.1).

    Carries the historical title and its observed actual outcomes. The server
    validates and persists the ground truth, then returns the audit scorecard
    comparing predicted vs actual with the computed MAPE (R11.6).
    """

    title_id: uuid.UUID = Field(..., description="The historical title being audited.")
    metrics: list[GroundTruthMetricInput] = Field(
        ..., min_length=1, description="One or more observed actual-outcome metrics."
    )


class AuditMetricResponse(BaseModel):
    """One predicted/actual row in the audit scorecard (R11.6, R11.7)."""

    metric: str
    predicted: Decimal
    actual: Decimal
    excluded: bool


class BacktestAuditResponse(BaseModel):
    """The audit scorecard returned by ``POST /backtest/audit`` (R11.6, R11.8)."""

    title_id: uuid.UUID
    metrics: list[AuditMetricResponse]
    mape: Decimal | None
    no_eligible_metrics: bool


# --------------------------------------------------------------------------- #
# GET /market/telemetry
# --------------------------------------------------------------------------- #


class MarketTelemetryResponse(BaseModel):
    """Cached market telemetry for a genre/territory pair (R13.3).

    ``found`` is ``False`` when the pair has never been polled; ``source_available``
    reflects whether the most recent poll succeeded (``False`` means the indices
    are retained-but-stale, R13.4).
    """

    genre_tag: str
    territory: str
    social_sentiment_index: Decimal | None
    chart_velocity_score: Decimal | None
    licensing_inflation_multiplier: Decimal | None
    source_available: bool
    found: bool
