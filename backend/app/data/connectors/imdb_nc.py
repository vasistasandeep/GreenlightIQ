"""IMDb non-commercial Source_Connector (title metadata + awards).

Onboards IMDb's non-commercial datasets as an Open_Data_Source supplying the
intrinsic ``runtime_minutes``, the ``award_signal`` correlate, and the temporal
``release_year`` (split-only). Title-level only -- zero PII (R2.3).

IMDb's datasets are licensed for NON-COMMERCIAL use only, so this connector's
provenance carries ``license="IMDB-NONCOMMERCIAL"`` and ``noncommercial=True``;
the manifest/license gate (:func:`app.data.connectors.base.validate_connector`)
requires that declaration and would otherwise quarantine the source (R9.5).

Snapshot-only reads by checksum; no live fetch in a build/test (R9.4). Standard
library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.connectors.base import Provenance, SnapshotBackedConnector

__all__ = ["IMDbNonCommercialConnector"]


class IMDbNonCommercialConnector(SnapshotBackedConnector):
    """Supplies runtime_minutes, award_signal, release_year from IMDb (non-commercial)."""

    source_name = "IMDb-NonCommercial"
    snapshot_filename = "imdb_nc.snapshot.json"
    expected_checksum = (
        "a9714b0109fd759dace56d1d81a97d0343646cea3984738c44ddd916f956ec65"
    )
    supplies = ("runtime_minutes", "award_signal", "release_year")

    def normalize(self, raw: Any) -> Mapping[str, Mapping[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        records = raw.get("records", []) if isinstance(raw, Mapping) else []
        for rec in records:
            if not isinstance(rec, Mapping):
                continue
            title_id = rec.get("id")
            if title_id is None:
                continue
            partial: dict[str, Any] = {}
            for key in self.supplies:
                if key in rec and rec[key] is not None:
                    partial[key] = rec[key]
            out[str(title_id)] = partial
        return out

    def provenance(self) -> Provenance:
        return Provenance(
            name="IMDb-NonCommercial",
            url="https://developer.imdb.com/non-commercial-datasets/",
            license="IMDB-NONCOMMERCIAL",
            access_date="2024-01-15",
            label_type="PROXY",
            noncommercial=True,
        )
