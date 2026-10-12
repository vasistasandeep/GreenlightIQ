"""Property-based tests for the Model_Versioning engine (R26 ↔ R12).

Targets :class:`app.engines.model_versioning.ModelVersioningEngine`
(``read_active``, ``create_version``, ``stamp``) and its immutable
create-and-flip workflow over ``model_versions``.

Per the design's testing strategy, engine orchestration is exercised against an
**in-memory fake** of :class:`~app.repositories.model_versions.ModelVersionRepository`
so these tests run with no database. The fake mirrors the repository contract the
engine relies on (``get_active``, ``create``, ``update``, ``get``, ``list_all``)
and the server-side behaviour the engine depends on:

* ``create`` assigns a fresh ``model_version_id`` (the real schema's
  ``gen_random_uuid()`` default) and a monotonically increasing ``created_at``
  (the ``now()`` default), since the engine inserts rows without those set.
* The "exactly one active version" invariant (the partial unique index
  ``WHERE is_active``) is enforced on every write, so a buggy engine that left
  two rows active would raise rather than pass silently.
* Stored rows are the engine-constructed ORM instances; immutability is checked
  by snapshotting a prior version's weights and re-reading it via ``get`` after
  later ``create_version`` calls.

Covers design Property 21 (Calibration creates a new immutable model version),
Property 22 (Valuation model-version stamp), and Property 23 (Historical
reproducibility), validating Requirements 12.3, 26.1, 26.2, 26.3, and 26.4.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from itertools import count

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.model_versioning import ModelVersioningEngine, NoActiveModelVersionError
from app.models.model_version import ModelVersion

_WEIGHT_SUM = Decimal("1.00")
_QUANTUM = Decimal("0.01")


class InMemoryModelVersionRepository:
    """In-memory fake of ``ModelVersionRepository`` enforcing one-active (R26.4).

    Stores engine-constructed :class:`ModelVersion` instances in insertion order
    and reproduces the server-side defaults the engine leans on: a generated
    ``model_version_id`` and an increasing ``created_at`` surrogate assigned on
    ``create``. The partial unique index (at most one ``is_active`` row) is
    checked after every mutating call so an engine that produced a transient or
    persistent two-active state would be caught here.
    """

    def __init__(self) -> None:
        self._rows: list[ModelVersion] = []
        self._seq = count(1)

    def _assert_one_active(self) -> None:
        active = [r for r in self._rows if r.is_active]
        assert len(active) <= 1, (
            "model_versions partial unique index violated: "
            f"{len(active)} active rows (R26.4 requires at most one)."
        )

    async def get_active(self) -> ModelVersion | None:
        """Return the single active model version, if any (R26.4)."""
        for row in self._rows:
            if row.is_active:
                return row
        return None

    async def create(self, instance: ModelVersion) -> ModelVersion:
        """Persist a new row, assigning the server-generated id/timestamp."""
        if getattr(instance, "model_version_id", None) is None:
            instance.model_version_id = uuid.uuid4()
        # Monotonic surrogate for the now() default so list_all can order rows.
        instance.created_at = next(self._seq)  # type: ignore[assignment]
        self._rows.append(instance)
        self._assert_one_active()
        return instance

    async def update(self, instance: ModelVersion, **values: object) -> ModelVersion:
        """Apply attribute updates to a managed row (used for the is_active flip)."""
        for key, value in values.items():
            setattr(instance, key, value)
        self._assert_one_active()
        return instance

    async def get(self, entity_id: uuid.UUID) -> ModelVersion | None:
        """Return the row with primary key ``entity_id`` or ``None``."""
        for row in self._rows:
            if row.model_version_id == entity_id:
                return row
        return None

    async def list_all(self) -> list[ModelVersion]:
        """Return all rows, newest first (version catalog, R26.3)."""
        return sorted(self._rows, key=lambda r: r.created_at, reverse=True)


def _coupled_weights() -> st.SearchStrategy[tuple[Decimal, Decimal]]:
    """A talent/narrative pair, each in [0.00, 1.00] summing to exactly 1.00.

    The talent weight is drawn at two-decimal precision (the NUMERIC(4,2) column
    precision) and the narrative weight is its complement, so each generated pair
    already satisfies the coupled sum CHECK the engine persists against (R12.2).
    """
    return st.decimals(
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ).map(lambda t: (t, _WEIGHT_SUM - t))


def _guardrail_params() -> st.SearchStrategy[dict[str, object]]:
    """A small, JSON-serialisable guardrail-parameter payload for a version."""
    return st.fixed_dictionaries(
        {
            "cpvh_ceiling_premium": st.sampled_from([Decimal("0.18"), Decimal("0.20")]).map(str),
            "ltv_floor": st.integers(min_value=1, max_value=5),
        }
    )


# A sequence of calibration applications: each element is the (weights, params)
# for one create_version call. At least one so there is always something active.
_calibration_sequence = st.lists(
    st.tuples(_coupled_weights(), _guardrail_params()),
    min_size=1,
    max_size=6,
)


async def _seed_initial(engine: ModelVersioningEngine) -> ModelVersion:
    """Create the initial active version (mirrors the task-2.3 seed)."""
    return await engine.create_version(
        talent_pedigree_weight=Decimal("0.50"),
        narrative_trope_weight=Decimal("0.50"),
        guardrail_params={"seed": True},
    )


def _weights_of(version: ModelVersion) -> tuple[Decimal, Decimal, dict]:
    """Snapshot the immutable parameter set of a version for later comparison."""
    return (
        version.talent_pedigree_weight,
        version.narrative_trope_weight,
        dict(version.guardrail_params),
    )


# Feature: cineroi-ai, Property 21: Calibration creates a new immutable model version
@given(weights=_coupled_weights(), params=_guardrail_params())
@settings(max_examples=150)
async def test_create_version_forks_new_immutable_row(
    weights: tuple[Decimal, Decimal],
    params: dict[str, object],
) -> None:
    """Validates: Requirements 12.3, 26.1, 26.4

    Applying a calibration inserts a NEW model version (new identifier) that
    becomes the single active row, sets ``supersedes_id`` to the prior active
    id, deactivates the prior row, and leaves the prior row's weights and
    guardrail parameters unchanged (immutability).
    """
    repo = InMemoryModelVersionRepository()
    engine = ModelVersioningEngine(repo)

    prior = await _seed_initial(engine)
    prior_id = prior.model_version_id
    prior_snapshot = _weights_of(prior)

    talent, narrative = weights
    new_version = await engine.create_version(
        talent_pedigree_weight=talent,
        narrative_trope_weight=narrative,
        guardrail_params=params,
    )

    # A brand-new row with a distinct identifier (R26.1).
    assert new_version.model_version_id is not None
    assert new_version.model_version_id != prior_id
    # The new row carries the applied parameter set and is active (R26.4).
    assert new_version.talent_pedigree_weight == talent
    assert new_version.narrative_trope_weight == narrative
    assert new_version.guardrail_params == params
    assert new_version.is_active is True
    # Lineage points back at the superseded version (R26.3 chain).
    assert new_version.supersedes_id == prior_id

    # The prior row is deactivated but otherwise byte-for-byte unchanged (R26.4).
    reread_prior = await repo.get(prior_id)
    assert reread_prior is not None
    assert reread_prior.is_active is False
    assert _weights_of(reread_prior) == prior_snapshot

    # Exactly one active version remains, and it is the new one (R26.4).
    active = await engine.read_active()
    assert active is not None
    assert active.model_version_id == new_version.model_version_id


# Feature: cineroi-ai, Property 21: Calibration creates a new immutable model version
@given(sequence=_calibration_sequence)
@settings(max_examples=150)
async def test_sequential_calibrations_preserve_every_prior_version(
    sequence: list[tuple[tuple[Decimal, Decimal], dict[str, object]]],
) -> None:
    """Validates: Requirements 12.3, 26.1, 26.4

    Across a sequence of calibration applications, each application forks a new
    immutable version and never mutates any earlier version's weights, so every
    prior parameter set survives verbatim and all identifiers are distinct.
    """
    repo = InMemoryModelVersionRepository()
    engine = ModelVersioningEngine(repo)

    await _seed_initial(engine)

    seen_ids: set[uuid.UUID] = set()
    snapshots: dict[uuid.UUID, tuple[Decimal, Decimal, dict]] = {}

    initial = await engine.read_active()
    assert initial is not None
    seen_ids.add(initial.model_version_id)
    snapshots[initial.model_version_id] = _weights_of(initial)

    for (talent, narrative), params in sequence:
        prior_active = await engine.read_active()
        assert prior_active is not None

        new_version = await engine.create_version(
            talent_pedigree_weight=talent,
            narrative_trope_weight=narrative,
            guardrail_params=params,
        )

        # Every forked version has a fresh, never-reused identifier (R26.1).
        assert new_version.model_version_id not in seen_ids
        assert new_version.supersedes_id == prior_active.model_version_id
        seen_ids.add(new_version.model_version_id)
        snapshots[new_version.model_version_id] = _weights_of(new_version)

        # Every previously created version is still retrievable and unchanged
        # (R26.3/R26.4 immutability), with only one active row (R26.4).
        for version_id, snap in snapshots.items():
            stored = await repo.get(version_id)
            assert stored is not None
            assert _weights_of(stored) == snap

    all_versions = await repo.list_all()
    # One seed + one row per calibration, all retained (R26.3).
    assert len(all_versions) == len(sequence) + 1
    assert sum(1 for v in all_versions if v.is_active) == 1


# Feature: cineroi-ai, Property 22: Valuation model-version stamp
@given(sequence=_calibration_sequence)
@settings(max_examples=150)
async def test_stamp_returns_currently_active_version(
    sequence: list[tuple[tuple[Decimal, Decimal], dict[str, object]]],
) -> None:
    """Validates: Requirements 26.2

    ``stamp`` returns the identifier of the model version active at call time;
    after each ``create_version`` the stamp resolves to the newly activated id.
    """
    repo = InMemoryModelVersionRepository()
    engine = ModelVersioningEngine(repo)

    seed = await _seed_initial(engine)
    assert await engine.stamp() == seed.model_version_id

    for (talent, narrative), params in sequence:
        new_version = await engine.create_version(
            talent_pedigree_weight=talent,
            narrative_trope_weight=narrative,
            guardrail_params=params,
        )
        # The stamp follows the active version to the newly created id (R26.2).
        stamp = await engine.stamp()
        assert stamp == new_version.model_version_id

        active = await engine.read_active()
        assert active is not None
        assert stamp == active.model_version_id


# Feature: cineroi-ai, Property 22: Valuation model-version stamp
async def test_stamp_without_active_version_raises() -> None:
    """Validates: Requirements 26.2

    With no active model version a valuation cannot be stamped reproducibly, so
    ``stamp`` raises :class:`NoActiveModelVersionError` rather than returning a
    default.
    """
    repo = InMemoryModelVersionRepository()
    engine = ModelVersioningEngine(repo)

    assert await engine.read_active() is None
    with pytest.raises(NoActiveModelVersionError):
        await engine.stamp()


# Feature: cineroi-ai, Property 23: Historical reproducibility
@given(sequence=_calibration_sequence)
@settings(max_examples=150)
async def test_captured_stamp_resolves_to_immutable_version(
    sequence: list[tuple[tuple[Decimal, Decimal], dict[str, object]]],
) -> None:
    """Validates: Requirements 26.3

    A stamp captured when a valuation was produced still resolves (via ``get``)
    to its original, immutable version with unchanged weights and guardrail
    parameters after any number of subsequent calibration applications.
    """
    repo = InMemoryModelVersionRepository()
    engine = ModelVersioningEngine(repo)

    await _seed_initial(engine)

    # Capture a stamp + the exact parameter set that produced an imagined
    # valuation at the current active version (mirrors R26.2 stamping).
    captured_stamp = await engine.stamp()
    captured_version = await repo.get(captured_stamp)
    assert captured_version is not None
    captured_snapshot = _weights_of(captured_version)

    # Apply every subsequent calibration — none of these may disturb the
    # already-stamped historical version.
    for (talent, narrative), params in sequence:
        await engine.create_version(
            talent_pedigree_weight=talent,
            narrative_trope_weight=narrative,
            guardrail_params=params,
        )

        # Reproducing the historical valuation is a pure read of its stamp: the
        # stamp still resolves and the resolved version is byte-for-byte intact
        # (R26.3), even though it is no longer the active version.
        reproduced = await repo.get(captured_stamp)
        assert reproduced is not None
        assert reproduced.model_version_id == captured_stamp
        assert _weights_of(reproduced) == captured_snapshot

    # After all calibrations the stamped version persists in the catalog but is
    # not active (a newer version superseded it).
    final = await repo.get(captured_stamp)
    assert final is not None
    assert _weights_of(final) == captured_snapshot
    assert final.is_active is False
