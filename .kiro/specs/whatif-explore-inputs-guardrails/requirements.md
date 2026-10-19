# Requirements Document

## Introduction

CineROI AI (GreenlightIQ) is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend). Its Guardrails_Engine evaluates each candidate title against four quantitative guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon) and produces a deterministic recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured explanation. The platform's core promise is that every saved verdict is defensible, deterministic, and reproducible under a stamped model version.

Today the title page has a What-If_Sensitivity panel that scales three inputs by multipliers (cost, viewership, churn) and recomputes a scorecard read-only via `POST /api/v1/valuation/{id}/what-if`, persisting nothing.

This feature, the **WhatIf_Explorer**, upgrades that capability into a first-class, highly informative exploration surface. It lets a user directly set - not just scale - the deal anchors (acquisition cost, projected viewing hours), the SVOD/AVOD revenue drivers (LTV, churn value, CPM, ad impressions, watch-time elasticity), and the guardrail thresholds (LTV-to-Cost floor, churn hurdle, CPVH ceiling, payback window), then see the recommendation and the four guardrail checks recompute live against the saved **Baseline**. Every change is shown as Baseline-versus-Scenario so the user always understands what moved and why the verdict did or did not change.

The WhatIf_Explorer is strictly a **read-only sandbox**: it persists nothing, writes no audit entry, forks no model version, and never alters the saved scorecard or the standard thresholds. It is the "explore anything" mode only; saving overrides (per-title supplied inputs) and changing policy (versioned thresholds) are explicitly out of scope and reserved for later increments. The surface MUST make its ephemeral, non-authoritative nature unmistakable so an explored scenario is never confused with the official verdict.

### Grounding (verified against the current codebase)

- `backend/app/engines/guardrails.py`: `Guardrails_Engine.evaluate_scenario(title_id, *, cost_multiplier, viewership_multiplier, churn_multiplier)` recomputes a scorecard WITHOUT persisting - it never calls `_persist` or the audit service and stamps the active model version read-only. It loads base `ValuationInputs` via the injected provider, normalizes cost, resolves base churn, scales inputs via `app/domain/sensitivity.py` `scale_inputs`, and runs the shared `_compute` core.
- `ValuationInputs` carries the SVOD/AVOD drivers: `churn_reduction_value`, `ltv`, `watch_time_elasticity`, `cpm`, `ad_impressions` (plus `churn_reduction_pct`, `monthly_margin`, `milestone_schedule`, `rate_date`). `app/domain/attribution.py` `ltv_attribution(...)` decomposes the LTV numerator into `subscription_value = churn_reduction_value * ltv` and `advertising_value = watch_time_elasticity * cpm * ad_impressions`.
- Guardrail thresholds: `CHURN_MITIGATION_THRESHOLD = Decimal("1.5")`, the LTV-to-Cost floor (3.2), the payback target window (9-12 months inclusive), and the CPVH ceilings (`app/domain/cpvh.py` `cpvh_ceiling`: 0.18 premium, 0.05 library) are the comparison yardsticks the checks use.
- The what-if API is `POST /api/v1/valuation/{title_id}/what-if` (`app/api/valuation.py`), authorized by `require_operation(Operation.VALUATION)`, with request model `WhatIfRequest` (`cost_multiplier`, `viewership_multiplier`, `churn_multiplier`, inclusive bounds [0.5, 2.0]); it returns a `ValuationScorecardResponse` and persists nothing.
- Frontend: `frontend/app/titles/[id]/_components/sensitivity-panel.tsx` is a `"use client"` panel that debounces `api.whatIf(titleId, {...multipliers})` and renders a non-persisted preview. `frontend/lib/types.ts` has `WhatIfRequest` and `MULTIPLIER_BOUNDS = { min: 0.5, max: 2.0 }`. Decimals arrive as JSON strings and are coerced with `toNumber`.
- The title deep-dive composes panels in `title-evaluation-view.tsx`; the standard page chrome is `AppShell` with `TopNav`. Backend tests use pytest (+ Hypothesis) under `backend/tests/{domain,engines,api}`; the frontend uses Vitest + Testing Library.

## Glossary

- **WhatIf_Explorer**: The feature described by this document - a dedicated, read-only exploration surface for a title where a user directly sets revenue drivers and guardrail thresholds and sees the verdict recompute live against the saved Baseline, persisting nothing.
- **Baseline**: The title's saved scorecard and the standard (model-version) thresholds, taken as the reference point. Every explored value is shown relative to its Baseline.
- **Scenario**: The current set of user-entered Input_Overrides and Threshold_Overrides, and the recommendation and guardrail checks recomputed from them.
- **Input_Overrides**: Explicit values for the SVOD/AVOD revenue drivers - LTV, churn value, CPM, ad impressions, watch-time elasticity - replacing the modeled Baseline inputs for the Scenario only.
- **Threshold_Overrides**: Explicit values for the guardrail yardsticks - LTV-to-Cost floor, churn hurdle, CPVH ceiling, payback window - replacing the Baseline thresholds for the Scenario only.
- **Scenario_Diff**: The per-field and per-check comparison of Baseline versus Scenario (old value, new value, direction, and whether a guardrail's pass/breach changed), plus a plain-language summary of what the user changed and the resulting verdict movement.
- **Read_Only_Sandbox**: The rule that the WhatIf_Explorer persists nothing, writes no audit entry, forks no model version, and never mutates the saved scorecard or the standard thresholds.
- **Macro_Multiplier**: One of the existing proportional scalers (cost, viewership, churn) that scales a Baseline value by a factor. Retained for coarse exploration; superseded by a direct Input_Override for the same dimension.
- **Scenario_Presets**: Named one-click scenarios that set a coherent group of overrides at once - Bear Case, Bull Case, and Target Deal (the latter derived from the stored negotiation ceiling that clears all correctable guardrails).
- **Scenario_Link**: A shareable representation of the current Scenario encoded entirely in the URL query string, so a scenario can be copied, bookmarked, and reopened without persisting anything server-side.

## Requirements

### Requirement 1: Direct, read-only exploration of inputs and thresholds

**User Story:** As a content buyer, I want to directly set the revenue drivers and guardrail thresholds for a title and see the verdict recompute live, so that I can explore "what would it take for this to clear?" without touching the saved record.

#### Acceptance Criteria

1. THE WhatIf_Explorer SHALL let the user set Input_Overrides for the deal anchors and the SVOD/AVOD revenue drivers - acquisition cost (`cost_usd`), projected viewing hours (`projected_viewing_hours`), the modeled churn-reduction percentage (`churn_reduction_pct`, the value compared to the 1.5% hurdle - distinct from `churn_reduction_value`, the per-subscriber dollar amount in the LTV equation), LTV, churn value, CPM, ad impressions, and watch-time elasticity - and recompute the Scenario from them. Direct dollar/integer overrides are required because buyers negotiate in exact figures (for example "what if the seller accepts $7.5M?"), not only in proportional multipliers.
2. THE WhatIf_Explorer SHALL let the user set Threshold_Overrides for each guardrail yardstick (LTV-to-Cost floor, churn hurdle, CPVH ceiling, payback-window maximum) and recompute the Scenario from them.
3. WHEN no override is set for a field, THE WhatIf_Explorer SHALL use that field's Baseline value, so an untouched explorer reproduces the saved scorecard's verdict exactly.
4. THE WhatIf_Explorer SHALL remain a Read_Only_Sandbox: it SHALL persist nothing, write no audit entry, fork no model version, and leave the saved scorecard and the standard thresholds unchanged.
5. THE WhatIf_Explorer SHALL continue to support the existing cost / viewership / churn Macro_Multipliers alongside the new direct overrides, so the current sensitivity behavior is preserved.
6. WHEN both a direct Input_Override and a Macro_Multiplier are supplied for the same dimension (e.g. `cost_usd` vs `cost_multiplier`, `projected_viewing_hours` vs `viewership_multiplier`, or `churn_reduction_pct` vs `churn_multiplier`), THE WhatIf_Explorer SHALL let the direct Input_Override take precedence and SHALL ignore the corresponding Macro_Multiplier for that dimension.
7. WHEN acquisition cost is modified in a Scenario (via Macro_Multiplier or direct `cost_usd` override), THE WhatIf_Explorer SHALL scale every milestone payment disbursement proportionally by (Scenario cost / Baseline cost) before computing the payback horizon, so the payback walk stays coherent with the modeled cost.
8. WHEN an override value is non-numeric, non-finite, or outside its allowed range, THE WhatIf_Explorer SHALL reject it through the standard validation envelope and SHALL NOT recompute from an invalid value. The allowed ranges are:

   | Parameter | Allowed range | Unit |
   |---|---|---|
   | `cost_usd` | 1.00 - 999,999,999.00 | USD |
   | `projected_viewing_hours` | 1 - 5,000,000,000 | hours |
   | `ltv` | 0.01 - 10,000.00 | USD |
   | `churn_reduction_value` | 0.01 - 1,000.00 | USD |
   | `cpm` | 0.50 - 250.00 | USD per 1,000 impressions |
   | `ad_impressions` | 0 - 100,000,000,000 | count |
   | `watch_time_elasticity` | 0.00 - 5.00 | ratio |
   | `churn_reduction_pct` | 0.10 - 5.00 | percentage points |
   | `cpvh_ceiling_override` | 0.01 - 2.00 | USD/hr |
   | `ltv_hurdle_override` | 1.00 - 10.00 | ratio multiple |
   | `churn_hurdle_override` | 0.10 - 5.00 | percentage points |
   | `payback_max_months_override` | 1 - 36 | months |

   The existing Macro_Multipliers retain their current inclusive bounds [0.5, 2.0].

### Requirement 2: Crystal-clear Baseline-versus-Scenario presentation

**User Story:** As an executive, I want to see exactly what I changed and how it moved the verdict, so that an explored scenario is never ambiguous.

#### Acceptance Criteria

1. THE WhatIf_Explorer SHALL display, for every editable field, its Baseline value alongside the current Scenario value.
2. THE WhatIf_Explorer SHALL display each of the four guardrail checks as Baseline versus Scenario - the computed value, the threshold in force, and the pass/breach status for each side - and SHALL show the LTV attribution split (SVOD subscription value vs AVOD ad-yield value) as Baseline versus Scenario, so the user sees which lever moved which check and how the revenue mix shifted.
3. WHEN Threshold_Overrides are applied, THE WhatIf_Explorer SHALL compute all pass/breach classifications, shortfall magnitudes, and the dominant factor against the Scenario's overridden thresholds (not the Baseline thresholds), so a relaxed hurdle correctly re-classifies a check and re-selects the dominant factor.
4. WHEN the Scenario recommendation differs from the Baseline recommendation, THE WhatIf_Explorer SHALL state the change explicitly in plain language (for example, that the scenario would change the verdict from one status to another).
5. THE WhatIf_Explorer SHALL present a plain-language Scenario_Diff summary of what the user changed and the resulting verdict movement.
6. THE WhatIf_Explorer SHALL provide a per-field reset and a global reset that return the Scenario to the Baseline.
7. WHILE a recompute is in flight, THE WhatIf_Explorer SHALL show a pending indicator and SHALL ignore stale responses superseded by a newer change.

### Requirement 3: Dedicated, unmistakably-ephemeral surface

**User Story:** As a user, I want the explorer to be its own clear space that I can never confuse with the official decision, so that exploration stays safe.

#### Acceptance Criteria

1. THE WhatIf_Explorer SHALL be presented as a dedicated tab or view on the title page, distinct from the saved Scorecard view, giving the controls and comparison room to be read clearly.
2. THE WhatIf_Explorer SHALL display a persistent, prominent notice that the surface is an exploration sandbox whose results are not saved and that the official scorecard is unchanged.
3. THE WhatIf_Explorer SHALL be excluded from the Greenlight Memo PDF export so an explored scenario never appears on an executive deliverable.
4. WHEN the explorer first opens, THE WhatIf_Explorer SHALL start from the Baseline and SHALL offer a short guided empty state with one-click Scenario_Presets so a first-time user knows how to begin. The presets are: **Bear Case** (viewership -25%, CPM -20%, churn -15%); **Bull Case** (viewership +30%, CPM +25%, churn +20%); and **Target Deal** (set acquisition cost to the stored negotiation ceiling that clears all correctable guardrails, leaving other inputs at Baseline). IF a title has no viable correctable ceiling - because it is already GREENLIGHT (no discount needed), or it carries a non-correctable (structural churn) breach that no price can fix - THEN the Target Deal preset SHALL be disabled with an explanatory tooltip (for example, "Already GREENLIGHT - no price change needed" or "Target deal unavailable: a structural churn breach cannot be resolved by price"), rather than setting a cost that still fails.
5. THE WhatIf_Explorer SHALL be accessible and keyboard-operable (labeled controls, focus handling, and status announced to assistive technology).
6. THE WhatIf_Explorer SHALL encode the active Scenario (its overrides and multipliers) entirely in the URL query string as a Scenario_Link, so a scenario can be copied, bookmarked, shared, and reopened - and survive a page refresh - without persisting anything server-side. Opening a Scenario_Link SHALL restore that exact Scenario.

### Requirement 4: Backend recompute endpoint

**User Story:** As a frontend developer, I want one read-only endpoint that recomputes a scenario from overrides, so that the explorer calls the backend the same way the rest of the app does.

#### Acceptance Criteria

1. THE WhatIf_Explorer SHALL extend the existing stateless what-if recompute path to accept optional Input_Overrides and Threshold_Overrides in addition to the current multipliers, remaining backward-compatible with requests that send only multipliers.
2. THE WhatIf_Explorer endpoint SHALL be authorized through the existing RBAC read permission and SHALL persist nothing and record no audit entry.
3. THE WhatIf_Explorer SHALL return, in its response, enough information to render the Scenario_Diff: the Scenario recommendation and guardrail checks, the Baseline values and thresholds used, and the recomputed LTV attribution split (SVOD subscription value vs AVOD ad-yield value) reflecting the active Scenario overrides, so the user sees how their input changes shifted the revenue mix.
4. THE WhatIf_Explorer SHALL expose the Baseline negotiation ceiling (the cost at which all correctable guardrails clear) so the frontend can populate the Target Deal preset without a second request.
5. WHEN a cost override is applied, THE WhatIf_Explorer backend SHALL apply the proportional milestone-schedule scaling (R1.7) and the direct-override-wins precedence (R1.6) inside the stateless recompute, so the payback and attribution math reflect the Scenario coherently.
6. WHEN the title does not exist, THE WhatIf_Explorer SHALL return the standard not-found envelope; WHEN an override is invalid, it SHALL return the standard validation envelope.

### Requirement 5: Tests and documentation

**User Story:** As a maintainer, I want the explorer covered by tests and documented everywhere the platform is documented, so that it stays correct and discoverable.

#### Acceptance Criteria

1. THE WhatIf_Explorer SHALL include backend tests covering: an untouched scenario reproducing the Baseline verdict, an Input_Override changing a guardrail outcome, a Threshold_Override changing a guardrail outcome, invalid-override rejection, and the Read_Only_Sandbox guarantee (no persistence, no audit entry).
2. THE WhatIf_Explorer SHALL include a frontend test covering an override recompute, the Baseline-versus-Scenario rendering, and a reset.
3. THE WhatIf_Explorer SHALL update the in-portal How It Works guide, the knowledge-base and architecture documents, and the NotebookLM export so the feature is documented in every place the platform documents its features.