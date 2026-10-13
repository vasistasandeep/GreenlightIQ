# Implementation Plan: Deal Decision Support

## Overview

This plan implements the three additive decision aids (Negotiation Playbook, LTV-to-Cost Attribution Breakdown, Absolute Churn Cohort Numbers) in dependency order: pure backend domain modules first (each a `hypothesis` property-test target), then engine wiring, then response schemas, then router composition, then frontend types and rendering, closing with a full-suite verification task.

Every task surfaces or derives values the `Guardrails_Engine` already computes. No thresholds, guardrail math, recommendation logic, persistence, or DB migration are touched (R12). All code mirrors the existing conventions: `Decimal`-only domain functions with float rejection, Decimal-as-JSON-string serialization, defensive `num()`/`toNumber()` coercion on the frontend, and ASCII-only UI strings.

## Tasks

- [ ] 1. Negotiation domain module (`backend/app/domain/negotiation.py`)
  - [ ] 1.1 Create `backend/app/domain/negotiation.py` with the pure negotiation helpers
    - Add a local `_as_decimal` guard mirroring `app/domain/ltv.py` that rejects `float` and `bool` inputs with `TypeError`.
    - Import `GuardrailCheck` from `app.domain.recommendation`; define `GuardrailName` Literal, `CounterProposalLever` TypedDict (`name`, `correctable`, `message`).
    - Implement `cpvh_implied_ceiling(normalized_cost_usd, computed_cpvh, cpvh_ceiling)` returning `normalized_cost_usd * (cpvh_ceiling / computed_cpvh)` unrounded, requiring `computed_cpvh > 0`.
    - Implement `ltv_implied_ceiling(normalized_cost_usd, computed_multiple, ltv_threshold)` returning `normalized_cost_usd * (computed_multiple / ltv_threshold)` unrounded, requiring `ltv_threshold > 0`.
    - Implement `target_purchase_ceiling(normalized_cost_usd, checks)`: binding (smallest) per-guardrail ceiling across breached, cost-correctable CPVH/LTV checks, rounded to whole USD; return `None` when cost `<= 0` or no cost-correctable CPVH/LTV guardrail is breached.
    - Implement `implied_discount_pct(current_ask_usd, ceiling_usd)`: `(current_ask - ceiling) / current_ask * 100` rounded to 1 dp; `0` when ceiling `>=` ask; `None` when ask `<= 0` or ceiling is `None`.
    - Implement `counter_proposal_levers(checks)`: one lever per breached check keyed by guardrail name + correctable flag using the design's ASCII-only rule table (unclassifiable `correctable is None` uses the structural message; unknown name uses the generic fallback); empty list when no breaches.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 1.2 Write property tests `backend/tests/domain/test_negotiation_properties.py`
    - Mirror `test_ltv_properties.py` conventions: Decimal-only strategies, `@settings(max_examples=200)`, one test per property, each tagged `# Feature: deal-decision-support, Property N: <text>`.
    - **Property 1: CPVH-implied ceiling** - formula + breach-direction iff. _Validates: Requirements 1.1_
    - **Property 2: LTV-implied ceiling** - formula + recomputed multiple equals threshold within rounding. _Validates: Requirements 1.2_
    - **Property 3: Target purchase ceiling is the binding minimum** - rounded whole-dollar minimum and null cases. _Validates: Requirements 1.3, 1.4, 1.5, 1.6_
    - **Property 4: Implied discount non-negative, clamped, rounded, null case**. _Validates: Requirements 2.1, 2.2, 2.3, 2.4_
    - **Property 5: One lever per breached check, correctly keyed and classified**. _Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5_
    - **Property 6: Lever messages are ASCII only**. _Validates: Requirements 3.2, 3.3_
    - **Property 10: Monetary helpers reject float inputs and compute exactly** (for `cpvh_implied_ceiling`, `ltv_implied_ceiling`). _Validates: Requirements 1.7_

- [ ] 2. Attribution domain module (`backend/app/domain/attribution.py`)
  - [ ] 2.1 Create `backend/app/domain/attribution.py` with `ltv_attribution`
    - Reuse the `_as_decimal` float-rejection pattern from `ltv.py`.
    - Define `LtvAttribution` TypedDict (`subscription_value`, `advertising_value`, `total_modeled_value`, `normalized_cost_usd`, `multiple`).
    - Implement `ltv_attribution(churn_reduction_value, ltv, watch_time_elasticity, cpm, ad_impressions, cost_usd)` with the signature identical to `compute_ltv_to_cost`; compute `subscription_value = churn_reduction_value * ltv` and `advertising_value = watch_time_elasticity * cpm * ad_impressions` with the SAME operand order as `compute_ltv_to_cost`; `total = subscription + advertising`; `multiple = total / cost_usd`; raise `ZeroDivisionError` on zero cost and `TypeError` on floats.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 2.2 Write property tests `backend/tests/domain/test_attribution_properties.py`
    - **Property 7: Attribution decomposes the numerator exactly** (subscription, advertising, total, multiple). _Validates: Requirements 5.1, 5.2, 5.3, 5.4_
    - **Property 8: Attribution multiple agrees with `compute_ltv_to_cost`** - generate the six inputs and assert equality. _Validates: Requirements 5.5_
    - **Property 10: `ltv_attribution` rejects float inputs and computes exactly**. _Validates: Requirements 5.6_

- [ ] 3. Cohort domain module (`backend/app/domain/cohort.py`)
  - [ ] 3.1 Create `backend/app/domain/cohort.py` with cohort helpers
    - Reuse the `_as_decimal` float-rejection pattern from `ltv.py`.
    - Implement `retained_subscribers(modeled_cohort_size, churn_reduction_pct)` = `round(size * (pct / 100))` to a whole number; `None` when size `<= 0` or `None`; `0` when pct `<= 0` and size `> 0`; floats rejected.
    - Implement `derive_modeled_cohort_size(normalized_cost_usd)` = `floor(normalized_cost_usd)` (one modeled subscriber per whole USD, labeled `Derived_Figure`); `None` when cost `<= 0` or `None`.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 8.1_

  - [ ]* 3.2 Write property tests `backend/tests/domain/test_cohort_properties.py`
    - **Property 9: Retained subscribers is a non-negative whole number with correct boundary cases**. _Validates: Requirements 7.1, 7.2, 7.3, 7.4_
    - **Property 10: `retained_subscribers` rejects float inputs and computes exactly**. _Validates: Requirements 7.5_

- [ ] 4. Checkpoint - Ensure all domain tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Extend the Guardrails_Engine (`backend/app/engines/guardrails.py`)
  - [ ] 5.1 Extend `ValuationResult` and `ValuationInputs` and compute the new values in `evaluate`
    - Add five additive keys to `ValuationResult`: `ltv_subscription_value`, `ltv_advertising_value`, `ltv_total_modeled_value`, `modeled_cohort_size`, `retained_subscribers` (each `Decimal | None`).
    - Add one optional defaulted field to `ValuationInputs`: `modeled_cohort_size: Decimal | None = None`.
    - In `evaluate`, after `_ltv_check` produces the multiple from the territory-weighted `weighted_cpm`/`weighted_ltv`, call `attribution.ltv_attribution(...)` with the SAME operands (R6.2) and store the three sub-values.
    - Source cohort size from `inputs.modeled_cohort_size` when present, else `cohort.derive_modeled_cohort_size(normalized.amount_usd)`; compute `cohort.retained_subscribers(size, inputs.churn_reduction_pct)`.
    - Wrap attribution/cohort derivation so any failure degrades the five fields to `None` without blocking the core valuation.
    - Do NOT modify `_projection_values` or `_audit_after` (no persistence, no migration).
    - _Requirements: 6.1, 6.2, 8.1, 8.2, 12.1, 12.2, 12.3_

  - [ ]* 5.2 Write engine example tests
    - Attribution sub-values are consistent with `ltv_to_cost_multiple`; cohort size/retained are carried; cohort size falls back to the documented derivation when the provider supplies none.
    - Recommendation status and the four thresholds are unchanged for representative titles (scope preservation).
    - _Requirements: 6.1, 6.2, 8.1, 8.2, 12.1, 12.2_

- [ ] 6. Response schema sub-models (`backend/app/schemas/api.py`)
  - [ ] 6.1 Add Pydantic sub-models and extend `ValuationScorecardResponse`
    - Add `CounterProposalLeverOut` (`name`, `correctable: bool | None = None`, `message`), `LtvAttributionOut` (`subscription_value`, `advertising_value`, `total_modeled_value`, `normalized_cost_usd`, `multiple`, all `Decimal | None = None`), `ChurnCohortOut` (`churn_reduction_pct`, `modeled_cohort_size`, `retained_subscribers` as `Decimal | None`, `derived: bool = True`).
    - Add five fields to `ValuationScorecardResponse`: `target_purchase_ceiling_usd: Decimal | None = None`, `implied_discount_pct: Decimal | None = None`, `counter_proposal_levers: list[CounterProposalLeverOut] = Field(default_factory=list)`, `ltv_attribution: LtvAttributionOut | None = None`, `churn_cohort: ChurnCohortOut | None = None`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.3, 6.4, 6.5, 8.3, 8.4, 8.5_

  - [ ] 6.2 Extend `QuickEvaluateResponse` (`backend/app/api/quick_evaluate.py`)
    - Import the three sub-models from `app/schemas/api.py`; add the four new fields (`implied_discount_pct`, `counter_proposal_levers`, `ltv_attribution`, `churn_cohort`) to `QuickEvaluateResponse` alongside the existing `target_purchase_ceiling_usd`.
    - _Requirements: 4.1, 4.2, 4.4, 6.3, 6.5, 8.3, 8.5_

- [ ] 7. Router wiring
  - [ ] 7.1 Wire `quick_evaluate.py` to the negotiation helper and engine fields
    - Delete the router-local `_target_ceiling`, `c_name`, and the ceiling-only use of `_raw_checks`; import `negotiation`.
    - Build `target_purchase_ceiling_usd` and `implied_discount_pct` via `negotiation.target_purchase_ceiling(result["normalized_cost_usd"], explanation["checks"])` and `negotiation.implied_discount_pct(result["normalized_cost_usd"], ceiling)`.
    - Build `counter_proposal_levers` from `negotiation.counter_proposal_levers(explanation["checks"])` mapped to `CounterProposalLeverOut`.
    - Build `ltv_attribution` (`LtvAttributionOut`) from `result["ltv_subscription_value"]`/`ltv_advertising_value`/`ltv_total_modeled_value`/`normalized_cost_usd`/`ltv_to_cost_multiple`, serializing null when the multiple is unavailable.
    - Build `churn_cohort` (`ChurnCohortOut`) from `result["churn_reduction_pct"]`/`modeled_cohort_size`/`retained_subscribers` with `derived=True`.
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 6.3, 6.4, 6.5, 8.3, 8.4, 8.5_

  - [ ] 7.2 Wire `valuation.py` to reconstruct the three objects from the persisted projection
    - After loading the projection, call `negotiation.target_purchase_ceiling(projection.normalized_cost_usd, explanation["checks"])` and `negotiation.implied_discount_pct(...)`, and `negotiation.counter_proposal_levers(explanation["checks"])`.
    - Reconstruct `ltv_attribution` as the total (`ltv_to_cost_multiple * normalized_cost_usd`) + normalized cost + multiple, with subscription/advertising split serialized null (honest degradation); serialize `ltv_attribution` null when the multiple is absent (R6.5).
    - Reconstruct `churn_cohort` via `cohort.derive_modeled_cohort_size(normalized_cost_usd)` + `cohort.retained_subscribers(size, churn_reduction_pct)`, always carrying `churn_reduction_pct` with `derived=True`; size/retained null when cost is non-positive (R8.5).
    - _Requirements: 4.3, 4.5, 4.6, 6.3, 6.4, 6.5, 8.3, 8.4, 8.5_

  - [ ]* 7.3 Write API-level example tests for both routers
    - `quick-evaluate` and `GET /valuation/{title_id}` return the five new fields; monetary/percentage values serialize as JSON strings; null branches: GREENLIGHT -> null ceiling/discount and empty levers; absent multiple -> null attribution; no cohort size -> null size/retained with percentage retained.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.3, 6.5, 8.3, 8.5_

- [ ] 8. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Frontend types (`frontend/lib/types.ts`)
  - [ ] 9.1 Add decision-support interfaces and extend response types
    - Add `CounterProposalLever` (`name`, `correctable: boolean | null`, `message`), `LtvAttribution` (five fields typed `number | string | null`), `ChurnCohort` (`churn_reduction_pct`, `modeled_cohort_size`, `retained_subscribers` as `number | string | null`, `derived: boolean`).
    - Extend `QuickEvaluateResponse` and `ValuationScorecard` with `target_purchase_ceiling_usd` (add to `ValuationScorecard`), `implied_discount_pct`, `counter_proposal_levers`, `ltv_attribution`, `churn_cohort`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.3, 8.3_

- [ ] 10. Title Evaluation view rendering
  - [ ] 10.1 Extend `negotiation-leverage.tsx`
    - Render target ceiling (`formatUsd`) and implied discount (`formatPercent`/`formatNumber`) when present and decision is NEGOTIATE_HARD/PASS; omit for GREENLIGHT.
    - Render server-provided `counter_proposal_levers` labeled by guardrail, preferring them over locally-derived levers, falling back when absent.
    - Coerce all new monetary/percentage values via `toNumber()` before formatting; ASCII-only strings.
    - _Requirements: 9.1, 9.3, 9.5, 9.6_

  - [ ] 10.2 Extend `financial-accordion.tsx`
    - In the CPVH/LTV section, when `scorecard.ltv_attribution` is present render subscription value, advertising value, total modeled value, normalized cost, and multiple; fall back to the plain multiple when null.
    - In the churn section, when `churn_cohort.retained_subscribers` is non-null render retained subscribers next to the percentage with a derived/modeled label; fall back to percentage only when null.
    - Coerce new values via `toNumber()`; ASCII-only strings.
    - _Requirements: 10.1, 10.3, 10.4, 11.1, 11.3, 11.4_

  - [ ]* 10.3 Write interaction tests for the title view components
    - NEGOTIATE_HARD/PASS vs GREENLIGHT (ceiling/discount shown vs omitted); server levers shown; attribution split present vs null fallback; retained subscribers with derived label vs null fallback; string-decimal coercion renders numbers not NaN.
    - _Requirements: 9.1, 9.3, 9.5, 9.6, 10.1, 10.3, 10.4, 11.1, 11.3, 11.4_

- [ ] 11. Asset Studio view rendering
  - [ ] 11.1 Add `subscribers()` formatter to `frontend/app/studio/_components/helpers.ts`
    - Integer with grouping, em dash when null; reuse existing `num`/`usd`/`pct`/`multiple`.
    - _Requirements: 11.2_

  - [ ] 11.2 Extend `valuation-report.tsx`
    - Add implied discount beside the existing ceiling banner; add a counter-proposal levers panel (omit for GREENLIGHT); add an LTV attribution panel (fall back to multiple when null); add retained subscribers beside churn with a derived label.
    - Coerce all new values via `num()`; ASCII-only strings.
    - _Requirements: 9.2, 9.4, 9.5, 9.6, 10.2, 10.3, 10.4, 11.2, 11.3, 11.4_

  - [ ]* 11.3 Write interaction tests for the studio view
    - NEGOTIATE_HARD/PASS vs GREENLIGHT; levers panel; attribution panel present vs null fallback; retained subscribers with derived label vs null fallback; string-decimal coercion.
    - _Requirements: 9.2, 9.4, 9.5, 9.6, 10.2, 10.3, 10.4, 11.2, 11.3, 11.4_

- [ ] 12. Final verification
  - [ ] 12.1 Run the full backend and frontend suites and resolve any failures
    - Backend: `python -m pytest -q -p no:cacheprovider` from `backend/` (expect the current 168 passed plus the new property/example tests, all green).
    - Frontend: `npm run typecheck && npm run lint && npm run build && npx vitest run` from `frontend/` (expect the current 116 tests plus new interaction tests, all green).
    - Fix any type, lint, build, or test failures introduced by this feature.
    - _Requirements: 12.1, 12.2, 12.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP; they are the test sub-tasks.
- Each task references specific requirement sub-clauses for traceability.
- Checkpoints (tasks 4, 8) ensure incremental validation; task 12 is the final full-suite gate.
- Property tests validate the universal correctness properties on the three pure domain modules; example/interaction tests cover response wiring and rendering (which are not PBT targets).
- No deploy, git, or DB-migration tasks: the feature is response-composition only and persists nothing new.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.2", "5.1"] },
    { "id": 2, "tasks": ["5.2", "6.1"] },
    { "id": 3, "tasks": ["6.2"] },
    { "id": 4, "tasks": ["7.1", "7.2", "9.1", "11.1"] },
    { "id": 5, "tasks": ["7.3", "10.1", "10.2", "11.2"] },
    { "id": 6, "tasks": ["10.3", "11.3"] },
    { "id": 7, "tasks": ["12.1"] }
  ]
}
```
