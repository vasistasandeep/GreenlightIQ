"""MovieLens Source_Connector (GroupLens ratings aggregates).

Onboards the MovieLens dataset (GroupLens) as an Open_Data_Source supplying the
aggregate popularity/quality correlates ``normalized_rating`` and
``log_vote_count``. Aggregates only -- the connector never ingests individual
user ratings, so no personal data enters the pipeline (R2.3, R9.5).

Snapshot-only reads by checksum; no live fetch in a build/test (R9.4). Standard
library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.connectors.base import Provenance, SnapshotBackedConnector

__all__ = ["MovieLensConnector"]


class MovieLensConnector(SnapshotBackedConnector):
    """Supplies normalized_rating, log_vote_count from MovieLens aggregates."""

    source_name = "MovieLens"
    snapshot_filename = "movielens.snapshot.json"
    expected_checksum = (
        "20b6c53412a1d23748f0b4284b4a29bec1b11e30c8e6595664e8d3792f5cd743"
    )
    supplies = ("normalized_rating", "log_vote_count")

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
            name="MovieLens",
            url="https://grouplens.org/datasets/movielens/",
            license="GROUPLENS-RESEARCH",
            access_date="2024-01-15",
            label_type="PROXY",
            noncommercial=False,
        )
