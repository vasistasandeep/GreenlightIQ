"""Property/unit tests for Backtesting_Module ground-truth handling (R11.2, R11.4).

Covers Property 17 (Ground-truth validation rejects invalid records, R11.2) from
the cineroi-ai design document, plus a unit test for the historical-title-without-
ground-truth exclusion (R11.4), exercising
``app.engines.backtesting.Backtesting_Module``.

Per the design testing strategy, engine orchestration is tested against *in-memory*
repository fakes rather than a real database. The fakes below model exactly the
slice of behaviour the module relies on:

* ``InMemoryGroundTruthRepository.create(instance)`` appends one row and assigns a
  fresh ``ground_truth_id`` (mirroring ``BaseRepository.create`` which flushes so
  server defaults populate). ``list_for_title`` returns the matching rows. A
  ``created`` list exposes exactly what was persisted so a test can assert that an
  invalid record persisted *nothing*.
* ``InMemoryFinancialProjectionRepository.get_latest_for_title`` returns a stored
  projection (unused by these validation/missing tests but injected for parity).
* ``InMemoryTitleRepository`` is a minimal stand-in injected for parity.

The real :class:`Backtesting_Module` accepts the repositories by injection, so the
``session`` argument is an inert stand-in that is never touched.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import GroundTruthInvalidError, GroundTruthMissingError
from app.engines.backtesting import Backtesting_Module
from app.models.historical_ground_truth import HistoricalGroundTruth


# ---------------------------------------------------------------------------
# In-memory repository fakes
# ---------------------------------------------------------------------------


class InMemoryGroundTruthRepository:
    """In-memory stand-in for ``GroundTruthRepository`` (R11.1, R11.2, R11.4).

    ``create`` appends one row and assigns a fresh id (mirroring the real
    repository's flush-on-create). ``list_for_title`` returns the rows matching a
    title id. The ``created`` list records every persisted row so a test can assert
    that a rejected record persisted nothing at all.
    """

    def __init__(self) -> None:
        self.created: list[HistoricalGroundTruth] = []

    async def create(self, instance: HistoricalGroundTruth) -> HistoricalGroundTruth:
        if getattr(instance, "ground_truth_id", None) is None:
            instance.ground_truth_id = uuid.uuid4()
        self.created.append(instance)
        return instance

    async def list_for_title(self, title_id: uuid.UUID) -> list[HistoricalGroundTruth]:
        return [row for row in self.created if row.title_id == title_id]

    async def get_metric(
        self, title_id: uuid.UUID, metric_name: str
    ) -> HistoricalGroundTruth | None:
        for row in self.created:
            if row.title_id == title_id and row.metric_name == metric_name:
                return row
        return None

    async def update(
        self, instance: HistoricalGroundTruth, **values: Any
    ) -> HistoricalGroundTruth:
        for key, value in values.items():
            setattr(instance, key, value)
        return instance


class InMemoryFinancialProjectionRepository:
    """Minimal in-memory stand-in for ``FinancialProjectionRepository``."""

    def __init__(self) -> None:
        self._by_title: dict[uuid.UUID, Any] = {}

    def set_latest(self, title_id: uuid.UUID, projection: Any) -> None:
        self._by_title[title_id] = projection

    async def get_latest_for_title(self, title_id: uuid.UUID) -> Any | None:
        return self._by_title.get(title_id)


class InMemoryTitleRepository:
    """Minimal in-memory stand-in for ``TitleRepository`` (injected for parity)."""


def _make_module() -> tuple[Backtesting_Module, InMemoryGroundTruthRepository]:
    """Build a ``Backtesting_Module`` wired to fresh in-memory fakes."""
    ground_truth = InMemoryGroundTruthRepository()
    module = Backtesting_Module(
        session=object(),  # type: ignore[arg-type]
        titles=InMemoryTitleRepository(),  # type: ignore[arg-type]
        financial_projections=InMemoryFinancialProjectionRepository(),  # type: ignore[arg-type]
        ground_truth=ground_truth,  # type: ignore[arg-type]
    )
    return module, ground_truth


# ---------------------------------------------------------------------------
# Record generation: a mix of valid and each kind of invalid record
# ---------------------------------------------------------------------------

_METRIC_NAMES = st.sampled_from(
    ["cpvh", "ltv_to_cost", "churn_reduction", "payback_horizon"]
)

# Numeric actuals the module must accept: ints, floats, Decimals, numeric strings.
_valid_actuals = st.one_of(
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.decimals(allow_nan=False, allow_infinity=False, places=4,
                min_value=Decimal("-1000000"), max_value=Decimal("1000000")),
    st.integers(min_value=-1000, max_value=1000).map(str),
)

# Non-numeric / boolean actuals the module must reject (R11.2). bool is explicitly
# rejected even though it subclasses int.
_non_numeric_actuals = st.one_of(
    st.booleans(),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=8),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)


@st.composite
def _valid_metric(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "metric_name": draw(_METRIC_NAMES),
        "actual_value": draw(_valid_actuals),
    }


@st.composite
def _valid_record(draw: st.DrawFn) -> dict[str, Any]:
    metrics = draw(st.lists(_valid_metric(), min_size=1, max_size=4))
    return {"title_id": uuid.uuid4(), "metrics": metrics}


# --- Each distinct kind of invalid record (R11.2) ------------------------- #


@st.composite
def _missing_title_id(draw: st.DrawFn) -> dict[str, Any]:
    """A record with no ``title_id`` (or an explicit ``None``)."""
    record: dict[str, Any] = {"metrics": draw(st.lists(_valid_metric(), min_size=1, max_size=3))}
    if draw(st.booleans()):
        record["title_id"] = None
    return record


@st.composite
def _missing_metrics(draw: st.DrawFn) -> dict[str, Any]:
    """A record with no metrics: absent, ``None``, or an empty list."""
    record: dict[str, Any] = {"title_id": uuid.uuid4()}
    choice = draw(st.sampled_from(["absent", "none", "empty"]))
    if choice == "none":
        record["metrics"] = None
    elif choice == "empty":
        record["metrics"] = []
    return record


@st.composite
def _metric_missing_name(draw: st.DrawFn) -> dict[str, Any]:
    """A record where one metric is missing ``metric_name`` (or it is ``None``)."""
    good = draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    bad: dict[str, Any] = {"actual_value": draw(_valid_actuals)}
    if draw(st.booleans()):
        bad["metric_name"] = None
    metrics = good + [bad] + draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    return {"title_id": uuid.uuid4(), "metrics": metrics}


@st.composite
def _metric_missing_actual(draw: st.DrawFn) -> dict[str, Any]:
    """A record where one metric is missing ``actual_value`` (or it is ``None``)."""
    good = draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    bad: dict[str, Any] = {"metric_name": draw(_METRIC_NAMES)}
    if draw(st.booleans()):
        bad["actual_value"] = None
    metrics = good + [bad] + draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    return {"title_id": uuid.uuid4(), "metrics": metrics}


@st.composite
def _metric_non_numeric_actual(draw: st.DrawFn) -> dict[str, Any]:
    """A record where one metric has a non-numeric/boolean ``actual_value``."""
    good = draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    bad = {"metric_name": draw(_METRIC_NAMES), "actual_value": draw(_non_numeric_actuals)}
    metrics = good + [bad] + draw(st.lists(_valid_metric(), min_size=0, max_size=2))
    return {"title_id": uuid.uuid4(), "metrics": metrics}


_invalid_record = st.one_of(
    _missing_title_id(),
    _missing_metrics(),
    _metric_missing_name(),
    _metric_missing_actual(),
    _metric_non_numeric_actual(),
)

# A record tagged with whether it is expected to be valid, so a single property
# can exercise both the accept and the reject paths across many examples.
_tagged_record = st.one_of(
    _valid_record().map(lambda r: (True, r)),
    _invalid_record.map(lambda r: (False, r)),
)


# ---------------------------------------------------------------------------
# Property 17: Ground-truth validation rejects invalid records (R11.2)
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 17: Ground-truth validation rejects invalid records
# Validates: Requirements 11.2
@settings(max_examples=200, deadline=None)
@given(tagged=_tagged_record)
async def test_ground_truth_validation_rejects_invalid_records(
    tagged: tuple[bool, dict[str, Any]],
) -> None:
    """Invalid records are rejected and persist nothing; valid records persist.

    For any Ground_Truth_Record that is missing a required field (``title_id``,
    the metric list, a metric's ``metric_name`` or ``actual_value``) or that
    carries a non-numeric / boolean actual value, ``persist_ground_truth`` raises
    :class:`GroundTruthInvalidError` and persists **no** rows — the ground-truth
    fake must have received zero creates. A fully valid record persists one row
    per DISTINCT metric name (persistence upserts per title+metric, so a repeated
    metric replaces rather than duplicates) and returns the title id (R11.2, R11.1).
    """
    is_valid, record = tagged
    module, ground_truth = _make_module()

    if is_valid:
        returned = await module.persist_ground_truth(record)  # type: ignore[arg-type]
        # A valid record persists exactly one row per distinct metric name and
        # returns the id; a repeated metric upserts rather than duplicating.
        assert returned == record["title_id"]
        distinct_metrics = {m["metric_name"] for m in record["metrics"]}
        assert len(ground_truth.created) == len(distinct_metrics)
        for row in ground_truth.created:
            assert row.title_id == record["title_id"]
            assert isinstance(row.actual_value, Decimal)
    else:
        with pytest.raises(GroundTruthInvalidError):
            await module.persist_ground_truth(record)  # type: ignore[arg-type]
        # Nothing was persisted: validation happens fully up front (R11.2).
        assert ground_truth.created == []


# ---------------------------------------------------------------------------
# Unit test: missing-ground-truth exclusion (R11.4)
# ---------------------------------------------------------------------------


async def test_audit_without_ground_truth_raises_missing_error() -> None:
    """Auditing a historical title with no ground truth raises missing error (R11.4).

    A title that has ``is_historical`` set but no corresponding Ground_Truth_Record
    is excluded from the audit: ``audit`` raises :class:`GroundTruthMissingError`
    (which maps to ``404 GROUND_TRUTH_MISSING``) rather than returning a scorecard.
    """
    module, ground_truth = _make_module()
    title_id = uuid.uuid4()

    # No ground-truth rows were created for this title.
    assert await ground_truth.list_for_title(title_id) == []

    with pytest.raises(GroundTruthMissingError):
        await module.audit(title_id)


async def test_audit_with_ground_truth_for_other_title_still_raises() -> None:
    """Ground truth for a *different* title does not satisfy the audited one (R11.4).

    Matching is on the title identifier (R11.3), so rows recorded for an unrelated
    title must not make the audited title appear to have ground truth.
    """
    module, ground_truth = _make_module()
    other_title = uuid.uuid4()
    audited_title = uuid.uuid4()

    await ground_truth.create(
        HistoricalGroundTruth(
            title_id=other_title,
            metric_name="cpvh",
            actual_value=Decimal("12.5"),
        )
    )

    with pytest.raises(GroundTruthMissingError):
        await module.audit(audited_title)
