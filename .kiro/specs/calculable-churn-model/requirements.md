# Requirements Document

## Introduction

CineROI AI (GreenlightIQ) is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend) whose Guardrails_Engine evaluates each candidate title against four quantitative guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon) and produces a greenlight recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured explanation.

The churn-mitigation guardrail (cineroi-ai R6) compares a title's modeled monthly churn-reduction percentage against a fixed 1.5 percent hurdle; a breach is non-correctable and forces PASS. Today that input is effectively hard-coded: it is a constant literal in the seed data, a value read verbatim from the title version source snapshot, or, in the Asset Studio quick-evaluate path, the placeholder formula `1.0 + (pedigree / 10) * 2.0`. None of these is explainable or auditable, and the number is the one guardrail input a reviewer cannot interrogate.

This feature, the **Churn_Mitigation_Model**, replaces the hard-coded input with a transparent, deterministic, additive, versioned model. It computes the churn-reduction percentage from a title's observable features (asset type, talent pedigree, production scale, exclusivity, and market telemetry), explains every point of the result as a per-feature contribution, lets an explicitly supplied value override the calculation, flags values near the 1.5 percent hurdle, and feeds the backtest so predictions can be scored against actual outcomes.

The scope is strictly limited to **how the churn-reduction percentage is produced, explained, overridden, flagged, and backtested**. This feature MUST NOT change the 1.5 percent hurdle, the other three guardrails, the recommendation logic, or the existing talent/narrative weight calibration. The seeded demo verdicts MUST remain unchanged.

### Grounding (verified against the current codebase)

- `backend/app/engines/guardrails.py`: `ValuationInputs` is a frozen dataclass whose `churn_reduction_pct: Decimal` is always set and is supplied by an injected `ValuationInputProvider`. `_compute(...)` builds the churn check via `_churn_check(inputs.churn_reduction_pct)`; `CHURN_MITIGATION_THRESHOLD = Decimal("1.5")`; a churn breach is classified non-correctable (`correctable = False`), which forces PASS. `_jsonable_explanation(...)` persists only `checks`, `dominant_factor`, and `unclassifiable`. The engine constructor takes title / projection / exchange-rate / license-term / telemetry repositories, a model-versioning engine, an audit service, and an input provider; it has **no** metadata-vector repository today. `evaluate_scenario(...)` (what-if) scales `churn_reduction_pct` via `app/domain/sensitivity.py` `scale_inputs(...)`.
- `backend/app/api/deps.py`: `SnapshotValuationInputProvider.get_inputs(...)` reads the active title version `source_snapshot` and coerces `churn_reduction_pct` to a Decimal, defaulting to 0 when absent.
- `backend/app/api/quick_evaluate.py`: `_modeled_inputs(...)` writes `churn_reduction_pct = round(1.0 + (pedigree / 10) * 2.0, 2)` into the snapshot together with `talent_pedigree_score` and `is_exclusive`; it creates **no** metadata-vector or license-term rows. `_metadata_profile(...)` separately derives `production_scale = min(10, (pedigree + min(10, len(synopsis) / 25)) / 2)` for the radar only. Pedigree defaults to 5 when blank.
- Data available per title: `titles.asset_type` (one of ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, CO_PRODUCTION); `metadata_vectors.talent_pedigree_score` and `production_scale_metric` (NUMERIC(4,2), range 0-10, `extraction_status` in {SUCCESS, FAILED}); `license_terms.is_exclusive` (boolean); `market_telemetry_cache.social_sentiment_index` (NUMERIC(6,2), keyed by `genre_tag` + `territory`, seeded in the 0-1 range and shown on the Market_Telemetry_Card as "Audience buzz index (0-1)").
- `model_versions.guardrail_params` is a JSONB column already carrying `cpvh_ceiling_*`, `ltv_to_cost_min`, `churn_mitigation_min_pct`, and `payback_target_months`. `backend/app/engines/calibration.py` forks a new model version with `guardrail_params=dict(active.guardrail_params)`, so any `churn_model` sub-object is already copied forward on calibration. Model-version rows are immutable.
- `database/seed/generate_seed_sql.py` (standard-library only, with a `--check` mode) builds the `model_versions` row (`guardrail_params`), each title's `source_snapshot`, and the stored `financial_projections`. The churn literals live in its `TITLES` tuple. There is no `schema.sql` that holds model-version data.
- `backend/app/engines/backtesting.py`: `PREDICTED_METRIC_FIELDS` maps the metric name `"churn_reduction"` to the `financial_projections.churn_reduction_pct` column; `POST /api/v1/backtest/audit` accepts `metrics: [{metric_name, actual_value}]`; MAPE excludes zero-actual metrics. `frontend/components/backtest/ground-truth-form.tsx` audits only CPVH and LTV-to-Cost; `variance-chart.tsx` has display labels for `cpvh` and `ltv_to_cost` only.
- Frontend churn surfaces: `frontend/app/titles/[id]/_components/financial-accordion.tsx` (the "Churn mitigation impact" section), `frontend/app/studio/_components/valuation-report.tsx`, and shared types in `frontend/lib/types.ts`. Decimal values are serialized as JSON strings over the wire; the frontend coerces defensively (`num()` / `toNumber()`).
- Tests: backend uses pytest + Hypothesis (property tests over pure `app/domain/*` functions) under `backend/tests/{domain,engines,api}`; the frontend uses Vitest + Testing Library.
- Path corrections versus common assumptions: the quick-evaluate router is `app/api/quick_evaluate.py` (not `routers/titles.py`); the accordion file is `financial-accordion.tsx` (not `FinancialAccordion.tsx`); domain tests belong under `backend/tests/domain/`.
- Seeded features per title (pedigree / production scale / exclusive / asset type / mean sentiment index scaled to 0-100): Aurora Protocol 8.5 / 9.0 / yes / ORIGINAL_SERIES / 65; Echoes of 2019 7.8 / 7.0 / yes / ORIGINAL_SERIES / 59; Monsoon Lanes 7.2 / 6.5 / no / CO_PRODUCTION / 63; The Ledger 6.0 / 5.5 / yes / ORIGINAL_FILM / 63; Vintage Reruns Vol. 7 4.0 / 3.5 / no / LICENSED_LIBRARY / 53.5. Seeded verdicts: Aurora, Echoes, and Monsoon GREENLIGHT; The Ledger NEGOTIATE_HARD (CPVH, LTV 2.9, and payback 15 breached, all correctable); Vintage Reruns PASS (churn 0.9 below 1.5, non-correctable). Current stored churn literals: 2.10 / 2.00 / 1.80 / 1.60 / 0.90.

## Glossary

- **Churn_Mitigation_Model**: The feature described by this document: a transparent, additive, versioned model that produces the modeled monthly churn-reduction percentage from a title's features, with a per-feature explanation, a supplied-value override, and a borderline-sensitivity flag.
- **Guardrails_Engine**: The existing financial engine (`backend/app/engines/guardrails.py`) that evaluates the four guardrails and emits a `ValuationResult` containing the recommendation status and `Explanation`.
- **Churn_Domain_Module**: The new pure domain module (`backend/app/domain/churn.py`) that holds the model parameters, the additive calculation, and the supplied-value resolution. Pure: no I/O, no database access, no global state; Decimal precision throughout.
- **Churn_Model_Params**: The parameter set for the model: an intercept, a per-asset-type offset table, a per-point pedigree weight, a per-point production-scale weight, an exclusivity lift, a per-point telemetry weight, and the output clamp bounds. All feature weights are non-negative.
- **Churn_Result**: The output of the calculation: the resolved churn-reduction percentage, the per-feature breakdown, the resolution method, the borderline flag, and supporting metadata (missing features, params source, bounds adjustment).
- **Churn_Method**: How the churn-reduction percentage was obtained, one of {SUPPLIED, CALCULATED}.
- **Telemetry_Heat**: The telemetry feature value for a title: the mean, over the title's target territories that have a cached reading for the title's genre, of `social_sentiment_index`, multiplied by 100 (converting the stored 0-1 index to a 0-100 scale), rounded to 2 decimal places. Territories with no reading are excluded from the mean; a title with no readings at all has a missing Telemetry_Heat.
- **Churn_Breakdown**: The ordered set of per-feature contributions, in percentage points, that sum (with any Bounds_Adjustment) to the calculated churn-reduction percentage: Base Platform Rate (the intercept), Asset Cadence (the asset-type offset), Talent Pedigree Contribution, Production Scale Contribution, Exclusivity Lift, and Market Telemetry Heat.
- **Bounds_Adjustment**: The signed difference between the clamped and unclamped calculated value, included as a breakdown entry when clamping changes the value so the breakdown always conserves.
- **Borderline_Sensitivity**: The condition that a churn-reduction percentage (calculated or supplied) lies within +/- 0.05 of the 1.5 percent hurdle, i.e. in the inclusive band [1.45, 1.55].
- **Churn_Mitigation_Threshold**: The fixed 1.5 percent hurdle the churn guardrail compares against (cineroi-ai R6.2). This feature does not change it.
- **Model_Version_Params**: The churn parameters stored under `model_versions.guardrail_params["churn_model"]`, versioned with the active model version and carried forward unchanged on calibration forks.
- **Supplied_Value**: An explicitly provided `churn_reduction_pct` in the title deal snapshot or the quick-evaluate payload that, when present and valid, overrides the calculation.
- **Illustrative_Coefficients**: The model parameters, labeled as tuned to the five demo titles and not fitted to real subscriber-outcome data.

## Requirements

### Requirement 1: Additive churn calculation in the domain

**User Story:** As a data scientist, I want the churn-reduction percentage computed by a pure, deterministic, additive function, so that every point of the result is traceable to a specific feature and the math is independently testable.

#### Acceptance Criteria

1. THE Churn_Domain_Module SHALL be a pure module with no I/O, no database access, and no global mutable state, and SHALL perform all arithmetic with Decimal precision.
2. THE Churn_Domain_Module SHALL compute the calculated churn-reduction percentage as the additive sum: intercept + asset-type offset + (pedigree weight x pedigree score) + (production-scale weight x production-scale score) + (exclusivity lift if the title is exclusive, else 0) + (telemetry weight x Telemetry_Heat).
3. THE Churn_Domain_Module SHALL require every feature weight (asset-type offsets, pedigree weight, production-scale weight, exclusivity lift, telemetry weight) to be non-negative.
4. WHEN the same feature inputs and the same Churn_Model_Params are supplied, THE Churn_Domain_Module SHALL return an identical Churn_Result (determinism).
5. WHEN the pedigree score, the production-scale score, or the Telemetry_Heat increases while all other inputs are held constant, THE Churn_Domain_Module SHALL return a calculated churn-reduction percentage that is greater than or equal to the previous value (monotonicity in each feature).
6. THE Churn_Domain_Module SHALL clamp each numeric feature to its valid domain before use: pedigree and production-scale scores to [0, 10] and Telemetry_Heat to [0, 100].
7. THE Churn_Domain_Module SHALL clamp the calculated churn-reduction percentage to the inclusive output bounds [0.10, 5.00] and round it to 2 decimal places using half-up rounding.
8. WHEN clamping changes the calculated value, THE Churn_Domain_Module SHALL include a Bounds_Adjustment entry in the Churn_Breakdown equal to the signed difference, so that the sum of the Churn_Breakdown entries equals the final calculated churn-reduction percentage.
9. THE Churn_Domain_Module SHALL return, as part of the Churn_Result, the per-feature Churn_Breakdown (one entry per feature named Base Platform Rate, Asset Cadence, Talent Pedigree Contribution, Production Scale Contribution, Exclusivity Lift, and Market Telemetry Heat), the list of features that were missing, and the Borderline_Sensitivity flag.

### Requirement 2: Missing and invalid feature handling

**User Story:** As a reviewer, I want a title with incomplete data to still produce an honest, conservative churn estimate, so that the valuation never fails for want of one feature and the gaps are visible.

#### Acceptance Criteria

1. WHEN a numeric feature (pedigree, production scale, or Telemetry_Heat) is absent, null, non-numeric, or non-finite, THE Churn_Domain_Module SHALL treat that feature's contribution as 0 and SHALL list the feature as missing in the Churn_Result.
2. WHEN exclusivity is unknown or absent, THE Churn_Domain_Module SHALL treat the title as not exclusive (zero Exclusivity Lift).
3. WHEN the asset type is absent or not one of the four known asset types, THE Churn_Domain_Module SHALL apply a zero asset-type offset and SHALL list the asset type as missing in the Churn_Result.
4. WHEN one or more features are missing, THE Churn_Domain_Module SHALL still return a CALCULATED Churn_Result (missing features reduce the contribution but do not change the method to SUPPLIED).

### Requirement 3: Versioned, illustrative model parameters

**User Story:** As a model owner, I want the churn coefficients stored with the active model version and clearly labeled as illustrative, so that valuations are reproducible and no one mistakes the demo coefficients for a fitted model.

#### Acceptance Criteria

1. THE Guardrails_Engine SHALL read the Churn_Model_Params from the active model version's `guardrail_params["churn_model"]`.
2. IF `guardrail_params["churn_model"]` is absent or structurally invalid, THEN THE Guardrails_Engine SHALL fall back to the Churn_Domain_Module built-in default parameters and SHALL record in the explanation that defaults were used.
3. THE Guardrails_Engine SHALL record in the churn explanation the params source (model version or defaults) and the model_version_id in effect.
4. WHEN a model version is forked by calibration, THE system SHALL carry the `churn_model` parameters forward into the new version unchanged (no churn-coefficient re-fitting occurs during calibration).
5. THE stored Model_Version_Params and the documentation SHALL label the churn coefficients as Illustrative_Coefficients, tuned to the five demo titles and not fitted to real subscriber-outcome data.
6. THE Churn_Model_Params SHALL be stored as plain JSON values within the JSONB `guardrail_params` column, requiring no database migration.

### Requirement 4: Supplied value wins

**User Story:** As a content buyer, I want to type a known churn-reduction number and have the system use it exactly, so that a negotiated or externally modeled figure is never silently overwritten by the model.

#### Acceptance Criteria

1. WHEN a finite numeric `churn_reduction_pct` is explicitly supplied for a title (in the title deal snapshot or the quick-evaluate payload), THE system SHALL use that value exactly as given, without clamping or re-rounding, and SHALL set Churn_Method to SUPPLIED.
2. WHEN no supplied value is present, THE system SHALL compute the churn-reduction percentage from the model and SHALL set Churn_Method to CALCULATED.
3. THE system SHALL treat a blank, null, non-numeric, or non-finite supplied churn value as "not supplied" and SHALL fall through to CALCULATED.
4. THE system SHALL treat a supplied value of 0 as supplied (SUPPLIED with value 0), not as missing.
5. THE quick-evaluate request SHALL accept an optional `churn_reduction_pct` field constrained to the inclusive range [0, 100]; when present and valid it is SUPPLIED, otherwise the Asset Studio path is CALCULATED.
6. WHEN an existing title version snapshot already contains a `churn_reduction_pct` value (e.g. a database seeded before this feature), THE system SHALL continue to report that title as SUPPLIED until the title is reseeded or re-ingested without a supplied churn value.

### Requirement 5: Borderline sensitivity flag

**User Story:** As an executive, I want a clear warning when a churn number sits right on the 1.5 percent line, so that I know the greenlight-versus-pass outcome hinges on a fragile input.

#### Acceptance Criteria

1. WHEN the resolved churn-reduction percentage (whether CALCULATED or SUPPLIED) lies within the inclusive band [1.45, 1.55], THE system SHALL set the Borderline_Sensitivity flag to true.
2. WHEN the resolved churn-reduction percentage lies outside [1.45, 1.55], THE system SHALL set the Borderline_Sensitivity flag to false.
3. THE Borderline_Sensitivity flag SHALL NOT change the guardrail's pass/breach result, the dominant factor, or the recommendation status.
4. WHEN the Borderline_Sensitivity flag is true, THE system SHALL make available an explanatory message with the wording "Borderline Sensitivity: within 0.05% of the 1.50% hurdle".

### Requirement 6: Feature resolution and telemetry heat

**User Story:** As an engineer, I want deterministic rules for where each feature comes from, so that the Asset Studio instant view and a persisted title compute the same number from the same facts.

#### Acceptance Criteria

1. THE Guardrails_Engine SHALL resolve the pedigree, production-scale, and exclusivity features from the title's explicit snapshot facts first (talent_pedigree_score, production_scale_metric, is_exclusive) and, when a fact is absent, from the title's latest SUCCESS metadata vector (pedigree, production scale) and the title's license terms (exclusivity).
2. THE Guardrails_Engine SHALL resolve the asset type from the title row.
3. THE Guardrails_Engine SHALL compute Telemetry_Heat as the mean, over the title's target territories that have a cached `social_sentiment_index` for the title's genre, of that index multiplied by 100, rounded to 2 decimal places half-up.
4. WHEN a target territory has no cached reading for the genre, THE Guardrails_Engine SHALL exclude that territory from the Telemetry_Heat mean.
5. WHEN no target territory has a cached reading for the genre, THE Guardrails_Engine SHALL treat Telemetry_Heat as missing (contributing 0 per Requirement 2).

### Requirement 7: Guardrails_Engine integration and persisted explanation

**User Story:** As a developer, I want the resolved churn number and its explanation threaded through the engine and persisted, so that every API surface and the audit log can show how churn was produced.

#### Acceptance Criteria

1. THE Guardrails_Engine SHALL use the resolved churn-reduction percentage (SUPPLIED or CALCULATED) as the input to the existing churn-mitigation guardrail check and SHALL leave the 1.5 percent hurdle and the non-correctable classification unchanged.
2. THE Guardrails_Engine SHALL embed, in the persisted `financial_projections.explanation` JSON, the Churn_Method, the Borderline_Sensitivity flag, and (when CALCULATED) the Churn_Breakdown, the missing features, the params source, and the model_version_id in effect.
3. THE `POST /api/v1/valuation/calculate` and `GET /api/v1/valuation/{title_id}` responses SHALL expose the churn explanation fields when present.
4. THE valuation audit entry SHALL record the Churn_Method.
5. WHEN the what-if endpoint applies a churn multiplier other than 1, THE response SHALL present the scaled churn value without a Churn_Breakdown that disagrees with it (the breakdown is omitted for a scaled scenario).
6. WHEN the what-if endpoint applies a churn multiplier other than 1, THE response SHALL re-evaluate the Borderline_Sensitivity flag against the scaled churn value, so the flag reflects whether the scaled value lies within [1.45, 1.55].
7. THE system SHALL render a stored explanation that lacks the new churn fields (produced before this feature) without error, treating the missing fields as absent.
8. THE existing ValuationInputProvider fakes that supply a Decimal churn value SHALL continue to work, treated as a Supplied_Value.

### Requirement 8: Asset Studio uses the same calculation

**User Story:** As a buyer using the Asset Studio form, I want the instant scorecard's churn number to match what the full engine would compute, so that the quick view and the saved record never disagree.

#### Acceptance Criteria

1. THE quick-evaluate path SHALL obtain its churn-reduction percentage from the same resolution logic as the Guardrails_Engine (Supplied_Value wins, else the additive model), and SHALL NOT use the former placeholder formula `1.0 + (pedigree / 10) * 2.0`.
2. THE quick-evaluate path SHALL derive the production-scale feature it feeds to the model from the same value shown as production scale on the metadata radar, so the explained input equals the displayed input.
3. WHEN the Asset Studio form submits no explicit churn value, THE quick-evaluate response SHALL report Churn_Method CALCULATED and SHALL include the Churn_Breakdown and Borderline_Sensitivity flag.

### Requirement 9: Seed regeneration and verdict stability

**User Story:** As a demo owner, I want the regenerated seed to produce churn by the model while keeping every demo verdict exactly as it is, so that the showcase stays coherent and the stored data matches a live recompute.

#### Acceptance Criteria

1. THE regenerated seed SHALL NOT place a `churn_reduction_pct` value in any seeded title's source snapshot, so that every seeded title resolves as CALCULATED.
2. THE regenerated seed SHALL embed the calibrated Churn_Model_Params under `guardrail_params["churn_model"]` on the active model version.
3. THE calibrated parameters SHALL produce, for the five seeded titles, churn-reduction percentages that preserve the current verdicts: Aurora Protocol, Echoes of 2019, and Monsoon Lanes GREENLIGHT; The Ledger NEGOTIATE_HARD; Vintage Reruns Vol. 7 PASS (3 GREENLIGHT, 1 NEGOTIATE_HARD, 1 PASS).
4. THE calibrated parameters SHALL produce seeded churn values within these tolerances: Aurora within 0.05 of 2.10; Echoes within 0.05 of 2.00; Monsoon within 0.05 of 1.80; The Ledger within the inclusive range [1.60, 1.65] (strictly above 1.50); Vintage Reruns within the inclusive range [0.80, 0.90] (strictly below 1.50).
5. THE churn-reduction percentage stored in each seeded `financial_projections` row SHALL equal the value a live recompute of that title produces from the seeded features and parameters.
6. THE seed generator's `--check` mode SHALL report the committed seed SQL as in sync after regeneration.
7. THE user guide, `CineROI_AI_Calculations_Reference.md`, and `CineROI_AI_Complete_Knowledge_Base.md` SHALL state churn numbers consistent with the regenerated seed.

### Requirement 10: Title scorecard "Churn Drivers Breakdown"

**User Story:** As an executive reviewing a title, I want to expand the churn section and see exactly which features drove the number, so that I can defend or challenge the churn estimate.

#### Acceptance Criteria

1. THE title scorecard's Financial breakdown churn section SHALL provide an expandable "Churn Drivers Breakdown" that lists the per-feature contributions: Base Platform Rate, Asset Cadence (the asset type), Talent Pedigree Contribution, Production Scale Contribution, Exclusivity Lift, and Market Telemetry Heat.
2. THE Asset Studio valuation report SHALL present the same Churn_Breakdown for a CALCULATED result.
3. WHEN the result is SUPPLIED, THE scorecard SHALL indicate that churn was supplied rather than calculated and SHALL NOT present a per-feature breakdown.
4. WHEN a feature is missing, THE breakdown SHALL show that feature contributing zero and label it as unavailable.
5. WHEN the Borderline_Sensitivity flag is true, THE scorecard SHALL display an amber pill with a warning indicator reading "Borderline Sensitivity: within 0.05% of the 1.50% hurdle".
6. THE breakdown control SHALL be keyboard operable, SHALL convey each contribution with a text value (not color alone), and SHALL treat the warning indicator as decorative with the text carrying the meaning.

### Requirement 11: Backtest Studio churn support

**User Story:** As an analyst, I want to enter the actual observed churn reduction for a historical title and see predicted-versus-actual churn, so that the churn model can be scored like the other metrics.

#### Acceptance Criteria

1. THE `POST /api/v1/backtest/audit` request SHALL accept an optional `actual_churn_reduction_pct` field that is persisted as the "churn_reduction" ground-truth metric.
2. THE audit SHALL continue to accept the existing `metrics` list, and SHALL require at least one metric from either the `metrics` list or the `actual_churn_reduction_pct` field.
3. THE Ground_Truth form on `/backtest` SHALL provide an optional "Actual churn reduction (%)" input.
4. THE variance chart SHALL label the churn metric with a human-readable name.
5. THE Backtest Studio SHALL display, for churn, the predicted value, the actual value, the variance (actual minus predicted), and the absolute percentage error, consistent with the existing MAPE rules (zero actuals excluded).

### Requirement 12: Documentation

**User Story:** As a new reader, I want the docs to describe the churn model, so that I understand how the number is produced and when it is overridden.

#### Acceptance Criteria

1. THE user guide (the "How Numbers Are Calculated" tab and the Guardrail 3 explainer) SHALL describe the additive churn model, the supplied-value override, and the borderline flag.
2. `CineROI_AI_Calculations_Reference.md` SHALL document the churn formula, the feature sources, the parameter storage, and the resolution precedence.
3. `CineROI_AI_Complete_Knowledge_Base.md` SHALL describe the Churn_Mitigation_Model consistently with the reference and the live numbers.

### Requirement 13: Verification expectations

**User Story:** As a maintainer, I want the model's guarantees covered by automated tests, so that regressions in the churn math or the demo verdicts are caught.

#### Acceptance Criteria

1. THE backend test suite SHALL include Hypothesis property tests covering monotonicity (increasing pedigree, production scale, or Telemetry_Heat never decreases the calculated churn), boundedness (the calculated churn always lies within [0.10, 5.00]), breakdown conservation (the sum of the Churn_Breakdown entries equals the calculated churn within a 0.01 tolerance), and precedence (a supplied finite value is returned exactly with Churn_Method SUPPLIED).
2. THE backend test suite SHALL include a seed regression test asserting the five seeded titles keep their verdicts (3 GREENLIGHT, 1 NEGOTIATE_HARD, 1 PASS) and their churn tolerances from Requirement 9.
3. THE frontend test suite SHALL include a component test confirming the Churn Drivers Breakdown renders the per-feature rows and the borderline pill.

## Out of Scope

- Changing the 1.5 percent Churn_Mitigation_Threshold, the CPVH / LTV / payback guardrails, or the recommendation logic.
- Changing the existing talent-pedigree / narrative-trope weight calibration.
- Automatically re-fitting or auto-correcting the churn coefficients from backtest results (only carry-forward on version forks is in scope).
- Fitting the coefficients to real subscriber-outcome data (the coefficients are illustrative).
- Any database schema migration (parameters live in the existing JSONB column).

## Open Questions for Design

1. The exact re-tuned non-negative constants and the tuning method. The reference starting values in the brief do not satisfy Requirement 9 (computed: Aurora 1.93, Echoes 1.81, Monsoon 1.37, Ledger 1.46, Reruns 0.86 with sentiment scaled x100, which flips Monsoon and Ledger to PASS). A re-tuned set with the same formula and all non-negative weights does satisfy it (verified example yielding 2.10 / 2.00 / 1.80 / 1.62 / 0.90). Design must pick and justify the final constants.
2. The exact persisted explanation JSON shape and the breakdown key names (feature keys, how missing features and the Bounds_Adjustment entry are encoded, how SUPPLIED is represented).
3. The Guardrails_Engine collaborator signature changes: adding a metadata-vector repository to the constructor, and whether `ValuationInputs.churn_reduction_pct` becomes optional (to represent "not supplied") versus a separate "supplied" flag, keeping existing fakes working.
4. Whether to surface the churn parameters in the model-version catalog UI, or keep them backend-only for now.
5. Whether the Asset Studio production-scale feature should reuse the radar derivation exactly or move to a shared helper (and whether that helper also feeds the radar).