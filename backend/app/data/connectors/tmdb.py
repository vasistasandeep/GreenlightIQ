"""TMDB Source_Connector (popularity/quality correlates).

Onboards The Movie Database as an Open_Data_Source supplying the open-data
popularity/quality correlates ``normalized_rating`` (vote average scaled to
[0, 1]) and ``log_vote_count`` (log-normalized vote volume), plus the intrinsic
``runtime_minutes``. Title-level only -- zero PII (R2.3).

During a normal read this connector loads a committed/cached ``Source_Snapshot``
by checksum and performs NO live network fetch (R9.4). A live ``fetch()`` runs
only in ``scripts/refresh_source_snapshots.py``; if that path ever needs an HTTP
client it isolates the import there, never at module load here.

Standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.connectors.base import Provenance, SnapshotBackedConnector

__all__ = ["TMDBConnector"]


class TMDBConnector(SnapshotBackedConnector):
    """Supplies normalized_rating, log_vote_count, runtime_minutes from TMDB."""

    source_name = "TMDB"
    snapshot_filename = "tmdb.snapshot.json"
    # sha256 of the snapshot's canonical JSON (stable across OS/editor).
    expected_checksum = (
        "1b050abd516feaff70978bad9cbe4519f38fd813cce669854be20f8f70f28112"
    )
    supplies = ("normalized_rating", "log_vote_count", "runtime_minutes")

    def normalize(self, raw: Any) -> Mapping[str, Mapping[str, Any]]:
        """Map raw TMDB records into ``{title_id: partial-feature-dict}`` (R9.1)."""
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
            name="TMDB",
            url="https://www.themoviedb.org/",
            license="TMDB-TERMS",
            access_date="2024-01-15",
            label_type="PROXY",
            noncommercial=False,
        )
