# Requirements Document

## Introduction

CineROI AI (GreenlightIQ) is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend) whose `Guardrails_Engine` evaluates each candidate title against four quantitative guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon) and produces a greenlight recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured, auditable explanation. The engine is deterministic and every valuation is stamped with the model version that produced it.

Today the quantitative *inputs* the engine consumes (projected viewing hours, churn-reduction percentage, and the LTV value drivers) are either hard-coded seed literals, verbatim snapshot values, or deterministic placeholder formulas. One input, the churn-reduction percentage, has already been upgraded to a transparent, additive, versioned model (the `Churn_Mitigation_Model`, `backend/app/domain/churn.py`). The remaining inputs are still placeholders, and none of the models are *fitted to data* or *measured against a held-out truth set*.

This feature, the **Content_Eval_System**, introduces a data-based modeling capability that (a) estimates the engine's guardrail inputs from features derived from open-source content data, (b) is fitted and measured against a versioned **KPI_Test_Dataset** (a labeled truth sheet), and (c) is scored by a **Backtest_Harness** that reports each model's accuracy and its effect on the platform's output KPIs, per model version. It is designed to be **scalable** (new models and signals plug in behind existing interfaces without re-architecting) and **fittable** (coefficients learned from data, not hand-tuned), while preserving the platform's non-negotiable guarantees: the decision engine stays deterministic, explainable, versioned, and auditable; AI never becomes the final gate on money; and every model output is traceable to its features.

The scope is the modeling and measurement layer: how guardrail inputs are produced from data, how they are fitted, how the truth set is defined and versioned, and how impact on KPIs is measured. It MUST NOT change the four guardrail thresholds, the recommendation logic, the governance sign-off gates, or the seeded demo verdicts. Every model remains overridable by an explicitly supplied value (the existing `SUPPLIED`-wins contract) and always has a deterministic fallback.

### Grounding (verified against the current codebase)

- `backend/app/engines/guardrails.py`: `ValuationInputs` is a frozen dataclass carrying `churn_reduction_pct`, `churn_reduction_value`, `ltv`, `watch_time_elasticity`, `cpm`, `ad_impressions`, a milestone schedule, and monthly margin; it is produced by an injected `ValuationInputProvider`. `_compute(...)` runs the four checks via pure `app/domain/*` functions. Constants: `CHURN_MITIGATION_THRESHOLD = Decimal("1.5")`; LTV floor 3.2; payback target 9-12. The engine stamps `model_version_id` and writes an append-only audit entry.
- `backend/app/api/deps.py`: `SnapshotValuationInputProvider.get_inputs(...)` reads the active title version `source_snapshot`. `backend/app/api/quick_evaluate.py` `_modeled_inputs(...)` writes placeholder inputs (e.g. `churn_reduction_pct = round(1.0 + (pedigree / 10) * 2.0, 2)`); viewing hours, when blank, are estimated by the engine.
- `backend/app/domain/churn.py`: the reference pattern - a pure, additive, versioned model with per-feature `ChurnContribution` breakdowns, a `SUPPLIED`-wins `resolve_churn(...)`, graceful degradation (neutral defaults for missing telemetry/genre), Decimal precision, and `Illustrative_Coefficients` tuned to the demo (explicitly not fitted to real outcomes).
- `backend/app/domain/cpvh.py`: CPVH = Cost(USD) / Projected Viewing Hours. `backend/app/domain/ltv.py` (and the LTV drivers in `ValuationInputs`): numerator = (churn_reduction_value x LTV) + (watch_time_elasticity x CPM x ad_impressions).
- `model_versions.guardrail_params` is a JSONB column already carrying per-guardrail params and a `churn_model` sub-object; `backend/app/engines/calibration.py` forks a new immutable model version copying `guardrail_params` forward. Model-version rows are immutable.
- `backend/app/engines/backtesting.py`: `PREDICTED_METRIC_FIELDS` maps metric names (e.g. `"churn_reduction"`, `"cpvh"`, `"ltv_to_cost"`) to `financial_projections` columns; `POST /api/v1/backtest/audit` accepts `metrics: [{metric_name, actual_value}]`; MAPE excludes zero-actual metrics. The Backtest Studio UI already audits CPVH and LTV-to-Cost.
- `backend/app/engines/feature_extraction.py`: produces the 1536-dim `Narrative_DNA` vector (deterministic placeholder embedding in demo mode) plus `talent_pedigree_score` and `production_scale_metric` in `metadata_vectors`.
- Data model: `titles` (asset_type, genre_tag, content_format, target_territories), `metadata_vectors`, `license_terms` (is_exclusive, milestones), `market_telemetry_cache` (social_sentiment_index per genre + territory), `financial_projections` (the stored predicted inputs + outputs), `model_versions`.
- `sample-imports/` already contains open-data-styled slates (CSV/JSON/PDF) with a generator-script pattern (`make_*.py`, standard-library only, with `--check`). `database/seed/generate_seed_sql.py` builds model-version + title + projection rows (standard library, `--check` mode).
- Tests: backend pytest + Hypothesis property tests over pure `app/domain/*`; frontend Vitest + Testing Library. `make_stress_slate.py` demonstrates large synthetic catalog generation.
- Honesty posture: the knowledge base and UI already label modeled drivers as deterministic placeholders / illustrative, not production data; the deck uses sample-slate figures. Any new model MUST carry the same honest labeling where it is proxy-trained.

## Glossary

- **Content_Eval_System**: The feature described by this document: the data-based modeling and measurement layer that estimates guardrail inputs from open-data features, is fitted and scored against a labeled truth set, and reports KPI impact per model version.
- **Guardrail_Input**: A quantitative value the `Guardrails_Engine` consumes to run a guardrail check. Each input is either a `Modeled_Engagement_Driver` (estimable from title features) or a `Platform_Rate` (a macro economic assumption that open data cannot supply). In scope for modeling: `Projected_Viewing_Hours` (CPVH), `Churn_Reduction_Pct` (churn), and the title-specific LTV drivers `Watch_Time_Elasticity` and relative ad-load receptivity. Payback is derived from these plus the milestone schedule and is not independently modeled here.
- **Modeled_Engagement_Driver**: A title-specific demand/engagement quantity a `Content_Eval_Model` estimates from the `Feature_Vector`: `Projected_Viewing_Hours`, `Churn_Reduction_Pct`, `Watch_Time_Elasticity`, and relative ad-load receptivity. These are the quantities open data can genuinely inform.
- **Platform_Rate**: A macro-economic assumption that is NOT estimable from open content data and is configured per platform/territory rather than modeled: base subscriber `LTV` ($), programmatic AVOD `CPM` ($), and the `Ad_Impressions` volume basis. A `Content_Eval_Model` MAY scale these by a modeled driver (e.g. ad-load receptivity scales the configured CPM basis) but MUST NOT invent the base dollar rate from open data.
- **Content_Eval_Model**: A pure, deterministic, versioned model that maps a title's `Feature_Vector` to one `Guardrail_Input` (or a coherent group of LTV drivers), with a per-feature contribution breakdown. One model per input keeps each unit independently fittable, explainable, and testable. The existing `Churn_Mitigation_Model` is the first member of this family and the reference implementation.
- **Feature_Vector**: The set of observable, explainable features derived from a title's data and from `Open_Data_Sources`, each with a documented provenance and transform. Features are the only thing a `Content_Eval_Model` may consume.
- **Open_Data_Source**: A permissively or non-commercially licensed external dataset used to derive features and/or proxy labels, with its license recorded. Examples: MovieLens (GroupLens), TMDB, IMDb non-commercial datasets, Wikidata. No source requiring a commercial license or exposing personal data is used.
- **Source_Connector**: A pluggable adapter that onboards one Open_Data_Source by fulfilling a fixed four-step contract: (1) fetch its raw records, (2) normalize them into the shared `Feature_Vector` contract, (3) write a checksummed local Source_Snapshot for offline reproducibility, and (4) register the source's license and access metadata in the provenance manifest. New sources are added by implementing this contract, not by changing the models, the dataset schema, or the harness.
- **Source_Snapshot**: The checksummed, committed-or-cached local copy of a Source_Connector's fetched raw records, so every build, fit, and measurement reads fixed bytes and never depends on a live external call.
- **Connector_Registry**: The ordered, declarative list of enabled Source_Connectors the feature pipeline draws from. Adding a source is a registry entry plus a connector implementation; the registry records which features each source supplies and its precedence when two sources offer the same feature.
- **KPI_Test_Dataset**: A versioned, labeled truth set ("the sheet"): a fixed set of titles, each row carrying its `Feature_Vector`, the expected `Guardrail_Input` values, the expected guardrail check outcomes, and the expected recommendation, plus provenance and a label-type tag (observed vs proxy vs synthetic). The held-out contract that any `Content_Eval_Model` is measured against.
- **Label_Type**: How a row's expected values were obtained: OBSERVED (real realized outcome), PROXY (derived from an open-data correlate, not a true platform outcome), or SYNTHETIC (generated for coverage). Every row and every fitted model carries its dominant label type for honest reporting.
- **Backtest_Harness**: The measurement component that runs a `Content_Eval_Model` (or the whole engine) over the `KPI_Test_Dataset`, computes per-input error (MAPE and others) and verdict-match rate, compares against a named baseline version, and reports the resulting change in platform `Output_KPIs`.
- **Output_KPI**: A portfolio-level metric already surfaced on the dashboard that a model can move: active pipeline valuation (USD), average LTV-to-Cost multiple, portfolio risk-exposure index, and model prediction-accuracy rate.
- **Model_Fit**: The process of learning a `Content_Eval_Model`'s coefficients from the `KPI_Test_Dataset` (or a training split of it) by an explicit, reproducible, deterministic fitting procedure, producing a new immutable `Content_Eval_Version`.
- **Content_Eval_Version**: An immutable, versioned parameter set for a `Content_Eval_Model`, stored alongside the existing model-version lineage (under `model_versions.guardrail_params`), carried forward on calibration forks, and referenced by every valuation it produced so the result is reproducible.
- **Deterministic_Fallback**: The current placeholder or illustrative model for an input, always retained and used when no fitted version is active, when features are insufficient, or when a supplied value is absent, so the system never fails to produce an input.
- **Supplied_Value**: An explicitly provided `Guardrail_Input` in the title snapshot or quick-evaluate payload that, when present and valid, overrides any model output (the existing `SUPPLIED`-wins contract).
- **Temporal_Split**: A train/test partition by release date (train on titles at or before a recorded cutoff year, test on titles after it) that simulates real greenlighting (past catalog informs future slates) and avoids the look-ahead leakage a random k-fold split would introduce.
- **False_Greenlight_Rate**: The fraction of titles the system predicted GREENLIGHT whose expected verdict was NEGOTIATE_HARD or PASS, the capital-loss error, tracked as the primary risk metric.
- **False_Pass_Rate**: The fraction of titles the system predicted PASS or NEGOTIATE_HARD whose expected verdict was GREENLIGHT, the opportunity-cost error.
- **Proxy_Label**: An expected value in the `KPI_Test_Dataset` derived from an open-data correlate (e.g. normalized popularity/ratings) rather than a true platform outcome; always tagged `Label_Type = PROXY` and reported as such.

## Requirements

### Requirement 1: Model family and the per-input contract

**User Story:** As a data scientist, I want each guardrail input produced by its own pure, deterministic, explainable model behind one shared interface, so that models are independently fittable and testable and plug in without touching the decision engine.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL model only the Modeled_Engagement_Drivers (`Projected_Viewing_Hours`, `Churn_Reduction_Pct`, `Watch_Time_Elasticity`, and relative ad-load receptivity), expressing each as a Content_Eval_Model that maps a Feature_Vector to that driver with no other inputs consulted; the Platform_Rates (`LTV`, `CPM`, `Ad_Impressions` basis) SHALL remain configured per platform/territory and SHALL NOT be invented from open data, though a modeled driver MAY scale a configured Platform_Rate.
2. THE Content_Eval_Model SHALL be a pure function of its Feature_Vector and its Content_Eval_Version parameters: no I/O, no database access, no global mutable state, Decimal precision throughout, and deterministic (identical inputs yield an identical result).
3. THE Content_Eval_Model SHALL return, with every output, a per-feature contribution breakdown that conserves to the final value, the list of missing and assumed features, and the Content_Eval_Version that produced it, matching the explanation contract already established by the Churn_Mitigation_Model.
4. THE Content_Eval_System SHALL produce every Guardrail_Input through the engine's existing `ValuationInputProvider` boundary, so the `Guardrails_Engine`, the four thresholds, the recommendation logic, and the governance gates are unchanged.
5. WHEN a valid Supplied_Value exists for an input, THE Content_Eval_System SHALL use it exactly and skip the model for that input (the SUPPLIED-wins contract), recording the method as SUPPLIED.
6. WHEN no fitted Content_Eval_Version is active, or the Feature_Vector lacks the features a model requires, THE Content_Eval_System SHALL use that input's Deterministic_Fallback and record the method and the reason.
7. THE Content_Eval_System SHALL NOT allow any Content_Eval_Model to be the final arbiter of a recommendation; the deterministic `Guardrails_Engine` and the existing sign-off gates remain the only decision authority.

### Requirement 2: Features from open data, with provenance and licensing

**User Story:** As a data engineer, I want every feature derived from a documented, appropriately licensed open-data source with an explicit transform, so the model is reproducible and legally clean.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL define a Feature_Vector in which every feature records its source (title field or named Open_Data_Source), its transform, and its valid domain.
2. THE Content_Eval_System SHALL only use Open_Data_Sources whose licenses permit the project's use, and SHALL record each source's name, URL, license, and access date in a committed provenance manifest.
3. THE Content_Eval_System SHALL NOT ingest or store personal data; features derived from external sources SHALL be title-level attributes only (metadata, aggregate popularity, ratings, awards), never individual user data.
4. WHEN an Open_Data_Source is unavailable or a feature is missing for a title, THE Content_Eval_System SHALL degrade gracefully using a neutral default (not zero where zero would unfairly penalize) and record the feature as assumed, matching the existing churn-model degradation behavior.
5. THE Content_Eval_System SHALL make feature derivation reproducible offline (a committed, standard-library generator or a cached snapshot with a recorded checksum), so a build does not depend on a live external call.
6. WHERE a feature or label is a Proxy_Label derived from an open-data correlate rather than a real platform outcome, THE Content_Eval_System SHALL label it PROXY wherever it is surfaced.

### Requirement 3: The KPI_Test_Dataset (the labeled truth sheet)

**User Story:** As a modeler, I want a versioned truth sheet of titles with expected inputs and outcomes, so any model can be measured against a fixed, honest target.

#### Acceptance Criteria

1. THE KPI_Test_Dataset SHALL be a versioned, human-readable artifact (CSV and/or JSON) committed to the repository, with a documented schema and a generator that supports a `--check` (idempotent, no-write verification) mode. THE committed benchmark SHALL be a curated, well-stratified set of 50 to 100 titles (spanning tentpole/blockbuster, mid-budget genre, indie drama, international co-production, and library catalog) so the full Backtest_Harness and regression suite run offline in under 2 seconds; larger exploratory sets are generated on demand, not committed.
2. Each row of the KPI_Test_Dataset SHALL carry a stable title identifier, the full Feature_Vector, the expected value for each in-scope Guardrail_Input, the expected per-guardrail check outcome, the expected recommendation, the Label_Type, and a provenance note.
3. THE KPI_Test_Dataset SHALL carry a release-year (or release-date) field per row and SHALL use a Temporal_Split for train vs held-out test (e.g. train on titles released on or before a cutoff year, test on titles released after it), so Model_Fit never trains on the rows used to report held-out accuracy and no future information leaks into training (no random k-fold, which would cause look-ahead leakage from sequels/franchise or future-popularity signals). The cutoff SHALL be recorded in the dataset metadata.
4. THE KPI_Test_Dataset SHALL include the five existing seeded demo titles with their current expected verdicts unchanged, so the demo remains stable and regressions are caught.
5. THE KPI_Test_Dataset SHALL record, at the dataset level, its version, creation date, the Open_Data_Sources used, and the dominant Label_Type, and SHALL be immutable once referenced by a published measurement (new data is a new version).
6. WHERE expected values are Proxy_Labels or SYNTHETIC, THE KPI_Test_Dataset SHALL tag them so no measurement overstates real-world accuracy.

### Requirement 4: Fitting a model from data (fittable)

**User Story:** As a data scientist, I want model coefficients learned from the truth sheet by an explicit, reproducible procedure, so the model is fitted to data rather than hand-tuned.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL provide a deterministic Model_Fit procedure that learns a Content_Eval_Model's coefficients from the training split of a named KPI_Test_Dataset version.
2. THE Model_Fit procedure SHALL be reproducible: the same dataset version, feature definitions, and configuration SHALL produce byte-identical Content_Eval_Version parameters (fixed random seeds, no wall-clock or environment dependence).
3. THE Model_Fit procedure SHALL respect the model's structural constraints (e.g. non-negative feature weights where the domain requires monotonicity) so a fitted model keeps the same explainability and monotonicity guarantees as the hand-tuned one.
4. WHERE the target is a heavy-tailed, power-law-distributed quantity (notably `Projected_Viewing_Hours`, where a tentpole title can be orders of magnitude above a library title), THE Model_Fit procedure SHALL fit and evaluate on a log scale (`log(1 + value)`) and SHALL optimize a percentage-scale objective (Log-Scale MAE or WAPE) rather than raw MSE/OLS, so the model achieves consistent percentage accuracy across blockbusters and catalog titles instead of overfitting the largest titles.
5. WHEN Model_Fit completes, THE Content_Eval_System SHALL emit an immutable Content_Eval_Version with its parameters, the dataset version it was fit on, the fit metrics on train and held-out test splits, and the Label_Type of its training labels.
6. THE Content_Eval_System SHALL retain the ability to run with the hand-tuned Illustrative_Coefficients (as a Deterministic_Fallback) so a fitted version is never required to boot or demo.
7. IF a fitted Content_Eval_Version scores worse on the held-out test split than the active baseline, THEN THE Content_Eval_System SHALL NOT auto-activate it and SHALL surface the regression for an explicit decision.

### Requirement 5: Versioning, reproducibility, and auditability

**User Story:** As a governance owner, I want every modeled input stamped with the exact model version that produced it, so any past decision is reproducible and auditable.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL store each Content_Eval_Version within the existing immutable model-version lineage (`model_versions.guardrail_params`), carried forward unchanged on calibration forks.
2. THE Content_Eval_System SHALL stamp every valuation with the Content_Eval_Version(s) used, so recomputing a past valuation under its stamped version reproduces the same inputs and verdict.
3. THE Content_Eval_System SHALL never mutate a published Content_Eval_Version; a change is always a new version.
4. WHEN a model produces an input, THE Content_Eval_System SHALL make the per-feature breakdown and the version available to the audit log and the explanation surfaces, consistent with the existing churn breakdown.
5. THE seeded demo verdicts SHALL remain byte-identical before and after this feature when no fitted version is activated, verified by the existing seed regression tests.

### Requirement 6: The Backtest_Harness and KPI impact measurement

**User Story:** As an executive, I want to see how much a model improved accuracy and which output KPIs it moved, so AI impact is measurable and defensible, not a claim.

#### Acceptance Criteria

1. THE Backtest_Harness SHALL run a named Content_Eval_Version (or the whole engine) over a named KPI_Test_Dataset version and compute per-input error (at minimum MAPE, consistent with the existing backtesting MAPE that excludes zero-actual metrics) on the held-out split.
2. THE Backtest_Harness SHALL compute the verdict-match rate (fraction of titles whose predicted recommendation equals the expected recommendation) AND, because acquisition errors are asymmetric, SHALL separately report the two directional error rates: the False_Greenlight_Rate (predicted GREENLIGHT where the expected verdict was NEGOTIATE_HARD or PASS, i.e. committing capital to a title that should not have cleared) and the False_Pass_Rate (predicted PASS/NEGOTIATE_HARD where the expected verdict was GREENLIGHT, i.e. a missed acquisition / opportunity cost). THE False_Greenlight_Rate SHALL be reported as the primary risk metric, since a false greenlight is a capital loss whereas a false pass is an opportunity cost.
3. THE Backtest_Harness SHALL report the change in each Output_KPI between a baseline version and the version under test, over the same dataset.
4. THE Backtest_Harness SHALL attribute impact to a single changed model at a time, so a reported KPI movement is traceable to one Content_Eval_Version (one-change-at-a-time discipline).
5. WHERE the measured dataset rows are Proxy_Labels or SYNTHETIC, THE Backtest_Harness SHALL label the reported accuracy as proxy accuracy, not real-world accuracy.
6. THE Backtest_Harness SHALL be invokable offline (CLI or test) over the committed dataset, with results reproducible from the dataset version and the model version alone.
7. THE Backtest_Harness SHALL integrate with the existing `POST /api/v1/backtest/audit` metric contract so the four modeled inputs (churn, CPVH via viewing hours, and the LTV drivers) can be scored through the same path the Backtest Studio already uses for CPVH and LTV.

### Requirement 7: Scalability of the modeling layer

**User Story:** As an architect, I want to add the next model or signal without re-architecting, so the system scales to many inputs and signals.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL allow a new Content_Eval_Model to be added as one unit behind the shared interface without changes to the `Guardrails_Engine`, the thresholds, or the recommendation logic.
2. THE Content_Eval_System SHALL allow a new feature (including a new Open_Data_Source or an embedding-derived signal) to be added to a Feature_Vector without breaking existing models or existing Content_Eval_Versions (older versions ignore unknown features).
3. THE Content_Eval_System SHALL keep each model's cost bounded: a single-title valuation that uses only precomputed features SHALL remain a synchronous operation, while any heavyweight feature derivation (large-batch ingestion, embedding computation, external fetches) SHALL run on the existing asynchronous Celery path.
4. THE Content_Eval_System SHALL support a batch evaluation over the whole portfolio that scales linearly with the number of titles and reuses precomputed features.
5. WHERE a model requires heavy inference (e.g. a hosted LLM or GPU embedding), THE Content_Eval_System SHALL isolate that behind a provider interface (mirroring the existing chat/embedding provider pattern) so the default build runs on a laptop with a deterministic provider and a hosted provider is opt-in.

### Requirement 8: Honesty, safety, and non-regression constraints

**User Story:** As a product owner, I want the modeling layer to stay honest and safe, so trust is preserved and nothing silently degrades.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL label any proxy-trained or illustrative model output as such wherever it is surfaced (UI, explanation, docs, deck), never presenting proxy accuracy as real-world accuracy.
2. THE Content_Eval_System SHALL preserve the existing non-correctable churn semantics and all four thresholds; a model MAY change an input value but MUST NOT change how a breach is classified.
3. THE Content_Eval_System SHALL keep a Supplied_Value authoritative over any model output, and a model output authoritative over the Deterministic_Fallback, in that strict precedence.
4. THE Content_Eval_System SHALL not transmit project data, title data, or any dataset to a third-party endpoint except through an explicitly configured, opt-in provider, and SHALL default to a local deterministic provider.
5. THE existing backend (pytest + Hypothesis) and frontend (Vitest) suites SHALL pass, and new pure models SHALL carry property-based tests for determinism, monotonicity, conservation of the breakdown, and domain clamping, matching the churn model's test depth.
6. THE Content_Eval_System SHALL update the knowledge base, architecture doc, calculations reference, and the in-portal guide to describe the modeling layer, the dataset, and the measurement loop, with honest labeling.

### Requirement 9: Pluggable source connectors for onboarding new open data

**User Story:** As a data engineer, I want to onboard a new open-data source by implementing one documented connector contract, so the system can grow to take features from additional sources later without changing the models, the dataset schema, or the harness.

#### Acceptance Criteria

1. THE Content_Eval_System SHALL define a Source_Connector contract with four steps: fetch raw records, normalize them into the shared Feature_Vector contract, write a checksummed Source_Snapshot, and register the source's license and access metadata in the provenance manifest.
2. THE Content_Eval_System SHALL draw features from a declarative Connector_Registry, so adding a source is a registry entry plus a connector implementation, with no change to a Content_Eval_Model, the KPI_Test_Dataset schema, or the Backtest_Harness.
3. WHEN two or more Source_Connectors supply the same feature for a title, THE Content_Eval_System SHALL resolve the value by the registry's documented precedence and record which source was used for that feature.
4. THE Content_Eval_System SHALL require every Source_Connector to produce a Source_Snapshot so that all feature derivation reads fixed, checksummed bytes offline; a live external fetch SHALL only occur in an explicit, out-of-build snapshot-refresh step, never inside a build, fit, test, or measurement.
5. THE Content_Eval_System SHALL reject or quarantine a Source_Connector whose license is absent, incompatible with the project's use, or whose records would introduce personal data, so an unvetted source cannot silently enter the pipeline.
6. THE Content_Eval_System SHALL carry each source's Label_Type contribution forward, so a feature or label originating from a PROXY/SYNTHETIC source remains labeled as such through the dataset and every reported metric.
7. THE Content_Eval_System SHALL add a new source without breaking existing Content_Eval_Versions: a version fitted before a source existed SHALL continue to resolve using only the features it was fitted on (unknown new features are ignored by older versions), preserving reproducibility.
