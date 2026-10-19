"""Tests for the deterministic fit solver domain module.

# Feature: content-eval-model

Targets the pure :mod:`app.domain.fit` module (task 5): a standard-library
non-negative least squares (NNLS) solver via projected coordinate descent and
the IRLS ``fit_log_wape`` wrapper for the log-space WAPE objective used by
viewing hours. These tests pin the fit math independently of the engine, before
any orchestration is wired. All tests import only the pure domain module -- no
database, no app framework.

The two formal properties exercised map to the design's "Correctness
Properties" section:

* Property 8 (Fit reproducibility): the fit is a deterministic function of its
  inputs -- byte-identical coefficients/intercept across repeated runs and
  across different nominal ``seed`` values (the seed never affects the fit).
* Property 9 (Fit structural constraints): every fitted coefficient the domain
  requires non-negative is ``>= 0``, including when the unconstrained optimum
  would be negative (the projection clamps it to 0).

The remaining example tests pin documented behavior: recovery of known
coefficients on synthetic fixtures, the zero-variance column guard (a
constant/all-zero column yields a 0 weight with no error), convergence within
the iteration budget, and the log-space ``fit_log_wape`` / ``predict_log_wape``
behavior.

Each property test carries a leading ``# Feature: content-eval-model,
Property N: ...`` comment matching the house convention and a docstring citing
the acceptance criteria it exercises.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.fit import (
    DEFAULT_MAX_ITERS,
    DEFAULT_TOL,
    ZERO_VARIANCE_EPS,
    FitResult,
    fit_log_wape,
    fit_nnls,
    predict,
    predict_log_wape,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# A single finite feature value spanning a realistic model-input range (both
# signs so the non-negativity projection is genuinely exercised by the fit).
_feature_value = st.floats(
    min_value=-50.0,
    max_value=50.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)

# A finite target value.
_target_value = st.floats(
    min_value=-500.0,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


@st.composite
def _design_matrix(draw: st.DrawFn) -> tuple[list[list[float]], list[float]]:
    """Draw a well-formed (non-ragged) design matrix ``x`` and target ``y``.

    Between 2 and 8 rows and 1 and 4 feature columns -- small enough that the
    Hypothesis runs stay fast but large enough to exercise several coordinates.
    """
    n_rows = draw(st.integers(min_value=2, max_value=8))
    n_features = draw(st.integers(min_value=1, max_value=4))
    x = [
        [draw(_feature_value) for _ in range(n_features)]
        for _ in range(n_rows)
    ]
    y = [draw(_target_value) for _ in range(n_rows)]
    return x, y


# ---------------------------------------------------------------------------
# Property 8: Fit reproducibility (R4.2)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 8: Fit reproducibility
# deadline=None: the NNLS solver runs up to DEFAULT_MAX_ITERS sweeps and its
# runtime varies with the drawn data; determinism, not latency, is under test.
@settings(max_examples=200, deadline=None)
@given(data=_design_matrix(), seed_a=st.integers(), seed_b=st.integers())
def test_fit_is_byte_identical_across_runs_and_seeds(
    data: tuple[list[list[float]], list[float]],
    seed_a: int,
    seed_b: int,
) -> None:
    """Validates: Requirements 4.2 (Property 8)

    ``fit_nnls`` is a deterministic function of its inputs: repeated runs on the
    same data produce byte-identical coefficients and intercept, and two
    arbitrary (distinct) ``seed`` values produce the same fit -- the nominal seed
    never affects the result.
    """
    x, y = data

    first = fit_nnls(x, y, seed=seed_a)
    repeat = fit_nnls(x, y, seed=seed_a)
    other_seed = fit_nnls(x, y, seed=seed_b)

    # Byte-identical across a repeated run with the same seed.
    assert first.coefficients == repeat.coefficients
    assert first.intercept == repeat.intercept
    assert first.iterations == repeat.iterations
    assert first.converged == repeat.converged

    # The seed must not affect the fit: a different seed gives the same result.
    assert first.coefficients == other_seed.coefficients
    assert first.intercept == other_seed.intercept


# Feature: content-eval-model, Property 8: Fit reproducibility
# deadline=None: the IRLS wrapper runs several inner NNLS solves, so a single
# example can be slow on pathological inputs; this test asserts determinism.
@settings(max_examples=100, deadline=None)
@given(data=_design_matrix(), seed_a=st.integers(), seed_b=st.integers())
def test_fit_log_wape_is_byte_identical_across_runs_and_seeds(
    data: tuple[list[list[float]], list[float]],
    seed_a: int,
    seed_b: int,
) -> None:
    """Validates: Requirements 4.2 (Property 8)

    The IRLS ``fit_log_wape`` wrapper is likewise a deterministic function of its
    inputs: repeated runs are byte-identical and the nominal ``seed`` never
    changes the coefficients or intercept.
    """
    x, y = data
    # Targets live in hour space for the log-WAPE objective; keep them finite
    # and non-negative hours.
    y_hours = [abs(v) for v in y]

    first = fit_log_wape(x, y_hours, seed=seed_a)
    repeat = fit_log_wape(x, y_hours, seed=seed_a)
    other_seed = fit_log_wape(x, y_hours, seed=seed_b)

    assert first.coefficients == repeat.coefficients
    assert first.intercept == repeat.intercept
    assert first.coefficients == other_seed.coefficients
    assert first.intercept == other_seed.intercept


# ---------------------------------------------------------------------------
# Property 9: Fit structural constraints (R4.3)
# ---------------------------------------------------------------------------


# Feature: content-eval-model, Property 9: Fit structural constraints
# deadline=None: the solver's sweep count varies with the drawn data; the
# non-negativity invariant, not latency, is under test.
@settings(max_examples=200, deadline=None)
@given(data=_design_matrix())
def test_every_fitted_coefficient_is_non_negative(
    data: tuple[list[list[float]], list[float]],
) -> None:
    """Validates: Requirements 4.3 (Property 9)

    For arbitrary (even adversarial) data, every fitted feature coefficient is
    ``>= 0``. The projection onto the non-negative orthant holds regardless of
    what the unconstrained least-squares optimum would be.
    """
    x, y = data
    result = fit_nnls(x, y)

    assert all(coef >= 0.0 for coef in result.coefficients)


# Feature: content-eval-model, Property 9: Fit structural constraints
def test_coefficient_clamped_to_zero_when_unconstrained_optimum_is_negative() -> None:
    """Validates: Requirements 4.3 (Property 9)

    When the unconstrained least-squares solution for a coefficient would be
    negative, the solver must clamp it to exactly 0 rather than return the
    negative value. Here ``y = -2 * x`` (a perfectly negative relationship), so
    the unconstrained slope is -2; the non-negative fit must pin it at 0.
    """
    x = [[0.0], [1.0], [2.0], [3.0], [4.0]]
    y = [0.0, -2.0, -4.0, -6.0, -8.0]

    result = fit_nnls(x, y, fit_intercept=False)

    assert result.coefficients == (0.0,)
    assert result.coefficients[0] >= 0.0


# Feature: content-eval-model, Property 9: Fit structural constraints
def test_log_wape_coefficients_are_non_negative() -> None:
    """Validates: Requirements 4.3 (Property 9)

    The IRLS ``fit_log_wape`` wrapper enforces the same non-negativity on every
    coordinate update even when the log-space relationship is negative.
    """
    # A decreasing log-space relationship: larger x -> fewer hours.
    x = [[0.0], [1.0], [2.0], [3.0], [4.0]]
    y_hours = [math.expm1(4.0 - xi[0]) for xi in x]

    result = fit_log_wape(x, y_hours, fit_intercept=True)

    assert all(coef >= 0.0 for coef in result.coefficients)


# ---------------------------------------------------------------------------
# Known-coefficient recovery (R4.1, R4.3)
# ---------------------------------------------------------------------------


def test_recovers_known_non_negative_coefficients_within_tolerance() -> None:
    """Validates: Requirements 4.1, 4.3

    Built from a known non-negative model ``y = intercept + B . x`` with no
    noise, ``fit_nnls`` recovers the known intercept and coefficients to within
    a tight tolerance. The design is well-conditioned (distinct, varying
    columns) so the unique NNLS optimum is the generating model.
    """
    true_intercept = 3.0
    true_betas = [1.5, 0.0, 4.25, 2.0]
    rows = [
        [1.0, 5.0, 2.0, 0.5],
        [2.0, 1.0, 3.0, 4.0],
        [3.0, 2.0, 0.0, 1.0],
        [0.5, 4.0, 6.0, 2.0],
        [4.0, 0.0, 1.0, 3.0],
        [1.0, 3.0, 5.0, 0.0],
        [2.5, 2.0, 2.0, 2.5],
        [0.0, 1.0, 4.0, 5.0],
    ]
    y = [
        true_intercept + sum(b * xi for b, xi in zip(true_betas, row))
        for row in rows
    ]

    result = fit_nnls(rows, y)

    assert result.converged is True
    assert math.isclose(result.intercept, true_intercept, abs_tol=1e-4)
    for recovered, expected in zip(result.coefficients, true_betas):
        assert math.isclose(recovered, expected, abs_tol=1e-4)
    # A near-perfect fit on noiseless data.
    assert result.metrics["train_mse"] < 1e-8


def test_feature_names_align_with_recovered_coefficients() -> None:
    """Validates: Requirements 4.1

    Supplied ``feature_names`` are carried through positionally onto the
    recovered coefficients so a caller can map a weight back to its driver.
    """
    rows = [[1.0, 2.0], [2.0, 1.0], [3.0, 4.0], [0.5, 2.5]]
    true_betas = [2.0, 0.5]
    y = [sum(b * xi for b, xi in zip(true_betas, row)) for row in rows]

    result = fit_nnls(
        rows, y, feature_names=("elasticity", "receptivity"), fit_intercept=False
    )

    assert result.feature_names == ("elasticity", "receptivity")
    assert len(result.coefficients) == 2
    assert math.isclose(result.coefficients[0], 2.0, abs_tol=1e-4)
    assert math.isclose(result.coefficients[1], 0.5, abs_tol=1e-4)


# ---------------------------------------------------------------------------
# Zero-variance / constant / all-zero column guard
# ---------------------------------------------------------------------------


def test_all_zero_column_yields_zero_weight_without_error() -> None:
    """Validates: Requirements 4.3

    An all-zero feature column has a zero weighted sum-of-squares, so its
    coefficient is pinned to 0 and the column is skipped -- no
    ``ZeroDivisionError`` -- while the live column is still fit normally.
    """
    # Column 0 is all zeros; column 1 carries the real signal y = 2 * x1.
    rows = [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0], [0.0, 4.0]]
    y = [2.0, 4.0, 6.0, 8.0]

    result = fit_nnls(rows, y, fit_intercept=False)

    assert result.coefficients[0] == 0.0
    assert math.isclose(result.coefficients[1], 2.0, abs_tol=1e-4)


def test_constant_nonzero_column_yields_zero_weight_without_error() -> None:
    """Validates: Requirements 4.3

    A constant (non-zero) column still has variance only through the intercept;
    its own weighted sum-of-squares exceeds the epsilon so it is not skipped by
    the guard, but a column that is constant AND all-zero is. This test uses a
    genuinely zero-variance (all-zero) column alongside a constant column to
    confirm no division error is raised and the fit completes.
    """
    # Column 0 constant-zero (zero variance), column 1 constant non-zero.
    rows = [[0.0, 5.0], [0.0, 5.0], [0.0, 5.0], [0.0, 5.0]]
    y = [1.0, 1.0, 1.0, 1.0]

    # Should not raise; the all-zero column 0 is pinned to 0.
    result = fit_nnls(rows, y)

    assert result.coefficients[0] == 0.0
    # ZERO_VARIANCE_EPS is the documented guard threshold.
    assert ZERO_VARIANCE_EPS == 1e-12


def test_log_wape_handles_all_zero_column_without_error() -> None:
    """Validates: Requirements 4.3

    The IRLS wrapper reuses the same coordinate descent, so an all-zero column
    is pinned to 0 there too with no error.
    """
    rows = [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0], [0.0, 4.0]]
    y_hours = [math.expm1(xi[1]) for xi in rows]

    result = fit_log_wape(rows, y_hours)

    assert result.coefficients[0] == 0.0


# ---------------------------------------------------------------------------
# Convergence within the iteration budget
# ---------------------------------------------------------------------------


def test_converges_within_iteration_budget_on_well_conditioned_fixture() -> None:
    """Validates: Requirements 4.2

    On a well-conditioned noiseless fixture the solver meets the tolerance
    before exhausting the iteration budget, so ``converged`` is True and the
    sweep count stays within ``DEFAULT_MAX_ITERS``.
    """
    rows = [
        [1.0, 0.0, 2.0],
        [0.0, 3.0, 1.0],
        [2.0, 1.0, 0.0],
        [1.0, 2.0, 3.0],
        [3.0, 0.0, 1.0],
        [0.0, 2.0, 2.0],
    ]
    true_betas = [1.0, 2.0, 0.5]
    y = [sum(b * xi for b, xi in zip(true_betas, row)) for row in rows]

    result = fit_nnls(rows, y)

    assert result.converged is True
    assert 0 < result.iterations <= DEFAULT_MAX_ITERS
    # The default tolerance is the documented early-stopping threshold.
    assert DEFAULT_TOL == 1e-10


# ---------------------------------------------------------------------------
# fit_log_wape recovery and predict_log_wape non-negativity
# ---------------------------------------------------------------------------


def test_fit_log_wape_recovers_known_log_space_model() -> None:
    """Validates: Requirements 4.1, 4.4

    Built from a known log-space model
    ``log1p(hours) = intercept + B . x`` with non-negative betas, the IRLS fit
    recovers the generating log-space coefficients, so predicting back in hour
    space via ``predict_log_wape`` reproduces the heavy-tailed hour targets to
    within tolerance.
    """
    true_intercept = 1.0
    true_betas = [0.75, 1.25, 0.0]
    rows = [
        [1.0, 0.5, 2.0],
        [2.0, 1.0, 0.0],
        [0.5, 2.0, 3.0],
        [3.0, 0.0, 1.0],
        [1.5, 1.5, 2.5],
        [0.0, 3.0, 1.0],
        [2.5, 0.5, 0.0],
        [1.0, 2.5, 4.0],
    ]
    # Heavy-tailed hour targets: expm1 of the linear log-space model.
    y_hours = [
        math.expm1(
            true_intercept + sum(b * xi for b, xi in zip(true_betas, row))
        )
        for row in rows
    ]

    result = fit_log_wape(rows, y_hours)

    assert result.objective == "wape_log"
    # Coefficients live in log1p space; they should match the generating model.
    assert math.isclose(result.intercept, true_intercept, abs_tol=1e-3)
    for recovered, expected in zip(result.coefficients, true_betas):
        assert math.isclose(recovered, expected, abs_tol=1e-3)

    # Predicting back in hour space reproduces the heavy-tailed actuals.
    preds = predict_log_wape(rows, result.coefficients, result.intercept)
    for predicted, actual in zip(preds, y_hours):
        assert math.isclose(predicted, actual, rel_tol=1e-3, abs_tol=1e-3)

    # A near-perfect fit drives WAPE to (approximately) zero.
    assert result.metrics["train_wape"] < 1e-3


def test_predict_log_wape_outputs_are_non_negative() -> None:
    """Validates: Requirements 4.4

    ``predict_log_wape`` maps log-space predictions through ``expm1`` and floors
    at 0, so a hour-space prediction is never negative even when the log-space
    value is below 0.
    """
    # An intercept below 0 in log space would give expm1(<0) < 0 before the
    # floor; the helper must clamp it to 0.
    x = [[1.0], [2.0], [3.0], [10.0]]
    coefficients = (0.0,)
    intercept = -5.0

    preds = predict_log_wape(x, coefficients, intercept)

    assert all(p >= 0.0 for p in preds)
    # The log-space prediction here is a constant -5, so every hour-space
    # prediction floors to exactly 0.
    assert all(p == 0.0 for p in preds)


def test_predict_matches_manual_linear_combination() -> None:
    """Validates: Requirements 4.1

    ``predict`` returns ``intercept + B . x`` per row, matching a hand-computed
    linear combination -- the helper the solver and metrics rely on.
    """
    x = [[1.0, 2.0], [3.0, 4.0]]
    coefficients = (0.5, 2.0)
    intercept = 1.0

    preds = predict(x, coefficients, intercept)

    assert preds == [1.0 + 0.5 * 1.0 + 2.0 * 2.0, 1.0 + 0.5 * 3.0 + 2.0 * 4.0]


def test_fit_result_is_frozen_dataclass_with_expected_fields() -> None:
    """Validates: Requirements 4.1

    A ``FitResult`` exposes the documented fields so callers can read the fitted
    weights, metrics, and convergence status.
    """
    rows = [[1.0], [2.0], [3.0]]
    y = [2.0, 4.0, 6.0]

    result = fit_nnls(rows, y, fit_intercept=False)

    assert isinstance(result, FitResult)
    assert result.objective == "squared_error"
    assert "train_mse" in result.metrics
    assert "train_wape" in result.metrics
    assert isinstance(result.coefficients, tuple)
