# Source_Snapshot provenance manifest

These are the committed/cached `Source_Snapshot` fixtures the pluggable
source-connector layer (`app.data.connectors`) reads by checksum. All reads are
offline and deterministic: build/fit/test/measurement code binds to the pinned
sha256 of each snapshot's canonical JSON. A live fetch happens only in the
out-of-build `scripts/refresh_source_snapshots.py` step (R9.4).

Every source below passes the manifest/license + PII gate
(`app.data.connectors.base.validate_connector`). All records are **title-level
only** (metadata, aggregate popularity/ratings, awards, franchise facts) — no
personal data (R2.3, R9.5). All labels are **PROXY** (open-data correlates, not
real platform outcomes) and are reported as such (R2.6, R9.6).

| Source | Supplies | License | Access date | Commercial? |
| --- | --- | --- | --- | --- |
| TMDB | normalized_rating, log_vote_count, runtime_minutes | TMDB-TERMS | 2024-01-15 | yes |
| MovieLens (GroupLens) | normalized_rating, log_vote_count | GROUPLENS-RESEARCH | 2024-01-15 | yes |
| IMDb (non-commercial datasets) | runtime_minutes, award_signal, release_year | IMDB-NONCOMMERCIAL | 2024-01-15 | **non-commercial only** |
| Wikidata | franchise_flag, award_signal | CC0-1.0 | 2024-01-15 | yes |

**IMDb is flagged non-commercial.** Its connector declares `noncommercial=True`;
the license gate quarantines an IMDb-licensed source that omits that declaration.

## Overlap precedence (documented, deterministic)

Connectors are listed in `connector_registry.ENABLED_CONNECTORS` in descending
authority. A feature value is resolved from the first connector, in that order,
that both declares the feature in `supplies` and provides a value for the title;
the chosen source is recorded per feature (R9.3).

1. IMDb-NonCommercial — authoritative title metadata (runtime, awards, year)
2. TMDB — broad popularity/quality ratings
3. MovieLens — research ratings aggregates (secondary to TMDB where they overlap)
4. Wikidata — structured franchise/award facts

So TMDB beats MovieLens for `normalized_rating`/`log_vote_count`; IMDb beats TMDB
for `runtime_minutes`; IMDb beats Wikidata for `award_signal`.

## Refreshing

```
# verify committed snapshots match pinned checksums (CI-safe, no write):
python scripts/refresh_source_snapshots.py --check

# print current canonical checksums to re-pin after a legitimate update:
python scripts/refresh_source_snapshots.py --repin
```

> These fixtures use invented demo title ids (`demo-tentpole-01` …) and small
> sample rows so the full suite runs offline in well under the time budget. They
> are not a redistribution of any source's dataset.
