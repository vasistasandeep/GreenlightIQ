# Implementation Plan: What-If Sensitivity

## Overview

Convert the feature design into a series of prompts for a code-generation LLM
that will implement each step with incremental progress. Each prompt builds on
the previous prompts and ends with wiring things together; there is no hanging
or orphaned code that is not integrated into a previous step. The plan focuses
only on tasks that involve writing, modifying, or testing code.

The build proceeds bottom-up: the pure scaling helper first (property-testable
in isolation), then the engine refactor that extracts `_compute` and adds
`evaluate_scenario`, then the stateless `/what-if` endpoint, then the frontend
client/types and the Sensitivity panel wired into the title view. Checkpoints
separate the backend domain/engine work, the frontend work, and the final
cross-stack verification. Backend uses Python (Hypothesis for property tests);
frontend uses TypeScript (vitest + Testing Library), matching the design.

## Tasks

- [x] 1. Create the pure scaling domain module `app/domain/sensitivity.py`
  - [x] 1.1 Implement `scale_inputs` and the `ScaledInputs` dataclass
    - Create `backend/app/domain/sensitivity.py` as a new pure module (no I/O),
      mirroring the `app/domain/*` layout (`cpvh.py`, `ltv.py`, `cohort.py`).
    - Define inclusive bounds `MULTIPLIER_MIN = Decimal("0.5")` and
      `MULTIPLIER_MAX = Decimal("2.0")` (both include 1.0).
    - Define `@dataclass(frozen=True) class ScaledInputs` carrying
      `inputs: ValuationInputs` and `viewing_hours: Decimal | None` (scaled
      hours travel alongside the inputs because hours live on the title, not on
      `ValuationInputs`).
    - Implement `scale_inputs(base, base_viewing_hours, *, cost_multiplier,
      viewership_multiplier, churn_multiplier) -> ScaledInputs` that returns a
      scaled COPY of `base` and never mutates `base`: scale `ad_impressions *=
      viewership_multiplier`, `churn_reduction_pct *= churn_multiplier`, and
      `viewing_hours = base_viewing_hours * viewership_multiplier` (a `None`
      base-hours value yields `None`). Cost is NOT scaled here (the engine scales
      the already-normalized USD amount by `cost_multiplier`).
    - Import `ValuationInputs` from the engine module (or a shared types module)
      consistent with how the design references it.
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 4.4_

  - [x]* 1.2 Write property test for field scaling (Property 2)
    - Generate base `ValuationInputs`, a base viewing-hours value (including
      `None`), and in-bounds multipliers; assert `scaled.churn_reduction_pct ==
      base.churn_reduction_pct * churn_multiplier`, `scaled.ad_impressions ==
      base.ad_impressions * viewership_multiplier`, and `scaled.viewing_hours ==
      base_viewing_hours * viewership_multiplier` (with `None` -> `None`).
    - Use Hypothesis, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 2: Scaling applies each multiplier to its target field exactly`
    - **Property 2: Scaling applies each multiplier to its target field exactly**
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [x]* 1.3 Write property test for base immutability (Property 3)
    - Deep-copy the base `ValuationInputs` before calling `scale_inputs`; assert
      every field of the original base is field-wise unchanged after the call.
    - Use Hypothesis, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 3: Scaling never mutates the base inputs`
    - **Property 3: Scaling never mutates the base inputs**
    - **Validates: Requirements 5.5**

- [x] 2. Refactor the Guardrails_Engine to extract `_compute` and add the scenario path
  - [x] 2.1 Add a `viewing_hours_override` parameter to `_cpvh_check`
    - In `backend/app/engines/guardrails.py`, add an optional
      `viewing_hours_override: Decimal | None = None` parameter to `_cpvh_check`.
      When `None` (the `evaluate` path), read `title.projected_viewing_hours`
      exactly as today (behavior unchanged, including the zero/None-hours guard,
      R4.5). When supplied (the scenario path), use that value instead. Do not
      mutate the title object.
    - _Requirements: 5.2, 3.3_

  - [x] 2.2 Extract the pure compute core into `_compute`
    - Introduce `_compute(self, title, inputs, normalized, exchange_rate_id,
      stamp, weighting, *, cpvh_hours_override=None) -> ValuationResult` that
      performs NO I/O: move the four guardrail checks, `determine_recommendation`,
      and the deal-support attribution/cohort block into it verbatim, passing
      `cpvh_hours_override` through to `_cpvh_check`. It performs no persistence
      and no audit.
    - Reorganize `evaluate` to `load + normalize + stamp + territory_weighting ->
      _compute(...) -> _persist -> audit.record -> return`, keeping its public
      contract and observable behavior unchanged so the existing suite stays
      green.
    - _Requirements: 3.3, 3.4_

  - [x]* 2.3 Write property test for identity scenario (Property 1)
    - Generate a title + `ValuationInputs` with in-memory fakes for
      repositories/audit; assert `evaluate_scenario(1.0, 1.0, 1.0)` yields the
      same recommendation status and the same four metrics (CPVH, LTV-to-cost
      multiple, churn-reduction pct, payback-horizon months) as the un-scaled
      compute core / `evaluate` result for the same inputs.
    - Use Hypothesis, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 1: Identity scenario reproduces the persisted scorecard`
    - **Property 1: Identity scenario reproduces the persisted scorecard**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

  - [x] 2.4 Implement `evaluate_scenario` (no persist, no audit)
    - Add `async def evaluate_scenario(self, title_id, *, cost_multiplier,
      viewership_multiplier, churn_multiplier) -> ValuationResult`:
      `load title (TitleNotFoundError if missing, R1.3) -> get_inputs ->
      _normalize_cost -> stamp (read-only active-version lookup; never written,
      R2.3) -> territory_weighting -> scaled_cost = normalized.amount_usd *
      cost_multiplier (R5.1) -> scaled = scale_inputs(inputs,
      title.projected_viewing_hours, ...) -> _compute(title, scaled.inputs,
      NormalizedCost(scaled_cost, ...), exchange_rate_id, stamp, weighting,
      cpvh_hours_override=scaled.viewing_hours)`.
    - Wrap the scaled cost in a `NormalizedCost` so `_compute` is agnostic to
      cost scaling; pass `exchange_rate_id` through unchanged. NEVER call
      `_persist` or `self._audit.record` on this path.
    - _Requirements: 1.1, 1.3, 2.3, 2.4, 5.1_

  - [x]* 2.5 Write property test for cost monotonicity (Property 4)
    - Generate inputs + two cost multipliers `m1 <= m2` in bounds (viewership and
      churn fixed); assert the recomputed CPVH is non-decreasing in the cost
      multiplier and the recomputed LTV-to-cost multiple is non-increasing.
    - Use Hypothesis, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 4: Cost multiplier moves CPVH and the LTV multiple in the modeled direction`
    - **Property 4: Cost multiplier moves CPVH and the LTV multiple in the modeled direction**
    - **Validates: Requirements 5.1**

  - [x]* 2.6 Write property test for viewership monotonicity (Property 5)
    - Generate inputs + two viewership multipliers `m1 <= m2` in bounds (cost and
      churn fixed); assert the recomputed CPVH is non-increasing in the
      viewership multiplier and the recomputed LTV-to-cost multiple is
      non-decreasing.
    - Use Hypothesis, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 5: Viewership multiplier moves CPVH down and the LTV multiple up`
    - **Property 5: Viewership multiplier moves CPVH down and the LTV multiple up**
    - **Validates: Requirements 5.2, 5.3**

  - [x]* 2.7 Write engine-level no-persist / no-audit spy test
    - With a spy audit service and a projection-repo spy, assert
      `evaluate_scenario` triggers zero persist calls and zero audit calls while
      still returning a complete `ValuationResult`.
    - _Requirements: 2.4_

- [x] 3. Checkpoint - domain and engine tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add the stateless `POST /{title_id}/what-if` endpoint
  - [x] 4.1 Implement `WhatIfRequest` and the `/what-if` route
    - In `backend/app/api/valuation.py`, add `class WhatIfRequest(BaseModel)`
      with `cost_multiplier` and `viewership_multiplier` required and
      `churn_multiplier` defaulting to `Decimal("1.0")`; each field uses
      `Field(gt=Decimal("0"), ge=Decimal("0.5"), le=Decimal("2.0"))` so
      non-positive and out-of-bounds values yield a 422 before the handler runs.
    - Add `async def what_if_valuation(title_id, body, actor, session, engine)`
      decorated `@router.post("/{title_id}/what-if",
      response_model=ValuationScorecardResponse,
      dependencies=[Depends(require_operation(Operation.VALUATION))])`. Call
      `engine.evaluate_scenario(...)` with the three multipliers.
    - Build the `ValuationScorecardResponse` the SAME way `quick_evaluate` does
      (full LTV attribution split populated from the fresh `ValuationResult`:
      `subscription_value`, `advertising_value`, `total_modeled_value`, cohort),
      using `negotiation.*` for levers/ceiling/discount. Explicitly do NOT call
      `session.commit()`.
    - Rely on the existing error envelope to map `TitleNotFoundError` to
      `404 TITLE_NOT_FOUND` (R1.3) and Pydantic validation to `422` (R4.1, R4.2).
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4, 5.1_

  - [x]* 4.2 Write API example tests for the happy path and contract fields
    - Known title + valid multipliers -> `200` with recommendation status and all
      four metrics plus deal-support fields populated (R1.1, R1.2).
    - Assert a Decimal field (e.g. `ltv_to_cost_multiple`) serializes as a JSON
      string (R1.4).
    - Body omitting `churn_multiplier` yields the same result as
      `churn_multiplier = 1.0` (R1.5).
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

  - [x]* 4.3 Write API example tests for not-found and the no-persistence invariant
    - Unknown title id -> `404 TITLE_NOT_FOUND`, no scorecard (R1.3).
    - Capture the stored projection (values + `row_version`) before, POST
      what-if, assert the row is unchanged (R2.1) and `model_version_id` is
      unchanged (R2.3).
    - Assert the audit-entry count is unchanged before vs after a what-if call
      (R2.2).
    - _Requirements: 1.3, 2.1, 2.2, 2.3_

  - [x]* 4.4 Write API tests for bounds (Property 6) and RBAC parity
    - `0` and negative multipliers -> `422`; exact bounds `0.5`, `1.0`, `2.0`
      accepted; `0.49` and `2.01` rejected -> `422` (the `WhatIfRequest`
      validation bounds test).
    - A role denied `Operation.VALUATION` receives `403`, parity with
      `GET /valuation`.
    - Use Hypothesis for the bounds test, minimum 100 iterations.
    - Tag: `Feature: what-if-sensitivity, Property 6: Multipliers are accepted exactly within their bounds`
    - **Property 6: Multipliers are accepted exactly within their bounds**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

- [x] 5. Add the frontend types and API client method
  - [x] 5.1 Add `WhatIfRequest`, `MULTIPLIER_BOUNDS`, and `api.whatIf`
    - In `frontend/lib/types.ts`, add `export interface WhatIfRequest {
      cost_multiplier: number; viewership_multiplier: number; churn_multiplier?:
      number; }` and `export const MULTIPLIER_BOUNDS = { min: 0.5, max: 2.0 } as
      const;`.
    - In `frontend/lib/api-client.ts`, add `whatIf(titleId, body, options?)` that
      POSTs to `/valuation/${titleId}/what-if` and returns
      `ValuationScorecard` (reusing the existing response type). Import
      `WhatIfRequest` into the client's type imports.
    - _Requirements: 1.5, 4.4, 6.3, 7.2_

- [x] 6. Build the Sensitivity panel and wire it into the title view
  - [x] 6.1 Implement `sensitivity-panel.tsx`
    - Create
      `frontend/app/titles/[id]/_components/sensitivity-panel.tsx` as a
      `"use client"` component `SensitivityPanel({ titleId })`.
    - Render three sliders: cost percentage, viewership bear/base/bull, and churn
      percentage, each constrained to `MULTIPLIER_BOUNDS` (min 0.5 / max 2.0) and
      all initialized to `1.0` (cost/churn step 0.05 over [0.5, 2.0]; viewership
      maps bear/base/bull to {0.5, 1.0, 2.0}).
    - Debounce ~400ms on the three multiplier values (clear the pending timer on
      each change; fire `api.whatIf(titleId, multipliers)` once after the quiet
      interval; track in-flight requests so a newer response supersedes an older
      one).
    - On response, render `RecommendationBadge` with the returned status and the
      four metrics (CPVH, LTV multiple, churn %, payback months), each coerced
      via `format.ts` `toNumber`; a value that cannot be coerced to a finite
      number renders a placeholder while the other metrics still render.
    - Always display the ASCII-only label `Scenario preview - not saved`. Use
      ASCII-only characters for every user-facing string. Give the panel root the
      existing `no-print` class.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1, 9.2_

  - [x] 6.2 Wire `SensitivityPanel` into `title-evaluation-view.tsx`
    - Render `<SensitivityPanel titleId={titleId} />` inside the
      `state.status === "ready"` grid as a full-width `lg:col-span-2` block so it
      appears only once a persisted scorecard has loaded.
    - _Requirements: 6.1_

  - [x]* 6.3 Write interaction tests for the Sensitivity panel
    - Three sliders render with accessible labels; `min`/`max` equal
      `MULTIPLIER_BOUNDS` (0.5 / 2.0); initial values are `1.0` (R6.1, R6.3,
      R6.4).
    - With fake timers, several rapid changes within the interval collapse to a
      single `api.whatIf` call after ~400ms carrying the latest multipliers
      (R7.1, R7.2).
    - A mocked response updates the `RecommendationBadge` status and the four
      metric values (R7.3).
    - The label `Scenario preview - not saved` is present and panel strings are
      ASCII-only (R8.1, R8.2, R6.2).
    - String-encoded metric values render as formatted numbers (R9.1); a
      non-coercible metric renders a placeholder while the other three render
      (R9.2).
    - The panel root carries `no-print` so it is excluded from the Greenlight
      Memo print.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1, 9.2_

- [x] 7. Checkpoint - frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Final cross-stack verification
  - [x] 8.1 Run the backend test suite
    - Run `python -m pytest -q -p no:cacheprovider` from `backend/`; confirm the
      183-test baseline plus the new property and example tests are green.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.2 Run the frontend checks
    - Run `npm run typecheck && npm run lint && npm run build && npx vitest run`
      from `frontend/`; confirm all are green.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1, 9.2_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a
  faster MVP; core implementation sub-tasks are never optional.
- Each task references specific requirements (granular sub-requirements) for
  traceability.
- Checkpoints ensure incremental validation at the backend, frontend, and
  cross-stack boundaries.
- Property tests validate the universal correctness properties (identity,
  field scaling, immutability, cost/viewership monotonicity, bounds); unit and
  example tests validate specific contracts, side-effect absence, and UI
  behavior.
- The engine refactor (task 2.2) moves the compute core verbatim so the
  persisting `evaluate` path's observable behavior and the existing suite are
  unaffected.
- UI strings are ASCII-only; metric rendering uses defensive string->number
  coercion via `format.ts` `toNumber`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.4"] },
    { "id": 4, "tasks": ["2.3", "2.5", "2.6", "2.7"] },
    { "id": 5, "tasks": ["4.1", "5.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "4.4", "6.1"] },
    { "id": 7, "tasks": ["6.2", "6.3"] },
    { "id": 8, "tasks": ["8.1", "8.2"] }
  ]
}
```
