"""Wikidata Source_Connector (franchise / award structured facts).

Onboards Wikidata as an Open_Data_Source supplying the ``franchise_flag`` (a 0/1
sequel/franchise indicator derived from the "part of the series" relation) and an
``award_signal`` correlate. Title-level structured facts only -- zero PII (R2.3).
Wikidata is released under CC0.

Snapshot-only reads by checksum; no live fetch in a build/test (R9.4). Standard
library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.connectors.base import Provenance, SnapshotBackedConnector

__all__ = ["WikidataConnector"]


class WikidataConnector(SnapshotBackedConnector):
    """Supplies franchise_flag, award_signal from Wikidata structured facts."""

    source_name = "Wikidata"
    snapshot_filename = "wikidata.snapshot.json"
    expected_checksum = (
        "555b14725b8b39fc0cf1e65ed8ca15960b74f0c7172aba9d70c190205b5113ab"
    )
    supplies = ("franchise_flag", "award_signal")

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
            name="Wikidata",
            url="https://www.wikidata.org/",
            license="CC0-1.0",
            access_date="2024-01-15",
            label_type="PROXY",
            noncommercial=False,
        )
