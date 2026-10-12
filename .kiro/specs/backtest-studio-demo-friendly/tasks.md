# Implementation Plan: Backtest Studio Demo-Friendly

## Overview

This is a frontend-only change. The work proceeds in dependency order: first the two
pure helpers (`selectAuditableTitles`, `mapAuditError`) with their property-based
tests, then the `GroundTruthForm` selector rework and its tests, then the
`BacktestStudioPage` wiring (fetch + filter + load status + error mapping) and its
tests, and a final verification pass over the whole frontend toolchain and suite. No
backend files are edited. Property tests use `fast-check` with >= 100 iterations and
are tagged `Feature: backtest-studio-demo-friendly, Property N: ...`.

## Tasks

- [x] 1. Set up test tooling and pure helpers
  - [x] 1.1 Add the `fast-check` dev dependency
    - Add `fast-check` to `devDependencies` in `frontend/package.json` and install it so
      the new property-based tests can import it (no other dependency changes)
    - This supports the property tests in tasks 1.3, 2.2, 2.3, 2.4
    - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 1.2 Create the pure `selectAuditableTitles` helper and shared view types
    - Create `frontend/lib/backtest/select-auditable-titles.ts`
    - Declare `AuditableTitleOption = { title_id: string; title_name: string }` and
      `TitlesLoadStatus = "loading" | "loaded" | "empty" | "error"`
    - Implement `selectAuditableTitles(titles: TitleSummary[]): AuditableTitleOption[]`
      that keeps only titles whose `recommendation_status !== null` and projects each
      to `{ title_id, title_name }`, preserving order
    - Keep the module pure (no React, no fetch) so it is directly property-testable
    - _Requirements: 2.2, 2.3_

  - [x]* 1.3 Write property test for `selectAuditableTitles`
    - Create `frontend/lib/backtest/select-auditable-titles.test.ts`
    - **Property 1: Auditable filter selects exactly the titles with a stored prediction**
    - Use `fast-check` (>= 100 iterations) over arrays of `TitleSummary`-shaped records
      with `recommendation_status` drawn from `{null, "GREENLIGHT", "NEGOTIATE_HARD", "PASS"}`;
      assert the result equals exactly the non-null entries by identity and count and
      excludes every null-status title
    - Tag: `Feature: backtest-studio-demo-friendly, Property 1: Auditable filter selects exactly the titles with a stored prediction`
    - _Requirements: 2.2_

- [x] 2. Implement the audit error message mapper
  - [x] 2.1 Create the pure `mapAuditError` function
    - Create `frontend/lib/backtest/map-audit-error.ts`
    - Implement `mapAuditError(err: unknown): string` branching on `ApiError`
      `errorCode`/`status`: `VALIDATION_FAILED` -> invalid/missing-title message;
      `status === 404 && TITLE_NOT_FOUND` -> "no longer exists" message;
      `status === 404 && GROUND_TRUTH_MISSING` -> "no stored prediction" message;
      `GROUND_TRUTH_INVALID` -> numeric-values message; unmapped code -> envelope
      `message` when a non-empty string, else the generic message; non-`ApiError` ->
      the generic message
    - Compose every returned string from ASCII characters only
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x]* 2.2 Write property test for known-code mapping
    - Create `frontend/lib/backtest/map-audit-error.test.ts`
    - **Property 2: Known error codes map to their specific actionable message**
    - Use `fast-check` (>= 100 iterations) generating `ApiError`s over the mapped-code
      set (honoring the 404 status distinction for the `TITLE_NOT_FOUND` /
      `GROUND_TRUTH_MISSING` pair) with arbitrary envelope messages; assert the exact
      per-code message
    - Add a couple of concrete per-branch examples for readability
    - Tag: `Feature: backtest-studio-demo-friendly, Property 2: Known error codes map to their specific actionable message`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x]* 2.3 Write property test for the unmapped-code fallback
    - Extend `frontend/lib/backtest/map-audit-error.test.ts`
    - **Property 3: Unmapped codes fall back to the envelope message, else the generic message**
    - Use `fast-check` (>= 100 iterations) generating `ApiError`s with codes outside the
      mapped set and optional/empty messages; assert envelope-message-when-non-empty,
      else the generic message
    - Add concrete examples (unmapped code with a message; unmapped code without a message)
    - Tag: `Feature: backtest-studio-demo-friendly, Property 3: Unmapped codes fall back to the envelope message, else the generic message`
    - _Requirements: 3.5_

  - [x]* 2.4 Write property test for the ASCII-only invariant
    - Extend `frontend/lib/backtest/map-audit-error.test.ts`
    - **Property 4: Mapper output is ASCII-only**
    - Use `fast-check` (>= 100 iterations) generating arbitrary inputs (varied `ApiError`s
      including non-ASCII envelope messages, plus non-`ApiError` values); assert every
      output character has a code point below 128
    - Tag: `Feature: backtest-studio-demo-friendly, Property 4: Mapper output is ASCII-only`
    - _Requirements: 3.6_

- [x] 3. Checkpoint - helpers pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Rework `GroundTruthForm` to use a title selector
  - [x] 4.1 Replace the free-text title input with a title `<select>` and new props
    - Modify `frontend/components/backtest/ground-truth-form.tsx`
    - Extend `GroundTruthFormProps` with `titles: AuditableTitleOption[]` and
      `titlesStatus: TitlesLoadStatus` (import both from
      `@/lib/backtest/select-auditable-titles`); keep `onSubmit`, `submitting`, `className`
    - Replace the `#gt-title-id` text input with a `<select id="gt-title-id">` labeled
      "Historical title", with a disabled placeholder option and one option per title
      (option text = `title_name`, value = `title_id`); the placeholder text reflects
      `titlesStatus` ("Loading titles..." while loading)
    - Change local state from free-text `titleId` to `selectedTitleId: string` set from
      the selected option value, and emit `title_id` as the selected value
    - Keep `AUDITED_METRICS`, `buildMetrics`, blank-field omission, and the
      `onSubmit({ title_id, metrics })` contract unchanged
    - Disable the submit button when `submitting`, OR no title is selected, OR
      `titlesStatus !== "loaded"`
    - When `titlesStatus === "empty"`, render the inline ASCII message
      "No titles with a stored prediction are available to audit."
    - Reuse the existing theme utility classes (`inputClass`, `border-border`,
      `bg-background`, etc.) so the dark AppShell styling is preserved
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.4, 4.3, 4.4_

  - [x]* 4.2 Update the `GroundTruthForm` tests for the selector and new props
    - Modify `frontend/components/backtest/ground-truth-form.test.tsx`
    - Pass `titles` + `titlesStatus="loaded"` in the shared setup and select a title via
      the combobox instead of typing an id; adapt "submits a shaped request", "omits
      blank metric fields", "blocks when no actuals", and "disables controls while
      submitting"
    - Replace the free-text "trims whitespace" and "missing title identifier" tests with
      selector equivalents: renders a selector listing each `title_name` as an option
      (R1.1, R1.2); selecting an option sets the submitted `title_id` (R1.3); submit
      stays disabled until a title is selected (R1.4); `titlesStatus="empty"` renders
      the no-auditable-titles message and keeps submit disabled (R2.4)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.4, 4.3_

- [x] 5. Wire the title lifecycle and error mapping into `BacktestStudioPage`
  - [x] 5.1 Load auditable titles on mount and pass them to the form
    - Modify `frontend/app/backtest/page.tsx`
    - Add state `titles: AuditableTitleOption[]`, `titlesStatus: TitlesLoadStatus`
      (initial `"loading"`), and `titlesError: string | null`
    - Add a `useEffect` on mount that calls `api.getDashboardSummary()`, derives the
      auditable list via `selectAuditableTitles(summary.titles)`, and sets status to
      `"loaded"` when non-empty or `"empty"` when none; on failure set status `"error"`
      and the fixed ASCII message "Could not load auditable titles. Please retry."
    - Pass `titles` and `titlesStatus` to `GroundTruthForm`
    - Render the titles-load-failure message near the existing audit `role="alert"`
      paragraph when `titlesStatus === "error"`
    - _Requirements: 2.1, 2.3, 2.5_

  - [x] 5.2 Route the audit error path through `mapAuditError`
    - In `frontend/app/backtest/page.tsx`, replace the audit-path
      `setAuditError(messageFor(err))` with `setAuditError(mapAuditError(err))`
    - Leave the calibration and finalization error paths on the existing `messageFor`
      helper; leave the success path (variance scorecard, MAPE, calibration enablement,
      sign-off) unchanged
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.5_

  - [x]* 5.3 Write page tests for load, error, mapping, and success regression
    - Create `frontend/app/backtest/page.test.tsx` following existing component-test
      conventions (vitest + Testing Library), mocking the `api` client
    - On mount the page calls `api.getDashboardSummary` and passes only auditable titles
      to the form (R2.1, R2.3)
    - A failed summary fetch renders the load-failure message and keeps submit disabled
      (R2.5)
    - An audit rejection renders the `mapAuditError` output in the alert (spot-check one
      mapped code end-to-end) (R3)
    - The success path still renders the variance scorecard/MAPE and enables calibration
      (R4.1, R4.2 regression)
    - _Requirements: 2.1, 2.3, 2.5, 3.1, 4.1, 4.2_

- [x] 6. Final verification and checkpoint
  - [x] 6.1 Run the frontend toolchain and full test suite
    - From `frontend/`, run `npm run typecheck`, `npm run lint`, `npm run build`, and
      `npm test` (vitest run) and confirm all green; the suite was 98 tests and grows
      with the new tests added above
    - Fix any type, lint, build, or test failures surfaced
    - _Requirements: 4.1, 4.2, 4.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; the core
  implementation tasks are never optional.
- Each task references the specific requirement sub-IDs it satisfies for traceability.
- Property tests use `fast-check` with >= 100 iterations and are tagged
  `Feature: backtest-studio-demo-friendly, Property N: ...`, each referencing a design
  Correctness Property.
- This is a frontend-only change; no backend, audit-compute, calibration, or auth
  modules are modified.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1"] },
    { "id": 1, "tasks": ["1.3", "2.2", "4.1"] },
    { "id": 2, "tasks": ["2.3", "4.2", "5.1"] },
    { "id": 3, "tasks": ["2.4", "5.2"] },
    { "id": 4, "tasks": ["5.3"] },
    { "id": 5, "tasks": ["6.1"] }
  ]
}
```
