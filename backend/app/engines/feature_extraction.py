"""Feature_Extraction_Engine: source documents -> metadata profile (R2).

This engine turns a title's raw source material (logline, pitch-deck text,
manifest content) into the four persisted extraction artifacts:

* a 1536-dimension Narrative_DNA embedding, every component in ``[-1.0, 1.0]``
  (R2.1);
* an Affective_Tone_Score naming exactly one *primary* and one *secondary*
  emotional trigger, each drawn from a fixed predefined set (R2.3);
* a ``talent_pedigree_score`` in ``[0.0, 10.0]`` rounded to 2 dp (R2.4);
* a ``production_scale_metric`` in ``[0.0, 10.0]`` rounded to 2 dp (R2.5).

The talent-pedigree and narrative-trope *weights* used to compute the two scalar
scores come from the active :class:`~app.models.model_version.ModelVersion` so a
later calibration (R12/R26) changes future extractions without touching this
code.

Embedding generation is abstracted behind the :class:`EmbeddingProvider`
interface so the 1536-dim model can be swapped (a real NLP model in production, a
deterministic in-process provider for local/offline use and tests). The engine
depends only on the interface; the concrete provider is injected.

Transaction model (R2.6-R2.8)
-----------------------------
``extract`` persists all four artifacts in a *single* unit of work. Like the
repositories it builds on, it ``flush``es rather than ``commit``s so the caller's
session owns the final commit; the four writes land in one ``MetadataVector`` row
inserted atomically. The engine translates the three failure modes R2 calls for
into typed exceptions and, in every failure case, records an extraction-failure
status row before surfacing the error:

* **No non-empty source** (R2.2) -> :class:`NoSourceContentError`, a FAILED
  status row is written, no embedding is produced.
* **Parse failure** (R2.8) -> :class:`DocumentParseError`, a FAILED status row is
  written and any previously persisted vector for the title is left untouched.
* **Persist failure** (R2.6/R2.7) -> :class:`ExtractionPersistenceError`; the
  partial write is rolled back (via a session SAVEPOINT) and a FAILED status row
  is written in its place so no half-written profile survives.

No method here opens a database connection on import; the session is injected.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol, TypedDict, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.model_versioning import (
    ModelVersioningEngine,
    NoActiveModelVersionError,
)
from app.models.metadata_vector import NARRATIVE_DNA_DIMENSIONS, MetadataVector
from app.repositories.metadata_vectors import MetadataVectorRepository

# --------------------------------------------------------------------------- #
# Predefined emotional-trigger categories (R2.3).
# --------------------------------------------------------------------------- #
#: The fixed set every Affective_Tone_Score primary/secondary trigger is drawn
#: from. Ordered so a deterministic provider can map a hash onto a stable index.
EMOTIONAL_TRIGGERS: tuple[str, ...] = (
    "SUSPENSE",
    "JOY",
    "FEAR",
    "NOSTALGIA",
    "AWE",
    "GRIEF",
    "ROMANCE",
    "HUMOR",
    "TENSION",
    "HOPE",
)

#: Score bounds shared by talent_pedigree_score and production_scale_metric (R2.4, R2.5).
_SCORE_MIN = Decimal("0.00")
_SCORE_MAX = Decimal("10.00")
_SCORE_QUANTUM = Decimal("0.01")  # 2 decimal places.

_EXTRACTION_STATUS_SUCCESS = "SUCCESS"
_EXTRACTION_STATUS_FAILED = "FAILED"


# --------------------------------------------------------------------------- #
# Public data shapes.
# --------------------------------------------------------------------------- #
class AffectiveToneScore(TypedDict):
    """Exactly one primary and one secondary emotional trigger (R2.3).

    Both values are members of :data:`EMOTIONAL_TRIGGERS`; the primary and
    secondary are always distinct.
    """

    primary: str
    secondary: str


class ExtractionOutput(TypedDict):
    """The four extraction artifacts produced for a title (R2.1, R2.3-R2.5)."""

    narrative_dna: list[float]  # len == 1536, each in [-1.0, 1.0] (R2.1)
    affective_tone: AffectiveToneScore  # 1 primary + 1 secondary trigger (R2.3)
    talent_pedigree_score: float  # [0.0, 10.0], 2 dp (R2.4)
    production_scale_metric: float  # [0.0, 10.0], 2 dp (R2.5)


@dataclass(frozen=True)
class SourceBundle:
    """The raw source material available for a title.

    Any of the fields may be ``None`` or blank; the engine treats the bundle as
    having content only when at least one field holds non-whitespace text
    (R2.1/R2.2). ``combined_text`` concatenates the present fields for the
    downstream embedding and scoring steps.
    """

    logline: str | None = None
    pitch_deck: str | None = None
    manifest_content: str | None = None

    def combined_text(self) -> str:
        """Return the concatenation of all present source fields, stripped."""
        parts = [
            part.strip()
            for part in (self.logline, self.pitch_deck, self.manifest_content)
            if part is not None and part.strip()
        ]
        return "\n".join(parts)

    def has_content(self) -> bool:
        """Return ``True`` iff at least one source field has non-whitespace text."""
        return bool(self.combined_text())


# --------------------------------------------------------------------------- #
# Typed failure modes (R2.2, R2.7, R2.8).
# --------------------------------------------------------------------------- #
class ExtractionError(RuntimeError):
    """Base class for Feature_Extraction_Engine failures.

    Carries the ``title_id`` whose extraction failed so callers (the Celery
    worker, the error envelope) can report the affected title.
    """

    def __init__(self, title_id: uuid.UUID, message: str) -> None:
        self.title_id = title_id
        super().__init__(message)


class NoSourceContentError(ExtractionError):
    """No non-empty source document was available for the title (R2.2)."""


class DocumentParseError(ExtractionError):
    """Parsing the source document failed (R2.8).

    When raised, any previously persisted data for the title is left unchanged.
    """


class ExtractionPersistenceError(ExtractionError):
    """Persisting the four artifacts failed and partial writes were rolled back (R2.7)."""


# --------------------------------------------------------------------------- #
# Embedding provider abstraction (swappable 1536-dim model).
# --------------------------------------------------------------------------- #
@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for a swappable Narrative_DNA embedding model.

    An implementation turns source text into a 1536-dimension vector whose
    components all lie in ``[-1.0, 1.0]`` (R2.1). Production wires a real NLP
    model; local/offline use and tests can inject
    :class:`DeterministicEmbeddingProvider`.
    """

    @property
    def dimensions(self) -> int:
        """The embedding dimensionality; MUST equal 1536 for this system (R2.1)."""
        ...

    def embed(self, text: str) -> list[float]:
        """Return a ``dimensions``-length vector, each component in ``[-1.0, 1.0]``.

        Raises:
            DocumentParseError: If ``text`` cannot be turned into an embedding.
                (The engine maps this to R2.8.)
        """
        ...


class BaseEmbeddingProvider(ABC):
    """Convenience ABC for embedding providers fixed to the system dimensionality.

    Subclasses implement :meth:`embed`; :attr:`dimensions` defaults to
    :data:`~app.models.metadata_vector.NARRATIVE_DNA_DIMENSIONS` (1536).
    """

    @property
    def dimensions(self) -> int:
        return NARRATIVE_DNA_DIMENSIONS

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return a 1536-length vector with every component in ``[-1.0, 1.0]``."""
        raise NotImplementedError


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    """A reproducible embedding provider that needs no external service.

    Expands a SHA-256 digest of the source text into a 1536-dimension vector by
    hashing ``text`` together with each dimension index and mapping the digest
    bytes into ``[-1.0, 1.0]``. The result is deterministic (same text -> same
    vector), fully in range (R2.1), and dependency-free, which makes it the
    default for local/offline use and tests. It is **not** a semantic embedding
    and is not intended for production relevance.
    """

    def embed(self, text: str) -> list[float]:
        if text is None:  # pragma: no cover - defensive; callers pass strings.
            raise TypeError("embedding text must be a string")
        base = text.encode("utf-8")
        vector: list[float] = []
        # Each SHA-256 digest yields 32 bytes; draw one byte per dimension by
        # salting the digest with a block counter so the stream is 1536 long.
        dims = self.dimensions
        block = 0
        while len(vector) < dims:
            digest = hashlib.sha256(base + block.to_bytes(4, "big")).digest()
            for byte in digest:
                if len(vector) >= dims:
                    break
                # Map a byte 0..255 to the closed interval [-1.0, 1.0].
                vector.append((byte / 127.5) - 1.0)
            block += 1
        return vector


# --------------------------------------------------------------------------- #
# The engine.
# --------------------------------------------------------------------------- #
class FeatureExtractionEngine:
    """Parse source documents into the persisted metadata profile (R2).

    Dependencies are injected: the :class:`EmbeddingProvider` (so the embedding
    model is swappable), the :class:`MetadataVectorRepository` (persistence), the
    :class:`ModelVersioningEngine` (active-version weights, R12/R26), and the
    owning :class:`~sqlalchemy.ext.asyncio.AsyncSession` (used to scope the
    atomic write and roll back a partial one). The engine ``flush``es; the caller
    owns the ``commit``.
    """

    def __init__(
        self,
        session: AsyncSession,
        repository: MetadataVectorRepository,
        embedding_provider: EmbeddingProvider,
        model_versioning: ModelVersioningEngine,
    ) -> None:
        self.session = session
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.model_versioning = model_versioning

    async def extract(
        self,
        title_id: uuid.UUID,
        sources: SourceBundle,
        model_version_id: uuid.UUID,
    ) -> ExtractionOutput:
        """Produce and persist the four extraction artifacts for a title (R2.1-R2.8).

        Args:
            title_id: The title whose profile is being extracted.
            sources: The raw source material (logline / pitch deck / manifest).
            model_version_id: The model version stamped onto the persisted row so
                the profile is tied to the weight set that produced it (R26.2).

        Returns:
            The computed :class:`ExtractionOutput` (also persisted).

        Raises:
            NoSourceContentError: No non-empty source document (R2.2).
            DocumentParseError: Source parsing/embedding failed; prior data for
                the title is left unchanged (R2.8).
            ExtractionPersistenceError: Persisting the artifacts failed; the
                partial write was rolled back (R2.7).
        """
        # R2.2 - no non-empty source: record a failure status, produce no vector.
        if not sources.has_content():
            await self._record_failure(title_id, model_version_id)
            raise NoSourceContentError(
                title_id,
                "no source content available for extraction (R2.2).",
            )

        text = sources.combined_text()

        # R2.8 - parse/embedding failure: record failure and leave prior data
        # untouched. We do NOT touch any existing persisted vector here; the
        # failure-status row is written in its own nested transaction below.
        try:
            narrative_dna = self._build_narrative_dna(text)
            affective_tone = self._build_affective_tone(text)
        except DocumentParseError:
            await self._record_failure(title_id, model_version_id)
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to the R2.8 type.
            await self._record_failure(title_id, model_version_id)
            raise DocumentParseError(
                title_id, f"failed to parse source document: {exc}"
            ) from exc

        # Scalar scores use the active model-version weights (R2.4, R2.5, R12/R26).
        talent_weight, trope_weight = await self._resolve_weights()
        talent_pedigree_score = self._score_talent_pedigree(text, talent_weight)
        production_scale_metric = self._score_production_scale(text, trope_weight)

        output: ExtractionOutput = {
            "narrative_dna": narrative_dna,
            "affective_tone": affective_tone,
            "talent_pedigree_score": float(talent_pedigree_score),
            "production_scale_metric": float(production_scale_metric),
        }

        # R2.6 / R2.7 - persist all four artifacts atomically; roll back on failure.
        await self._persist_atomically(
            title_id=title_id,
            model_version_id=model_version_id,
            output=output,
            talent_pedigree_score=talent_pedigree_score,
            production_scale_metric=production_scale_metric,
        )
        return output

    # ----------------------------------------------------------------- #
    # Artifact construction.
    # ----------------------------------------------------------------- #
    def _build_narrative_dna(self, text: str) -> list[float]:
        """Embed ``text`` and validate the R2.1 shape/range contract.

        Raises:
            DocumentParseError: If the provider returns a vector of the wrong
                length or with any component outside ``[-1.0, 1.0]`` — treated as
                a parse failure for the title (R2.8).
        """
        vector = self.embedding_provider.embed(text)
        if len(vector) != NARRATIVE_DNA_DIMENSIONS:
            raise ValueError(
                f"embedding provider returned {len(vector)} dimensions; "
                f"expected {NARRATIVE_DNA_DIMENSIONS} (R2.1)."
            )
        for component in vector:
            if not (-1.0 <= component <= 1.0):
                raise ValueError(
                    "embedding component out of range [-1.0, 1.0] (R2.1)."
                )
        return [float(component) for component in vector]

    def _build_affective_tone(self, text: str) -> AffectiveToneScore:
        """Select exactly one primary + one distinct secondary trigger (R2.3).

        Deterministically maps the text onto two distinct members of
        :data:`EMOTIONAL_TRIGGERS` using a stable hash so the same text always
        yields the same pair.
        """
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        count = len(EMOTIONAL_TRIGGERS)
        primary_index = digest[0] % count
        # Offset by a second digest byte (1..count-1) so secondary != primary.
        secondary_index = (primary_index + 1 + (digest[1] % (count - 1))) % count
        return AffectiveToneScore(
            primary=EMOTIONAL_TRIGGERS[primary_index],
            secondary=EMOTIONAL_TRIGGERS[secondary_index],
        )

    async def _resolve_weights(self) -> tuple[Decimal, Decimal]:
        """Return (talent_pedigree_weight, narrative_trope_weight) from active version.

        Raises:
            NoActiveModelVersionError: If no active model version exists — scoring
                has no defined weights without one.
        """
        active = await self.model_versioning.read_active()
        if active is None:
            raise NoActiveModelVersionError(
                "cannot extract: no active model version provides weights (R2.4/R2.5)."
            )
        return active.talent_pedigree_weight, active.narrative_trope_weight

    def _score_talent_pedigree(self, text: str, weight: Decimal) -> Decimal:
        """Compute talent_pedigree_score in [0.0, 10.0], 2 dp, weighted (R2.4)."""
        signal = self._text_signal(text, salt="talent")
        return self._scaled_score(signal, weight)

    def _score_production_scale(self, text: str, weight: Decimal) -> Decimal:
        """Compute production_scale_metric in [0.0, 10.0], 2 dp, weighted (R2.5)."""
        signal = self._text_signal(text, salt="production")
        return self._scaled_score(signal, weight)

    @staticmethod
    def _text_signal(text: str, *, salt: str) -> Decimal:
        """Derive a stable signal in [0.0, 1.0] from the text for a given facet."""
        digest = hashlib.sha256(f"{salt}:{text}".encode("utf-8")).digest()
        # Use the first two bytes as a 16-bit fraction of the unit interval.
        raw = (digest[0] << 8) | digest[1]
        return Decimal(raw) / Decimal(0xFFFF)

    @staticmethod
    def _scaled_score(signal: Decimal, weight: Decimal) -> Decimal:
        """Scale a [0,1] signal by a [0,1] weight onto [0.0, 10.0], 2 dp, clamped.

        Clamping guarantees the R2.4/R2.5 bounds hold even if a future weight set
        were out of its own range.
        """
        score = signal * weight * _SCORE_MAX
        score = score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
        if score < _SCORE_MIN:
            return _SCORE_MIN
        if score > _SCORE_MAX:
            return _SCORE_MAX
        return score

    # ----------------------------------------------------------------- #
    # Persistence (R2.6, R2.7) and failure recording (R2.2, R2.7, R2.8).
    # ----------------------------------------------------------------- #
    async def _persist_atomically(
        self,
        *,
        title_id: uuid.UUID,
        model_version_id: uuid.UUID,
        output: ExtractionOutput,
        talent_pedigree_score: Decimal,
        production_scale_metric: Decimal,
    ) -> None:
        """Insert the single ``MetadataVector`` row holding all four artifacts (R2.6).

        The four artifacts live on one row, so a single insert is inherently
        atomic. The write runs inside a nested transaction (SAVEPOINT) so that if
        the flush fails the partial write is rolled back without discarding the
        caller's wider unit of work; a FAILED status row is then recorded in its
        place and :class:`ExtractionPersistenceError` is raised (R2.7).
        """
        record = MetadataVector(
            title_id=title_id,
            narrative_dna=output["narrative_dna"],
            affective_primary=output["affective_tone"]["primary"],
            affective_secondary=output["affective_tone"]["secondary"],
            talent_pedigree_score=talent_pedigree_score,
            production_scale_metric=production_scale_metric,
            model_version_id=model_version_id,
            extraction_status=_EXTRACTION_STATUS_SUCCESS,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except Exception as exc:  # noqa: BLE001 - normalize to the R2.7 type.
            # The SAVEPOINT rollback has already undone the partial write; record
            # the failure in a fresh nested transaction so the status row survives.
            await self._record_failure(title_id, model_version_id)
            raise ExtractionPersistenceError(
                title_id, f"failed to persist extraction artifacts: {exc}"
            ) from exc

    async def _record_failure(
        self, title_id: uuid.UUID, model_version_id: uuid.UUID
    ) -> None:
        """Write a FAILED extraction-status row for a title (R2.2, R2.7, R2.8).

        The row carries a zero vector purely to satisfy the non-null embedding
        column; its ``extraction_status = 'FAILED'`` marks it as a failure marker
        rather than a usable profile. Written in its own nested transaction so a
        failure here cannot poison the caller's unit of work.
        """
        marker = MetadataVector(
            title_id=title_id,
            narrative_dna=[0.0] * NARRATIVE_DNA_DIMENSIONS,
            affective_primary="",
            affective_secondary="",
            talent_pedigree_score=None,
            production_scale_metric=None,
            model_version_id=model_version_id,
            extraction_status=_EXTRACTION_STATUS_FAILED,
        )
        async with self.session.begin_nested():
            self.session.add(marker)
            await self.session.flush()
