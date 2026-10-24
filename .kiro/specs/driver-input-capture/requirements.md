# Requirements Document

## Introduction

The **Advanced_Content_Eval_Drivers** feature (spec `advanced-content-eval-drivers`, implemented only on the git worktree branch `feat/advanced-content-eval-drivers` at `c:\Projects\GreenlightIQ\.worktrees\advanced-content-eval-drivers`) adds four industry drivers -- Comps_Engine (A), Lineage_Decay (B), Momentum_Telemetry (C), and Macro_Modifiers (D) -- that feed the CineROI AI `Guardrails_Engine` through the existing `ValuationInputProvider` boundary. Each driver is a pure domain module governed by a per-driver kill-switch (`CINEROI_ENABLE_COMPS`, `CINEROI_ENABLE_LINEAGE`, `CINEROI_ENABLE_MOMENTUM`, `CINEROI_ENABLE_MACRO_MODIFIERS`) that defaults false.

Those drivers read their modeling facts from a title's active `title_versions.source_snapshot` (the `SnapshotValuationInputProvider` / `ContentEvalValuationInputProvider` in `backend/app/api/deps.py`). The problem this feature solves: **no entry path ever writes those facts.** The Asset Studio quick-evaluate form (`backend/app/api/quick_evaluate.py` `_modeled_inputs`) never emits `is_franchise`, `production_stage`, `source_ip_provenance`, etc.; the batch ingest (`backend/app/engines/ingestion.py`) has no columns or manifest fields for them; and the pitch-PDF parser (`backend/app/domain/pitch_parse.py`) never recognizes them. As a result every title carries only neutral/absent driver facts, so even with the four flags on the drivers resolve to their neutral/no-op paths and the lineage/momentum/macro inputs are effectively "not taken" -- enabling the drivers does not change any verdict or breakdown.

The **Driver_Input_Capture** feature closes that gap. It lets users SUPPLY the exact driver input facts across all three ingest paths, validates and persists them into each title's active `source_snapshot` so the existing flag-gated provider reads them with **no provider change required**, enables the four driver flags in the demo configuration, and thereby makes enabling the drivers actually move verdicts for titles that carry real (non-neutral) facts. The feature preserves the existing inertness guarantee: a title (or CSV row, or pitch) that supplies none of the new facts behaves exactly as today -- neutral defaults, byte-identical output when the flags are off, and the neutral/no-op driver paths when the flags are on.

The scope of this document is **requirements only**: no implementation, no migrations applied, no tests run. It produces exactly this `requirements.md`.

### Grounding (verified against the worktree code this feature targets)

- **Integration seam.** `backend/app/api/deps.py` `SnapshotValuationInputProvider.get_inputs` resolves the title's active version via `TitleVersionRepository.get_active(title_id)` and reads modeling facts out of `active.source_snapshot` (a JSONB dict). The Advanced_Content_Eval_Drivers provider resolution reads the driver facts from this same snapshot. Writing the facts into `source_snapshot` is therefore the complete integration seam -- the provider needs no change to consume them.
- **Asset Studio path.** `backend/app/api/quick_evaluate.py` `POST /api/v1/titles/quick-evaluate` builds the snapshot in `_modeled_inputs(body, rate_date)` from a `QuickEvaluateRequest`, then creates the `Title` and an active `TitleVersion` with `source_snapshot=_modeled_inputs(...)`, runs the engine inline, and returns a scorecard. The form fields live in `frontend/app/studio`. Today `_modeled_inputs` writes churn/LTV/payback modeling keys and the calculable-churn feature facts, but none of the four drivers' facts.
- **Batch path.** `backend/app/engines/ingestion.py` parses CSV and JSON manifests into `_ParsedRecord` rows, validates them, and persists each via `_append_version`, whose `_snapshot(record)` copies every raw record field into the snapshot (stringifying Decimals/UUIDs). New driver-fact columns/fields that are recognized and validated flow into the snapshot through this path. `MIN_ACQUISITION_COST`/`MAX_ACQUISITION_COST`, `ASSET_TYPE_SET`, and per-field `RejectionDetail` are the existing validation pattern.
- **Pitch path.** `backend/app/api/quick_evaluate.py` `POST /api/v1/titles/parse-pitch` extracts PDF text and calls `backend/app/domain/pitch_parse.py` `parse_pitch_text`, returning a `ParsedPitchResponse` of best-effort pre-fill fields. It **never persists** -- the user reviews and edits before submitting the Asset Studio form.
- **Driver facts the provider reads (exact snapshot keys).** Driver B (Lineage): `is_franchise`, `franchise_order`, `parent_title_viewing_hours`, `parent_completion_rate`. Driver C (Momentum): `production_stage`, `v_trailer`, `e_ratio`, `s_velocity`, plus derived staleness fields `telemetry_last_updated_at` / `telemetry_source_available`. Driver D (Macro): `source_ip_provenance`, `release_window`, `release_month`, `vernacular_track_count`. Driver A (Comps): no user-entered fact -- comps are auto-retrieved via pgvector budget-band similarity.
- **Production_Stage enum.** `CONCEPT_SCRIPT`, `IN_PRODUCTION`, `FESTIVAL_PREVIEW`, `ACQUISITION_READY` -- a new enum distinct from `app.domain.deal_stage.DealStage`; momentum is stage-gated and active only for `FESTIVAL_PREVIEW` / `ACQUISITION_READY`.
- **Documented macro domains.** `source_ip_provenance` in {ORIGINAL_SCREENPLAY, BESTSELLER_BOOK, TRUE_CRIME_IP, WEBTOON_MANGA, PUBLIC_DOMAIN}; `release_window` in {DIRECT_TO_STREAMING, DAY_AND_DATE, THEATRICAL_30D, THEATRICAL_60D_PLUS}.
- **Flags.** `backend/app/core/config.py` `Settings` (pydantic-settings, `env_prefix="CINEROI_"`). The four `enable_*` driver flags default false; while a flag is false the driver is fully inert and the output is byte-identical to today.

## Glossary

- **Driver_Input_Capture**: The feature described by this document: the capture, validation, and snapshot persistence of the Advanced_Content_Eval_Drivers' input facts across the Asset Studio, batch, and pitch-parse paths, plus the demo enablement of the four driver flags.
- **Source_Snapshot**: The JSONB `title_versions.source_snapshot` dict on a title's active version; the single place the `ValuationInputProvider` reads driver facts from. Writing a fact here is the whole integration seam.
- **Driver_Fact**: One of the user-supplied modeling inputs a driver consumes, named by its exact snapshot key (see below).
- **Asset_Studio_Form**: The single-title quick-evaluate form (`frontend/app/studio`) whose submission maps to a `QuickEvaluateRequest` and is persisted by `POST /api/v1/titles/quick-evaluate`.
- **Batch_Manifest**: A CSV or JSON manifest submitted to the batch ingest (`backend/app/engines/ingestion.py`), one record per prospective title.
- **Pitch_Prefill**: The best-effort fields the pitch-PDF parser (`POST /api/v1/titles/parse-pitch`, `parse_pitch_text`) returns to pre-populate the Asset_Studio_Form; never persisted directly.
- **Lineage_Facts**: `is_franchise` (boolean), `franchise_order` (integer, 1 = original, >= 2 = sequel/entry number), `parent_title_viewing_hours` (Decimal, the parent title's projected hours), `parent_completion_rate` (Decimal in [0, 1]).
- **Momentum_Facts**: `production_stage` (Production_Stage enum), `v_trailer` (Trailer Velocity Index, Decimal), `e_ratio` (Organic Engagement Ratio, Decimal), `s_velocity` (search-intent velocity, Decimal).
- **Macro_Facts**: `source_ip_provenance` (enum), `release_window` (enum), `release_month` (integer 1..12, nullable), `vernacular_track_count` (integer >= 1).
- **Production_Stage**: The enum {CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY}; distinct from `DealStage`.
- **Source_IP_Provenance_Set**: {ORIGINAL_SCREENPLAY, BESTSELLER_BOOK, TRUE_CRIME_IP, WEBTOON_MANGA, PUBLIC_DOMAIN}.
- **Release_Window_Set**: {DIRECT_TO_STREAMING, DAY_AND_DATE, THEATRICAL_30D, THEATRICAL_60D_PLUS}.
- **Buzz_Level**: A friendly Asset_Studio_Form control with values {LOW, MEDIUM, HIGH} that maps to the raw Momentum_Facts signal values (`v_trailer`, `e_ratio`, `s_velocity`); the raw numeric signals are not exposed as direct input boxes in the form.
- **Raw_Signal_Mode**: The API / CSV / JSON acceptance of the raw Momentum_Facts numeric values directly, available to power users, bypassing the Buzz_Level mapping.
- **Driver_Flag**: One of the four per-driver kill-switches in settings (`enable_comps`, `enable_lineage`, `enable_momentum`, `enable_macro_modifiers`), env-prefixed `CINEROI_`.
- **Neutral_Title**: A title (or batch row, or parsed pitch) that supplies none of the Driver_Facts, whose behavior must be identical to today's (neutral defaults; byte-identical with flags off; neutral/no-op driver paths with flags on).
- **Validation_Bounds**: The documented input constraints: enum membership for each enum fact; `franchise_order >= 1`; `parent_completion_rate` in [0, 1]; `vernacular_track_count >= 1`; `release_month` in 1..12; `v_trailer` / `e_ratio` / `s_velocity` / `parent_title_viewing_hours` finite and non-negative.

## Requirements

### Requirement 1: Asset Studio capture of lineage and macro facts

**User Story:** As a content buyer using the Asset Studio quick-evaluate form, I want to enter a title's franchise lineage and market-context facts, so that the drivers evaluate my title on its real attributes instead of neutral defaults.

#### Acceptance Criteria

1. THE Asset_Studio_Form SHALL expose optional controls for each Lineage_Fact (`is_franchise`, `franchise_order`, `parent_title_viewing_hours`, `parent_completion_rate`) and each Macro_Fact (`source_ip_provenance`, `release_window`, `release_month`, `vernacular_track_count`).
2. WHEN a user submits the Asset_Studio_Form with one or more Lineage_Facts or Macro_Facts, THE Quick_Evaluate_Endpoint SHALL write each supplied fact into the created title's active Source_Snapshot under its exact snapshot key.
3. WHERE `source_ip_provenance` is offered, THE Asset_Studio_Form SHALL present the Source_IP_Provenance_Set members as the only selectable values.
4. WHERE `release_window` is offered, THE Asset_Studio_Form SHALL present the Release_Window_Set members as the only selectable values.
5. WHEN a user leaves a Lineage_Fact or Macro_Fact control empty, THE Quick_Evaluate_Endpoint SHALL omit that key from the Source_Snapshot, so an unsupplied fact is absent rather than written as a neutral literal.
6. WHEN a user submits `is_franchise = false` (or leaves it unset), THE Asset_Studio_Form SHALL treat the lineage parent fields as not applicable and SHALL NOT require `parent_title_viewing_hours` or `parent_completion_rate`.

### Requirement 2: Asset Studio momentum capture via friendly controls

**User Story:** As a content modeler using the Asset Studio form, I want to indicate a title's production stage and pre-release buzz through plain controls rather than raw telemetry numbers, so that I can supply momentum signals without knowing the underlying index formulas.

#### Acceptance Criteria

1. THE Asset_Studio_Form SHALL expose a production-stage control whose selectable values are exactly the Production_Stage members {CONCEPT_SCRIPT, IN_PRODUCTION, FESTIVAL_PREVIEW, ACQUISITION_READY}.
2. THE Asset_Studio_Form SHALL expose a Buzz_Level control with the values {LOW, MEDIUM, HIGH} and SHALL NOT present raw `v_trailer`, `e_ratio`, or `s_velocity` numeric input boxes.
3. WHEN a user selects a Buzz_Level, THE Quick_Evaluate_Endpoint SHALL map that level to documented raw values for `v_trailer`, `e_ratio`, and `s_velocity` and SHALL write those raw values into the Source_Snapshot under their exact snapshot keys.
4. WHEN a user selects a `production_stage`, THE Quick_Evaluate_Endpoint SHALL write `production_stage` into the Source_Snapshot under its exact snapshot key.
5. WHEN a user leaves the Buzz_Level control unset, THE Quick_Evaluate_Endpoint SHALL omit `v_trailer`, `e_ratio`, and `s_velocity` from the Source_Snapshot so the Momentum_Telemetry driver resolves its neutral path.
6. WHEN a title is freshly entered through the Asset_Studio_Form, THE Quick_Evaluate_Endpoint SHALL treat the telemetry staleness fields (`telemetry_last_updated_at`, `telemetry_source_available`) as fresh and available and SHALL NOT expose them as user-entered controls.

### Requirement 3: Batch CSV and JSON capture of driver facts

**User Story:** As a data analyst ingesting a slate through a CSV or JSON manifest, I want optional columns and fields for every driver fact, so that a bulk-loaded title carries the same lineage, momentum, and macro inputs a single-title submission can.

#### Acceptance Criteria

1. THE Batch_Ingest SHALL accept an optional manifest column (CSV) or field (JSON) for each Lineage_Fact, each Macro_Fact, and each raw Momentum_Fact (`production_stage`, `v_trailer`, `e_ratio`, `s_velocity`), each identified by its exact snapshot key.
2. WHEN a Batch_Manifest record carries one or more driver facts that pass validation, THE Batch_Ingest SHALL persist each supplied fact into that title's active Source_Snapshot under its exact snapshot key.
3. WHERE a Batch_Manifest record supplies raw Momentum_Facts directly, THE Batch_Ingest SHALL accept the raw numeric values (Raw_Signal_Mode) without requiring a Buzz_Level mapping.
4. WHEN a Batch_Manifest record omits a driver fact, THE Batch_Ingest SHALL omit that key from the record's Source_Snapshot, leaving the title a Neutral_Title with respect to that fact.
5. IF a Batch_Manifest record carries a driver fact that violates its Validation_Bounds, THEN THE Batch_Ingest SHALL reject that record with a per-field RejectionDetail naming the offending field and the violated bound, and SHALL continue processing the remaining records.
6. WHEN a Batch_Manifest supplies a `target_territories` list and a `vernacular_track_count`, THE Batch_Ingest SHALL persist `vernacular_track_count` as the supplied value without inferring it from the territory list.

### Requirement 4: Pitch-PDF pre-fill of recognizable driver facts

**User Story:** As a buyer uploading a pitch deck, I want the parser to pre-fill any driver facts it can recognize from the deck, so that I start from a populated form and only review rather than re-type.

#### Acceptance Criteria

1. WHEN a pitch PDF contains text indicating a franchise entry (for example "sequel", "season 2", "part II", or an explicit entry number), THE Pitch_Parser SHALL set `is_franchise = true` and SHALL set `franchise_order` to the recognized entry number when one is present.
2. WHEN a pitch PDF contains text indicating a theatrical release window (for example "theatrical release", "day-and-date", "30-day theatrical window"), THE Pitch_Parser SHALL set `release_window` to the matching Release_Window_Set member.
3. WHEN a pitch PDF contains text indicating a source-IP provenance (for example "based on the bestselling novel", "true-crime", "adapted from the webtoon"), THE Pitch_Parser SHALL set `source_ip_provenance` to the matching Source_IP_Provenance_Set member.
4. WHEN a pitch PDF contains text indicating a production stage (for example "in production", "festival preview", "acquisition-ready screener"), THE Pitch_Parser SHALL set `production_stage` to the matching Production_Stage member.
5. THE Pitch_Parser SHALL include each recognized Driver_Fact in the Pitch_Prefill response and SHALL omit any fact it cannot recognize, so an unrecognized fact is absent rather than guessed.
6. THE Pitch_Parser SHALL NOT persist any recognized Driver_Fact, and THE Asset_Studio_Form SHALL render every pre-filled Driver_Fact as a user-editable control the user reviews before submitting.

### Requirement 5: Validation of supplied driver facts

**User Story:** As a maintainer, I want every supplied driver fact validated against documented bounds before it reaches a snapshot, so that no out-of-domain value ever flows to a driver.

#### Acceptance Criteria

1. IF a supplied `source_ip_provenance`, `release_window`, or `production_stage` is not a member of its documented set, THEN THE relevant capture path SHALL reject that value and SHALL NOT write it to the Source_Snapshot.
2. IF a supplied `franchise_order` is less than 1 or is non-integer, THEN THE relevant capture path SHALL reject the value and report that `franchise_order` must be an integer greater than or equal to 1.
3. IF a supplied `parent_completion_rate` is outside the inclusive range [0, 1], THEN THE relevant capture path SHALL reject the value and report the [0, 1] bound.
4. IF a supplied `vernacular_track_count` is less than 1 or is non-integer, THEN THE relevant capture path SHALL reject the value and report that `vernacular_track_count` must be an integer greater than or equal to 1.
5. IF a supplied `release_month` is present and is outside the inclusive range 1..12, THEN THE relevant capture path SHALL reject the value and report the 1..12 bound; WHERE `release_month` is absent, THE relevant capture path SHALL treat it as a valid null.
6. IF a supplied `parent_title_viewing_hours`, `v_trailer`, `e_ratio`, or `s_velocity` is non-finite or negative, THEN THE relevant capture path SHALL reject the value and report the finite-non-negative bound.
7. WHEN a supplied Lineage_Fact, Momentum_Fact, or Macro_Fact passes its Validation_Bounds, THE relevant capture path SHALL persist it in the type the provider expects (boolean, integer, or decimal-string) under its exact snapshot key.

### Requirement 6: Persistence and provider integration without provider change

**User Story:** As a platform owner, I want the captured facts written into the exact snapshot location the drivers already read, so that no provider or engine code changes to consume them.

#### Acceptance Criteria

1. THE capture paths SHALL write every validated Driver_Fact into `title_versions.source_snapshot` on the title's active version, under the exact snapshot keys the Advanced_Content_Eval_Drivers provider reads (`is_franchise`, `franchise_order`, `parent_title_viewing_hours`, `parent_completion_rate`, `production_stage`, `v_trailer`, `e_ratio`, `s_velocity`, `source_ip_provenance`, `release_window`, `release_month`, `vernacular_track_count`).
2. THE capture paths SHALL NOT modify `SnapshotValuationInputProvider` or `ContentEvalValuationInputProvider` in `backend/app/api/deps.py`; the Source_Snapshot write SHALL be the complete integration seam.
3. WHEN a title carrying validated Driver_Facts is evaluated with the corresponding Driver_Flags enabled, THE Guardrails_Engine SHALL surface each supplied fact in the existing per-driver explanation breakdown.
4. THE capture paths SHALL write the Driver_Facts alongside the existing modeling keys in the Source_Snapshot without removing or altering any existing key.
5. WHEN a title's active version is replaced by a later ingest (a new active version), THE capture paths SHALL write the Driver_Facts into the new active version's Source_Snapshot so the provider reads the latest supplied facts.

### Requirement 7: Driver enablement in the demo configuration

**User Story:** As a demo operator, I want the four driver flags on in the demo configuration, so that a title carrying real facts shows a verdict and breakdown that reflect the drivers.

#### Acceptance Criteria

1. THE demo configuration SHALL set `CINEROI_ENABLE_COMPS`, `CINEROI_ENABLE_LINEAGE`, `CINEROI_ENABLE_MOMENTUM`, and `CINEROI_ENABLE_MACRO_MODIFIERS` to true.
2. WHEN a title carrying validated non-neutral Driver_Facts is evaluated with the four Driver_Flags enabled, THE Guardrails_Engine SHALL produce a verdict or breakdown that differs from the same title's neutral-defaults evaluation.
3. WHILE the four Driver_Flags are enabled, THE Guardrails_Engine SHALL resolve a Neutral_Title to the drivers' neutral/no-op paths so that a title supplying no Driver_Facts is unaffected by enablement.
4. WHERE a single Driver_Flag is disabled, THE Guardrails_Engine SHALL leave that driver fully inert for every title regardless of the facts the title carries.
5. WHEN the demo seed data is regenerated with the four Driver_Flags enabled, THE seeded demo titles that carry no Driver_Facts SHALL retain their current verdicts (Aurora Protocol, Monsoon Lanes, Echoes of 2019 GREENLIGHT; The Ledger NEGOTIATE_HARD; Vintage Reruns Vol. 7 PASS).

### Requirement 8: Backward compatibility and inertness for titles without facts

**User Story:** As a maintainer, I want a title, row, or pitch that supplies no driver facts to behave exactly as it does today, so that the feature is purely additive and the existing demo and tests are untouched.

#### Acceptance Criteria

1. WHEN a Neutral_Title is evaluated with all four Driver_Flags disabled, THE Guardrails_Engine SHALL produce output byte-identical to the pre-feature output for that title.
2. WHEN a Neutral_Title is evaluated with the four Driver_Flags enabled, THE Guardrails_Engine SHALL resolve each driver to its neutral/no-op path, leaving the verdict and breakdown equal to the neutral-defaults evaluation.
3. WHEN a Batch_Manifest contains no driver-fact columns or fields, THE Batch_Ingest SHALL accept and persist each record exactly as it does today, writing no driver-fact keys to any Source_Snapshot.
4. WHEN a pitch PDF contains no recognizable driver facts, THE Pitch_Parser SHALL return the same Pitch_Prefill fields it returns today, with no driver-fact keys added.
5. THE Driver_Facts SHALL all be optional on every capture path, so that no existing submission, manifest, or pitch becomes invalid by the introduction of the new fields.

### Requirement 9: Comps inputs are out of scope and not user-entered

**User Story:** As a user, I want it made explicit that I do not supply comps inputs, so that I am not confused into looking for comps fields that do not exist.

#### Acceptance Criteria

1. THE Driver_Input_Capture feature SHALL NOT expose any user control, API parameter, CSV column, JSON field, or pitch-parse mapping for Comps_Engine (Driver A) inputs.
2. THE Comps_Engine SHALL continue to retrieve its comp set automatically via pgvector budget-band similarity, independent of any user-supplied fact.
3. THE Asset_Studio_Form, Batch_Ingest, and Pitch_Parser SHALL treat the comps anchor as an auto-derived value and SHALL NOT write any comps anchor fact to a Source_Snapshot.

### Requirement 10: Honest framing of supplied facts as illustrative modeling inputs

**User Story:** As an executive reviewing a valuation, I want the supplied driver facts shown as the user-entered modeling inputs they are, so that I understand the drivers remain illustrative rather than fitted ground truth.

#### Acceptance Criteria

1. THE per-driver explanation breakdown SHALL surface each supplied Driver_Fact as a user-supplied modeling input distinct from a fitted or empirically derived value.
2. WHERE a Buzz_Level was used to produce `v_trailer`, `e_ratio`, and `s_velocity`, THE per-driver explanation SHALL be able to represent that the raw momentum signals were derived from a friendly Buzz_Level selection.
3. THE Driver_Input_Capture feature SHALL NOT present the supplied facts or the resulting driver contributions as validated real-world outcomes.
