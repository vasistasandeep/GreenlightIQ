"""Backtesting_Module: historical backtest audit and MAPE scorecard (R11).

Quantifies model accuracy by comparing a title's *predicted* guardrail outputs
against its *actual* observed outcomes (ground truth):

- :meth:`Backtesting_Module.persist_ground_truth` validates and persists a
  :class:`GroundTruthRecord` to ``historical_ground_truth``, returning the id of
  the persisted row. Records missing a required field or carrying a non-numeric
  actual value are rejected *without persisting any data* (R11.1, R11.2).
- :meth:`Backtesting_Module.audit` retrieves ground truth for an ``is_historical``
  title (matching on the title identifier), pairs each actual value with the
  corresponding predicted value from the latest ``financial_projections`` row,
  computes MAPE via :func:`app.domain.mape.compute_mape` (excluding zero-actual
  metrics), and returns an :class:`AuditScorecard` reporting per-metric
  predicted/actual/excluded plus the computed MAPE (R11.3–R11.8).

The module is a thin orchestration layer over the repository data-access layer.
It receives its dependencies by injection (an :class:`AsyncSession` and the
title / financial-projection / ground-truth repositories) and performs no I/O on
import. The MAPE arithmetic itself lives in the pure, dependency-free
:mod:`app.domain.mape` domain function so it stays a property-based-testing
target; this module only assembles the ``(actual, predicted)`` pairs and renders
the scorecard around that result.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GroundTruthInvalidError, GroundTruthMissingError
from app.domain.mape import compute_mape
from app.models.historical_ground_truth import HistoricalGroundTruth
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.ground_truth import GroundTruthRepository
from app.repositories.titles import TitleRepository

__all__ = [
    "GroundTruthRecord",
    "GroundTruthMetric",
    "AuditMetric",
    "AuditScorecard",
    "PREDICTED_METRIC_FIELDS",
    "Backtesting_Module",
]


# ---------------------------------------------------------------------------
# Predicted-metric mapping
# ---------------------------------------------------------------------------

#: Canonical audited metric name -> the ``financial_projections`` column holding
#: the model's *predicted* value for that metric. Ground-truth records are keyed
#: by these same metric names, so :meth:`Backtesting_Module.audit` pairs an
#: actual value with its prediction by looking the metric name up here (R11.5).
#: Only metrics present in *both* the stored projection and the ground-truth set
#: are audited; a ground-truth metric without a known predicted field, or with a
#: null stored prediction, has no comparable prediction and is skipped.
PREDICTED_METRIC_FIELDS: dict[str, str] = {
    "cpvh": "calculated_cpvh",
    "ltv_to_cost": "ltv_to_cost_multiple",
    "churn_reduction": "churn_reduction_pct",
    "payback_horizon": "payback_horizon_months",
}


# ---------------------------------------------------------------------------
# Input / output shapes
# ---------------------------------------------------------------------------


class GroundTruthMetric(TypedDict):
    """One observed actual-outcome metric within a ground-truth submission.

    Attributes:
        metric_name: The audited metric this actual belongs to (e.g. ``"cpvh"``).
        actual_value: The observed actual value; must be numeric (R11.2).
    """

    metric_name: str
    actual_value: Any


class GroundTruthRecord(TypedDict):
    """A ground-truth submission for one historical title (R11.1).

    Attributes:
        title_id: The title the observed outcomes belong to.
        metrics: One or more observed actual-outcome metrics.
    """

    title_id: uuid.UUID
    metrics: list[GroundTruthMetric]


class AuditMetric(TypedDict):
    """One audited metric row in the scorecard (design R11).

    Attributes:
        metric: The audited metric name.
        predicted: The model's predicted value for the metric.
        actual: The observed actual value for the metric.
        excluded: ``True`` when the metric was excluded from the MAPE
            computation because its actual value is zero (R11.7).
    """

    metric: str
    predicted: Decimal
    actual: Decimal
    excluded: bool


class AuditScorecard(TypedDict):
    """The audit result returned for a title (design R11).

    Attributes:
        title_id: The audited title.
        metrics: Per-metric predicted/actual/excluded rows (R11.6, R11.7).
        mape: The computed MAPE as a percentage rounded to 2 dp, or ``None``
            when every metric was excluded (R11.8).
        no_eligible_metrics: ``True`` when all metrics were excluded and MAPE is
            undefined; carries the :data:`~app.domain.mape.NO_ELIGIBLE_METRICS`
            reason code (R11.8).
    """

    title_id: uuid.UUID
    metrics: list[AuditMetric]
    mape: Decimal | None
    no_eligible_metrics: bool


class Backtesting_Module:
    """Historical backtest audit + MAPE scorecard builder (R11).

    Constructed with an injected :class:`~sqlalchemy.ext.asyncio.AsyncSession`;
    the title, financial-projection, and ground-truth repositories are bound to
    that same session so every read/write participates in the caller's
    unit-of-work. Like the repositories it builds on, writes ``flush`` rather
    than ``commit`` — the surrounding request/task owns the transaction
    boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        titles: TitleRepository | None = None,
        financial_projections: FinancialProjectionRepository | None = None,
        ground_truth: GroundTruthRepository | None = None,
    ) -> None:
        self.session = session
        self.titles = titles or TitleRepository(session)
        self.financial_projections = (
            financial_projections or FinancialProjectionRepository(session)
        )
        self.ground_truth = ground_truth or GroundTruthRepository(session)

    # ------------------------------------------------------------------ #
    # Ground-truth persistence (R11.1, R11.2)
    # ------------------------------------------------------------------ #

    async def persist_ground_truth(self, record: GroundTruthRecord) -> uuid.UUID:
        """Validate and persist a ground-truth submission (R11.1, R11.2).

        Validates the whole record *before* writing anything: the record must
        carry a ``title_id`` and at least one metric, and every metric must have
        a non-empty ``metric_name`` and a numeric ``actual_value``. If any part
        is invalid the method raises :class:`GroundTruthInvalidError` and
        persists **no** rows (R11.2) — validation is fully performed up front so
        a later bad metric cannot leave earlier metrics committed.

        Args:
            record: The ground-truth submission to validate and persist.

        Returns:
            The ``title_id`` the persisted actuals belong to, identifying the
            persisted record for the confirmation response (R11.1).

        Raises:
            GroundTruthInvalidError: A required field is missing or an actual
                value is non-numeric; nothing is persisted (R11.2).
        """
        title_id = self._require(record, "title_id")

        metrics = record.get("metrics")
        if not metrics:
            raise GroundTruthInvalidError(
                "A ground-truth record must contain at least one metric.",
                details={"field": "metrics"},
            )

        # Validate every metric and coerce actuals to Decimal BEFORE any write,
        # so a bad metric late in the list persists nothing (R11.2).
        validated: list[tuple[str, Decimal]] = []
        for index, metric in enumerate(metrics):
            metric_name = self._require(
                metric, "metric_name", context={"metric_index": index}
            )
            if "actual_value" not in metric or metric["actual_value"] is None:
                raise GroundTruthInvalidError(
                    "Ground-truth metric is missing a required field.",
                    details={"field": "actual_value", "metric_index": index},
                )
            actual_value = self._coerce_numeric(
                metric["actual_value"],
                metric_name=str(metric_name),
                metric_index=index,
            )
            validated.append((str(metric_name), actual_value))

        # All metrics are valid; persist them within the caller's transaction.
        # Upsert per (title, metric): a repeat submission for the same metric
        # replaces the prior actual rather than appending a duplicate row, so a
        # title carries exactly one ground-truth value per metric and the audit
        # scorecard renders one bar pair per metric (not one per submission).
        for metric_name, actual_value in validated:
            existing = await self.ground_truth.get_metric(title_id, metric_name)
            if existing is not None:
                await self.ground_truth.update(existing, actual_value=actual_value)
            else:
                await self.ground_truth.create(
                    HistoricalGroundTruth(
                        title_id=title_id,
                        metric_name=metric_name,
                        actual_value=actual_value,
                    )
                )

        return title_id

    # ------------------------------------------------------------------ #
    # Audit (R11.3 - R11.8)
    # ------------------------------------------------------------------ #

    async def audit(self, title_id: uuid.UUID) -> AuditScorecard:
        """Audit a historical title's predictions against ground truth (R11.3-R11.8).

        Retrieves the ground-truth records for the title (matching on the title
        identifier), pairs each actual value with the corresponding predicted
        value from the title's latest ``financial_projections`` row, computes
        MAPE excluding zero-actual metrics, and returns the scorecard.

        Args:
            title_id: The ``is_historical`` title to audit.

        Returns:
            An :class:`AuditScorecard` reporting, for each audited metric, the
            predicted value, the actual value, and whether it was excluded from
            MAPE (actual == 0), plus the computed MAPE — or ``None`` with
            ``no_eligible_metrics=True`` when every metric was excluded (R11.6,
            R11.7, R11.8).

        Raises:
            GroundTruthMissingError: The title has no ground-truth records, so it
                is excluded from the audit (R11.4).
        """
        # R11.3: retrieve ground truth for the title, matching on identifier.
        truths = await self.ground_truth.list_for_title(title_id)
        if not truths:
            # R11.4: a historical title without ground truth is excluded with an
            # error indicating ground-truth data is unavailable.
            raise GroundTruthMissingError(
                "No ground-truth record exists for the requested title.",
                details={"title_id": str(title_id)},
            )

        projection = await self.financial_projections.get_latest_for_title(title_id)

        # Collapse to one ground-truth value per metric, keeping the most recent
        # submission. New writes upsert (see persist_ground_truth), but this also
        # defends against any legacy duplicate rows so the scorecard always has a
        # single predicted/actual pair per metric.
        latest_by_metric: dict[str, HistoricalGroundTruth] = {}
        for truth in truths:
            current = latest_by_metric.get(truth.metric_name)
            if current is None or (
                truth.recorded_at is not None
                and current.recorded_at is not None
                and truth.recorded_at >= current.recorded_at
            ):
                latest_by_metric[truth.metric_name] = truth

        # Pair predicted vs actual per metric by metric name. Only metrics that
        # have both a comparable prediction and an actual are auditable.
        audit_metrics: list[AuditMetric] = []
        mape_pairs: list[tuple[Decimal, Decimal]] = []
        for truth in latest_by_metric.values():
            predicted = self._predicted_for(projection, truth.metric_name)
            if predicted is None:
                # No comparable prediction for this metric; nothing to audit.
                continue

            actual = Decimal(truth.actual_value)
            excluded = actual == 0  # R11.7: zero-actual excluded from MAPE.
            audit_metrics.append(
                AuditMetric(
                    metric=truth.metric_name,
                    predicted=predicted,
                    actual=actual,
                    excluded=excluded,
                )
            )
            if not excluded:
                mape_pairs.append((actual, predicted))

        # R11.5/R11.8: delegate the arithmetic to the pure domain function. It
        # returns None when no pair is eligible (every actual is zero, or there
        # are no comparable pairs at all).
        mape = compute_mape(mape_pairs)
        no_eligible = mape is None

        return AuditScorecard(
            title_id=title_id,
            metrics=audit_metrics,
            mape=mape,
            # R11.8: surface the stable reason code intent via the boolean flag.
            no_eligible_metrics=no_eligible,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _predicted_for(projection: Any, metric_name: str) -> Decimal | None:
        """Return the predicted value for ``metric_name`` from a projection.

        Looks the metric name up in :data:`PREDICTED_METRIC_FIELDS` to find the
        projection column holding the prediction. Returns ``None`` — meaning
        "no comparable prediction" — when there is no projection, the metric
        name is unknown, or the stored prediction is null.
        """
        if projection is None:
            return None
        field = PREDICTED_METRIC_FIELDS.get(metric_name)
        if field is None:
            return None
        value = getattr(projection, field, None)
        if value is None:
            return None
        return Decimal(value)

    @staticmethod
    def _require(
        mapping: Any,
        field: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Return ``mapping[field]`` or raise :class:`GroundTruthInvalidError`.

        A missing key or a ``None`` value both count as "missing a required
        field" (R11.2). ``context`` adds structured locating info (e.g. the
        offending metric index) to the error details.
        """
        value = mapping.get(field) if hasattr(mapping, "get") else None
        if value is None:
            details: dict[str, Any] = {"field": field}
            if context:
                details.update(context)
            raise GroundTruthInvalidError(
                "Ground-truth record is missing a required field.",
                details=details,
            )
        return value

    @staticmethod
    def _coerce_numeric(
        value: Any,
        *,
        metric_name: str,
        metric_index: int,
    ) -> Decimal:
        """Coerce an actual value to :class:`Decimal` or reject it (R11.2).

        Booleans and non-numeric values (e.g. strings that are not numbers) are
        rejected with :class:`GroundTruthInvalidError`, which identifies the
        offending metric. Nothing is persisted on failure.
        """
        # bool is a subclass of int; a boolean actual is not a valid number here.
        if isinstance(value, bool):
            raise GroundTruthInvalidError(
                "Ground-truth metric has a non-numeric actual value.",
                details={
                    "field": "actual_value",
                    "metric_name": metric_name,
                    "metric_index": metric_index,
                },
            )
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise GroundTruthInvalidError(
                "Ground-truth metric has a non-numeric actual value.",
                details={
                    "field": "actual_value",
                    "metric_name": metric_name,
                    "metric_index": metric_index,
                },
            ) from exc
