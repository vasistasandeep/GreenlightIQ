# Implementation Plan: Dashboard Accuracy and Payback Audit

## Overview

This plan implements the three enhancements from the design in a test-driven,
incremental order. The pure accuracy helper (`backend/app/domain/accuracy.py`)
and its property tests come first, because the dashboard wiring and the seed
integration assertion both depend on it. Component 2 (frontend payback threading)
is independent and can proceed in parallel, but its type additions mirror the
backend field added in Component 1. Component 3 (seed) is implemented after the
helper exists so the integration assertion can verify a non-null rate against
real classification logic.

Languages are taken directly from the design: Python (backend helper, handler,
seed generator, pytest + Hypothesis) and TypeScript (frontend form, types,
selector, vitest). No pseudocode was used, so no language choice is required.

## Tasks

- [ ] 1. Create the pure accuracy helper and classify actual verdicts
  - [x] 1.1 Implement `actual_verdict` and `verdict_match_rate` in `backend/app/domain/accuracy.py`
    - Create `backend/app/domain/accuracy.py` as a pure, I/O-free module.
    - Define `ACCURACY_DECIMAL_PLACES = 4` and `REQUIRED_METRICS = ("cpvh", "ltv_to_cost", "churn_reduction", "payback_horizon")`.
    - Implement `actual_verdict(asset_type, actuals)`: classify each actual metric into a `GuardrailCheck` with the same `name`/`threshold`/`passed`/`breached`/`correctable` semantics as the live `_cpvh_check`/`_ltv_check`/`_churn_check`/`_payback_check` helpers, importing the CPVH ceiling from `app.domain.cpvh.cpvh_ceiling` (keyed off `AssetType(asset_type)`), the LTV floor from `app.domain.ltv.LTV_TO_COST_THRESHOLD` (3.2), and `CHURN_MITIGATION_THRESHOLD` (1.5) / `PAYBACK_TARGET_MAX_MONTHS` (12) from `app.engines.guardrails`. Correctability: CPVH/LTV/payback `True`, churn `False`.
    - Feed the classified checks to the unchanged `app.domain.recommendation.determine_recommendation` and return its verdict string.
    - Return `None` when any required metric is missing or when the asset type yields no CPVH ceiling (not classifiable).
    - Implement `verdict_match_rate(pairs)`: over the eligible subset (both predicted and actual verdicts present/classifiable), return `round(matches / eligible_count, ACCURACY_DECIMAL_PLACES)`, or `None` when the eligible subset is empty. Never emit `0.0` to mean "not measured".
    - Reuse existing thresholds/constants by import; do not re-declare values.
    - _Requirements: 1.1, 1.2, 2.1, 2.3, 2.4, 2.5, 2.6, 3.3, 5.1, 5.3_

  - [x]* 1.2 Write property test: accuracy is a fraction or null
    - **Feature: dashboard-accuracy-and-payback-audit, Property 1: Model_Accuracy_Rate is null or a float in [0, 1], and null iff the eligible subset is empty**
    - Hypothesis, backend, minimum 100 iterations.
    - **Validates: Requirements 2.4, 2.5, 2.6**

  - [x]* 1.3 Write property test: eligibility excludes insufficient ground truth
    - **Feature: dashboard-accuracy-and-payback-audit, Property 2: a title with no ground truth, a missing required metric, or an unclassifiable actual verdict is counted neither as a match nor a miss**
    - Assert the rate is unchanged when such a partial title is added or removed.
    - Hypothesis, backend, minimum 100 iterations.
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [x]* 1.4 Write property test: accuracy equals matches over eligible
    - **Feature: dashboard-accuracy-and-payback-audit, Property 3: for a non-empty eligible subset, the rate equals round(matches / eligible_count, 4)**
    - Hypothesis, backend, minimum 100 iterations.
    - **Validates: Requirements 1.1, 1.3, 2.5, 3.3**

  - [x]* 1.5 Write property test: determinism
    - **Feature: dashboard-accuracy-and-payback-audit, Property 4: computing the rate twice over the same inputs yields the identical value with no dependence on clock, randomness, or ordering**
    - Hypothesis, backend, minimum 100 iterations.
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 1.6 Write property test: actual verdict reuses the live recommendation rule
    - **Feature: dashboard-accuracy-and-payback-audit, Property 5: for all-four-classifiable titles, actual_verdict equals determine_recommendation over checks classified with the title's own thresholds and the live correctability rules (churn non-correctable)**
    - Include a case where a churn breach forces PASS to confirm non-correctability is honored.
    - Hypothesis, backend, minimum 100 iterations.
    - **Validates: Requirements 1.2, 5.3**

- [x] 2. Checkpoint - accuracy helper and its property tests
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Wire verdict-match accuracy into the dashboard handler
  - [x] 3.1 Add `payback_horizon_months` to the backend `TitleSummary` and populate it
    - In `backend/app/api/dashboard.py`, add `payback_horizon_months: int | None = None` to `TitleSummary` (additive, optional, nullable).
    - Populate it in the per-title build from `projection.payback_horizon_months`; leave `None` when there is no projection.
    - Keep the `{kpis, titles}` structure and all existing field names/types unchanged.
    - _Requirements: 4.1, 4.3, 4.4, 8.3_

  - [x] 3.2 Compute `model_accuracy_rate` from ground truth in the handler
    - Add `GroundTruthRepository` as a third repository alongside the existing two; read ground truth per title through the existing async repository layer, keeping the handler `async`.
    - For each title with ground truth, collapse to one value per metric name (newest by `recorded_at`, mirroring the audit collapse) into an `actuals` dict, call `actual_verdict`, and pair it with the stored `recommendation_status`.
    - Replace the literal `model_accuracy_rate=None` with `verdict_match_rate(pairs)`; exclude titles whose latest projection has a null `recommendation_status`.
    - Do not consult the harness dataset-level `verdict_match_rate`.
    - Leave `active_pipeline_valuation_usd`, `avg_ltv_to_cost`, and `portfolio_risk_exposure` computed from exactly the same inputs as today.
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 2.2, 2.4, 4.2, 5.2, 5.3, 9.1, 9.2_

  - [ ]* 3.3 Write pytest: null when zero eligible titles
    - Portfolio with no ground truth → `kpis.model_accuracy_rate is None`.
    - _Requirements: 6.1_

  - [ ]* 3.4 Write pytest: known fraction for a fixed title set
    - Fixed titles with known predicted and classifiable actual verdicts (some matching, some not) → assert the exact rounded fraction.
    - _Requirements: 6.2_

  - [ ]* 3.5 Write pytest: insufficient ground truth is excluded
    - A title with only two of four metrics is excluded; adding/removing it does not change the rate (not counted as match or miss).
    - _Requirements: 6.3_

  - [x]* 3.6 Write pytest: three existing KPIs are invariant
    - Golden assertion that `active_pipeline_valuation_usd`, `avg_ltv_to_cost`, and `portfolio_risk_exposure` are identical to the pre-enhancement computation for a fixed fixture.
    - **Feature: dashboard-accuracy-and-payback-audit, Property 6: enabling the accuracy figure leaves the three existing KPIs unchanged**
    - _Requirements: 4.2, 4.3, 6.4, 11.3_

- [x] 4. Checkpoint - dashboard handler accuracy wiring
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Thread predicted payback through the frontend option shape
  - [x] 5.1 Add `payback_horizon_months` to the frontend `TitleSummary`
    - In `frontend/lib/types.ts`, add `payback_horizon_months: number | null;` to the `TitleSummary` interface (frontend mirror of the backend field).
    - _Requirements: 8.3_

  - [x] 5.2 Carry payback through `AuditableTitleOption` and `selectAuditableTitles`
    - In `frontend/lib/backtest/select-auditable-titles.ts`, add `payback_horizon_months: number | null;` to `AuditableTitleOption` and map it from `title.payback_horizon_months` in `selectAuditableTitles`, preserving input order.
    - _Requirements: 8.4_

  - [x]* 5.3 Write vitest: selector preserves order and payback
    - **Feature: dashboard-accuracy-and-payback-audit, Property 8: selectAuditableTitles returns, in input order, the subset of titles with a non-null recommendation_status, each carrying payback_horizon_months unchanged**
    - **Validates: Requirements 8.4**

- [ ] 6. Add the payback input and read-only predicted payback to the form
  - [x] 6.1 Add the `payback_horizon` metric to `AUDITED_METRICS`
    - In `frontend/components/backtest/ground-truth-form.tsx`, extend the `AuditedMetricKey` union with `"payback_horizon"` and add the fourth `AUDITED_METRICS` entry (`label: "Actual payback horizon (months)"`), so rendering and `buildMetrics()` thread it automatically (blank omitted, non-finite rejected with a field-identifying message).
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.3_

  - [x] 6.2 Show read-only predicted payback from the selected option
    - Extend `predictedFor(key)` so `key === "payback_horizon"` returns `formatPredicted(selectedTitle?.payback_horizon_months)`, rendering the `-` placeholder when absent (never zero).
    - _Requirements: 8.1, 8.2_

  - [x]* 6.3 Write vitest: payback metric threading
    - **Feature: dashboard-accuracy-and-payback-audit, Property 7: submitting a numeric payback produces exactly one payback_horizon metric equal to that value; a blank payback omits the metric entirely**
    - Also assert a non-numeric payback blocks submission with a message identifying the payback field.
    - **Validates: Requirements 7.2, 7.3, 9.3, 10.1, 10.2, 10.4**

  - [x]* 6.4 Write vitest: predicted payback display
    - Renders the title's `payback_horizon_months` when present and the `-` placeholder when absent.
    - _Requirements: 8.1, 8.2, 10.3_

- [x] 7. Checkpoint - frontend payback input and threading
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Seed deterministic demo ground truth and verify the accuracy card
  - [x] 8.1 Emit `historical_ground_truth` rows in `generate_seed_sql.py`
    - Add a `TITLE_GROUND_TRUTH` data block and an INSERT section in `render()` for `title-echoes`: four rows (`cpvh`=0.1710, `ltv_to_cost`=3.42, `churn_reduction`=1.90, `payback_horizon`=11).
    - Use `ground_truth_id = det_uuid(f"title-echoes-gt-{metric_name}")`, `title_id = det_uuid("title-echoes")`, metric names only from `PREDICTED_METRIC_FIELDS`, and `ON CONFLICT (ground_truth_id) DO NOTHING;`.
    - Emit the section after the titles INSERT, with a SQL comment marking the rows as demo/illustrative (not production outcomes).
    - Leave every other seeded entity unchanged.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 8.2 Regenerate `02_seed_data.sql` and confirm `--check` byte-stability
    - Run `generate_seed_sql.py` to regenerate `database/seed/02_seed_data.sql`, then run `generate_seed_sql.py --check` and confirm it passes (byte-stable, idempotent).
    - _Requirements: 12.2, 12.3_

  - [ ]* 8.3 Write property test: seed idempotence and determinism
    - **Feature: dashboard-accuracy-and-payback-audit, Property 9: regenerating the seed produces byte-identical historical_ground_truth INSERTs, and re-applying inserts no duplicate and raises no error (ON CONFLICT DO NOTHING on the deterministic ground_truth_id)**
    - Hypothesis, backend, minimum 100 iterations (over re-run counts / ordering).
    - **Validates: Requirements 12.2, 12.3**

  - [x]* 8.4 Write pytest: demo seed yields a non-null matching rate
    - Load `title-echoes` (title + projection + the four seeded ground-truth rows) as a fixture, call the dashboard handler, and assert `kpis.model_accuracy_rate is not None` and equals `1.0` (the one eligible title matches, derived from at least one Eligible_Audited_Title).
    - **Feature: dashboard-accuracy-and-payback-audit, Property 10: every seeded actual passes its guardrail, so the recomputed Actual_Verdict is GREENLIGHT, equals the seeded Predicted_Verdict, and yields a non-null Model_Accuracy_Rate**
    - **Validates: Requirements 12.1, 12.4, 12.7**

- [x] 9. Final checkpoint - full suite verification
  - Run the full backend pytest suite.
  - Run the frontend typecheck, lint, and vitest suite.
  - Regenerate the seed and confirm `generate_seed_sql.py --check` passes.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test tasks) and can be skipped for a faster MVP, but they guard the honesty and determinism guarantees.
- Each task references the specific granular requirements and/or correctness property it satisfies for traceability.
- Property-based tests (Properties 1-6, 9, 10) use Hypothesis in the backend with a minimum of 100 iterations and the required `Feature: ... Property N: ...` tag; payback-threading properties (7, 8) use vitest in the frontend.
- Checkpoints provide incremental validation. Pure logic and its tests (task 1) precede the handler wiring (task 3); the seed and its integration assertion (task 8) come after the helper exists.
- Scope stays tight to the three enhancements: the backtest harness, MAPE arithmetic, `POST /backtest/audit` persistence, the three existing KPIs, and unrelated endpoints are untouched.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "3.1", "5.2", "6.1"] },
    { "id": 2, "tasks": ["3.2", "5.3", "6.2", "8.1"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "3.6", "6.3", "6.4", "8.2"] },
    { "id": 4, "tasks": ["8.3", "8.4"] }
  ]
}
```
