"""Deterministic fitting core for the Content_Eval_System (content-eval-model).

A tiny, standard-library **non-negative least squares (NNLS)** solver via
projected coordinate descent, plus an **IRLS** (iteratively reweighted least
squares) wrapper that fits/evaluates on a log scale and optimizes a
percentage-scale objective (WAPE / Log-Scale MAE) for the heavy-tailed
``Projected_Viewing_Hours`` target. It learns the per-feature coefficients that
the hand-tuned :mod:`app.domain.churn` and :mod:`app.domain.viewing_hours`
models would otherwise carry as ``Illustrative_Coefficients``.

Determinism (R4.2, Property 8). The procedure is fully reproducible: a fixed
iteration count (:data:`DEFAULT_MAX_ITERS`), a fixed convergence tolerance
(:data:`DEFAULT_TOL`), and **no randomness, no wall-clock, and no environment
dependence**. There is a nominal ``seed`` parameter for API symmetry, but the
solver uses it for nothing — the fit is a deterministic function of its inputs
alone. Features are always iterated in a fixed, caller-supplied column order
(never over a ``set`` or a ``dict`` whose order could drift), so repeated runs on
any OS produce byte-identical coefficients. All arithmetic is plain IEEE-754
``float`` (no numpy/BLAS), so there is no cross-platform matrix-library drift.

Structural constraints (R4.3, Property 9). Every coefficient is projected to
``>= 0`` immediately after its coordinate update, so a fitted model keeps the
monotonicity and explainability guarantees of the hand-tuned models. The
intercept is optionally unconstrained (it is a base level, not a feature
weight), controlled by ``fit_intercept`` / ``nonneg_intercept``.

Zero-variance guard. The coordinate update divides by
``denom = sum(w_n * x_nj**2)``. When a column is constant or all-zero across the
training rows (``denom <= 1e-12``) the coefficient is pinned to ``0`` and the
column is skipped, so a sparse/constant feature can never raise
``ZeroDivisionError``.

Objectives. Two modes are provided:

* :func:`fit_nnls` — plain squared-error NNLS for the additive drivers
  (churn, watch-time elasticity, ad-load receptivity).
* :func:`fit_log_wape` — the IRLS wrapper for viewing hours: targets and
  predictions live in ``log1p`` space and the loss optimized/reported is WAPE
  (weighted absolute percentage error) with a Log-Scale MAE companion metric.

This module is pure: no I/O, no database access, no async, no global mutable
state, and it imports only the Python standard library, so it is importable
without the application framework.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "DEFAULT_MAX_ITERS",
    "DEFAULT_TOL",
    "DEFAULT_SEED",
    "ZERO_VARIANCE_EPS",
    "FitResult",
    "fit_nnls",
    "fit_log_wape",
    "predict",
    "predict_log_wape",
]

# Fixed iteration budget. A convex non-negative objective over 5-8 features and
# 50-100 rows converges well within this (and well under the 2-second budget).
DEFAULT_MAX_ITERS = 500

# Fixed convergence tolerance: stop early once the largest absolute coefficient
# change in a full sweep drops below this. Early stopping is deterministic (it
# depends only on the data), so it never breaks byte-identical reproducibility.
DEFAULT_TOL = 1e-10

# Nominal seed, kept only for API symmetry / provenance. The solver is fully
# deterministic and consumes no randomness, so the value never affects the fit.
DEFAULT_SEED = 0

# Zero-variance denominator guard: a column whose weighted sum-of-squares is at
# or below this is treated as constant/sparse and its coefficient pinned to 0.
ZERO_VARIANCE_EPS = 1e-12

# IRLS floor so a weight derived from a near-zero prediction stays finite.
_IRLS_WEIGHT_FLOOR = 1e-9


@dataclass(frozen=True)
class FitResult:
    """The outcome of a :func:`fit_nnls` / :func:`fit_log_wape` run.

    ``coefficients`` is positional, aligned with the training design-matrix
    columns (and with ``feature_names`` when supplied). ``intercept`` is the
    fitted base level. ``metrics`` carries train (and, when a held-out split is
    supplied, test) error figures keyed by name. ``iterations`` is the number of
    coordinate-descent sweeps actually run and ``converged`` whether the
    tolerance was met before the iteration budget was exhausted.
    """

    coefficients: tuple[float, ...]
    intercept: float
    feature_names: tuple[str, ...]
    metrics: dict[str, float]
    iterations: int
    converged: bool
    objective: str


def _validate_design(
    x: Sequence[Sequence[float]],
    y: Sequence[float],
    feature_names: Sequence[str] | None,
) -> tuple[int, int, tuple[str, ...]]:
    """Validate the design matrix / target shapes and resolve column names.

    Returns ``(n_rows, n_features, names)``. Raises ``ValueError`` on a ragged
    matrix or a target length mismatch; an empty matrix is permitted (it yields
    an all-zero fit) so a degenerate training split never crashes a fit.
    """
    n_rows = len(x)
    if n_rows != len(y):
        raise ValueError(
            f"row count mismatch: {n_rows} feature rows vs {len(y)} targets"
        )
    n_features = len(x[0]) if n_rows else 0
    for i, row in enumerate(x):
        if len(row) != n_features:
            raise ValueError(
                f"ragged design matrix: row {i} has {len(row)} columns, "
                f"expected {n_features}"
            )
    if feature_names is None:
        names = tuple(f"x{j}" for j in range(n_features))
    else:
        if len(feature_names) != n_features:
            raise ValueError(
                f"feature_names length {len(feature_names)} != "
                f"{n_features} columns"
            )
        names = tuple(feature_names)
    return n_rows, n_features, names


def _coordinate_descent(
    x: Sequence[Sequence[float]],
    y: Sequence[float],
    weights: Sequence[float],
    n_features: int,
    fit_intercept: bool,
    nonneg_intercept: bool,
    max_iters: int,
    tol: float,
) -> tuple[list[float], float, int, bool]:
    """Weighted non-negative least squares by projected coordinate descent.

    Minimizes ``sum_n weights[n] * (y[n] - intercept - sum_j beta[j]*x[n][j])**2``
    subject to ``beta[j] >= 0`` (and, when ``nonneg_intercept``, the intercept
    too). Columns and rows are visited in fixed ascending index order so the
    float accumulation is identical on every run and platform. Returns
    ``(beta, intercept, iterations, converged)``.
    """
    n_rows = len(x)
    beta = [0.0] * n_features
    intercept = 0.0

    # Residual r[n] = y[n] - prediction[n]; maintained incrementally so each
    # coordinate update is O(n_rows) and the whole sweep is O(n_rows*n_features).
    residual = list(y)

    # Precompute each column's weighted sum-of-squares (the coordinate-descent
    # denominator). A column at/below the zero-variance epsilon is constant or
    # all-zero; its coefficient is pinned to 0 and the column is skipped.
    denom = [0.0] * n_features
    for j in range(n_features):
        acc = 0.0
        for n in range(n_rows):
            xnj = x[n][j]
            acc += weights[n] * xnj * xnj
        denom[j] = acc

    weight_sum = 0.0
    for n in range(n_rows):
        weight_sum += weights[n]

    converged = False
    iterations = 0
    for _ in range(max_iters):
        iterations += 1
        max_delta = 0.0

        # Intercept update (treated as a column of ones). Skipped entirely when
        # fit_intercept is false so additive models that must pass through the
        # origin are not given a free base level.
        if fit_intercept and weight_sum > ZERO_VARIANCE_EPS:
            acc = 0.0
            for n in range(n_rows):
                acc += weights[n] * (residual[n] + intercept)
            new_intercept = acc / weight_sum
            if nonneg_intercept and new_intercept < 0.0:
                new_intercept = 0.0
            delta = new_intercept - intercept
            if delta != 0.0:
                for n in range(n_rows):
                    residual[n] -= delta
                intercept = new_intercept
            if abs(delta) > max_delta:
                max_delta = abs(delta)

        # Feature coordinate updates, in fixed ascending column order.
        for j in range(n_features):
            # Zero-variance feature guard (R4.3 / Property 9 safety): a constant
            # or all-zero column has denom <= eps; pin its weight to 0 and skip
            # so the division below never raises ZeroDivisionError.
            if denom[j] <= ZERO_VARIANCE_EPS:
                if beta[j] != 0.0:
                    # Undo any prior contribution (defensive; beta[j] starts 0).
                    old = beta[j]
                    for n in range(n_rows):
                        residual[n] += old * x[n][j]
                    beta[j] = 0.0
                continue

            # Partial residual numerator: project the current residual onto
            # column j while adding back this column's own contribution.
            acc = 0.0
            for n in range(n_rows):
                xnj = x[n][j]
                acc += weights[n] * xnj * (residual[n] + beta[j] * xnj)
            new_beta = acc / denom[j]

            # Projection onto the non-negative orthant (Property 9).
            if new_beta < 0.0:
                new_beta = 0.0

            delta = new_beta - beta[j]
            if delta != 0.0:
                for n in range(n_rows):
                    residual[n] -= delta * x[n][j]
                beta[j] = new_beta
            if abs(delta) > max_delta:
                max_delta = abs(delta)

        if max_delta <= tol:
            converged = True
            break

    return beta, intercept, iterations, converged


def predict(
    x: Sequence[Sequence[float]],
    coefficients: Sequence[float],
    intercept: float,
) -> list[float]:
    """Linear prediction ``intercept + sum_j beta[j] * x[n][j]`` per row.

    Pure helper mirroring the solver's internal accumulation order so a
    re-prediction is byte-identical to the residuals the fit converged on.
    """
    preds: list[float] = []
    for row in x:
        acc = intercept
        for j, coef in enumerate(coefficients):
            acc += coef * row[j]
        preds.append(acc)
    return preds


def predict_log_wape(
    x: Sequence[Sequence[float]],
    coefficients: Sequence[float],
    intercept: float,
) -> list[float]:
    """Predict in original (hour) space from a :func:`fit_log_wape` model.

    The model is fit in ``log1p`` space, so the hour-space prediction is
    ``expm1(intercept + sum_j beta[j] * x[n][j])``, floored at 0 (a log-space
    prediction below 0 would imply a negative hour count).
    """
    log_preds = predict(x, coefficients, intercept)
    return [max(0.0, math.expm1(p)) for p in log_preds]


def _wape(actuals: Sequence[float], preds: Sequence[float]) -> float:
    """Weighted Absolute Percentage Error: ``sum|a-p| / sum|a|``.

    WAPE is scale-free and robust for heavy-tailed targets (a few blockbusters
    do not dominate as they would under MSE). Returns 0.0 when every actual is 0
    (there is no magnitude to err against), matching the MAPE module's
    no-eligible-magnitude convention.
    """
    num = 0.0
    den = 0.0
    for a, p in zip(actuals, preds):
        num += abs(a - p)
        den += abs(a)
    if den <= ZERO_VARIANCE_EPS:
        return 0.0
    return num / den


def _log_mae(actuals: Sequence[float], preds: Sequence[float]) -> float:
    """Log-Scale MAE: mean ``|log1p(a) - log1p(p)|`` over the rows.

    A companion to WAPE that reports error on the scale the model is fit on, so
    a blockbuster and a library title contribute comparably.
    """
    n = len(actuals)
    if n == 0:
        return 0.0
    total = 0.0
    for a, p in zip(actuals, preds):
        total += abs(math.log1p(max(0.0, a)) - math.log1p(max(0.0, p)))
    return total / n


def _mse(actuals: Sequence[float], preds: Sequence[float]) -> float:
    """Mean squared error over the rows (0.0 for an empty split)."""
    n = len(actuals)
    if n == 0:
        return 0.0
    total = 0.0
    for a, p in zip(actuals, preds):
        d = a - p
        total += d * d
    return total / n


def fit_nnls(
    x: Sequence[Sequence[float]],
    y: Sequence[float],
    *,
    feature_names: Sequence[str] | None = None,
    fit_intercept: bool = True,
    nonneg_intercept: bool = False,
    sample_weights: Sequence[float] | None = None,
    x_test: Sequence[Sequence[float]] | None = None,
    y_test: Sequence[float] | None = None,
    max_iters: int = DEFAULT_MAX_ITERS,
    tol: float = DEFAULT_TOL,
    seed: int = DEFAULT_SEED,
) -> FitResult:
    """Fit a non-negative least-squares model by projected coordinate descent.

    Squared-error objective for the additive drivers (churn, watch-time
    elasticity, ad-load receptivity). Every feature coefficient is constrained
    ``>= 0`` (Property 9); the intercept is unconstrained unless
    ``nonneg_intercept`` is set. The fit is a deterministic function of its
    inputs — ``seed`` is accepted only for API symmetry and never consulted
    (Property 8).

    Args:
        x: Training design matrix, ``n_rows`` lists of ``n_features`` floats.
        y: Training targets, length ``n_rows``.
        feature_names: Optional column labels (defaults to ``x0..x{k-1}``).
        fit_intercept: Fit a base level; set false for origin-constrained models.
        nonneg_intercept: Constrain the intercept ``>= 0`` as well.
        sample_weights: Optional per-row weights (defaults to all 1.0).
        x_test, y_test: Optional held-out split for test metrics (R4.5).
        max_iters: Fixed iteration budget.
        tol: Fixed convergence tolerance.
        seed: Ignored; present for provenance/API symmetry only.

    Returns:
        A :class:`FitResult` with non-negative ``coefficients``, the fitted
        ``intercept``, and ``metrics`` (``train_mse``, ``train_wape``; plus
        ``test_*`` when a held-out split is supplied).
    """
    _ = seed  # deterministic: the seed is intentionally unused.
    n_rows, n_features, names = _validate_design(x, y, feature_names)

    if sample_weights is None:
        weights = [1.0] * n_rows
    else:
        if len(sample_weights) != n_rows:
            raise ValueError(
                f"sample_weights length {len(sample_weights)} != {n_rows} rows"
            )
        weights = [float(w) for w in sample_weights]

    beta, intercept, iterations, converged = _coordinate_descent(
        x,
        [float(v) for v in y],
        weights,
        n_features,
        fit_intercept,
        nonneg_intercept,
        max_iters,
        tol,
    )

    train_preds = predict(x, beta, intercept)
    metrics: dict[str, float] = {
        "train_mse": _mse(y, train_preds),
        "train_wape": _wape(y, train_preds),
    }
    if x_test is not None and y_test is not None:
        _validate_design(x_test, y_test, names)
        test_preds = predict(x_test, beta, intercept)
        metrics["test_mse"] = _mse(y_test, test_preds)
        metrics["test_wape"] = _wape(y_test, test_preds)

    return FitResult(
        coefficients=tuple(beta),
        intercept=intercept,
        feature_names=names,
        metrics=metrics,
        iterations=iterations,
        converged=converged,
        objective="squared_error",
    )


def fit_log_wape(
    x: Sequence[Sequence[float]],
    y: Sequence[float],
    *,
    feature_names: Sequence[str] | None = None,
    fit_intercept: bool = True,
    nonneg_intercept: bool = False,
    x_test: Sequence[Sequence[float]] | None = None,
    y_test: Sequence[float] | None = None,
    max_iters: int = DEFAULT_MAX_ITERS,
    tol: float = DEFAULT_TOL,
    irls_iters: int = 20,
    seed: int = DEFAULT_SEED,
) -> FitResult:
    """Fit viewing hours in log space, optimizing WAPE via IRLS (R4.4).

    The heavy-tailed ``Projected_Viewing_Hours`` target is fit on ``log1p(y)``
    so a tentpole title does not dominate the loss, and the objective reported
    and optimized is WAPE (a percentage-scale error) rather than raw MSE.

    WAPE minimization is approximated by iteratively reweighted least squares:
    each outer iteration solves a weighted NNLS on the log-space target with
    row weights ``1 / max(|actual_hours|, floor)`` (so each row contributes in
    proportion to the percentage error it induces), then re-derives the weights
    from the latest hour-space prediction. The weights come from the actuals, so
    the reweighting is deterministic and convergent. Non-negativity is enforced
    on every coordinate update, exactly as in :func:`fit_nnls` (Property 9), and
    ``seed`` is never consulted (Property 8).

    Returns a :class:`FitResult` whose coefficients predict in ``log1p`` space
    (use :func:`predict_log_wape` to get hours) and whose metrics include
    ``train_wape`` / ``train_log_mae`` (and ``test_*`` when a split is given).
    """
    _ = seed  # deterministic: the seed is intentionally unused.
    n_rows, n_features, names = _validate_design(x, y, feature_names)

    y_hours = [float(v) for v in y]
    y_log = [math.log1p(max(0.0, v)) for v in y_hours]

    # Fixed WAPE weighting: rows are weighted by inverse actual magnitude so the
    # squared log-space objective tracks the percentage objective. Derived from
    # the actuals alone -> deterministic and independent of iteration order.
    weights = [1.0 / max(abs(v), _IRLS_WEIGHT_FLOOR) for v in y_hours]

    beta = [0.0] * n_features
    intercept = 0.0
    iterations = 0
    converged = False

    # IRLS outer loop. With fixed weights the inner NNLS already solves the
    # reweighted problem; the loop re-confirms convergence deterministically and
    # stops as soon as the coefficients stop moving.
    for _outer in range(max(1, irls_iters)):
        new_beta, new_intercept, inner_iters, inner_converged = _coordinate_descent(
            x,
            y_log,
            weights,
            n_features,
            fit_intercept,
            nonneg_intercept,
            max_iters,
            tol,
        )
        iterations += inner_iters
        max_delta = abs(new_intercept - intercept)
        for j in range(n_features):
            d = abs(new_beta[j] - beta[j])
            if d > max_delta:
                max_delta = d
        beta, intercept = new_beta, new_intercept
        if inner_converged and max_delta <= tol:
            converged = True
            break

    train_preds = predict_log_wape(x, beta, intercept)
    metrics: dict[str, float] = {
        "train_wape": _wape(y_hours, train_preds),
        "train_log_mae": _log_mae(y_hours, train_preds),
    }
    if x_test is not None and y_test is not None:
        _validate_design(x_test, y_test, names)
        y_test_hours = [float(v) for v in y_test]
        test_preds = predict_log_wape(x_test, beta, intercept)
        metrics["test_wape"] = _wape(y_test_hours, test_preds)
        metrics["test_log_mae"] = _log_mae(y_test_hours, test_preds)

    return FitResult(
        coefficients=tuple(beta),
        intercept=intercept,
        feature_names=names,
        metrics=metrics,
        iterations=iterations,
        converged=converged,
        objective="wape_log",
    )
