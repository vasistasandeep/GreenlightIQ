"""Tests for the pluggable source-connector layer (task 7).

# Feature: content-eval-model

Covers the four behaviors the task calls out, plus the connector reproducibility
and backward-compatibility property:

- **Snapshot-only reads** -- a normal read loads committed, checksummed bytes and
  NO live ``fetch()`` is reachable in a build/test; the shipped connectors raise
  from ``fetch()`` so a live call is confined to the refresh script (R9.4).
- **Overlap precedence** -- when two connectors supply the same feature, the
  registry resolves per its documented precedence and records which source was
  used (R9.3).
- **License/PII rejection** -- a connector with an absent/incompatible license or
  PII-bearing records is rejected by the manifest gate before its data can enter
  the pipeline (R9.5).
- **Backward compatibility (Property 14)** -- adding a mock connector that
  introduces an unknown feature leaves an existing derived ``FeatureVector``
  byte-identical, because :func:`app.domain.features.derive_features` ignores
  unknown keys (R9.7).

Pure/stdlib tests: no database, no app framework, no network.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.data.connectors.base import (
    LicenseValidationError,
    Provenance,
    SnapshotBackedConnector,
    SnapshotChecksumError,
    SourceConnectorError,
    canonical_bytes,
    compute_checksum,
    validate_connector,
    validate_provenance,
)
from app.data.connectors.connector_registry import (
    ENABLED_CONNECTORS,
    build_feature_source_map,
    default_connectors,
    resolve_features,
    resolved_to_raw,
    validate_registry,
)
from app.data.connectors.imdb_nc import IMDbNonCommercialConnector
from app.data.connectors.movielens import MovieLensConnector
from app.data.connectors.tmdb import TMDBConnector
from app.data.connectors.wikidata import WikidataConnector
from app.domain.features import derive_features

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _InMemoryConnector:
    """A minimal in-memory SourceConnector for precedence / PII / compat tests.

    It never touches disk or network: ``load`` returns the configured normalized
    records, and ``fetch`` raises (a live fetch is only ever the refresh script's
    job). This lets a test construct overlapping / malicious / unknown-feature
    sources without committing fixtures for them.
    """

    def __init__(
        self,
        name: str,
        supplies: tuple[str, ...],
        records: Mapping[str, Mapping[str, Any]],
        *,
        license_id: str = "CC0-1.0",
        label_type: str = "PROXY",
        noncommercial: bool = False,
        url: str = "https://example.test/",
        access_date: str = "2024-01-15",
    ) -> None:
        self._name = name
        self.supplies = supplies
        self._records = records
        self._license = license_id
        self._label_type = label_type
        self._noncommercial = noncommercial
        self._url = url
        self._access_date = access_date

    def fetch(self) -> Any:  # pragma: no cover - must never run in a test
        raise SourceConnectorError("live fetch is not available in tests")

    def normalize(self, raw: Any) -> Mapping[str, Mapping[str, Any]]:
        return self._records

    def snapshot(self, raw: Any):  # pragma: no cover - unused here
        raise NotImplementedError

    def provenance(self) -> Provenance:
        return Provenance(
            name=self._name,
            url=self._url,
            license=self._license,
            access_date=self._access_date,
            label_type=self._label_type,
            noncommercial=self._noncommercial,
        )

    def load(self) -> Mapping[str, Mapping[str, Any]]:
        return self._records


ALL_SHIPPED = (
    IMDbNonCommercialConnector,
    TMDBConnector,
    MovieLensConnector,
    WikidataConnector,
)


# ---------------------------------------------------------------------------
# Snapshot-only reads: no live fetch happens in tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ALL_SHIPPED)
def test_shipped_connector_fetch_is_disabled_in_build(factory) -> None:
    """A live ``fetch()`` is not reachable in a build/test (R9.4)."""
    conn = factory()
    with pytest.raises(SourceConnectorError):
        conn.fetch()


@pytest.mark.parametrize("factory", ALL_SHIPPED)
def test_load_reads_committed_snapshot_by_checksum(factory) -> None:
    """A normal read loads committed bytes and verifies the pinned checksum."""
    conn = factory()
    records = conn.load()
    assert isinstance(records, Mapping)
    assert records  # the fixtures are non-empty
    # Every normalized record only carries keys the connector declares.
    for partial in records.values():
        assert set(partial).issubset(set(conn.supplies))


@pytest.mark.parametrize("factory", ALL_SHIPPED)
def test_load_is_deterministic(factory) -> None:
    """Reads depend only on snapshot bytes: repeated loads are identical."""
    conn = factory()
    assert conn.load() == conn.load()


@pytest.mark.parametrize("factory", ALL_SHIPPED)
def test_snapshot_checksum_is_correctly_pinned(factory) -> None:
    """The pinned ``expected_checksum`` matches the canonical bytes on disk."""
    conn = factory()
    raw = conn.read_raw()  # raises if the pinned checksum is wrong
    assert compute_checksum(canonical_bytes(raw)) == conn.expected_checksum


def test_tampered_snapshot_is_rejected_by_checksum(tmp_path) -> None:
    """A snapshot whose bytes drift from the pinned checksum is rejected (R9.4)."""

    class _Pinned(SnapshotBackedConnector):
        source_name = "Pinned"
        snapshot_filename = "pinned.snapshot.json"
        expected_checksum = "0" * 64  # deliberately wrong
        supplies = ("normalized_rating",)

        def normalize(self, raw: Any):
            return {}

        def provenance(self) -> Provenance:
            return Provenance("Pinned", "https://x.test/", "CC0-1.0", "2024-01-15")

    path = tmp_path / "pinned.snapshot.json"
    path.write_bytes(canonical_bytes({"records": []}))
    conn = _Pinned(snapshots_dir=tmp_path)
    with pytest.raises(SnapshotChecksumError):
        conn.read_raw()


def test_missing_snapshot_is_rejected(tmp_path) -> None:
    """A missing snapshot raises rather than silently fetching (R9.4)."""

    class _Missing(SnapshotBackedConnector):
        source_name = "Missing"
        snapshot_filename = "nope.snapshot.json"
        expected_checksum = "0" * 64
        supplies = ()

        def normalize(self, raw: Any):
            return {}

        def provenance(self) -> Provenance:
            return Provenance("Missing", "https://x.test/", "CC0-1.0", "2024-01-15")

    with pytest.raises(SnapshotChecksumError):
        _Missing(snapshots_dir=tmp_path).read_raw()


def test_no_network_client_imported_by_the_package() -> None:
    """Importing the connector package + reading snapshots pulls in no HTTP client (R9.4).

    Run in a clean subprocess so the assertion is not polluted by other modules
    (httpx is a real project dependency used elsewhere). A live fetch isolates
    its HTTP import inside the refresh script's fetch path only, so neither the
    package nor the snapshot-read path may import a network client at module load.
    """
    import subprocess
    import sys

    code = (
        "import sys;"
        "import app.data.connectors as c;"
        "from app.data.connectors.connector_registry import resolve_features;"
        "resolve_features();"
        "banned=[m for m in ('httpx','requests','urllib3','aiohttp','socket') "
        "if m in sys.modules and m!='socket'];"
        "assert not banned, banned;"
        "print('clean')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


# ---------------------------------------------------------------------------
# Overlap precedence: registry resolves and records the chosen source
# ---------------------------------------------------------------------------


def test_registry_documents_overlapping_feature_sources() -> None:
    """The feature->source map lists overlaps in precedence order (R9.3)."""
    feature_map = build_feature_source_map()
    # TMDB and MovieLens both supply the rating correlates; TMDB wins (listed first).
    assert feature_map["normalized_rating"] == ["TMDB", "MovieLens"]
    assert feature_map["log_vote_count"] == ["TMDB", "MovieLens"]
    # IMDb and TMDB both supply runtime; IMDb wins.
    assert feature_map["runtime_minutes"] == ["IMDb-NonCommercial", "TMDB"]
    # IMDb and Wikidata both supply award_signal; IMDb wins.
    assert feature_map["award_signal"] == ["IMDb-NonCommercial", "Wikidata"]


def test_resolution_picks_highest_precedence_source_and_records_it() -> None:
    """Resolved features come from the top-precedence source and record it (R9.3)."""
    resolved = resolve_features()
    tent = resolved["demo-tentpole-01"]
    # rating correlates resolve from TMDB over MovieLens
    assert tent["normalized_rating"].source == "TMDB"
    assert tent["log_vote_count"].source == "TMDB"
    # runtime / award / year resolve from IMDb
    assert tent["runtime_minutes"].source == "IMDb-NonCommercial"
    assert tent["award_signal"].source == "IMDb-NonCommercial"
    assert tent["release_year"].source == "IMDb-NonCommercial"
    # franchise only comes from Wikidata
    assert tent["franchise_flag"].source == "Wikidata"
    # label type is carried through for honesty (R9.6)
    assert tent["normalized_rating"].label_type == "PROXY"


def test_overlap_precedence_is_order_sensitive() -> None:
    """Swapping registry order flips which source wins an overlap (R9.3)."""
    rating_records = {"t1": {"normalized_rating": 0.9}}
    high = _InMemoryConnector("HIGH", ("normalized_rating",), rating_records)
    low = _InMemoryConnector("LOW", ("normalized_rating",), {"t1": {"normalized_rating": 0.1}})

    first_wins = resolve_features([high, low], validate=False)
    assert first_wins["t1"]["normalized_rating"].source == "HIGH"
    assert first_wins["t1"]["normalized_rating"].value == 0.9

    reordered = resolve_features([low, high], validate=False)
    assert reordered["t1"]["normalized_rating"].source == "LOW"
    assert reordered["t1"]["normalized_rating"].value == 0.1


# ---------------------------------------------------------------------------
# License / PII rejection: the manifest gate blocks unvetted sources
# ---------------------------------------------------------------------------


def test_all_shipped_connectors_pass_the_manifest_gate() -> None:
    """Every enabled connector passes the license/PII gate (R9.5)."""
    provs = validate_registry()
    assert [p.name for p in provs] == [
        "IMDb-NonCommercial",
        "TMDB",
        "MovieLens",
        "Wikidata",
    ]


def test_absent_license_is_rejected() -> None:
    """A source with an absent license is rejected (R9.5)."""
    conn = _InMemoryConnector("NoLicense", ("award_signal",), {"t1": {"award_signal": 0.3}}, license_id="")
    with pytest.raises(LicenseValidationError):
        validate_connector(conn)


def test_incompatible_license_is_rejected() -> None:
    """A source with an incompatible license is rejected (R9.5)."""
    conn = _InMemoryConnector("Proprietary", ("award_signal",), {"t1": {"award_signal": 0.3}}, license_id="ALL-RIGHTS-RESERVED")
    with pytest.raises(LicenseValidationError):
        validate_connector(conn)


def test_noncommercial_license_requires_declaration() -> None:
    """A non-commercial license must be declared noncommercial, else quarantined (R9.5)."""
    undeclared = _InMemoryConnector(
        "IMDbish", ("runtime_minutes",), {"t1": {"runtime_minutes": 100}},
        license_id="IMDB-NONCOMMERCIAL", noncommercial=False,
    )
    with pytest.raises(LicenseValidationError):
        validate_provenance(undeclared.provenance())

    declared = _InMemoryConnector(
        "IMDbish", ("runtime_minutes",), {"t1": {"runtime_minutes": 100}},
        license_id="IMDB-NONCOMMERCIAL", noncommercial=True,
    )
    validate_provenance(declared.provenance())  # does not raise


def test_pii_bearing_records_are_rejected() -> None:
    """A connector whose records carry personal data is rejected (R9.5)."""
    conn = _InMemoryConnector(
        "Leaky", ("normalized_rating",),
        {"t1": {"normalized_rating": 0.5, "email": "a@b.test", "user_id": "u-1"}},
    )
    with pytest.raises(LicenseValidationError):
        validate_connector(conn)


def test_missing_provenance_fields_are_rejected() -> None:
    """Blank name/url/access_date fail the gate (R9.1, R9.5)."""
    with pytest.raises(LicenseValidationError):
        validate_provenance(None)
    with pytest.raises(LicenseValidationError):
        validate_provenance(Provenance("", "https://x.test/", "CC0-1.0", "2024-01-15"))
    with pytest.raises(LicenseValidationError):
        validate_provenance(Provenance("X", "", "CC0-1.0", "2024-01-15"))
    with pytest.raises(LicenseValidationError):
        validate_provenance(Provenance("X", "https://x.test/", "CC0-1.0", ""))


# ---------------------------------------------------------------------------
# Backward compatibility (Property 14): adding a connector with an unknown
# feature leaves an existing derived FeatureVector byte-identical.
# ---------------------------------------------------------------------------


def test_adding_unknown_feature_connector_leaves_featurevector_identical() -> None:
    """# Property 14: a new connector's unknown feature does not disturb an older
    fitted version's resolved FeatureVector (R9.7).

    An existing fitted Content_Eval_Version resolves using only the features it
    was fitted on; ``derive_features`` ignores unknown keys, so introducing a new
    source that supplies a brand-new feature leaves the derived vector identical.
    """
    base_connectors = default_connectors()
    before_resolved = resolve_features(base_connectors)
    before_raw = resolved_to_raw(before_resolved)
    before_vectors = {tid: derive_features(raw) for tid, raw in before_raw.items()}

    # A mock new source introducing a feature key no model knows about.
    new_source = _InMemoryConnector(
        "ExperimentalSignals",
        ("sentiment_velocity_v2",),
        {tid: {"sentiment_velocity_v2": 0.42} for tid in before_raw},
    )
    after_connectors = [*base_connectors, new_source]
    after_resolved = resolve_features(after_connectors)
    after_raw = resolved_to_raw(after_resolved)
    after_vectors = {tid: derive_features(raw) for tid, raw in after_raw.items()}

    # The new raw key is present...
    assert all("sentiment_velocity_v2" in after_raw[tid] for tid in after_raw)
    # ...but every derived FeatureVector is byte-identical to before.
    assert after_vectors == before_vectors


def test_enabled_connectors_are_in_documented_precedence_order() -> None:
    """The registry's declared order matches the documented precedence policy."""
    assert ENABLED_CONNECTORS == (
        IMDbNonCommercialConnector,
        TMDBConnector,
        MovieLensConnector,
        WikidataConnector,
    )
