"""The declarative Connector_Registry: ordered sources + overlap precedence (R9.2, R9.3).

The registry is the single declarative place that enumerates the enabled
Source_Connectors and, per feature, which source supplies it and who wins when
two sources overlap. Adding a new Open_Data_Source is exactly one registry entry
plus one connector module -- no change to a Content_Eval_Model, the
KPI_Test_Dataset schema, or the Backtest_Harness (R9.2).

Overlap precedence (documented, deterministic)
----------------------------------------------
Connectors are listed in :data:`ENABLED_CONNECTORS` in descending authority. A
feature value is resolved from the FIRST connector, in that order, that both
(a) declares the feature in its ``supplies`` and (b) actually provides a value
for the title. The chosen source is recorded per feature so a resolved value is
always traceable (R9.3).

The order encodes the project's source-trust policy:

1. ``IMDb-NonCommercial`` -- authoritative, curated title metadata (runtime,
   awards, release year).
2. ``TMDB``               -- broad, well-maintained popularity/quality ratings.
3. ``MovieLens``          -- research ratings aggregates (secondary to TMDB for
   the rating correlates they both supply).
4. ``Wikidata``           -- structured franchise/award facts.

So when TMDB and MovieLens both supply ``normalized_rating`` / ``log_vote_count``
for a title, TMDB wins; when IMDb and TMDB both supply ``runtime_minutes``, IMDb
wins; when IMDb and Wikidata both supply ``award_signal``, IMDb wins.

Resolution reads only committed, checksummed Source_Snapshot bytes (no live
fetch), so it is reproducible and offline (R9.4). Because
:func:`app.domain.features.derive_features` ignores unknown keys, adding a
connector that introduces a brand-new feature leaves every pre-existing fitted
Content_Eval_Version's resolved inputs byte-identical (R9.7, Property 14).

Standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.data.connectors.base import (
    Provenance,
    SourceConnector,
    validate_connector,
)
from app.data.connectors.imdb_nc import IMDbNonCommercialConnector
from app.data.connectors.movielens import MovieLensConnector
from app.data.connectors.tmdb import TMDBConnector
from app.data.connectors.wikidata import WikidataConnector

__all__ = [
    "ENABLED_CONNECTORS",
    "ResolvedFeature",
    "default_connectors",
    "build_feature_source_map",
    "resolve_features",
    "resolved_to_raw",
    "validate_registry",
]


# The ordered, declarative list of enabled connectors (descending authority).
# Earlier entries win an overlap. Adding a source = appending (or inserting at
# the right precedence) one factory here plus its connector module.
ENABLED_CONNECTORS: tuple[type[SourceConnector], ...] = (
    IMDbNonCommercialConnector,
    TMDBConnector,
    MovieLensConnector,
    WikidataConnector,
)


def default_connectors() -> list[SourceConnector]:
    """Instantiate the enabled connectors in registry (precedence) order."""
    return [factory() for factory in ENABLED_CONNECTORS]


@dataclass(frozen=True)
class ResolvedFeature:
    """A single resolved feature value plus the source it was chosen from (R9.3)."""

    value: Any
    source: str
    label_type: str


def build_feature_source_map(
    connectors: Sequence[SourceConnector] | None = None,
) -> dict[str, list[str]]:
    """Return ``{feature_key: [source_name, ...]}`` in precedence order.

    Documents which sources supply each feature and the order in which overlaps
    are resolved (the first listed source wins). Derived from each connector's
    ``supplies`` declaration, so it stays in sync with the registry automatically.
    """
    conns = list(connectors) if connectors is not None else default_connectors()
    mapping: dict[str, list[str]] = {}
    for conn in conns:
        name = conn.provenance().name
        for key in conn.supplies:
            mapping.setdefault(key, []).append(name)
    return mapping


def resolve_features(
    connectors: Sequence[SourceConnector] | None = None,
    *,
    validate: bool = True,
) -> dict[str, dict[str, ResolvedFeature]]:
    """Resolve every title's features across all connectors by precedence (R9.3).

    Returns ``{title_id: {feature_key: ResolvedFeature}}``. For each feature the
    value comes from the first connector (in registry order) that supplies and
    provides it; the chosen source name and its Label_Type are recorded so the
    result is fully traceable (R9.3, R9.6).

    When ``validate`` is True (the default), each connector must pass the
    manifest/license + PII gate before its data is admitted; an unvetted source
    raises and never enters the result (R9.5). All reads are snapshot-only, by
    checksum -- no live fetch (R9.4).
    """
    conns = list(connectors) if connectors is not None else default_connectors()
    resolved: dict[str, dict[str, ResolvedFeature]] = {}

    for conn in conns:
        prov = validate_connector(conn) if validate else conn.provenance()
        records = conn.load()
        for title_id, partial in records.items():
            title = resolved.setdefault(title_id, {})
            for key in conn.supplies:
                if key not in partial or partial[key] is None:
                    continue
                # First writer wins: connectors are in descending precedence,
                # so a feature already resolved by a higher-authority source is
                # left untouched (the documented overlap rule, R9.3).
                if key in title:
                    continue
                title[key] = ResolvedFeature(
                    value=partial[key],
                    source=prov.name,
                    label_type=prov.label_type,
                )
    return resolved


def resolved_to_raw(
    resolved: Mapping[str, Mapping[str, ResolvedFeature]],
) -> dict[str, dict[str, Any]]:
    """Flatten resolved features to plain ``{title_id: {feature: value}}`` dicts.

    This is the raw mapping a consumer passes straight to
    :func:`app.domain.features.derive_features`.
    """
    return {
        title_id: {key: rf.value for key, rf in feats.items()}
        for title_id, feats in resolved.items()
    }


def validate_registry(
    connectors: Sequence[SourceConnector] | None = None,
) -> list[Provenance]:
    """Validate every enabled connector through the manifest gate (R9.5).

    Returns the provenance entries in registry order on success; raises
    :class:`~app.data.connectors.base.LicenseValidationError` for the first
    connector that fails the license/PII gate.
    """
    conns = list(connectors) if connectors is not None else default_connectors()
    return [validate_connector(conn) for conn in conns]
