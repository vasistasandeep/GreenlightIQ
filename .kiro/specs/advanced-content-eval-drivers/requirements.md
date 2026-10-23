# Requirements Document

## Introduction

CineROI AI (GreenlightIQ) is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend) whose `Guardrails_Engine` (`backend/app/engines/guardrails.py`) evaluates each candidate title against four quantitative guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon) and produces a greenlight recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured, auditable explanation. The engine is deterministic, stamps every valuation with its model version, and consumes its quantitative inputs through the frozen `ValuationInputs` dataclass produced by an injected `ValuationInputProvider`.

The Layer-A engagement/viewership inputs are already modeled by the `Content_Eval_System` (content-eval-model) family of pure domain modules: `Projected_Viewing_Hours` via a log-space linear model (`backend/app/domain/viewing_hours.py`), `Churn_Reduction_Pct` via an additive model (`backend/app/domain/churn.py`), and the LTV drivers `Watch_Time_Elasticity` / `Ad_Load_Receptivity` (`backend/app/domain/engagement.py`). Each reads the shared `FeatureVector` contract (`backend/app/domain/features.py`), conserves a per-feature breakdown, clamps to a documented domain, obeys the `SUPPLIED` > model > `DETERMINISTIC_FALLBACK` precedence, and carries `Illustrative_Coefficients` that are explicitly not fitted to real outcomes.

The modeled viewing-hours intercept is still a blunt platform-wide constant (`DEFAULT_VIEWING_HOURS_PARAMS.intercept`, `exp(8) - 1 ~= 2980` base hours), the engagement signals ignore franchise lineage and market momentum, and no macro market modifier (source-IP provenance, theatrical windowing halo, seasonality, vernacular reach) touches the prediction. This feature, the **Advanced_Content_Eval_Drivers**, replaces those blunt heuristics with four industry drivers that feed `ValuationInputs` through the same pure-domain discipline:

- **Driver A - Comps_Engine**: a k-NN retrieval over the 1536-dim `metadata_vectors.narrative_dna` embedding (pgvector `<=>` cosine distance) that anchors a title's viewing hours and churn mitigation to the empirical median of its five nearest historical comps, replacing the generic constant intercept with an empirical Bayesian prior.
- **Driver B - Lineage_Decay**: a franchise floor and retention credit derived from parent-title performance.
- **Driver C - Momentum_Telemetry**: stage-gated trailer/social/search momentum that activates only for produced titles and degrades to neutral when the telemetry feed is stale or unavailable.
- **Driver D - Macro_Modifiers**: multiplicative market modifiers for source-IP provenance, theatrical-to-streaming windowing halo, calendar seasonality, and vernacular/dubbing reach.

All four drivers conserve the existing Option-B hour-space breakdown attribution (reusing the established `rounding_or_bounds_adjustment` line item in `viewing_hours.py` as the residual sink), preserve strict `Decimal` precision under the fixed decimal context, enforce monotonicity and clamp boundedness, and obey the `SUPPLIED` > `FITTED` > `DETERMINISTIC_FALLBACK` precedence. Every new coefficient ships as a `DETERMINISTIC_FALLBACK` illustrative constant; fitting under non-negativity constraints is deferred follow-up work. Every driver is governed by a per-driver kill-switch that defaults off, so the five seeded demo titles (Aurora Protocol, Monsoon Lanes, The Ledger, Vintage Reruns Vol. 7, Echoes of 2019) and all existing tests remain byte-identical until a driver is explicitly enabled.

The scope of this document is **requirements only**: no implementation, no migrations applied, no tests run. It produces exactly this `requirements.md`.

### Grounding (verified against the current codebase)

- `backend/app/domain/deal_stage.py`: `DealStage` is the **human acquisition pipeline** (SCREENING, EVALUATED, IN_NEGOTIATION, APPROVED, CLOSED_WON, CLOSED_LOST, PASSED), not a production-readiness stage. The `titles.deal_stage` column and its CHECK constraint (`ASSET_TYPES`/`DEAL_STAGES` in `backend/app/models/title.py`) enforce that same set. The production-readiness stages Driver C needs (CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY) **do not exist today** and MUST be introduced as a new, separate enum, leaving the deal-stage lifecycle untouched.
- `backend/app/domain/windowing.py`: `WindowType` is **licensing-window exclusivity** (EXCLUSIVE, NON_EXCLUSIVE) with `validate_windowing` / `compute_payback_horizon` / `project_window_value`; it has nothing to do with theatrical-to-streaming release windows. Driver D's release-window halo (DIRECT_TO_STREAMING, DAY_AND_DATE, THEATRICAL_30D, THEATRICAL_60D_PLUS) is a **new** concept and MUST NOT redefine `WindowType`.
- `backend/app/domain/viewing_hours.py`: the log-space model `y_log = intercept + sum_i(beta_i * x_i)`, `H_hat = exp(y_log) - 1`, Option-B hour-space allocation `H0 = exp(intercept) - 1`, and a single trailing contribution with `key="rounding_or_bounds_adjustment"` / `label="Rounding or Bounds Adjustment"` that absorbs the floor-clamp delta and quantization residual so `sum(breakdown.hours) == viewing_hours` exactly. `VIEWING_HOURS_FLOOR = Decimal("1")`, `VIEWING_HOURS_QUANTUM = Decimal("1")` (whole hours), fixed `Context(prec=50, rounding=ROUND_HALF_UP)`. `DEFAULT_VIEWING_HOURS_PARAMS.intercept = Decimal("8.0")`. `resolve_viewing_hours` implements SUPPLIED-wins; `parse_params` full-fallback to `DEFAULTS` on any invalid field.
- `backend/app/domain/features.py`: the shared `FeatureVector` already carries `franchise_flag` (0/1 indicator with `FRANCHISE_NEUTRAL = 0`, assumed when absent), plus `asset_type`, `genre`, `content_format`, `runtime_minutes`, `is_exclusive`, `production_scale`, `talent_pedigree`, `normalized_rating`, `log_vote_count`, `award_signal`, and the split-only `release_year`. `PREDICTIVE_FEATURES` is the authoritative predictor list. Label normalizers `normalize_label` / `normalize_genre` / `normalize_asset_type`.
- `backend/app/domain/churn.py`: additive model; `CHURN_MITIGATION_THRESHOLD = Decimal("1.5")`, `MIN_CHURN = 0.10`, `MAX_CHURN = 5.00`, `BORDERLINE_BAND = 0.05`, a single `bounds_adjustment` conservation entry, `resolve_churn` SUPPLIED-wins. Churn mitigation is additive in percentage points; a breach of the 1.5 hurdle is non-correctable and forces PASS.
- `backend/app/models/metadata_vector.py`: `metadata_vectors.narrative_dna` is a pgvector `Vector(1536)` (`NARRATIVE_DNA_DIMENSIONS = 1536`); `talent_pedigree_score` / `production_scale_metric` are `Numeric(4,2)` in [0,10]; `extraction_status` in {SUCCESS, FAILED}; FKs to `titles` (CASCADE) and `title_versions`.
- `backend/app/repositories/metadata_vectors.py`: `MetadataVectorRepository.rank_similar_titles(...)` already does title-to-title cosine similarity with `MetadataVector.narrative_dna.cosine_distance(title_vector)`, returns `SimilarTitle(title_id, title_name, genre_tag, recommendation_status, cosine_similarity)`, dedups multiple vectors per title to the closest row, and orders by the derived `1 - distance` expression (not the bare `<=>`) to force an exact sequential scan at demo data volumes where the IVFFlat ANN index returns zero candidates. The comps surface `GET /valuation/{title_id}/comps` and `ComparableTitlesResponse` / `TitleCompOut` already exist.
- `backend/app/models/market_telemetry_cache.py`: `market_telemetry_cache` keyed uniquely by `(genre_tag, territory)`, with `social_sentiment_index` / `chart_velocity_score` `Numeric(6,2)`, `licensing_inflation_multiplier` `Numeric(6,3)`, a `source_available` boolean (`server_default="true"`; `False` means retained-but-stale), and a `last_updated_at` timestamp (the staleness clock). `MarketTelemetryResponse` exposes `source_available` and `found`.
- `backend/app/models/title.py`: `titles` carries `asset_type` (ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, CO_PRODUCTION), `acquisition_cost_or_budget` `Numeric(14,2)`, `native_currency`, `target_territories` JSONB, `genre_tag`, `deal_stage`, `projected_viewing_hours` `Numeric(16,2)`, `is_historical`. Normalized USD cost comes from the currency/FX path (`backend/app/domain/currency.py`); the budget band in Driver A is computed in normalized USD.
- `backend/app/schemas/api.py`: `ValuationScorecardResponse.explanation: dict[str, Any]` is the pass-through structured explanation; `MetadataBreakdown` summarizes the vector by `narrative_dna_dimensions` rather than serializing it; `WhatIfResponse` extends the scorecard. Decimal fields serialize as JSON strings and the frontend coerces defensively (`num()` / `toNumber()`).
- `backend/app/core/config.py`: `Settings` (pydantic-settings, `env_prefix="CINEROI_"`, `.env`) is where per-driver kill-switches live; `get_settings()` is the cached accessor. No `enable_*` flags exist yet.
- `database/migrations/` (Alembic `script_location = migrations`, `database/alembic.ini`) holds the migration lineage; `database/seed/generate_seed_sql.py` (standard-library only, `--check` idempotent mode) builds the model-version row (`guardrail_params` JSONB, already carrying `churn_model` and the viewing-hours/engagement sub-objects), each seeded title's `source_snapshot`, and the stored `financial_projections`. The five canonical demo titles and their verdicts: Aurora Protocol, Monsoon Lanes, Echoes of 2019 GREENLIGHT; The Ledger NEGOTIATE_HARD; Vintage Reruns Vol. 7 PASS.
- `model_versions.guardrail_params` is a JSONB column; `backend/app/engines/calibration.py` forks a new immutable model version copying `guardrail_params` forward, so any new driver sub-objects are carried forward unchanged. Model-version rows are immutable.
- Tests: backend pytest + Hypothesis property tests over pure `app/domain/*`; frontend Vitest + Testing Library. `CineROI_AI_Calculations_Reference.md` and `CineROI_AI_Architecture_And_Data_Flow.md` at repo root document the formula/threshold conventions and worked examples.

## Glossary

- **Advanced_Content_Eval_Drivers**: The feature described by this document: four industry drivers (Comps_Engine, Lineage_Decay, Momentum_Telemetry, Macro_Modifiers) that upgrade the Layer-A engagement/viewership modeling, each a pure domain module feeding `ValuationInputs`.
- **Comps_Engine (Driver A)**: The k-NN retrieval over `metadata_vectors.narrative_dna` that selects the five nearest historical comps within a budget band and matching asset type, and anchors viewing hours and churn mitigation to their medians.
- **Comp_Set**: The ordered set of `k = 5` nearest historical comps selected by the Comps_Engine for a query title.
- **Budget_Band**: The normalized-USD cost window `[0.65 * cost, 1.35 * cost]` (+/-35%) within which a candidate comp's own normalized-USD cost must fall to be eligible.
- **H_comps**: The median projected viewing hours of the Comp_Set, used as the empirical Bayesian prior replacing the generic constant intercept in the viewing-hours model.
- **C_comps**: The median churn-mitigation percentage of the Comp_Set, used as the comps anchor for the churn driver.
- **Comps_Dispersion**: The inter-quartile range (IQR) of the Comp_Set's viewing hours, a confidence/spread signal surfaced for the UI.
- **Lineage_Decay (Driver B)**: The franchise floor and additive churn retention credit derived from a title's franchise lineage and parent-title performance.
- **Franchise_Floor**: `parent_title_viewing_hours * (alpha_base_decay + beta_comp * parent_completion_rate)`, a lower bound on projected viewing hours for a franchise entry with parent data.
- **Momentum_Telemetry (Driver C)**: The stage-gated trailer/social/search momentum multiplier that is active only for produced titles and degrades to neutral when telemetry is stale or unavailable.
- **Production_Stage**: A new enum distinct from `DealStage`, with members CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY, describing how far a title has progressed toward release.
- **Momentum_Multiplier**: The combined multiplicative factor the Momentum_Telemetry driver applies to the full prediction, neutral at 1.00.
- **Macro_Modifiers (Driver D)**: The four multiplicative market modifiers (source-IP provenance, release-window halo, calendar seasonality, vernacular/dubbing reach).
- **Source_IP_Provenance**: The documented-domain multiplier keyed by IP origin: ORIGINAL_SCREENPLAY 1.00, BESTSELLER_BOOK 1.20, TRUE_CRIME_IP 1.25, WEBTOON_MANGA 1.15, PUBLIC_DOMAIN 0.95.
- **Release_Window_Halo**: The documented-domain marketing-halo multiplier keyed by theatrical-to-streaming window: DIRECT_TO_STREAMING 1.00, DAY_AND_DATE 1.10, THEATRICAL_30D 1.25, THEATRICAL_60D_PLUS 1.40.
- **Calendar_Seasonality (M_calendar)**: The seasonality multiplier for festive release windows (1.15-1.30) versus off-peak (0.85-0.90), clamped to [0.80, 1.35].
- **Vernacular_TAM_Factor**: The total-addressable-market multiplier from primary-language-only (1.00) up to four-plus vernacular audio tracks (up to 2.20), based on target-territory census splits.
- **Option_B_Conservation**: The hour-space attribution identity whereby the Comps anchor hours, every additive and multiplicative per-driver hour delta (including the Stage 2 `Hours_momentum` and the Stage 7 structural `Hours_franchise_floor`), and the `rounding_or_bounds_adjustment` residual sum exactly to the final predicted hours.
- **Residual_Sink**: The existing `rounding_or_bounds_adjustment` breakdown line item in `viewing_hours.py`, reused as the only entry that carries the rounding/clamp residual, so the Comps anchor contribution shown on the breakdown strictly equals `H_comps`.
- **Attribution_Order**: The fixed, normative order in which drivers are applied and attributed: Comps anchor -> additive beta_i -> Momentum_Multiplier (`ln(M_momentum)`, Stage 2) -> Release_Window_Halo -> Source_IP_Provenance -> Vernacular_TAM_Factor -> Calendar_Seasonality -> Franchise_Floor (a one-sided hour-space `max` clamp, Stage 7). Multiplicative Decimal deltas do not commute, so the order is part of the contract. (Amended by the erratum in Requirement 5 to include the Momentum_Multiplier term and the Franchise_Floor stage.)
- **Source_Tier**: The provenance of a resolved driver value: one of SUPPLIED, FITTED, or DETERMINISTIC_FALLBACK, in that strict precedence.
- **Driver_Flag**: A per-driver kill-switch in settings (`enable_comps`, `enable_lineage`, `enable_momentum`, `enable_macro_modifiers`), all defaulting to false.
- **STAGE_EXCLUDED**: The flag recorded when Momentum_Telemetry is gated off because a title has not reached a momentum-eligible Production_Stage; its multiplier is forced to 1.00 and never penalizes an unproduced pitch.
- **Telemetry_Staleness_Window**: The maximum age of a `market_telemetry_cache` reading (measured from `last_updated_at`) beyond which the feed is treated as stale and the Momentum_Multiplier degrades to 1.00; set to 14 days.
- **Illustrative_Coefficients**: Fixed, domain-grounded constants shipped as the drivers' DETERMINISTIC_FALLBACK parameters, explicitly not fitted to real data.

## Requirements

### Requirement 1: Comps_Engine vector-similarity anchor (Driver A)

**User Story:** As a data scientist, I want a title's projected viewing hours and churn mitigation anchored to the empirical median of its five nearest historical comps, so that the prediction starts from a data-grounded prior instead of a blunt platform-wide constant.

#### Acceptance Criteria

1. WHEN the Comps_Engine selects a Comp_Set for a query title, THE Comps_Engine SHALL rank candidate historical titles by cosine distance (`metadata_vectors.narrative_dna.cosine_distance`, pgvector `<=>`) ascending against the query title's 1536-dim `narrative_dna` embedding.
2. THE Comps_Engine SHALL restrict candidate comps to historical titles (`titles.is_historical = true`) whose own normalized-USD cost falls within the Budget_Band (`[0.65 * cost, 1.35 * cost]`, +/-35%) and whose `titles.asset_type` equals the query title's asset type, excluding the query title itself.
3. THE Comps_Engine SHALL select `k = 5` nearest eligible comps and SHALL compute H_comps as the median of the Comp_Set's projected viewing hours and C_comps as the median of the Comp_Set's churn-mitigation percentages, with all arithmetic in Decimal.
4. WHERE two or more candidate comps have equal cosine distance, THE Comps_Engine SHALL break the tie deterministically by ascending `title_id`, so the Comp_Set is reproducible.
5. IF fewer than `k = 5` eligible comps exist within the Budget_Band and asset type, THEN THE Comps_Engine SHALL shrink `k` to the number of eligible comps and compute the medians over that smaller set, and IF zero eligible comps exist THEN THE Comps_Engine SHALL fall back to the DETERMINISTIC_FALLBACK constant intercept of the viewing-hours model and record the comps Source_Tier as DETERMINISTIC_FALLBACK. (Shrinking `k` is chosen over widening the band because widening silently changes the comparability contract the buyer is shown, whereas a smaller honestly-labeled Comp_Set keeps every comp inside the stated +/-35% band and asset type.)
6. WHEN the Comps_Engine computes a Comp_Set of at least one comp, THE Comps_Engine SHALL supply H_comps as the empirical Bayesian prior that replaces the generic constant intercept in `backend/app/domain/viewing_hours.py`, such that the viewing-hours base hours `H0` derive from H_comps rather than from `exp(intercept) - 1`.
7. THE Comps_Engine SHALL output Comps_Dispersion as the inter-quartile range of the Comp_Set's viewing hours, surfaced for the UI as a confidence/spread signal, and SHALL be a pure Decimal computation.
8. THE Comps_Engine math (median, IQR, band membership, tie-break) SHALL be a pure domain function with no I/O; only the vector retrieval (the pgvector `<=>` query) SHALL run in Postgres, and the pure math SHALL be independently exercisable with in-memory vectors.

### Requirement 2: Lineage_Decay franchise floor and retention credit (Driver B)

**User Story:** As a content buyer, I want a sequel's valuation to reflect its franchise's built-in loyalty and its parent title's performance, so that a franchise entry is not scored as if it were a cold standalone launch.

#### Acceptance Criteria

1. THE Lineage_Decay driver SHALL read the franchise lineage inputs `is_franchise` (boolean), `franchise_order` (integer; 1 = original), `parent_title_viewing_hours` (Decimal, 90-day), and `parent_completion_rate` (Decimal in [0.00, 1.00]).
2. WHEN a title is a franchise entry with valid parent data, THE Lineage_Decay driver SHALL compute the Franchise_Floor as `parent_title_viewing_hours * (alpha_base_decay + beta_comp * parent_completion_rate)` and SHALL raise the title's projected viewing hours to at least the Franchise_Floor.
3. IF a title is a sequel (`is_franchise = true` and `franchise_order > 1`) but lacks parent data (`parent_title_viewing_hours` or `parent_completion_rate` absent or non-finite), THEN THE Lineage_Decay driver SHALL fall back to the title's genre baseline with an assumed parent completion rate of 0.70 and SHALL record the fallback as assumed.
4. THE Lineage_Decay driver SHALL compute an additive churn-mitigation credit `delta_C_franchise` within the inclusive bound [+0.15%, +0.45%] for built-in franchise loyalty, and SHALL clamp the credit to that bound.
5. WHEN a title is not a franchise entry (`is_franchise = false` or `franchise_order = 1`), THE Lineage_Decay driver SHALL apply no Franchise_Floor and a zero churn credit, leaving the base prediction unchanged.
6. THE Lineage_Decay driver SHALL be a pure Decimal domain function (no I/O) and SHALL leave its inputs unmodified.

### Requirement 3: Stage-gated Momentum_Telemetry with neutral fallbacks (Driver C)

**User Story:** As a content buyer, I want trailer, social, and search momentum to lift a produced title's valuation but never penalize an unproduced pitch or inject garbage from a dead feed, so that momentum is a trustworthy signal.

#### Acceptance Criteria

1. THE Momentum_Telemetry driver SHALL define a new Production_Stage enum with members CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, and ACQUISITION_READY, distinct from `app.domain.deal_stage.DealStage`, and SHALL NOT alter the existing deal-stage lifecycle or the `titles.deal_stage` column.
2. WHEN a title's Production_Stage is FESTIVAL_PREVIEW or ACQUISITION_READY, THE Momentum_Telemetry driver SHALL compute the Momentum_Multiplier from the Trailer Velocity Index `V_trailer` (first-72h organic views normalized by trailer marketing budget), the Organic Engagement Ratio `E_ratio` (`(Likes + 2 * Comments) / Views`), and the Search Momentum Velocity `S_velocity` (intent velocity versus genre baseline, clamped to [0.50, 2.00]).
3. WHEN a title's Production_Stage is CONCEPT_SCRIPT or IN_PRODUCTION, THE Momentum_Telemetry driver SHALL force the Momentum_Multiplier to 1.00 and SHALL set the STAGE_EXCLUDED flag, so an unproduced or in-production title is never penalized by absent momentum.
4. WHILE the governing `market_telemetry_cache` reading is stale (its `last_updated_at` is older than the Telemetry_Staleness_Window of 14 days) or unavailable (`source_available = false`), THE Momentum_Telemetry driver SHALL degrade the Momentum_Multiplier to 1.00 and SHALL record the degradation reason, rather than injecting a value from a stale or dead feed.
5. THE Momentum_Telemetry driver SHALL clamp the composed Momentum_Multiplier to a documented inclusive bound and SHALL never let any momentum metric reduce the prediction below the non-momentum baseline (the multiplier is bounded at or above 1.00 when active).
6. THE Momentum_Telemetry driver math SHALL be a pure Decimal domain function; the staleness decision SHALL be computed from the reading's `last_updated_at` and `source_available` passed in as inputs, not queried inside the pure function.

### Requirement 4: Macro_Modifiers with documented domains and clamps (Driver D)

**User Story:** As a content strategist, I want source-IP provenance, theatrical windowing, seasonality, and vernacular reach to multiply a title's projected demand within documented bounds, so that market context is reflected without unbounded speculation.

#### Acceptance Criteria

1. THE Macro_Modifiers driver SHALL apply a Source_IP_Provenance multiplier from the documented domain: ORIGINAL_SCREENPLAY 1.00, BESTSELLER_BOOK 1.20, TRUE_CRIME_IP 1.25, WEBTOON_MANGA 1.15, PUBLIC_DOMAIN 0.95, and SHALL apply 1.00 for an absent or unrecognized provenance, recording it as assumed.
2. THE Macro_Modifiers driver SHALL apply a Release_Window_Halo multiplier from the documented domain: DIRECT_TO_STREAMING 1.00, DAY_AND_DATE 1.10, THEATRICAL_30D 1.25, THEATRICAL_60D_PLUS 1.40, as a new concept that SHALL NOT redefine `app.domain.windowing.WindowType` (licensing-window exclusivity).
3. THE Macro_Modifiers driver SHALL apply a Calendar_Seasonality multiplier in the festive-window range 1.15-1.30 (Diwali / Christmas / Eid / summer) or the off-peak range 0.85-0.90, clamped to the inclusive bound [0.80, 1.35].
4. THE Macro_Modifiers driver SHALL apply a Vernacular_TAM_Factor from 1.00 (primary-language-only) up to 2.20 (four-plus vernacular audio tracks), derived from target-territory census splits, and SHALL clamp the factor to its documented inclusive bound.
5. THE Macro_Modifiers driver SHALL apply each multiplier within its stated clamp and, for a positive/premium modifier, SHALL never reduce the prediction below its pre-modifier value (monotone and bounded per modifier).
6. THE Macro_Modifiers driver SHALL be a pure Decimal domain function (no I/O) and SHALL leave its inputs unmodified.

### Requirement 5: Option-B conservation, monotonicity, and the property-test suite

**User Story:** As a maintainer, I want the combined drivers to conserve the hour-space breakdown exactly, stay monotone and bounded, and be covered by property tests, so that attribution is auditable and regressions are caught.

#### Acceptance Criteria

1. THE combined model SHALL compute the log-space prediction `y_log = ln(1 + H_comps) + sum_i(beta_i * x_i) + ln(M_momentum) + ln(M_window) + ln(M_ip) + ln(M_vernacular) + ln(M_calendar)` and the hour-space prediction `H_hat = exp(y_log) - 1`, all under the existing fixed Decimal context. The `ln(M_momentum)` term (Stage 2, Driver C) is neutral (`M_momentum = 1.00`, a 0-hour line) whenever Driver C is flag-off, STAGE_EXCLUDED, stale, or unavailable, so the flag-off path is byte-identical to the momentum-free prediction.
2. THE hour-space breakdown SHALL conserve exactly: `Hours_comps + sum_i(Hours_i) + Hours_momentum + Hours_window + Hours_ip + Hours_vernacular + Hours_calendar + Hours_franchise_floor + rounding_or_bounds_adjustment == H_hat` after quantization, with the `rounding_or_bounds_adjustment` Residual_Sink carrying only the rounding/clamp residual. `Hours_franchise_floor` (the Stage 7 one-sided `max` lift, Driver B) is attributed to its own line and is a structural offset that is never routed through the Residual_Sink; `Hours_momentum` is 0 when Driver C is neutral.
3. THE combined model SHALL NOT dump the rounding residual into the Comps anchor; the Comps anchor contribution shown on the breakdown SHALL strictly equal H_comps (the empirical median of the comps), keeping it 100% auditable.
4. THE combined model SHALL apply and attribute the drivers in the fixed Attribution_Order (Comps anchor -> additive beta_i -> Momentum_Multiplier (`ln(M_momentum)`, Stage 2) -> Release_Window_Halo -> Source_IP_Provenance -> Vernacular_TAM_Factor -> Calendar_Seasonality -> Franchise_Floor (Stage 7, a one-sided hour-space `max` clamp applied after the fully-assembled multiplicative hours)), because the multiplicative Decimal hour-deltas do not commute and the order is therefore normative.

> **Erratum (R5 normative amendment).** The original R5.1 `y_log`, R5.2 conservation identity, R5.4 Attribution_Order, and the glossary Attribution_Order omitted the Driver-C `ln(M_momentum)` term and the Driver-B `Franchise_Floor` stage. Because R3 requires a Momentum_Multiplier that scales the full prediction and R2.2 requires a franchise floor on the fully-assembled hours, this erratum amends R5.1/R5.2/R5.4 and the glossary to the seven-term log-space order with `ln(M_momentum)` as Stage 2 and the `Franchise_Floor` as the Stage 7 hour-space `max` clamp, with matching `Hours_momentum` and `Hours_franchise_floor` lines in the conservation identity. The design document is aligned with R5.x as amended; the two documents state the same normative conservation identity.
5. THE combined model SHALL be strictly monotone and bounded: every additive beta_i SHALL be non-negative so positive buzz / higher engagement / premium IP never decreases viewing hours or churn retention, and every multiplier SHALL be clamped to its stated empirical bound.
6. THE combined model SHALL use only the Python standard library `math`/`decimal` for its arithmetic (zero external runtime math dependency); vector similarity SHALL run in Postgres via pgvector, and the pure-Python vector math SHALL be exercisable in unit tests.
7. THE backend test suite SHALL include Hypothesis property tests asserting: the conservation identity to exact Decimal, additive-weight monotonicity (`beta_i >= 0`), multiplier boundedness within each stated clamp, determinism and the equal-distance tie-break, and STAGE_EXCLUDED neutrality (a CONCEPT_SCRIPT / IN_PRODUCTION title yields a 1.00 Momentum_Multiplier that leaves the prediction unchanged).

### Requirement 6: Explanation JSON schema extensions and UI diff representation

**User Story:** As an executive reviewing a title, I want each driver's contribution and provenance shown in the explanation and the breakdown card, so that I can see and defend how every driver moved the number.

#### Acceptance Criteria

1. THE persisted `financial_projections.explanation` JSON (passed through `ValuationScorecardResponse.explanation`) SHALL carry, per driver, a provenance object `{source_tier, value, bounds, inputs_used}` where `source_tier` is one of SUPPLIED / FITTED / DETERMINISTIC_FALLBACK.
2. THE explanation extension SHALL include, for the Comps_Engine, H_comps, C_comps, Comps_Dispersion, the realized `k`, and the comp title identifiers, extending the existing comps surface (`ComparableTitlesResponse` / `TitleCompOut`) rather than replacing it.
3. THE viewing-hours breakdown SHALL add one line item per active driver (Comps anchor, Release_Window_Halo, Source_IP_Provenance, Vernacular_TAM_Factor, Calendar_Seasonality) while preserving the single `rounding_or_bounds_adjustment` Residual_Sink entry so the breakdown still conserves.
4. WHEN a driver changes a breakdown line item relative to the baseline, THE UI SHALL render the changed line item as a signed hour delta (value before, value after, and the difference) using ASCII-only text, consistent with the existing defensive numeric coercion for string-encoded Decimals.
5. THE explanation SHALL render without error when read from a stored valuation produced before this feature, treating the missing driver fields as absent (backward compatible, additive-only schema change).

### Requirement 7: Per-driver feature-flag kill-switches and incremental rollout

**User Story:** As a platform owner, I want every driver behind a kill-switch that defaults off, so that I can roll the drivers out one at a time and guarantee the demo and the existing tests are untouched until I opt in.

#### Acceptance Criteria

1. THE settings (`backend/app/core/config.py`, env prefix `CINEROI_`) SHALL define four per-driver Driver_Flags: `enable_comps`, `enable_lineage`, `enable_momentum`, and `enable_macro_modifiers`, each a boolean defaulting to false.
2. WHILE a Driver_Flag is false, THE corresponding driver SHALL be fully inert: it SHALL NOT alter `ValuationInputs`, the breakdown, the explanation, or the verdict for any title.
3. WHILE all four Driver_Flags are false (the default), THE five seeded demo titles SHALL produce byte-identical verdicts and explanations to the pre-feature baseline, and the existing backend and frontend test suites SHALL pass unchanged.
4. THE Driver_Flags SHALL be independent, so enabling one driver SHALL NOT require or implicitly enable another, supporting incremental rollout.
5. THE `SUPPLIED` > `FITTED` > `DETERMINISTIC_FALLBACK` precedence SHALL hold regardless of flag state: a valid supplied input SHALL always override any enabled driver.

### Requirement 8: Alembic migration and seed backfill with explicit neutral defaults

**User Story:** As a database owner, I want every new driver column created with an explicit neutral default and the seed backfilled, so that demo byte-identity is guaranteed by the data, not by chance.

#### Acceptance Criteria

1. THE migration SHALL be added under `database/migrations/` following the existing Alembic lineage and SHALL create every new driver column with an explicit neutral server-side default.
2. THE migration SHALL add, on `titles` (or a driver-scoped child table, decided in design), the lineage columns `is_franchise` (boolean, default false), `franchise_order` (integer, default 1), `parent_title_viewing_hours` (`Numeric(16,2)`, nullable, default null), and `parent_completion_rate` (`Numeric(3,2)`, nullable, default null).
3. THE migration SHALL add a `production_stage` column (text, default `CONCEPT_SCRIPT`) with a CHECK constraint over {CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY}, separate from `deal_stage`.
4. THE migration SHALL add the macro-modifier descriptor columns `source_ip_provenance` (text, default `ORIGINAL_SCREENPLAY`), `release_window` (text, default `DIRECT_TO_STREAMING`), and the inputs needed for Calendar_Seasonality and Vernacular_TAM_Factor (release month/window and vernacular audio-track count), each with an explicit neutral default that yields a 1.00 multiplier.
5. THE migration SHALL store the drivers' Illustrative_Coefficients as plain JSON sub-objects under the existing `model_versions.guardrail_params` JSONB column (keys `comps`, `lineage`, `momentum`, `macro_modifiers`), requiring no new coefficient table, so calibration forks carry them forward unchanged.
6. THE regenerated seed (`database/seed/generate_seed_sql.py`) SHALL backfill the new columns for the five demo titles with their neutral defaults so that, with all Driver_Flags false, a live recompute reproduces each seeded `financial_projections` row exactly, and the generator's `--check` mode SHALL report the committed seed SQL as in sync.

### Requirement 9: Calibration-tier treatment (DETERMINISTIC_FALLBACK now, FITTED deferred)

**User Story:** As a model owner, I want the new coefficients shipped as fixed illustrative constants and kept out of the calibrator, so that this feature lands safely without entangling the constrained-optimization solver.

#### Acceptance Criteria

1. THE drivers' coefficients SHALL ship as DETERMINISTIC_FALLBACK Illustrative_Coefficients (fixed, domain-grounded constants), labeled as such wherever surfaced, and SHALL NOT be fitted to real outcome data in this feature.
2. THE drivers SHALL NOT be entangled with `backend/app/engines/calibration.py` or the constrained-optimization path; calibration SHALL continue to fork a model version copying `guardrail_params` (including the new driver sub-objects) forward unchanged.
3. WHEN a driver's `guardrail_params` sub-object is absent or structurally invalid, THE driver SHALL fall back to its built-in default coefficients and record the params source as DETERMINISTIC_FALLBACK, mirroring the full-fallback parse contract of the existing domain models.
4. THE documentation SHALL carry a NON-NORMATIVE future-work note that making the additive `beta_i` FITTED under `beta_i >= 0` non-negativity constraints is a deferred follow-up requirement, out of scope here.

### Requirement 10: Comps confidence output and telemetry staleness degradation rules

**User Story:** As an executive, I want to see how tight a title's comp set is and to know when momentum is based on stale data, so that I can weigh the confidence of the modeled number.

#### Acceptance Criteria

1. THE Comps_Engine SHALL surface Comps_Dispersion (the IQR of the Comp_Set viewing hours) and the realized comp count `k` on the explanation and the comps UI surface, so a wide dispersion or a small `k` reads as lower confidence.
2. THE Telemetry_Staleness_Window SHALL be 14 days, measured from the governing `market_telemetry_cache` reading's `last_updated_at`.
3. WHEN the governing telemetry reading's age exceeds the Telemetry_Staleness_Window, THE Momentum_Telemetry driver SHALL degrade the Momentum_Multiplier to 1.00 and SHALL label the momentum contribution as stale (not as a real reading).
4. WHEN the governing telemetry reading has `source_available = false`, THE Momentum_Telemetry driver SHALL degrade the Momentum_Multiplier to 1.00 and SHALL label the momentum contribution as unavailable, distinct from the stale label.
5. THE explanation SHALL record the staleness/availability basis (the reading age and `source_available`) used for the degradation decision, so the neutral multiplier is auditable.

## Out of Scope

- Implementation code, applied migrations, executed tests, or any change to application/domain/ORM/seed files; this feature is spec-documents-only (this step produces only `requirements.md`).
- Fitting the new additive coefficients from data (FITTED tier) or any change to `backend/app/engines/calibration.py`'s constrained optimization; explicitly deferred (R9.4).
- Changing the four guardrail thresholds (CPVH ceiling, LTV-to-Cost floor, the 1.5 churn hurdle, payback target), the recommendation logic, the non-correctable churn classification, or the governance sign-off gates.
- Redefining `app.domain.deal_stage.DealStage` or `app.domain.windowing.WindowType`; the Production_Stage and Release_Window_Halo concepts are new and additive.
- Live external fetching of trailer/social/search telemetry or source-IP/census data at valuation time; the drivers consume already-cached/already-supplied inputs (consistent with how `churn.py` receives `Telemetry_Heat` rather than querying for it).
- Any change to the seeded demo verdicts while the Driver_Flags remain at their default-false state.

## Assumptions

- The production-readiness stages (CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY) are modeled as a brand-new `Production_Stage` enum because the existing `DealStage` is a human acquisition pipeline with entirely different members; the brief's instruction to "reuse/extend existing deal_stage.py" is interpreted as "do not disturb deal_stage; add a sibling enum," since reusing it would conflate two orthogonal lifecycles.
- The theatrical-to-streaming `Release_Window_Halo` is a new concept rather than an extension of `windowing.py`, because `windowing.py`'s `WindowType` models licensing exclusivity (EXCLUSIVE / NON_EXCLUSIVE), a different axis.
- The Budget_Band is computed in normalized USD (via the existing currency/FX path) so that comps across native currencies are comparable; "+/-35% normalized USD cost" is read as the inclusive band `[0.65 * cost, 1.35 * cost]`.
- `k = 5` is the target comp count; the `<k` fallback shrinks `k` rather than widening the band (R1.5), and the existing `rank_similar_titles` default `limit=3` is specific to the display surface and is not the comps-anchor `k`.
- The Telemetry_Staleness_Window of 14 days is a concrete illustrative choice aligned with the 90-day `market_telemetry_cache` retention; it is a design-adjustable constant stored with the momentum coefficients.
- New lineage/macro columns are assumed to live on `titles` for the demo's single-version-per-title shape; the design may instead scope them to a child table, but either way every column carries an explicit neutral default (R8).
