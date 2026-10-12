"""Pure domain functions for licensing windowing and milestone-based payback (R22, R7).

This module is intentionally free of any I/O, database access, or framework
dependencies: it contains only deterministic functions over typed inputs so it
can be exhaustively exercised by property-based tests (design Properties 30-31).

Three concerns are captured here:

* :func:`validate_windowing` -- reject License_Terms whose summed windowing
  periods exceed ``license_duration_months`` (R22.4). ``windowing_rules`` is an
  ordered list of ``{window_type: EXCLUSIVE|NON_EXCLUSIVE, start_month,
  end_month}``. A violation raises :class:`WindowingExceedsLicenseError`, which
  the system maps to the ``WINDOWING_EXCEEDS_LICENSE`` (HTTP 422) error envelope.

* :func:`compute_payback_horizon` -- walk the milestone payment schedule month
  by month, accumulating disbursements against the monthly contribution margin,
  and return the first month (an ``int``) at which cumulative contribution turns
  strictly positive (R7.1, R22.2). This deliberately uses the milestone-based
  disbursement, never a single lump sum.

* :func:`project_window_value` / :func:`partition_windows` -- distinguish
  exclusive windows from non-exclusive windows when projecting value (R22.3).

All monetary values use :class:`decimal.Decimal` for exact precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from typing import Iterable, Mapping, Optional, Sequence, Union

__all__ = [
    "WindowType",
    "WindowingError",
    "WindowingExceedsLicenseError",
    "PaybackComputationError",
    "WindowingRule",
    "Milestone",
    "WindowValueProjection",
    "validate_windowing",
    "windowing_period_total",
    "compute_payback_horizon",
    "partition_windows",
    "project_window_value",
]

Number = Union[Decimal, int, str]


class WindowType(str, Enum):
    """The two licensing window exclusivity classifications (R22.3)."""

    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class WindowingError(ValueError):
    """Base class for windowing/payback domain errors."""


class WindowingExceedsLicenseError(WindowingError):
    """Raised when summed windowing periods exceed the license duration (R22.4).

    The system maps this to the ``WINDOWING_EXCEEDS_LICENSE`` (HTTP 422) error
    envelope and rejects the License_Terms with a descriptive message naming the
    summed window months and the license duration.
    """

    def __init__(self, windowing_months: int, license_duration_months: int) -> None:
        self.windowing_months = windowing_months
        self.license_duration_months = license_duration_months
        super().__init__(
            "Windowing exceeds the license duration: summed windowing periods "
            f"({windowing_months} months) exceed the license duration "
            f"({license_duration_months} months)."
        )


class PaybackComputationError(WindowingError):
    """Raised when payback cannot be computed from the given inputs.

    This covers a non-positive monthly contribution margin (the title never
    turns positive, so no finite payback horizon exists) and malformed
    milestone data.
    """


@dataclass(frozen=True)
class WindowingRule:
    """A single ordered windowing rule within License_Terms (R22).

    ``start_month`` and ``end_month`` are 1-based inclusive month offsets within
    the license. The window spans ``end_month - start_month + 1`` months.
    """

    window_type: WindowType
    start_month: int
    end_month: int

    @property
    def duration_months(self) -> int:
        """The inclusive length of this window in months."""
        return self.end_month - self.start_month + 1


@dataclass(frozen=True)
class Milestone:
    """A single milestone disbursement in the payment schedule (R22.2).

    ``month`` is the 1-based month in which ``amount`` (in ``currency``) is
    disbursed. Payback computation treats ``amount`` as a cost outflow.
    """

    month: int
    amount: Decimal
    currency: str = "USD"


@dataclass(frozen=True)
class WindowValueProjection:
    """Projected value split by window exclusivity (R22.3)."""

    exclusive_value: Decimal
    non_exclusive_value: Decimal

    @property
    def total_value(self) -> Decimal:
        return self.exclusive_value + self.non_exclusive_value


def _to_decimal(value: Number) -> Decimal:
    """Coerce a numeric input to ``Decimal`` without binary-float error.

    ``float`` is intentionally not accepted: money math must stay exact.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly.
        raise TypeError("amount must be numeric, not bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(
        f"amount must be Decimal, int, or str; got {type(value).__name__}"
    )


def _coerce_rule(rule: Union[WindowingRule, Mapping[str, object]]) -> WindowingRule:
    """Coerce a mapping (e.g. decoded JSONB) or a :class:`WindowingRule`."""
    if isinstance(rule, WindowingRule):
        return rule
    window_type = rule["window_type"]
    if not isinstance(window_type, WindowType):
        window_type = WindowType(str(window_type))
    start_month = int(rule["start_month"])  # type: ignore[arg-type]
    end_month = int(rule["end_month"])  # type: ignore[arg-type]
    if end_month < start_month:
        raise WindowingError(
            f"window end_month ({end_month}) precedes start_month ({start_month})."
        )
    return WindowingRule(
        window_type=window_type,
        start_month=start_month,
        end_month=end_month,
    )


def _coerce_milestone(
    milestone: Union[Milestone, Mapping[str, object]],
) -> Milestone:
    """Coerce a mapping (e.g. decoded JSONB) or a :class:`Milestone`."""
    if isinstance(milestone, Milestone):
        return milestone
    month = int(milestone["month"])  # type: ignore[arg-type]
    amount = _to_decimal(milestone["amount"])  # type: ignore[index]
    currency = str(milestone.get("currency", "USD"))  # type: ignore[union-attr]
    return Milestone(month=month, amount=amount, currency=currency)


def windowing_period_total(
    windowing_rules: Iterable[Union[WindowingRule, Mapping[str, object]]],
) -> int:
    """Return the summed length (in months) of all windowing periods (R22.4).

    Each window contributes ``end_month - start_month + 1`` months. The windows
    are summed as given (the design treats ``windowing_rules`` as an ordered
    list of periods whose total is compared against the license duration).
    """
    total = 0
    for raw in windowing_rules:
        total += _coerce_rule(raw).duration_months
    return total


def validate_windowing(
    terms: Mapping[str, object],
) -> int:
    """Validate License_Terms windowing against the license duration (R22.4).

    ``terms`` is a mapping carrying at least:

    * ``license_duration_months``: the total license duration (``int`` > 0).
    * ``windowing_rules``: an ordered list of windowing rules, each a
      :class:`WindowingRule` or a mapping with ``window_type``, ``start_month``,
      and ``end_month``.

    The terms are accepted if and only if the sum of the windowing periods is
    less than or equal to ``license_duration_months`` (R22.4, Property 31).

    Returns:
        The summed windowing-period months (useful to the caller / tests).

    Raises:
        WindowingExceedsLicenseError: If the summed windowing periods strictly
            exceed ``license_duration_months``.
        WindowingError: If the license duration is missing or not positive, or a
            window is malformed.
    """
    license_duration = terms.get("license_duration_months")
    if license_duration is None:
        raise WindowingError("license_duration_months is required.")
    license_duration = int(license_duration)  # type: ignore[arg-type]
    if license_duration <= 0:
        raise WindowingError(
            f"license_duration_months must be positive; got {license_duration}."
        )

    rules = terms.get("windowing_rules") or []
    summed = windowing_period_total(rules)  # type: ignore[arg-type]

    if summed > license_duration:
        raise WindowingExceedsLicenseError(
            windowing_months=summed,
            license_duration_months=license_duration,
        )
    return summed


def compute_payback_horizon(
    milestone_schedule: Sequence[Union[Milestone, Mapping[str, object]]],
    monthly_margin: Number,
    *,
    max_months: Optional[int] = None,
) -> int:
    """Compute the payback horizon from a milestone schedule (R7.1, R22.2).

    Walks the schedule month by month starting at month 1. For each month the
    cumulative contribution is::

        cumulative_margin   = monthly_margin * months_elapsed
        cumulative_outflow  = sum of milestone amounts disbursed through month
        cumulative_contrib  = cumulative_margin - cumulative_outflow

    and returns the first month at which ``cumulative_contrib`` turns strictly
    positive. Because disbursements are spread across the milestone schedule
    rather than taken as a single lump sum at month 1, the horizon reflects the
    real licensing cash flow (R22.2) and never a lump-sum approximation.

    Args:
        milestone_schedule: Milestone disbursements, each a :class:`Milestone`
            or a mapping with ``month``/``amount``/``currency``. Months need not
            be sorted; months at or below zero are treated as disbursed by
            month 1.
        monthly_margin: The monthly contribution margin earned each month. Must
            be strictly positive, otherwise cumulative contribution can never
            turn positive and no finite horizon exists.
        max_months: Optional safety cap on how many months to walk. Defaults to
            the latest milestone month plus a margin large enough to recover the
            total disbursement at the given monthly margin, guaranteeing a
            finite walk when a positive horizon exists.

    Returns:
        The first month (1-based ``int``) at which cumulative contribution turns
        strictly positive.

    Raises:
        PaybackComputationError: If ``monthly_margin`` is not strictly positive,
            or if no positive-contribution month is reached within ``max_months``.
    """
    margin = _to_decimal(monthly_margin)
    if margin <= 0:
        raise PaybackComputationError(
            "monthly contribution margin must be strictly positive to reach a "
            f"finite payback horizon; got {margin}."
        )

    milestones = [_coerce_milestone(m) for m in milestone_schedule]

    # Group disbursements by the month in which they are paid. Non-positive
    # months are folded into month 1 (disbursed at the start of the license).
    outflow_by_month: dict[int, Decimal] = {}
    total_outflow = Decimal(0)
    latest_month = 1
    for m in milestones:
        month = m.month if m.month >= 1 else 1
        outflow_by_month[month] = outflow_by_month.get(month, Decimal(0)) + m.amount
        total_outflow += m.amount
        latest_month = max(latest_month, month)

    # Bound the walk. Once every milestone is disbursed, each further month adds
    # exactly ``margin`` of contribution, so the horizon cannot exceed the last
    # milestone month plus ceil(total_outflow / margin) months.
    if max_months is None:
        if total_outflow <= 0:
            # No positive outflow: contribution is positive from month 1.
            recovery_months = 1
        else:
            recovery_months = int(
                (total_outflow / margin).to_integral_value(rounding=ROUND_CEILING)
            )
        max_months = latest_month + max(recovery_months, 1)

    cumulative_outflow = Decimal(0)
    for month in range(1, max_months + 1):
        cumulative_outflow += outflow_by_month.get(month, Decimal(0))
        cumulative_contribution = (margin * month) - cumulative_outflow
        if cumulative_contribution > 0:
            return month

    raise PaybackComputationError(
        "cumulative contribution did not turn positive within "
        f"{max_months} months (total disbursement {total_outflow}, monthly "
        f"margin {margin}); no finite payback horizon under this schedule."
    )


def partition_windows(
    windowing_rules: Iterable[Union[WindowingRule, Mapping[str, object]]],
) -> tuple[list[WindowingRule], list[WindowingRule]]:
    """Split windowing rules into exclusive and non-exclusive windows (R22.3).

    Returns a ``(exclusive, non_exclusive)`` tuple preserving the original order
    within each group, so callers can project value differently for the two
    kinds of windows.
    """
    exclusive: list[WindowingRule] = []
    non_exclusive: list[WindowingRule] = []
    for raw in windowing_rules:
        rule = _coerce_rule(raw)
        if rule.window_type is WindowType.EXCLUSIVE:
            exclusive.append(rule)
        else:
            non_exclusive.append(rule)
    return exclusive, non_exclusive


def project_window_value(
    windowing_rules: Iterable[Union[WindowingRule, Mapping[str, object]]],
    *,
    exclusive_value_per_month: Number,
    non_exclusive_value_per_month: Number,
) -> WindowValueProjection:
    """Project value distinguishing exclusive from non-exclusive windows (R22.3).

    Exclusive windows command a premium per-month value relative to
    non-exclusive windows, so value is projected separately for each kind rather
    than with a single blended rate. Each window contributes
    ``duration_months * rate`` where the rate depends on the window's
    exclusivity.

    Args:
        windowing_rules: The ordered windowing rules.
        exclusive_value_per_month: Projected value per month of an exclusive
            window (typically the premium rate).
        non_exclusive_value_per_month: Projected value per month of a
            non-exclusive window.

    Returns:
        A :class:`WindowValueProjection` carrying the exclusive and
        non-exclusive value components (and their total via ``total_value``).
    """
    exclusive_rate = _to_decimal(exclusive_value_per_month)
    non_exclusive_rate = _to_decimal(non_exclusive_value_per_month)

    exclusive_rules, non_exclusive_rules = partition_windows(windowing_rules)

    exclusive_value = sum(
        (Decimal(r.duration_months) * exclusive_rate for r in exclusive_rules),
        Decimal(0),
    )
    non_exclusive_value = sum(
        (Decimal(r.duration_months) * non_exclusive_rate for r in non_exclusive_rules),
        Decimal(0),
    )

    return WindowValueProjection(
        exclusive_value=exclusive_value,
        non_exclusive_value=non_exclusive_value,
    )
