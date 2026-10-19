"""The Source_Connector contract plus snapshot and manifest/license helpers.

Defines the four-step contract every Open_Data_Source adapter fulfills (R9.1):

1. ``fetch()``        -- pull raw records from one source (live; out-of-build only).
2. ``normalize(raw)`` -- map raw records into the shared feature contract, i.e.
   ``Mapping[title_id, partial-feature-dict]`` consumable by
   :func:`app.domain.features.derive_features`.
3. ``snapshot(raw)``  -- write a committed/cached ``Source_Snapshot`` and return
   its path + sha256 checksum, so every build/fit/test/measurement reads fixed
   bytes offline (R9.4).
4. ``provenance()``   -- return ``{name, url, license, access_date}`` for the
   provenance manifest and the license/PII gate (R9.1, R9.5).

It also provides the snapshot primitives (deterministic, canonical-JSON bytes +
sha256) and the manifest/license validator (:func:`validate_connector`) that is
the single gate a source must pass before its data enters the pipeline (R9.5).

This module is pure and standard-library only: no network client is imported
here or anywhere else in the package at module load. A live fetch would isolate
its HTTP import inside the refresh script's fetch path only, never here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "COMPATIBLE_LICENSES",
    "NONCOMMERCIAL_LICENSES",
    "PII_FEATURE_KEYS",
    "Provenance",
    "SnapshotRef",
    "SourceConnector",
    "SourceConnectorError",
    "SnapshotChecksumError",
    "LicenseValidationError",
    "SnapshotBackedConnector",
    "SNAPSHOTS_DIR",
    "canonical_bytes",
    "compute_checksum",
    "write_snapshot",
    "read_snapshot",
    "validate_connector",
    "validate_provenance",
    "validate_records_no_pii",
    "find_pii_keys",
]

# ---------------------------------------------------------------------------
# License policy (the manifest/license gate's single source of truth)
# ---------------------------------------------------------------------------

# Licenses whose terms permit the project's (commercial) use. A source whose
# license is absent or outside this set is rejected unless it is explicitly an
# accepted non-commercial license AND the connector declares non-commercial use.
COMPATIBLE_LICENSES = frozenset(
    {
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "ODC-BY-1.0",
        "TMDB-TERMS",  # TMDB API terms: attribution, non-endorsement.
        "GROUPLENS-RESEARCH",  # MovieLens research/educational use.
    }
)

# Non-commercial licenses the project may use only in a non-commercial context
# (e.g. IMDb's non-commercial datasets). A connector carrying one of these must
# set ``noncommercial=True`` in its provenance, else it is quarantined.
NONCOMMERCIAL_LICENSES = frozenset({"IMDB-NONCOMMERCIAL"})

# Feature keys that would carry personal data about an individual. The shared
# FeatureVector is title-level only (R2.3), so any of these appearing in a
# connector's normalized records is a hard reject: an unvetted source cannot
# silently introduce PII into the pipeline (R9.5).
PII_FEATURE_KEYS = frozenset(
    {
        "user_id",
        "user_name",
        "username",
        "email",
        "email_address",
        "ip_address",
        "ip",
        "phone",
        "phone_number",
        "address",
        "street_address",
        "ssn",
        "national_id",
        "date_of_birth",
        "dob",
        "birthdate",
        "full_name",
        "first_name",
        "last_name",
        "device_id",
        "gps",
        "geolocation",
        "payment_card",
        "credit_card",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SourceConnectorError(Exception):
    """Base error for the source-connector layer."""


class SnapshotChecksumError(SourceConnectorError):
    """Raised when a Source_Snapshot's bytes do not match the expected checksum."""


class LicenseValidationError(SourceConnectorError):
    """Raised when a connector fails the license/PII manifest gate (R9.5)."""


# ---------------------------------------------------------------------------
# Provenance + snapshot reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """A source's manifest metadata: name, url, license, and access date (R9.1).

    ``label_type`` records the dominant Label_Type the source contributes
    (OBSERVED / PROXY / SYNTHETIC) so honesty labeling flows through to the
    dataset and every reported metric (R9.6). ``noncommercial`` marks a source
    used only under a non-commercial license (e.g. IMDb), which the license gate
    requires for a license in :data:`NONCOMMERCIAL_LICENSES`.
    """

    name: str
    url: str
    license: str
    access_date: str
    label_type: str = "PROXY"
    noncommercial: bool = False

    def as_manifest_entry(self) -> dict[str, Any]:
        """Return the JSON-serializable manifest entry for ``PROVENANCE.md``."""
        return {
            "name": self.name,
            "url": self.url,
            "license": self.license,
            "access_date": self.access_date,
            "label_type": self.label_type,
            "noncommercial": self.noncommercial,
        }


@dataclass(frozen=True)
class SnapshotRef:
    """A reference to a written/committed Source_Snapshot: its path + sha256.

    ``read_snapshot(ref)`` reads the bytes back and re-verifies the checksum, so
    every downstream consumer binds to fixed bytes by checksum (R9.4).
    """

    path: Path
    checksum: str

    def as_dict(self) -> dict[str, str]:
        return {"path": str(self.path), "checksum": self.checksum}


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceConnector(Protocol):
    """The four-step Source_Connector contract (R9.1).

    A connector onboards exactly one Open_Data_Source. Implementations are small
    and independently testable, and MUST NOT perform a live network fetch at
    import or during ``normalize`` / ``snapshot`` / ``provenance`` -- only
    ``fetch()`` may touch the network, and it is invoked solely by the
    out-of-build refresh script (R9.4).
    """

    #: The set of FeatureVector keys this connector can supply, in priority order.
    supplies: Sequence[str]

    def fetch(self) -> Any:
        """Pull raw records from the source (LIVE; out-of-build refresh only).

        Build/fit/test/measurement code never calls this; it reads committed
        snapshot bytes by checksum instead. An implementation that needs an HTTP
        client MUST import it inside this method, not at module load.
        """
        ...

    def normalize(self, raw: Any) -> Mapping[str, Mapping[str, Any]]:
        """Map raw records into ``{title_id: partial-feature-dict}`` (R9.1).

        The partial feature dicts use the shared feature keys consumed by
        :func:`app.domain.features.derive_features`; unknown keys are ignored by
        that function, preserving older fitted versions (R9.7).
        """
        ...

    def snapshot(self, raw: Any) -> SnapshotRef:
        """Write a committed/cached Source_Snapshot and return its path+checksum."""
        ...

    def provenance(self) -> Provenance:
        """Return the source's manifest metadata for the license/PII gate."""
        ...

    def load(self) -> Mapping[str, Mapping[str, Any]]:
        """Read the committed snapshot by checksum and return normalized records.

        This is the only entry point build/fit/test/measurement code uses. It
        performs no live fetch.
        """
        ...


# ---------------------------------------------------------------------------
# Snapshot primitives (deterministic, canonical-JSON + sha256)
# ---------------------------------------------------------------------------


def canonical_bytes(raw: Any) -> bytes:
    """Serialize ``raw`` to deterministic, canonical UTF-8 JSON bytes.

    Keys are sorted and separators are fixed so the same logical records always
    produce the same bytes (and therefore the same checksum) across platforms --
    the basis for reproducible, checksum-bound snapshot reads (R2.5, R9.4).
    """
    text = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def compute_checksum(data: bytes) -> str:
    """Return the lowercase hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def write_snapshot(path: Path, raw: Any) -> SnapshotRef:
    """Write ``raw`` to ``path`` as canonical JSON and return its SnapshotRef.

    Used by ``snapshot()`` implementations and the refresh script. Deterministic:
    re-writing identical ``raw`` yields identical bytes and checksum.
    """
    data = canonical_bytes(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return SnapshotRef(path=path, checksum=compute_checksum(data))


def read_snapshot(ref: SnapshotRef) -> Any:
    """Read a Source_Snapshot's bytes, verify the checksum, and parse the JSON.

    Raises :class:`SnapshotChecksumError` if the file is missing or its bytes do
    not match ``ref.checksum`` -- the reproducibility guarantee that feature
    derivation depends only on fixed, checksummed bytes (R9.4). Never performs a
    network fetch.
    """
    if not ref.path.exists():
        raise SnapshotChecksumError(f"snapshot missing: {ref.path}")
    data = ref.path.read_bytes()
    actual = compute_checksum(data)
    if actual != ref.checksum:
        raise SnapshotChecksumError(
            f"snapshot checksum mismatch for {ref.path}: "
            f"expected {ref.checksum}, got {actual}"
        )
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------------------
# Manifest / license / PII gate (R9.5)
# ---------------------------------------------------------------------------


def validate_provenance(prov: Provenance | None) -> None:
    """Validate a source's provenance against the license policy (R9.5).

    Rejects (raises :class:`LicenseValidationError`) when:

    - provenance is absent, or name/url/access_date is blank;
    - the license is absent/blank;
    - the license is neither in :data:`COMPATIBLE_LICENSES` nor an accepted
      non-commercial license declared with ``noncommercial=True``.
    """
    if prov is None:
        raise LicenseValidationError("source has no provenance manifest entry")
    if not (prov.name and prov.name.strip()):
        raise LicenseValidationError("source provenance is missing a name")
    if not (prov.url and prov.url.strip()):
        raise LicenseValidationError(f"source '{prov.name}' provenance is missing a url")
    if not (prov.access_date and prov.access_date.strip()):
        raise LicenseValidationError(
            f"source '{prov.name}' provenance is missing an access_date"
        )
    license_id = (prov.license or "").strip()
    if not license_id:
        raise LicenseValidationError(
            f"source '{prov.name}' has an absent license and is rejected"
        )
    if license_id in COMPATIBLE_LICENSES:
        return
    if license_id in NONCOMMERCIAL_LICENSES:
        if not prov.noncommercial:
            raise LicenseValidationError(
                f"source '{prov.name}' uses non-commercial license '{license_id}' "
                "but did not declare noncommercial=True"
            )
        return
    raise LicenseValidationError(
        f"source '{prov.name}' license '{license_id}' is incompatible with the "
        "project's use and is rejected"
    )


def find_pii_keys(records: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Return any :data:`PII_FEATURE_KEYS` present across the normalized records."""
    found: set[str] = set()
    for partial in records.values():
        if not isinstance(partial, Mapping):
            continue
        for key in partial:
            if str(key).strip().lower() in PII_FEATURE_KEYS:
                found.add(str(key).strip().lower())
    return found


def validate_records_no_pii(records: Mapping[str, Mapping[str, Any]], name: str) -> None:
    """Reject a connector whose normalized records would introduce PII (R9.5)."""
    pii = find_pii_keys(records)
    if pii:
        raise LicenseValidationError(
            f"source '{name}' would introduce personal data "
            f"(keys: {', '.join(sorted(pii))}) and is rejected"
        )


def validate_connector(connector: SourceConnector) -> Provenance:
    """Run the full manifest gate for ``connector`` and return its Provenance.

    This is THE gate a source must pass before its data enters the pipeline
    (R9.5). It validates the license/provenance, then loads the connector's
    normalized records (snapshot-only, no live fetch) and rejects any that would
    introduce personal data. Raises :class:`LicenseValidationError` on failure.
    """
    prov = connector.provenance()
    validate_provenance(prov)
    records = connector.load()
    validate_records_no_pii(records, prov.name)
    return prov


def merge_disallowed_pii(record_sets: Iterable[Mapping[str, Mapping[str, Any]]]) -> None:
    """Assert none of the given normalized record sets carry PII (defensive helper)."""
    for records in record_sets:
        validate_records_no_pii(records, name="<merged>")


# ---------------------------------------------------------------------------
# Shared snapshot-backed connector base
# ---------------------------------------------------------------------------

#: Directory holding the committed/cached Source_Snapshot fixtures.
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "snapshots"


class SnapshotBackedConnector:
    """Base for the shipped connectors: snapshot-only reads, no live fetch.

    A concrete connector sets :attr:`source_name`, :attr:`snapshot_filename`,
    :attr:`expected_checksum` (the sha256 of the snapshot's *canonical* JSON, so
    it is stable across OS line-endings and editor reformatting), :attr:`supplies`,
    and implements :meth:`normalize` and :meth:`provenance`. :meth:`load` reads
    the committed snapshot by checksum and returns normalized records; it never
    touches the network.

    :meth:`fetch` raises by default -- a live fetch belongs only in the
    out-of-build refresh script, which overrides it (or calls a module-level
    ``fetch`` that isolates its HTTP import). This keeps builds/tests offline
    (R9.4).
    """

    source_name: str = ""
    snapshot_filename: str = ""
    expected_checksum: str = ""
    supplies: Sequence[str] = ()

    def __init__(self, snapshots_dir: Path | None = None) -> None:
        self._snapshots_dir = snapshots_dir or SNAPSHOTS_DIR

    @property
    def snapshot_path(self) -> Path:
        return self._snapshots_dir / self.snapshot_filename

    @property
    def snapshot_ref(self) -> SnapshotRef:
        """The committed snapshot reference (path + pinned canonical checksum)."""
        return SnapshotRef(path=self.snapshot_path, checksum=self.expected_checksum)

    def fetch(self) -> Any:  # pragma: no cover - never called in a build/test
        """Not available in a build/test: live fetch runs only in the refresh script."""
        raise SourceConnectorError(
            f"{self.source_name}: live fetch is disabled in build/test; run "
            "scripts/refresh_source_snapshots.py to refresh snapshots"
        )

    def read_raw(self) -> Any:
        """Read + checksum-verify the raw snapshot bytes (no network).

        Verifies the sha256 of the snapshot's canonical JSON against the pinned
        :attr:`expected_checksum`, so feature derivation depends only on fixed,
        checksummed bytes regardless of file formatting (R9.4).
        """
        if not self.snapshot_path.exists():
            raise SnapshotChecksumError(f"snapshot missing: {self.snapshot_path}")
        parsed = json.loads(self.snapshot_path.read_bytes().decode("utf-8"))
        actual = compute_checksum(canonical_bytes(parsed))
        if actual != self.expected_checksum:
            raise SnapshotChecksumError(
                f"snapshot checksum mismatch for {self.snapshot_path}: "
                f"expected {self.expected_checksum}, got {actual}"
            )
        return parsed

    def normalize(self, raw: Any) -> Mapping[str, Mapping[str, Any]]:  # noqa: D401
        raise NotImplementedError

    def provenance(self) -> Provenance:
        raise NotImplementedError

    def snapshot(self, raw: Any) -> SnapshotRef:
        """Write ``raw`` to this connector's snapshot path and return its ref."""
        return write_snapshot(self.snapshot_path, raw)

    def load(self) -> Mapping[str, Mapping[str, Any]]:
        """Read the committed snapshot by checksum and return normalized records."""
        return self.normalize(self.read_raw())
