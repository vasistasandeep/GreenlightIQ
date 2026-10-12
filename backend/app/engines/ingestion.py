"""Ingestion_Service: batch content manifests -> versioned title records (R1, R21, R22, R24, R27).

The Ingestion_Service is the front door of the valuation pipeline. It accepts a
batch manifest in one of three formats (CSV / JSON / PDF), validates the request
envelope and each record, persists one versioned title per *valid* record, and
dispatches feature extraction for each accepted record. It returns a summary that
always conserves the batch: ``accepted_count + rejected_count == total`` (R1.9,
R1.10).

Two layers of validation
-------------------------
There are two distinct failure granularities, mirrored in the design:

* **Whole-request guards** fail the *entire* request before any record is
  created. Only two conditions qualify (per the Error Handling table):

  * an unsupported ``content_type`` -> :class:`UnsupportedFormatError` (415, R1.4);
  * a CSV manifest with more than :data:`MAX_CSV_ROWS` data rows ->
    :class:`RowLimitExceededError` (422, R1.5).

  A malformed payload that cannot be parsed at all (e.g. invalid JSON, an
  unreadable PDF) is also a whole-request failure, surfaced as
  :class:`UnsupportedFormatError` identifying the format that failed to parse.

* **Per-row validation** rejects only the offending record and *continues* with
  the rest (R1.7, R1.8). Each rejection is captured as a
  :class:`RejectionDetail` ``{row_index, field, reason}`` and reported in the
  summary; the record is never written. The validated-but-rejected rows plus the
  accepted rows always sum to the total submitted (R1.10).

Versioning (R24)
----------------
Every accepted record is stored as an immutable *version* of a title rather than
overwriting prior data (R24.1). A new submission for an *existing* title (matched
by ``title_id`` supplied on the record) appends a child
:class:`~app.models.title_version.TitleVersion` with an incrementing
``version_number`` (R24.2) and becomes the single active version for that title
(R24.4); prior versions and their metadata vectors are left untouched (R24.3). A
submission without a ``title_id`` creates a brand-new title and its first
version (number 1).

Idempotency (R27.1)
-------------------
The ``idempotency_key`` is recorded on the ``jobs`` row created for the batch. On
replay — a request carrying a key that already has a stored job — the service
returns the *stored* :class:`IngestionResult` unchanged and creates no duplicate
records (R27.1). The check is performed up front via
:meth:`~app.repositories.jobs.JobRepository.get_by_idempotency_key`.

Native currency and License_Terms (R21.1, R22.1)
------------------------------------------------
Each record captures its cost in its native currency (R21.1); the currency is
persisted on the title and never silently converted at ingest time (normalization
to USD is the Guardrails_Engine's job, R21.2). When a record carries licensing
terms, a :class:`~app.models.license_term.LicenseTerm` row is captured alongside
the title (R22.1).

Dependency injection and testability
------------------------------------
Every collaborator is injected: the owning
:class:`~sqlalchemy.ext.asyncio.AsyncSession`, the title / title-version / job /
license-term / metadata-vector repositories, the
:class:`~app.engines.model_versioning.ModelVersioningEngine` (to resolve the
``model_version_id`` an extraction is stamped with), and an *optional* extraction
trigger. The trigger is a plain async callable invoked once per accepted record
(R1.6); leaving it ``None`` makes the service exercisable without a live
extraction pipeline or database. Like the repositories it builds on, the service
``flush``es rather than ``commit``s — the caller (API route / Celery task) owns
the transaction boundary.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RowLimitExceededError, UnsupportedFormatError
from app.models.license_term import LicenseTerm
from app.models.title import ASSET_TYPES, Title
from app.models.title_version import TitleVersion
from app.repositories.jobs import JobRepository
from app.repositories.license_terms import LicenseTermRepository
from app.repositories.metadata_vectors import MetadataVectorRepository
from app.repositories.titles import TitleRepository, TitleVersionRepository

# --------------------------------------------------------------------------- #
# Validation constants.
# --------------------------------------------------------------------------- #
#: Maximum number of CSV *data* rows a single batch may carry (R1.5). A manifest
#: with strictly more than this is rejected whole; exactly this many is accepted.
MAX_CSV_ROWS = 10_000

#: Allowed ingest content types (R1.4). Anything else fails the whole request.
SUPPORTED_CONTENT_TYPES = ("csv", "json", "pdf")
ContentType = Literal["csv", "json", "pdf"]

#: The permitted ``asset_type`` enum values (R1.8). Reuses the ORM's canonical set.
ASSET_TYPE_SET = frozenset(ASSET_TYPES)

#: Acquisition-cost bounds, inclusive, in native currency units (R1.8).
MIN_ACQUISITION_COST = Decimal("0.01")
MAX_ACQUISITION_COST = Decimal("999999999.99")

#: Default native currency when a record omits one (R21.1). INR/USD/EUR/GBP are
#: the minimum supported set; USD is the base currency.
DEFAULT_NATIVE_CURRENCY = "USD"

_JOB_TYPE_INGEST = "INGEST"
_JOB_STATUS_COMPLETED = "COMPLETED"


# --------------------------------------------------------------------------- #
# Public data shapes.
# --------------------------------------------------------------------------- #
class RejectionDetail(TypedDict):
    """A single rejected record in a batch summary (R1.7, R1.8).

    Attributes:
        row_index: Zero-based index of the record within the submitted batch, so
            a caller can point back at the exact offending row.
        field: The field whose value triggered the rejection (e.g.
            ``"title_name"``, ``"acquisition_cost_or_budget"``, ``"asset_type"``).
        reason: A human-readable description of why the record was rejected.
    """

    row_index: int
    field: str
    reason: str


class IngestionResult(TypedDict):
    """The summary returned for a completed batch ingestion (R1.9, R1.10).

    ``accepted_count + rejected_count`` always equals the total number of records
    submitted in the batch (R1.10). ``rejections`` lists one
    :class:`RejectionDetail` per rejected record.
    """

    job_id: str
    accepted_count: int
    rejected_count: int
    rejections: list[RejectionDetail]


# --------------------------------------------------------------------------- #
# Extraction trigger abstraction (R1.6).
# --------------------------------------------------------------------------- #
#: An extraction trigger is any async callable invoked once per accepted record
#: with the newly created ``title_id``, its ``title_version_id``, and the active
#: ``model_version_id`` to stamp the extraction with (R1.6, R26.2). The service
#: stays decoupled from the Celery dispatch / Feature_Extraction_Engine wiring so
#: it is exercisable without a live pipeline; ``None`` disables the trigger.
ExtractionTrigger = Callable[[uuid.UUID, uuid.UUID, Optional[uuid.UUID]], Awaitable[None]]


class UserContext(Protocol):
    """The minimal actor contract the service needs (R25.1 attribution).

    Only ``user_id`` is consumed here (stamped onto the created ``titles`` and
    ``jobs`` rows); a fuller context is defined by the auth layer. Accepting a
    structural type keeps this engine independent of that later task.
    """

    @property
    def user_id(self) -> uuid.UUID | None: ...


# --------------------------------------------------------------------------- #
# Internal parsed-record shape.
# --------------------------------------------------------------------------- #
@dataclass
class _ParsedRecord:
    """A raw record parsed from the payload, prior to validation.

    Holds the as-submitted values keyed by field name plus the zero-based batch
    index. Validation reads from :attr:`raw`; accessors coerce individual fields.
    """

    row_index: int
    raw: dict[str, Any] = field(default_factory=dict)

    def get_str(self, key: str) -> str | None:
        """Return a stripped string for ``key`` or ``None`` when absent/blank."""
        value = self.raw.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None


# --------------------------------------------------------------------------- #
# The service.
# --------------------------------------------------------------------------- #
class IngestionService:
    """Validate, version, and persist batch manifests into titles (R1, R24, R27).

    Collaborators are injected; see the module docstring. The service never opens
    a connection on import and ``flush``es rather than ``commit``s so the caller
    owns the transaction boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        title_repository: TitleRepository,
        title_version_repository: TitleVersionRepository,
        job_repository: JobRepository,
        license_term_repository: LicenseTermRepository,
        metadata_vector_repository: MetadataVectorRepository,
        *,
        model_version_id: uuid.UUID | None = None,
        extraction_trigger: ExtractionTrigger | None = None,
    ) -> None:
        self.session = session
        self.titles = title_repository
        self.title_versions = title_version_repository
        self.jobs = job_repository
        self.license_terms = license_term_repository
        self.metadata_vectors = metadata_vector_repository
        #: The model version an accepted record's extraction is stamped with
        #: (R26.2). Supplied by the caller (resolved from the active version);
        #: forwarded to the extraction trigger and may be ``None`` in tests.
        self.model_version_id = model_version_id
        self.extraction_trigger = extraction_trigger

    async def ingest(
        self,
        payload: bytes,
        content_type: str,
        idempotency_key: str,
        actor: UserContext | None = None,
    ) -> IngestionResult:
        """Ingest a batch manifest, returning an accepted/rejected summary (R1).

        Args:
            payload: The raw request body (CSV / JSON / PDF bytes).
            content_type: One of ``"csv"``, ``"json"``, ``"pdf"`` (R1.4).
            idempotency_key: A caller-supplied key; a replayed key returns the
                stored result unchanged and creates no duplicates (R27.1).
            actor: The requesting user, attributed on created rows (R25.1).

        Returns:
            An :class:`IngestionResult` whose accepted and rejected counts sum to
            the total submitted (R1.10).

        Raises:
            UnsupportedFormatError: ``content_type`` is not CSV/JSON/PDF, or the
                payload could not be parsed in its declared format (R1.4).
            RowLimitExceededError: A CSV manifest exceeds :data:`MAX_CSV_ROWS`
                data rows (R1.5).
        """
        # --- Idempotent replay (R27.1): return the stored result unchanged. ---
        if idempotency_key:
            existing = await self.jobs.get_by_idempotency_key(idempotency_key)
            if existing is not None and existing.result is not None:
                return self._result_from_job(existing)

        normalized_type = self._normalize_content_type(content_type)

        # --- Parse the payload into raw records (whole-request guards, R1.4/R1.5). ---
        records = self._parse(payload, normalized_type)
        total = len(records)

        actor_id = actor.user_id if actor is not None else None

        # --- Per-row validation + persistence (R1.1-R1.3, R1.7, R1.8). ---
        rejections: list[RejectionDetail] = []
        accepted: list[tuple[uuid.UUID, uuid.UUID]] = []  # (title_id, title_version_id)

        for record in records:
            rejection = self._validate(record)
            if rejection is not None:
                rejections.append(rejection)
                continue
            title_id, version_id = await self._persist_record(record, actor_id)
            accepted.append((title_id, version_id))

        # --- Trigger feature extraction per accepted record (R1.6). ---
        for title_id, version_id in accepted:
            await self._trigger_extraction(title_id, version_id)

        accepted_count = len(accepted)
        rejected_count = len(rejections)
        # Conservation invariant (R1.10): every submitted record is either
        # accepted or rejected, never both and never dropped.
        assert accepted_count + rejected_count == total  # noqa: S101

        job = await self._record_job(
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            rejections=rejections,
        )

        return {
            "job_id": str(job.job_id),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "rejections": rejections,
        }

    # ------------------------------------------------------------------ #
    # Whole-request guards and parsing (R1.4, R1.5).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_content_type(content_type: str) -> ContentType:
        """Lower-case and validate ``content_type`` against the allow-list (R1.4).

        Raises:
            UnsupportedFormatError: The format is not CSV/JSON/PDF.
        """
        normalized = (content_type or "").strip().lower()
        if normalized not in SUPPORTED_CONTENT_TYPES:
            raise UnsupportedFormatError(
                f"Unsupported ingest format {content_type!r}; "
                f"expected one of {', '.join(SUPPORTED_CONTENT_TYPES)}.",
                details={"content_type": content_type},
            )
        return normalized  # type: ignore[return-value]

    def _parse(self, payload: bytes, content_type: ContentType) -> list[_ParsedRecord]:
        """Dispatch to the format-specific parser.

        A payload that cannot be parsed in its declared format is a whole-request
        failure surfaced as :class:`UnsupportedFormatError` (R1.4). CSV row-limit
        overflow raises :class:`RowLimitExceededError` (R1.5).
        """
        if content_type == "csv":
            return self._parse_csv(payload)
        if content_type == "json":
            return self._parse_json(payload)
        return self._parse_pdf(payload)

    def _parse_csv(self, payload: bytes) -> list[_ParsedRecord]:
        """Parse a CSV manifest into one record per data row (R1.1).

        Enforces the :data:`MAX_CSV_ROWS` ceiling on *data* rows (header
        excluded) as a whole-request guard (R1.5).
        """
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsupportedFormatError(
                "CSV payload is not valid UTF-8 text.",
                details={"content_type": "csv"},
            ) from exc

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            # Empty payload -> an empty batch (zero records), not an error.
            return []

        records: list[_ParsedRecord] = []
        for index, row in enumerate(reader):
            if index >= MAX_CSV_ROWS:
                # Strictly more than the ceiling: reject the whole request (R1.5).
                raise RowLimitExceededError(
                    f"CSV manifest exceeds the {MAX_CSV_ROWS}-row limit.",
                    details={"max_rows": MAX_CSV_ROWS},
                )
            cleaned = {
                (key.strip() if key is not None else key): value
                for key, value in row.items()
            }
            records.append(_ParsedRecord(row_index=index, raw=cleaned))
        return records

    def _parse_json(self, payload: bytes) -> list[_ParsedRecord]:
        """Parse a JSON pitch deck into one record per title object (R1.2).

        Accepts either a top-level array of title objects or a single object with
        a ``titles`` array. A single bare object is treated as one record.
        """
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UnsupportedFormatError(
                "JSON payload could not be parsed.",
                details={"content_type": "json"},
            ) from exc

        if isinstance(data, dict) and isinstance(data.get("titles"), list):
            items = data["titles"]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            raise UnsupportedFormatError(
                "JSON payload must be a title object or an array of title objects.",
                details={"content_type": "json"},
            )

        records: list[_ParsedRecord] = []
        for index, item in enumerate(items):
            raw = item if isinstance(item, dict) else {}
            records.append(_ParsedRecord(row_index=index, raw=raw))
        return records

    def _parse_pdf(self, payload: bytes) -> list[_ParsedRecord]:
        """Extract text from a PDF script summary into a single record (R1.3).

        A PDF carries one title; the extracted text becomes manifest content so
        the downstream Feature_Extraction_Engine has source material. Record
        fields (title_name, cost, etc.) are expected on the embedded document
        metadata or supplied out of band; here we surface the extracted text and
        any document info so per-row validation can run.
        """
        try:
            from pypdf import PdfReader  # Imported lazily to keep import-time light.

            reader = PdfReader(io.BytesIO(payload))
            text_parts = [page.extract_text() or "" for page in reader.pages]
            extracted_text = "\n".join(part for part in text_parts if part).strip()
            doc_info = {
                str(key).lstrip("/"): str(value)
                for key, value in (reader.metadata or {}).items()
            }
        except Exception as exc:  # noqa: BLE001 - normalize any parse fault (R1.4).
            raise UnsupportedFormatError(
                "PDF payload could not be parsed.",
                details={"content_type": "pdf"},
            ) from exc

        raw: dict[str, Any] = dict(doc_info)
        raw["source_text"] = extracted_text
        # Fall back to the PDF title metadata as the title_name if present.
        if "title_name" not in raw and "Title" in raw:
            raw["title_name"] = raw["Title"]
        return [_ParsedRecord(row_index=0, raw=raw)]

    # ------------------------------------------------------------------ #
    # Per-row validation (R1.7, R1.8).
    # ------------------------------------------------------------------ #
    def _validate(self, record: _ParsedRecord) -> RejectionDetail | None:
        """Validate one record; return a :class:`RejectionDetail` or ``None``.

        Rejection reasons, in order (first failure wins):

        * missing ``title_name`` (R1.7);
        * missing ``acquisition_cost_or_budget`` (R1.7);
        * non-numeric or out-of-range ``acquisition_cost_or_budget`` (R1.8);
        * ``asset_type`` outside the enum set when supplied (R1.8).

        ``None`` means the record is valid and may be persisted.
        """
        if record.get_str("title_name") is None:
            return RejectionDetail(
                row_index=record.row_index,
                field="title_name",
                reason="title_name is required.",
            )

        cost_raw = record.get_str("acquisition_cost_or_budget")
        if cost_raw is None:
            return RejectionDetail(
                row_index=record.row_index,
                field="acquisition_cost_or_budget",
                reason="acquisition_cost_or_budget is required.",
            )

        try:
            cost = Decimal(cost_raw)
        except (InvalidOperation, ValueError):
            return RejectionDetail(
                row_index=record.row_index,
                field="acquisition_cost_or_budget",
                reason=f"acquisition_cost_or_budget {cost_raw!r} is not a valid number.",
            )
        if not cost.is_finite() or not (
            MIN_ACQUISITION_COST <= cost <= MAX_ACQUISITION_COST
        ):
            return RejectionDetail(
                row_index=record.row_index,
                field="acquisition_cost_or_budget",
                reason=(
                    f"acquisition_cost_or_budget {cost_raw} is outside the "
                    f"allowed range {MIN_ACQUISITION_COST}-{MAX_ACQUISITION_COST}."
                ),
            )

        asset_type = record.get_str("asset_type")
        if asset_type is not None and asset_type not in ASSET_TYPE_SET:
            return RejectionDetail(
                row_index=record.row_index,
                field="asset_type",
                reason=(
                    f"asset_type {asset_type!r} is not one of "
                    f"{', '.join(sorted(ASSET_TYPE_SET))}."
                ),
            )

        return None

    # ------------------------------------------------------------------ #
    # Persistence: versioned title children (R24) + native currency / license.
    # ------------------------------------------------------------------ #
    async def _persist_record(
        self, record: _ParsedRecord, actor_id: uuid.UUID | None
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Persist one validated record as a versioned title child (R24).

        A record carrying an existing ``title_id`` appends a new version to that
        title (R24.1, R24.2); otherwise a new title and its first version are
        created. The new version becomes the single active one (R24.4) and the
        title's ``active_version_id`` is pointed at it. Native currency (R21.1)
        and any License_Terms (R22.1) are captured on the title.

        Returns:
            ``(title_id, title_version_id)`` for the accepted record.
        """
        existing_title_id = self._parse_uuid(record.get_str("title_id"))

        if existing_title_id is not None:
            title = await self.titles.get(existing_title_id)
        else:
            title = None

        if title is None:
            title = await self._create_title(record, actor_id)
        # else: a new submission for an existing title -> version-only append.

        version = await self._append_version(title, record)
        return title.title_id, version.title_version_id

    async def _create_title(
        self, record: _ParsedRecord, actor_id: uuid.UUID | None
    ) -> Title:
        """Insert a new ``titles`` row from a validated record (R17.1, R21.1).

        Captures the cost in its native currency without converting it (R21.1);
        normalization to USD is deferred to the Guardrails_Engine (R21.2). Also
        captures License_Terms when the record carries them (R22.1).
        """
        cost = Decimal(record.get_str("acquisition_cost_or_budget"))  # validated.
        native_currency = (
            record.get_str("native_currency") or DEFAULT_NATIVE_CURRENCY
        ).upper()
        asset_type = record.get_str("asset_type") or "LICENSED_LIBRARY"

        title = Title(
            title_name=record.get_str("title_name"),
            asset_type=asset_type,
            acquisition_cost_or_budget=cost,
            native_currency=native_currency,
            target_territories=self._parse_territories(record),
            genre_tag=record.get_str("genre_tag"),
            projected_viewing_hours=self._parse_decimal(
                record.get_str("projected_viewing_hours")
            ),
            created_by=actor_id,
        )
        await self.titles.create(title)

        await self._capture_license_terms(title.title_id, record)
        return title

    async def _append_version(
        self, title: Title, record: _ParsedRecord
    ) -> TitleVersion:
        """Append an incrementing, active version to a title (R24.1-R24.4).

        Computes the next ``version_number`` from the current maximum (R24.2),
        deactivates the prior active version so the partial unique index never
        sees two active rows, inserts the new active version with an immutable
        source snapshot (R24.1, R24.3), and repoints the title's
        ``active_version_id`` at it (R24.4). Prior versions' metadata vectors are
        never touched (R24.3).
        """
        next_number = (
            await self.title_versions.latest_version_number(title.title_id) + 1
        )

        # Deactivate the current active version first (R24.4 single-active guard).
        current_active = await self.title_versions.get_active(title.title_id)
        if current_active is not None:
            await self.title_versions.update(current_active, is_active=False)

        version = TitleVersion(
            title_id=title.title_id,
            version_number=next_number,
            source_snapshot=self._snapshot(record),
            is_active=True,
        )
        await self.title_versions.create(version)

        # Point the title at its new active version (R24.4).
        title.active_version_id = version.title_version_id
        await self.session.flush()
        return version

    async def _capture_license_terms(
        self, title_id: uuid.UUID, record: _ParsedRecord
    ) -> None:
        """Capture License_Terms for a title when the record carries them (R22.1).

        Reads a ``license_terms`` object from the record (duration, exclusivity,
        windowing rules, holdbacks, milestone schedule). When absent, no license
        row is created — licensing is optional at ingest.
        """
        terms = record.raw.get("license_terms")
        if not isinstance(terms, dict):
            return

        duration = self._parse_int(terms.get("license_duration_months"))
        if duration is None or duration <= 0:
            # Without a positive duration the row would violate the DB CHECK;
            # skip rather than fail the accepted record. Full R22.4 windowing
            # validation lives with the licensing task.
            return

        license_row = LicenseTerm(
            title_id=title_id,
            license_duration_months=duration,
            is_exclusive=bool(terms.get("is_exclusive", False)),
            windowing_rules=terms.get("windowing_rules") or [],
            holdbacks=terms.get("holdbacks"),
            milestone_schedule=terms.get("milestone_schedule") or [],
        )
        await self.license_terms.create(license_row)

    # ------------------------------------------------------------------ #
    # Extraction trigger (R1.6).
    # ------------------------------------------------------------------ #
    async def _trigger_extraction(
        self, title_id: uuid.UUID, title_version_id: uuid.UUID
    ) -> None:
        """Invoke the injected extraction trigger for an accepted record (R1.6).

        No-op when no trigger is injected, keeping the service exercisable without
        a live extraction pipeline. The active ``model_version_id`` (if resolved)
        is forwarded so the extraction is stamped with the version in effect
        (R26.2).
        """
        if self.extraction_trigger is None:
            return
        await self.extraction_trigger(title_id, title_version_id, self.model_version_id)

    # ------------------------------------------------------------------ #
    # Job / idempotency bookkeeping (R27.1).
    # ------------------------------------------------------------------ #
    async def _record_job(
        self,
        *,
        idempotency_key: str,
        actor_id: uuid.UUID | None,
        accepted_count: int,
        rejected_count: int,
        rejections: list[RejectionDetail],
    ) -> Any:
        """Persist the ``jobs`` row carrying the batch result and idempotency key.

        The stored ``result`` is the exact :class:`IngestionResult` payload (minus
        ``job_id``, which is the job's own id) so a later replay with the same key
        reconstructs the identical summary (R27.1).
        """
        from app.models.job import Job

        job = Job(
            job_type=_JOB_TYPE_INGEST,
            status=_JOB_STATUS_COMPLETED,
            idempotency_key=idempotency_key or None,
            result={
                "accepted_count": accepted_count,
                "rejected_count": rejected_count,
                "rejections": rejections,
            },
            requested_by=actor_id,
        )
        return await self.jobs.create(job)

    @staticmethod
    def _result_from_job(job: Any) -> IngestionResult:
        """Reconstruct the stored :class:`IngestionResult` from a job row (R27.1)."""
        stored = job.result or {}
        return {
            "job_id": str(job.job_id),
            "accepted_count": int(stored.get("accepted_count", 0)),
            "rejected_count": int(stored.get("rejected_count", 0)),
            "rejections": list(stored.get("rejections", [])),
        }

    # ------------------------------------------------------------------ #
    # Field coercion helpers.
    # ------------------------------------------------------------------ #
    def _snapshot(self, record: _ParsedRecord) -> dict[str, Any]:
        """Return a JSON-serializable immutable snapshot of a record (R24.1).

        Decimal/UUID values are stringified so the snapshot round-trips through
        JSONB unchanged.
        """
        snapshot: dict[str, Any] = {}
        for key, value in record.raw.items():
            if isinstance(value, (Decimal, uuid.UUID)):
                snapshot[key] = str(value)
            else:
                snapshot[key] = value
        return snapshot

    def _parse_territories(self, record: _ParsedRecord) -> list[str]:
        """Parse ``target_territories`` into a list of country codes (R17.3).

        Accepts an already-parsed list (JSON) or a delimited string (CSV). An
        absent value yields an empty list.
        """
        value = record.raw.get("target_territories")
        if isinstance(value, list):
            return [str(code).strip().upper() for code in value if str(code).strip()]
        text = record.get_str("target_territories")
        if text is None:
            return []
        # Support JSON-encoded arrays embedded in a CSV cell, else split on
        # common delimiters.
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(code).strip().upper() for code in parsed if str(code).strip()]
        except json.JSONDecodeError:
            pass
        separators = [";", ",", "|"]
        for sep in separators:
            if sep in text:
                return [code.strip().upper() for code in text.split(sep) if code.strip()]
        return [text.upper()]

    @staticmethod
    def _parse_uuid(value: str | None) -> uuid.UUID | None:
        """Parse a UUID string, returning ``None`` when absent or malformed."""
        if value is None:
            return None
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_decimal(value: str | None) -> Decimal | None:
        """Parse a Decimal string, returning ``None`` when absent or malformed."""
        if value is None:
            return None
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        """Parse an int from a raw value, returning ``None`` on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
