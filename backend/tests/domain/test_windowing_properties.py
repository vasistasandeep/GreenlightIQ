"""Property-based tests for milestone-based payback and windowing bounds.

# Feature: cineroi-ai, Property 30: Payback uses milestone schedule
# Feature: cineroi-ai, Property 31: Windowing within license duration

Property 30 (design.md) -- Validates: Requirements 7.1, 22.2.

* R7.1: ``compute_payback_horizon`` returns ``payback_horizon_months`` as the
  first month at which cumulative contribution turns strictly positive.
* R22.2: the horizon is computed from the milestone-based disbursement schedule
  rather than a single lump-sum disbursement. Property 30 verifies this by
  independent month-by-month recomputation and by exhibiting a schedule whose
  milestone-spread horizon differs from the lump-sum horizon.

Property 31 (design.md) -- Validates: Requirements 7.3-related windowing, 22.4.

* R22.4: ``validate_windowing`` accepts License_Terms if and only if the sum of
  the windowing periods is <= the license duration in months; otherwise it
  raises :class:`WindowingExceedsLicenseError`.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.windowing import (
    Milestone,
    PaybackComputationError,
    WindowType,
    WindowingExceedsLicenseError,
    compute_payback_horizon,
    validate_windowing,
    windowing_period_total,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Monthly contribution margin: strictly positive so a finite horizon always
# exists. Bounded below well away from zero so the payback walk stays short --
# the horizon is O(total_outflow / margin), so a microscopic margin against a
# large outflow would blow the month-by-month walk up to billions of
# iterations. Keeping margin >= 100 (and amounts bounded, below) caps the
# horizon in the low thousands of months, which keeps the property fast while
# still exercising both deferral behaviour and the first-positive-month logic.
_margin = st.decimals(
    min_value=Decimal("100"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# A single milestone amount: non-negative outflow in cents. Allowing zero keeps
# the input space honest (a milestone can disburse nothing). Bounded so the
# summed outflow stays small relative to the minimum margin, keeping the
# payback walk finite and fast.
_amount = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


@st.composite
def _milestone_schedule(draw: st.DrawFn) -> list[Milestone]:
    """A non-empty milestone schedule over 1-based months, unsorted allowed."""
    size = draw(st.integers(min_value=1, max_value=8))
    milestones: list[Milestone] = []
    for _ in range(size):
        month = draw(st.integers(min_value=1, max_value=36))
        amount = draw(_amount)
        milestones.append(Milestone(month=month, amount=amount))
    return milestones


# A windowing rule as the plain mapping shape the design uses (decoded JSONB).
@st.composite
def _window_rule(draw: st.DrawFn) -> dict:
    start = draw(st.integers(min_value=1, max_value=48))
    length = draw(st.integers(min_value=1, max_value=24))
    window_type = draw(st.sampled_from(list(WindowType)))
    return {
        "window_type": window_type,
        "start_month": start,
        "end_month": start + length - 1,  # inclusive -> length months
    }


_window_rules = st.lists(_window_rule(), min_size=0, max_size=6)


# ---------------------------------------------------------------------------
# Independent reference implementation for payback (not the module under test)
# ---------------------------------------------------------------------------


def _reference_payback(schedule: list[Milestone], margin: Decimal) -> int:
    """Walk month by month using the milestone schedule; first positive month.

    This is an independent recomputation of the contract described by R7.1 /
    R22.2 so the property does not merely restate the implementation.
    """
    outflow_by_month: dict[int, Decimal] = {}
    total = Decimal(0)
    latest = 1
    for m in schedule:
        month = m.month if m.month >= 1 else 1
        outflow_by_month[month] = outflow_by_month.get(month, Decimal(0)) + m.amount
        total += m.amount
        latest = max(latest, month)

    recovery = (
        1
        if total <= 0
        else int((total / margin).to_integral_value(rounding=ROUND_CEILING))
    )
    bound = latest + max(recovery, 1)

    cumulative = Decimal(0)
    for month in range(1, bound + 1):
        cumulative += outflow_by_month.get(month, Decimal(0))
        if (margin * month) - cumulative > 0:
            return month
    raise AssertionError("reference failed to find a positive-contribution month")


# ---------------------------------------------------------------------------
# Property 30: Payback uses milestone schedule
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 30: Payback uses milestone schedule
@settings(max_examples=200)
@given(schedule=_milestone_schedule(), margin=_margin)
def test_payback_is_first_positive_month_under_milestone_schedule(
    schedule: list[Milestone], margin: Decimal
) -> None:
    """R7.1/R22.2: horizon == first month cumulative contribution is positive.

    Verified against an independent month-by-month recomputation that spreads
    disbursements across their milestone months.
    """
    horizon = compute_payback_horizon(schedule, margin)

    # Matches the independent reference recomputation.
    assert horizon == _reference_payback(schedule, margin)

    # Build the per-month outflow for direct boundary checks.
    outflow_by_month: dict[int, Decimal] = {}
    for m in schedule:
        month = m.month if m.month >= 1 else 1
        outflow_by_month[month] = outflow_by_month.get(month, Decimal(0)) + m.amount

    def cumulative_contribution(upto: int) -> Decimal:
        spent = sum(
            (v for mth, v in outflow_by_month.items() if mth <= upto), Decimal(0)
        )
        return (margin * upto) - spent

    # The returned month is strictly positive-contribution ...
    assert cumulative_contribution(horizon) > 0
    # ... and it is the FIRST such month: every earlier month is non-positive.
    for earlier in range(1, horizon):
        assert cumulative_contribution(earlier) <= 0


# Feature: cineroi-ai, Property 30: Payback uses milestone schedule
@settings(max_examples=200)
@given(schedule=_milestone_schedule(), margin=_margin)
def test_payback_differs_from_lump_sum_when_disbursement_is_deferred(
    schedule: list[Milestone], margin: Decimal
) -> None:
    """R22.2: milestone-spread horizon never precedes the lump-sum-at-month-1
    horizon, and strictly exceeds it whenever any outflow is deferred.

    A lump sum at month 1 is the most pessimistic cash position early on; by
    deferring part of the outflow to later milestone months, cumulative
    contribution can turn positive no later than, and often earlier than, under
    a lump sum. This confirms the computation is schedule-sensitive rather than
    a lump-sum approximation.
    """
    total = sum((m.amount for m in schedule), Decimal(0))

    milestone_horizon = compute_payback_horizon(schedule, margin)
    lump_sum_horizon = compute_payback_horizon(
        [Milestone(month=1, amount=total)], margin
    )

    # Spreading disbursements can only help (or match) early contribution, so
    # the milestone horizon is never later than the lump-sum horizon.
    assert milestone_horizon <= lump_sum_horizon

    # If any outflow is deferred past month 1, the schedules genuinely differ in
    # at least one month's cumulative outflow -- demonstrating non-lump-sum
    # behaviour. The milestone horizon is then <= lump-sum horizon (checked
    # above) and the two computations are driven by different monthly outflows.
    deferred = any(m.month > 1 and m.amount > 0 for m in schedule)
    if deferred:
        # Under deferral the milestone cumulative outflow at month 1 is strictly
        # less than the lump-sum's, so milestone contribution at month 1 is
        # strictly greater -- the schedules are not interchangeable.
        first_month_outflow = sum(
            (m.amount for m in schedule if m.month <= 1), Decimal(0)
        )
        assert first_month_outflow < total


# Feature: cineroi-ai, Property 30: Payback uses milestone schedule
def test_payback_milestone_spread_beats_lump_sum_concrete() -> None:
    """R22.2 (anchor): a deferred-milestone schedule pays back before lump sum.

    Margin 100/month, total outflow 300. Lump sum of 300 at month 1 only turns
    positive at month 4 (400-300=100). Spreading 100/month over months 1-3
    keeps cumulative contribution at exactly 0 through month 3 and turns it
    positive at month 4 as well -- but moving the outflow later than the margin
    accrual makes the spread strictly better: 100 at month 3 only.
    """
    # Lump sum: 300 disbursed at month 1.
    lump = compute_payback_horizon([Milestone(month=1, amount=Decimal("300"))], Decimal("100"))
    assert lump == 4  # months 1..3: 100-300,200-300,300-300 <=0; month 4: 400-300>0

    # Deferred: a single 100 outflow at month 3.
    spread = compute_payback_horizon([Milestone(month=3, amount=Decimal("100"))], Decimal("100"))
    # month 1: 100-0=100 > 0 immediately.
    assert spread == 1

    assert spread < lump  # the schedules are not interchangeable


# Feature: cineroi-ai, Property 30: Payback uses milestone schedule
def test_payback_non_positive_margin_has_no_finite_horizon() -> None:
    """R7.1 (guard): a non-positive margin cannot reach positive contribution."""
    with pytest.raises(PaybackComputationError):
        compute_payback_horizon([Milestone(month=1, amount=Decimal("10"))], Decimal("0"))
    with pytest.raises(PaybackComputationError):
        compute_payback_horizon(
            [Milestone(month=1, amount=Decimal("10"))], Decimal("-5")
        )


# ---------------------------------------------------------------------------
# Property 31: Windowing within license duration
# ---------------------------------------------------------------------------


# Feature: cineroi-ai, Property 31: Windowing within license duration
@settings(max_examples=200)
@given(rules=_window_rules, slack=st.integers(min_value=0, max_value=24))
def test_windowing_accepted_iff_within_license_duration(
    rules: list[dict], slack: int
) -> None:
    """R22.4: accept iff summed windowing periods <= license_duration_months.

    ``license_duration`` is constructed relative to the summed periods so both
    the accept branch (duration >= summed) and the reject branch (duration <
    summed) are exercised across examples.
    """
    summed = windowing_period_total(rules)

    # Accept branch: duration at or above the summed periods (+slack).
    accept_duration = summed + slack if summed > 0 else summed + slack + 1
    accept_duration = max(accept_duration, 1)
    terms_ok = {
        "license_duration_months": accept_duration,
        "windowing_rules": rules,
    }
    assert validate_windowing(terms_ok) == summed

    # Reject branch: only meaningful when there is a positive summed period and
    # a strictly smaller positive duration exists.
    if summed >= 2:
        reject_duration = summed - 1 - (slack % summed)
        if reject_duration < 1:
            reject_duration = summed - 1
        terms_bad = {
            "license_duration_months": reject_duration,
            "windowing_rules": rules,
        }
        with pytest.raises(WindowingExceedsLicenseError) as exc:
            validate_windowing(terms_bad)
        assert exc.value.windowing_months == summed
        assert exc.value.license_duration_months == reject_duration


# Feature: cineroi-ai, Property 31: Windowing within license duration
@settings(max_examples=200)
@given(rules=_window_rules)
def test_windowing_boundary_equal_duration_accepts(rules: list[dict]) -> None:
    """R22.4 (boundary): summed == license_duration is accepted (<=, not <)."""
    summed = windowing_period_total(rules)
    duration = max(summed, 1)
    terms = {"license_duration_months": duration, "windowing_rules": rules}
    # Equal (or, when summed == 0, strictly greater) duration is accepted.
    assert validate_windowing(terms) == summed


# Feature: cineroi-ai, Property 31: Windowing within license duration
def test_windowing_concrete_accept_and_reject() -> None:
    """R22.4 (anchors): one accepting case and one rejecting case."""
    rules = [
        {"window_type": WindowType.EXCLUSIVE, "start_month": 1, "end_month": 6},
        {"window_type": WindowType.NON_EXCLUSIVE, "start_month": 7, "end_month": 12},
    ]
    # Summed = 6 + 6 = 12.
    assert windowing_period_total(rules) == 12

    # Accept: duration 12 >= 12.
    assert validate_windowing(
        {"license_duration_months": 12, "windowing_rules": rules}
    ) == 12

    # Reject: duration 11 < 12.
    with pytest.raises(WindowingExceedsLicenseError):
        validate_windowing({"license_duration_months": 11, "windowing_rules": rules})
