# KPI_Test_Dataset provenance manifest

This records the sources and licenses behind the committed `KPI_Test_Dataset`
(`content_eval_dataset.csv` + `content_eval_dataset.json`, with the sidecar
`DATASET_META.json`) built by `make_content_eval_dataset.py`. The dataset is the
versioned, labeled truth sheet the Content_Eval_System measures every
Content_Eval_Model against (content-eval-model, Requirement 3).

The generator is standard-library only, deterministic, and offline. It consumes
the connector layer's committed, checksummed `Source_Snapshot` fixtures through
the `Connector_Registry`
(`app.data.connectors.connector_registry.resolve_features`) for the open-data
correlates on the five seeded demo rows, so those rows are reproducible from
fixed bytes by checksum (R2.5, R9.2). The full connector-layer provenance lives
in `backend/app/data/snapshots/PROVENANCE.md`; this manifest references it rather
than duplicating it.

## Honesty posture (R2.6, R3.6)

Every row is **PROXY** or **SYNTHETIC** — there are **no OBSERVED** (real,
realized platform) outcomes in this dataset. Any accuracy a measurement reports
over this dataset is therefore **proxy accuracy, not real-world accuracy**, and
must be labeled as such wherever it is surfaced. The dominant `Label_Type` is
recorded in the dataset metadata block and the sidecar.

- **PROXY rows (5):** the five seeded demo titles (Aurora Protocol, Echoes of
  2019, Monsoon Lanes, The Ledger, Vintage Reruns Vol. 7). Their open-data
  correlates come from the connector snapshots below; their expected verdicts are
  pinned to the current seeded demo so the demo stays stable and regressions are
  caught (R3.4).
- **SYNTHETIC rows (55):** deterministically generated coverage spanning the five
  strata (tentpole / mid-budget genre / indie drama / international co-production
  / library catalog). Generated for stratification only — never a real outcome —
  and tagged `SYNTHETIC` on every surface.

## Sources + licenses

These are the Open_Data_Sources the demo rows' correlates are drawn from, via the
connector layer. Each passes the connector manifest/license + PII gate
(`app.data.connectors.base.validate_connector`); all records are **title-level
only** (metadata, aggregate popularity/ratings, awards, franchise facts) with
**zero personal data** (R2.3, R9.5).

| Source | Supplies | License | Access date | Commercial? |
| --- | --- | --- | --- | --- |
| IMDb (non-commercial datasets) | runtime_minutes, award_signal, release_year | IMDB-NONCOMMERCIAL | 2024-01-15 | **non-commercial only** |
| TMDB | normalized_rating, log_vote_count, runtime_minutes | TMDB-TERMS | 2024-01-15 | yes |
| MovieLens (GroupLens) | normalized_rating, log_vote_count | GROUPLENS-RESEARCH | 2024-01-15 | yes |
| Wikidata | franchise_flag, award_signal | CC0-1.0 | 2024-01-15 | yes |

**IMDb is flagged non-commercial.** Its connector declares `noncommercial=True`;
the license gate quarantines an IMDb-licensed source that omits that declaration.
Overlap precedence (IMDb > TMDB > MovieLens > Wikidata) is documented in
`backend/app/data/snapshots/PROVENANCE.md` and the connector registry.

The source manifest is also embedded (programmatically, from the live connector
provenance) in the dataset `metadata.sources` block and the sidecar
`DATASET_META.json`, so it can never drift from the connector layer.

## Temporal_Split (R3.3)

Train vs held-out test is partitioned by a recorded **release-year cutoff**, not
a random k-fold (which would leak future/franchise signal and cause look-ahead
bias). Train = titles released **on or before** the cutoff; test = titles
released **after** it. The cutoff is recorded in the metadata block and the
sidecar.

- **Cutoff year:** `2019`
- Every stratum and both label types appear on both sides of the cutoff, so the
  held-out split is a meaningful sample rather than a trivial one or two rows.

## Regenerating / verifying

```
# write the committed artifacts:
python database/kpi_dataset/make_content_eval_dataset.py

# verify the committed artifacts are up to date (idempotent, no write):
python database/kpi_dataset/make_content_eval_dataset.py --check
```

> The demo rows use the invented demo title ids from the connector fixtures
> (`demo-tentpole-01` …) and small sample correlate values; the synthetic rows
> are invented titles. This dataset is not a redistribution of any source's
> dataset.
