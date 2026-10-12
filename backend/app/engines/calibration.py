"""Calibration_Controller: auto-calibration of feature-extraction weights (R12 ↔ R26).

When a backtest audit reports a high predictive error, this controller nudges the
two coupled feature-extraction weights — ``talent_pedigree_weight`` and
``narrative_trope_weight`` — and installs the adjusted pair as a *new* immutable
model version. It never mutates weights in place (R26.1, R26.4); every applied
calibration forks a fresh ``model_versions`` row via the
:class:`~app.engines.model_versioning.ModelVersioningEngine`.

Behavior (design "Calibration_Controller")
------------------------------------------
``evaluate_and_apply(audit, actor)`` branches on the audit's MAPE:

* **MAPE > 10%** — compute weight-adjustment offsets, each bounded to
  ``[-1.00, 1.00]`` (R12.1); apply and re-normalize the coupled weights so both
  stay within ``[0.00, 1.00]`` and sum to exactly ``1.00`` (R12.2); then create
  and activate a new model version carrying the adjusted weights (R12.3, R26.4).
  Returns ``adjustment_required=True`` with the new ``model_version_id`` and the
  offsets that were applied.
* **MAPE <= 10%** — report that no adjustment is required and leave the active
  weights untouched; no new version is created (R12.5). Returns
  ``adjustment_required=False``.
* **Offset out of range** — if the offsets would move either weight outside
  ``[0.00, 1.00]``, reject the calibration *before* any version is created,
  preserving the prior weights, and raise
  :class:`~app.core.errors.CalibrationOutOfRangeError` (422, R12.4).

A ``None`` MAPE (no eligible metrics in the audit, R11.8) is treated like
"nothing to calibrate": no adjustment is required.

Offset-derivation strategy
---------------------------
The offset model is deliberately simple, deterministic, and documented so it can
be reasoned about and later tuned. The controller computes a single *severity*
scalar from how far MAPE overshoots the 10% threshold:

    severity = min((mape - THRESHOLD) / 100, MAX_SEVERITY)

i.e. the percentage-point overshoot expressed as a fraction (a 25% MAPE is a
15-point overshoot → ``0.15``), clamped to :data:`MAX_SEVERITY` so a single
noisy audit can never swing a weight by more than that in one step. High audit
error is interpreted as the current emphasis being miscalibrated, so the
controller shifts weight *away from* the dominant feature and *toward* the other
by ``severity``: the larger active weight receives ``-severity`` and the smaller
receives ``+severity`` (ties nudge talent down, narrative up). The resulting
offsets are inherently within ``[-1.00, 1.00]`` because ``MAX_SEVERITY <= 1``.

The two offsets, the active weights, and the normalization are then handed to the
pure :mod:`app.domain.weights` functions, which enforce the ``[-1,1]`` offset
bound, the ``[0,1]`` weight bound, and the sum-to-``1.00`` invariant, raising if
any is violated — those raises are what this controller maps to the R12.4
rejection.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, TypedDict
from uuid import UUID

from app.core.errors import CalibrationOutOfRangeError
from app.core.security import UserContext
from app.domain.weights import CalibrationError, apply_offsets
from app.engines.model_versioning import ModelVersioningEngine

__all__ = [
    "MAPE_THRESHOLD",
    "MAX_SEVERITY",
    "AuditScorecardLike",
    "CalibrationResult",
    "Calibration_Controller",
]


# A MAPE strictly greater than this (expressed as a percentage) triggers
# calibration; at or below it, no adjustment is required (R12.1, R12.5).
MAPE_THRESHOLD: Decimal = Decimal("10")

# The maximum magnitude a single calibration step may shift either coupled
# weight. Kept at or below 1.00 so derived offsets always satisfy the
# [-1.00, 1.00] bound (R12.1) and one noisy audit cannot flip the weighting.
MAX_SEVERITY: Decimal = Decimal("0.10")


class AuditScorecardLike(Protocol):
    """Structural type for the audit input: anything exposing a ``mape``.

    The Backtesting_Module produces the concrete ``AuditScorecard``; this
    controller depends only on its ``mape`` attribute — the Mean Absolute
    Percentage Error as a percentage, or ``None`` when no metrics were eligible
    for computation (R11.8). Depending structurally keeps calibration decoupled
    from the backtesting module's full scorecard shape.
    """

    @property
    def mape(self) -> Decimal | None: ...


class CalibrationResult(TypedDict):
    """The outcome of :meth:`Calibration_Controller.evaluate_and_apply`.

    ``adjustment_required`` is ``True`` only when the audit exceeded the MAPE
    threshold and a new model version was created. In that case
    ``new_model_version_id`` is the id of the newly activated version and
    ``offsets`` is the applied ``{parameter: offset}`` map (each in
    ``[-1.00, 1.00]``, R12.1). When no adjustment is required both are ``None``.
    """

    adjustment_required: bool
    new_model_version_id: UUID | None
    offsets: dict[str, Decimal] | None


class Calibration_Controller:
    """Evaluate an audit and, if needed, fork an adjusted model version (R12).

    The controller owns no persistence of its own: it reads the active version
    and writes the forked version exclusively through the injected
    :class:`~app.engines.model_versioning.ModelVersioningEngine`, so the swap is
    immutable and transactional (R26). Weight arithmetic is delegated to the pure
    :mod:`app.domain.weights` functions.
    """

    def __init__(self, model_versioning: ModelVersioningEngine) -> None:
        """Bind the controller to a model-versioning engine.

        Args:
            model_versioning: The engine used to read the active model version
                and to create-and-activate the forked version on calibration.
        """
        self._model_versioning = model_versioning

    async def evaluate_and_apply(
        self, audit: AuditScorecardLike, actor: UserContext
    ) -> CalibrationResult:
        """Evaluate an audit's MAPE and apply calibration when it is too high (R12).

        Args:
            audit: The backtest audit scorecard; only its ``mape`` is consulted.
            actor: The identity requesting the calibration (reserved for audit
                attribution by the caller; the fork itself is actor-agnostic).

        Returns:
            A :class:`CalibrationResult`. ``adjustment_required`` is ``True`` with
            a populated ``new_model_version_id`` and ``offsets`` when a new
            version was created (MAPE > 10%, R12.3); ``False`` with both ``None``
            when no adjustment is required (MAPE <= 10% or no eligible metrics,
            R12.5).

        Raises:
            CalibrationOutOfRangeError: If the computed offsets would move a
                weight outside ``[0.00, 1.00]``; the prior weights are retained
                and no version is created (R12.4).
        """
        mape = audit.mape

        # No eligible metrics (R11.8) or error within tolerance (R12.5): no-op.
        if mape is None or mape <= MAPE_THRESHOLD:
            return CalibrationResult(
                adjustment_required=False,
                new_model_version_id=None,
                offsets=None,
            )

        active = await self._model_versioning.read_active()
        if active is None:
            # No weights exist to adjust; there is nothing to calibrate against.
            # Treated as a no-op rather than a spurious first version.
            return CalibrationResult(
                adjustment_required=False,
                new_model_version_id=None,
                offsets=None,
            )

        offsets = self._derive_offsets(
            mape=mape,
            talent_pedigree_weight=active.talent_pedigree_weight,
            narrative_trope_weight=active.narrative_trope_weight,
        )

        # Apply + normalize via the pure domain layer. Any bound violation raises
        # a CalibrationError; map it to the out-of-range rejection WITHOUT having
        # created a version, so the prior weights remain in effect (R12.4).
        try:
            adjusted = apply_offsets(
                active.talent_pedigree_weight,
                active.narrative_trope_weight,
                offsets["talent_pedigree_weight"],
                offsets["narrative_trope_weight"],
            )
        except CalibrationError as exc:
            raise CalibrationOutOfRangeError(
                str(exc),
                details={
                    "offsets": {k: str(v) for k, v in offsets.items()},
                    "prior_weights": {
                        "talent_pedigree_weight": str(active.talent_pedigree_weight),
                        "narrative_trope_weight": str(active.narrative_trope_weight),
                    },
                },
            ) from exc

        # Carry the prior guardrail parameters forward unchanged: calibration
        # adjusts only the coupled feature weights (R12.3). The engine performs
        # the immutable create-and-activate fork (R26.1, R26.4).
        new_version = await self._model_versioning.create_version(
            talent_pedigree_weight=adjusted.talent_pedigree,
            narrative_trope_weight=adjusted.narrative_trope,
            guardrail_params=dict(active.guardrail_params),
        )

        return CalibrationResult(
            adjustment_required=True,
            new_model_version_id=new_version.model_version_id,
            offsets=offsets,
        )

    def _derive_offsets(
        self,
        *,
        mape: Decimal,
        talent_pedigree_weight: Decimal,
        narrative_trope_weight: Decimal,
    ) -> dict[str, Decimal]:
        """Derive bounded weight-adjustment offsets from the audit severity (R12.1).

        See the module docstring for the full rationale. In short: ``severity`` is
        the MAPE overshoot above the 10% threshold expressed as a fraction and
        clamped to :data:`MAX_SEVERITY`; weight is shifted off the currently
        dominant coupled weight onto the other by ``severity``. Both resulting
        offsets lie in ``[-1.00, 1.00]`` because ``0 < severity <= MAX_SEVERITY <= 1``.

        Args:
            mape: The audit MAPE as a percentage; the caller guarantees it is
                greater than :data:`MAPE_THRESHOLD`.
            talent_pedigree_weight: The active talent-pedigree weight.
            narrative_trope_weight: The active narrative-trope weight.

        Returns:
            An ``{parameter: offset}`` mapping for the two coupled weights.
        """
        overshoot = (mape - MAPE_THRESHOLD) / Decimal("100")
        severity = min(overshoot, MAX_SEVERITY)

        # Shift weight away from the dominant feature toward the other. Ties nudge
        # talent down / narrative up so the derivation is fully deterministic.
        if talent_pedigree_weight >= narrative_trope_weight:
            talent_offset = -severity
            narrative_offset = severity
        else:
            talent_offset = severity
            narrative_offset = -severity

        return {
            "talent_pedigree_weight": talent_offset,
            "narrative_trope_weight": narrative_offset,
        }
