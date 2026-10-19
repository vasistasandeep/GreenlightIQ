"""Pluggable source-connector layer for the Content_Eval_System (R9).

A new Open_Data_Source is onboarded by implementing one documented contract --
the :class:`~app.data.connectors.base.SourceConnector` protocol -- and adding a
single entry to the :mod:`~app.data.connectors.connector_registry`. No change to
a Content_Eval_Model, the KPI_Test_Dataset schema, or the Backtest_Harness is
required (R9.2).

The four shipped connectors (:mod:`tmdb`, :mod:`movielens`, :mod:`imdb_nc`,
:mod:`wikidata`) are the first implementations of the contract. During a normal
read they load committed/cached ``Source_Snapshot`` fixtures by checksum and
NEVER perform a live network fetch (R9.4); the only place ``fetch()`` runs live
is the out-of-build ``scripts/refresh_source_snapshots.py`` step.

Standard library only: no third-party dependency and no HTTP client is imported
at module load anywhere in this package.
"""

from __future__ import annotations

from app.data.connectors.base import (
    LicenseValidationError,
    Provenance,
    SnapshotBackedConnector,
    SnapshotChecksumError,
    SnapshotRef,
    SourceConnector,
    SourceConnectorError,
    compute_checksum,
    read_snapshot,
    validate_connector,
    validate_provenance,
    validate_records_no_pii,
    write_snapshot,
)

__all__ = [
    "LicenseValidationError",
    "Provenance",
    "SnapshotBackedConnector",
    "SnapshotChecksumError",
    "SnapshotRef",
    "SourceConnector",
    "SourceConnectorError",
    "compute_checksum",
    "read_snapshot",
    "validate_connector",
    "validate_provenance",
    "validate_records_no_pii",
    "write_snapshot",
]
