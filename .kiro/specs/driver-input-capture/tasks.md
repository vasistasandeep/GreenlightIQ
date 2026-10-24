# Implementation Plan: Driver_Input_Capture

## Overview

This plan implements the write side of the Advanced_Content_Eval_Drivers across all three ingest paths (Asset Studio quick-evaluate, batch CSV/JSON, pitch-PDF pre-fill), a shared pure validation + Buzz_Level mapping module, demo flag enablement, and the Asset Studio frontend controls. No provider or engine change is made; the twelve `source_snapshot` keys are the complete integration seam.

**Implementation target:** All code tasks are implemented on the git worktree branch `feat/advanced-content-eval-drivers` at `c:\Projects\GreenlightIQ\.worktrees\advanced-content-eval-drivers` (NOT main). This `tasks.md` spec file itself lives in the normal main-tree location `.kiro/specs/driver-input-capture/`.

The work is structured into four sequential waves matching the reviewer's approved breakdown: (1) the shared domain core + validation module, (2) the ingest paths + persistence, (3) provider round-trip / seed-invariance / config, and (4) the frontend Asset Studio section.

## Tasks

- [x] 1. Wave 1 — Domain core and validation module
  - [x] 1.1 Create the shared driver domain module `backend/app/domain/drivers.py`
    - Create `backend/app/domain/drivers.py` as a pure, I/O-free module mirroring the `momentum.py` / `lineage.py` / `macro_modifiers.py` style (frozen constants, `coerce_*` helpers, never raises on coercion).
    - Define the canonical sets `SOURCE_IP_PROVENANCE_SET` = {ORIGINAL_SCREENPLAY, BESTSELLER_BOOK, TRUE_CRIME_IP, WEBTOON_MANGA, PUBLIC_DOMAIN} and `RELEASE_WINDOW_SET` = {DIRECT_TO_STREAMING, DAY_AND_DATE, THEATRICAL_30D, THEATRICAL_60D_PLUS}; reuse `Production_Stage` imported from `app.domain.momentum`.
    - Define the `BUZZ_LEVEL_SIGNALS: dict[str, BuzzSignals]` constant with the verified arithmetic: LOW `v=0.50 / e=0.02 / s=0.50` (→ multiplier 1.00), MEDIUM `v=1.00 / e=0.05 / s=1.10` (→ 1.1850), HIGH `v=2.00 / e=0.10 / s=1.50` (→ 1.4450); plus the frozen `BuzzSignals` dataclass of three `Decimal` fields.
    - Define the `FieldError` dataclass `{field, reason}`.
    - Implement `build_driver_facts(raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[FieldError]]`: for each of the twelve keys, skip absent/blank input (omit, never a neutral literal), validate against the R5 bounds, and on success serialize per the design's serialization table — decimal facts (`parent_title_viewing_hours`, `parent_completion_rate`, `v_trailer`, `e_ratio`, `s_velocity`) as strings; `is_franchise` as native bool; `franchise_order`, `release_month`, `vernacular_track_count` as native int; `production_stage`, `source_ip_provenance`, `release_window` as native enum-literal strings. Lineage parent fields are considered only when `is_franchise` is true.
    - _Requirements: 1.1, 2.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_
    - _Properties: 1, 2, 3, 4, 8_

  - [x]* 1.2 Write property tests for the driver domain module `backend/tests/domain/test_drivers_properties.py`
    - Use Hypothesis, ≥ 100 iterations per property, each tagged `# Feature: driver-input-capture, Property {n}: {property_text}`.
    - **Property 2: Buzz_Level mapping is bounded and monotonic** — feed each of {LOW, MEDIUM, HIGH} through the real `calculate_momentum` at a non-excluded stage; assert every multiplier is within `[1.00, 1.50]` and the three are monotonic non-decreasing, plus an example pinning 1.00 / 1.1850 / 1.4450.
    - **Property 3: Out-of-bounds facts are rejected with a per-field reason and never written** — generate out-of-bounds values per field; assert `build_driver_facts` returns a `FieldError` naming the field and bound and writes no key, while a valid sibling value persists.
    - **Property 1 / Property 4: supplied facts persist under exact keys in the expected type; omitted facts are absent, not defaulted** — generate random valid fact subsets; assert exact-key presence with the correct JSON type (decimals as strings round-trip to `Decimal`), and that omitted facts produce no key.
    - _Properties: 1, 2, 3, 4, 8_
    - _Requirements: 1.2, 2.3, 3.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 2. Wave 1 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Wave 2 — Ingest paths and persistence
  - [x] 3.1 Extend the Asset Studio quick-evaluate path in `backend/app/api/quick_evaluate.py`
    - Extend `QuickEvaluateRequest` with the optional lineage fields (`is_franchise`, `franchise_order`, `parent_title_viewing_hours`, `parent_completion_rate`), macro fields (`source_ip_provenance`, `release_window`, `release_month`, `vernacular_track_count`), and the friendly momentum controls `production_stage` and `buzz_level` (`Literal["LOW","MEDIUM","HIGH"]`). Do NOT add raw `v_trailer`/`e_ratio`/`s_velocity` input fields to this model (R2.2).
    - Add Pydantic `field_validator`s (mirroring `_valid_asset_type` / `_valid_currency`) that reject enum values outside their sets and out-of-range numerics at the request boundary, producing a 422 naming the offending field at the boundary.
    - Extend `_modeled_inputs` to assemble the `raw` driver dict (lineage parents only when `is_franchise`; expand `buzz_level` via `drivers.BUZZ_LEVEL_SIGNALS` into `v_trailer`/`e_ratio`/`s_velocity`), call `drivers.build_driver_facts`, and `snapshot.update(facts)` — omitting absent facts, leaving telemetry staleness fields unwritten (fresh/available default), and writing `momentum_input_source = {"buzz_level": <level>}` when a buzz level was used (R10.2).
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.4, 10.2_
    - _Properties: 1, 4_

  - [x] 3.2 Extend batch validation and persistence in `backend/app/engines/ingestion.py`
    - Accept an optional CSV column / JSON field for each of the twelve driver keys by its exact snapshot name, including the raw momentum signals directly (Raw_Signal_Mode — no Buzz_Level required on the batch path).
    - In `_validate`, run `drivers.build_driver_facts` over the record's candidate driver keys after the existing title_name/cost/asset_type checks (unchanged order); turn the first driver-fact `FieldError` into a `RejectionDetail{row_index, field, reason}` and reject the record; the per-row loop continues so the conservation invariant `accepted + rejected == total` holds.
    - In `_snapshot`, merge the validated `build_driver_facts` output over the twelve driver keys (overwriting the raw string copies with correctly typed, stringified-decimal values) while leaving every existing key untouched; a record omitting a driver key writes no key for it.
    - Persist `vernacular_track_count` exactly as supplied — never infer it from `target_territories`.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.4, 8.3_
    - _Properties: 1, 3, 4_

  - [x] 3.3 Add pitch recognition heuristics in `backend/app/domain/pitch_parse.py`
    - Extend `parse_pitch_text` with the recognition regex tables from the design: franchise cue → `is_franchise=true` (+ `franchise_order` when a numeric entry is captured); release window → matching `Release_Window_Set` member; source-IP → matching `Source_IP_Provenance_Set` member; production stage → matching `Production_Stage` member (first/most-specific match wins).
    - Extend `ParsedPitchResponse` with the matching optional fields so the router returns them as pre-fill.
    - Include only recognized facts; omit any fact that cannot be recognized (no guessing); never persist.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 8.4_
    - _Properties: 4_

  - [x]* 3.4 Write pitch recognition example / edge tests in `backend/tests/domain/`
    - Representative snippets per cue → expected recognized facts (R4.1–R4.4); a no-cue deck → no driver keys added (R4.5, R8.4).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 8.4_

  - [x]* 3.5 Write batch anti-inference / conservation example tests in `backend/tests/engines/`
    - A 3-territory record with `vernacular_track_count=1` persists 1, not 3 (R3.6); a record with an out-of-bounds driver fact is rejected with a per-field `RejectionDetail` while sibling records are accepted and `accepted + rejected == total` holds (R3.5); a manifest with no driver columns persists records with no driver keys (R8.3).
    - _Requirements: 3.5, 3.6, 8.3_
    - _Properties: 3, 4_

- [x] 4. Wave 2 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Wave 3 — Provider round-trip, seed invariance, and config
  - [x] 5.1 Write provider round-trip and non-neutral impact tests in `backend/tests/api/test_driver_input_capture.py`
    - **Property 5: Supplied facts round-trip through the real provider** — generate valid fact sets, persist to a title's active snapshot via a capture path, resolve through the unmodified `AdvancedDriversValuationInputProvider` (all four flags on); assert resolver outputs equal the pure-domain computation (lineage `is_active`/floor, momentum multiplier == `calculate_momentum`, macro product). Hypothesis, ≥ 100 iterations, tagged.
    - **Property 6: Non-neutral facts change the evaluation when flags are on** — a title carrying real facts, persisted to its snapshot and resolved through the real provider with flags on, produces a verdict/breakdown that differs from the same title's neutral-defaults resolution. Hypothesis, ≥ 100 iterations, tagged.
    - Backward-compat inertness example: a title supplying no driver facts resolves identically flags-on vs flags-off.
    - _Requirements: 6.1, 6.2, 6.3, 7.2, 8.1, 8.2_
    - _Properties: 5, 6_

  - [x] 5.2 Enable the four driver flags in the demo configuration `docker-compose.yml`
    - In the `x-backend-env: &backend-env` anchor, add `CINEROI_ENABLE_COMPS`, `CINEROI_ENABLE_LINEAGE`, `CINEROI_ENABLE_MOMENTUM`, and `CINEROI_ENABLE_MACRO_MODIFIERS` each defaulted to `true` for the demo (overridable via the root `.env`, e.g. `${CINEROI_ENABLE_COMPS:-true}`). Do NOT change the `Settings` code defaults, which stay `False`.
    - _Requirements: 7.1, 7.4_

  - [x] 5.3 Write the seed-invariance regression guard in `backend/tests/api/test_driver_input_capture.py`
    - **Property 7: Neutral and seeded titles are invariant under flag enablement** — a parameterized test over the five seeded titles (Aurora Protocol, Monsoon Lanes, Echoes of 2019 → GREENLIGHT; The Ledger → NEGOTIATE_HARD; Vintage Reruns Vol. 7 → PASS) asserting each stays byte-identical with all four flags enabled vs disabled, and retains its seeded verdict.
    - _Requirements: 7.3, 7.5, 8.1, 8.2_
    - _Properties: 7_

  - [x]* 5.4 Write the comps-absence property test in `backend/tests/api/` or `backend/tests/domain/`
    - **Property 8: No comps anchor fact is ever written** — generate Asset Studio submissions, batch records, and parsed pitch texts; assert the produced snapshot contains no `comps` key and no comps-anchor fact. Hypothesis, ≥ 100 iterations, tagged.
    - _Requirements: 9.1, 9.3_
    - _Properties: 8_

- [x] 6. Wave 3 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Wave 4 — Frontend Asset Studio controls
  - [x] 7.1 Add the "Advanced drivers (optional)" section to `frontend/app/studio/_components/asset-form.tsx`
    - Add an `is_franchise` toggle that reveals `franchise_order` (number, min 1), `parent_title_viewing_hours`, and `parent_completion_rate` only when on, and hides / does not require them when off (R1.6).
    - Add a `production_stage` select bound to the four `Production_Stage` members (R2.1), a `buzz_level` select {LOW, MEDIUM, HIGH} with NO raw numeric inputs (R2.2), plus `source_ip_provenance` (Source_IP_Provenance_Set), `release_window` (Release_Window_Set), `release_month` (1..12, optional), and `vernacular_track_count` (min 1) controls.
    - Stage-gate the Buzz_Level control: DISABLE it and annotate "Inactive in early stage (STAGE_EXCLUDED) — buzz does not affect an unproduced title's verdict." when `production_stage` is `CONCEPT_SCRIPT` or `IN_PRODUCTION` (clarification #4), enabled for `FESTIVAL_PREVIEW` / `ACQUISITION_READY`.
    - Extend the frontend quick-evaluate request type with the new optional driver fields.
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 2.1, 2.2, 5.1_

  - [x] 7.2 Wire pitch-deck prefill auto-population into the Asset Studio form
    - Populate the new "Advanced drivers" controls from the `ParsedPitchResponse` pre-fill fields returned by `parse-pitch`, rendering each as a user-editable control the user reviews before submitting (R4.6); unrecognized facts leave their controls empty.
    - _Requirements: 4.5, 4.6_

  - [x]* 7.3 Write Vitest component tests for the Asset Studio driver section
    - Buzz_Level disabled/annotated for `CONCEPT_SCRIPT`/`IN_PRODUCTION` and enabled otherwise (clarification #4); lineage parent fields revealed only when `is_franchise` is on (R1.6); pitch prefill populates the controls (R4.6).
    - _Requirements: 1.6, 2.2, 4.6_

- [x] 8. Final checkpoint — full suite in the worktree
  - In `c:\Projects\GreenlightIQ\.worktrees\advanced-content-eval-drivers`: run the backend test suite (`backend/` pytest), and the frontend typecheck, lint, and Vitest (`frontend/`). Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test sub-tasks) and can be skipped for a faster MVP; core implementation tasks are never marked optional.
- Each task references specific sub-requirement clauses and the design's Correctness Properties for traceability.
- All code tasks are implemented on the worktree branch `feat/advanced-content-eval-drivers`; this spec file lives in the main-tree `.kiro/specs/driver-input-capture/`.
- The provider and engine (`backend/app/api/deps.py`) are NOT modified — the twelve `source_snapshot` keys are the complete integration seam.
- Property tests use Hypothesis (≥ 100 iterations) and are tagged `# Feature: driver-input-capture, Property {n}: {property_text}`; unit/example tests cover recognition, anti-inference, framing, and the seed regression.
- Checkpoints provide incremental validation at each wave boundary.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "3.1", "3.2", "3.3"] },
    { "id": 2, "tasks": ["3.4", "3.5", "5.1", "5.2"] },
    { "id": 3, "tasks": ["5.3", "5.4", "7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3"] }
  ]
}
```
