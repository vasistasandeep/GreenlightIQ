"""Model-version management service (R26 ↔ R12).

Model versions are **immutable** rows in ``model_versions``. Calibration never
mutates feature-extraction weights or guardrail parameters in place; instead it
*forks* a new version: it reads the active row, inserts a brand-new row with
``supersedes_id`` pointing at the prior active id, and flips ``is_active`` so the
new row becomes the single active version (R26.1, R26.4). A partial unique index
(``WHERE is_active``) guarantees exactly one active version at a time.

This engine wraps :class:`~app.repositories.model_versions.ModelVersionRepository`
and exposes the three operations the rest of the system needs:

* :meth:`ModelVersioningEngine.read_active` — fetch the current active version
  (what calibration reads before computing offsets, and what the
  Guardrails_Engine resolves a stamp from).
* :meth:`ModelVersioningEngine.create_version` — the immutable create-and-flip
  workflow that calibration uses (R26.1, R26.4).
* :meth:`ModelVersioningEngine.stamp` — resolve the active ``model_version_id``
  the Guardrails_Engine stamps onto a valuation as it is produced (R26.2).

Reproducibility (R26.3)
-----------------------
R26.3 — "retain all historical Model_Version definitions so a prior valuation
can be reproduced from its stamped Model_Version" — is satisfied structurally,
not by any method here:

* ``model_versions`` rows are never updated or deleted; ``create_version`` only
  *inserts* and toggles ``is_active``. Every past weight set and guardrail
  parameter set therefore remains on disk, reachable via the repository's
  ``list_all`` / ``get`` / ``get_superseded_by`` chain helpers.
* A valuation's stamp (``financial_projections.model_version_id``, R26.2) is
  written once when the valuation is produced and is **never** rewritten by this
  engine. Creating a new active version does not touch any existing valuation
  row, so a historical valuation keeps pointing at the exact (immutable) version
  that produced it and can be recomputed from it. Reproducing a prior valuation
  is thus a pure *read* of its stamped version — handled by callers that load
  ``get(valuation.model_version_id)`` — which is why this engine deliberately
  offers no "re-stamp" or "update stamp" operation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.models.model_version import ModelVersion
from app.repositories.model_versions import ModelVersionRepository


class NoActiveModelVersionError(RuntimeError):
    """Raised when an active model version is required but none exists.

    The system seeds an initial active model version (task 2.3); encountering no
    active row at runtime means the environment is uninitialized. The
    Guardrails_Engine cannot stamp a valuation (R26.2) without one, so this is a
    hard error rather than a silently-created default.
    """


class ModelVersioningEngine:
    """Service for reading and immutably forking ``model_versions`` (R26).

    The engine is constructed with a
    :class:`~app.repositories.model_versions.ModelVersionRepository` bound to the
    surrounding unit-of-work's :class:`~sqlalchemy.ext.asyncio.AsyncSession`. Like
    the repositories it builds on, every method ``flush``es rather than
    ``commit``s, so the caller (request/task) owns the transaction boundary and
    the create-and-flip executes atomically within it.
    """

    def __init__(self, repository: ModelVersionRepository) -> None:
        self._repo = repository

    async def read_active(self) -> ModelVersion | None:
        """Return the single active model version, or ``None`` if none exists.

        This is the read calibration performs before computing weight offsets and
        the lookup :meth:`stamp` resolves against (R26.4).
        """
        return await self._repo.get_active()

    async def stamp(self) -> uuid.UUID:
        """Return the active ``model_version_id`` to stamp onto a valuation (R26.2).

        The Guardrails_Engine calls this as it produces a valuation and writes the
        returned id to ``financial_projections.model_version_id`` so the valuation
        is permanently tied to the exact parameter set that produced it. Because
        the stamp is captured at valuation time and never rewritten, later
        calibrations leave the historical stamp intact (R26.3).

        Raises:
            NoActiveModelVersionError: If no active model version exists — a
                valuation must not be produced without a reproducible stamp.
        """
        active = await self._repo.get_active()
        if active is None:
            raise NoActiveModelVersionError(
                "cannot stamp a valuation: no active model version exists (R26.2)."
            )
        return active.model_version_id

    async def create_version(
        self,
        *,
        talent_pedigree_weight: Decimal,
        narrative_trope_weight: Decimal,
        guardrail_params: dict[str, Any],
    ) -> ModelVersion:
        """Insert a new immutable active version, superseding the prior one (R26.1, R26.4).

        Implements the calibration fork: the prior active version (if any) is
        deactivated and the new row is inserted with ``supersedes_id`` pointing at
        it and ``is_active = True``. The prior row's weights and parameters are
        **never** mutated — only its ``is_active`` flag is cleared — so the old
        version remains an exact, reproducible snapshot (R26.3, R26.4).

        The deactivate-then-insert ordering matters: the ``WHERE is_active``
        partial unique index permits only one active row, so the prior active row
        is cleared and flushed *before* the new active row is inserted, preventing
        a transient two-active state. Both writes share the caller's transaction,
        so the swap is atomic — a failure rolls back to the prior active version.

        Args:
            talent_pedigree_weight: Talent-pedigree weight for the new version;
                must be in ``[0.00, 1.00]`` and sum with ``narrative_trope_weight``
                to exactly ``1.00`` (DB CHECK, R12.2). Normalization is the
                caller's responsibility (see :mod:`app.domain.weights`).
            narrative_trope_weight: Narrative-trope weight for the new version.
            guardrail_params: The guardrail parameter set captured by this version.

        Returns:
            The newly created, flushed, active :class:`ModelVersion` (its
            server-generated ``model_version_id`` and ``created_at`` are populated).
        """
        prior = await self._repo.get_active()
        supersedes_id = prior.model_version_id if prior is not None else None

        # Clear the prior active flag FIRST so the partial unique index never sees
        # two active rows. This mutates only is_active, not the immutable weights.
        if prior is not None:
            await self._repo.update(prior, is_active=False)

        new_version = ModelVersion(
            talent_pedigree_weight=talent_pedigree_weight,
            narrative_trope_weight=narrative_trope_weight,
            guardrail_params=guardrail_params,
            supersedes_id=supersedes_id,
            is_active=True,
        )
        return await self._repo.create(new_version)
