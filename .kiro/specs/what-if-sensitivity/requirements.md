# Requirements Document

## Introduction

CineROI AI evaluates acquisition titles and produces a persisted valuation scorecard: a recommendation status (GREENLIGHT, NEGOTIATE_HARD, PASS) plus four guardrail metrics (CPVH, LTV-to-cost multiple, churn-reduction percentage, payback-horizon months), an explanation, and deal-support fields. Today that scorecard is produced only by the persisting valuation path, which writes to the database and records an audit entry.

An enterprise UX audit asked for interactive "what-if" sensitivity analysis on the title evaluation view. Executives want to drag sliders for cost, viewership, and churn mitigation and watch the recommendation badge and the four guardrail metrics recompute live, WITHOUT changing any stored record. Typical questions: "What viewership would turn this NEGOTIATE_HARD green?" or "What if churn mitigation underperforms by 20%?"

This feature adds a stateless recompute path. The backend exposes a read-only endpoint that applies bounded scenario multipliers to a title's existing modeled inputs, re-runs the SAME pure guardrail math and recommendation logic the persisting path uses, and returns a freshly computed scorecard without persisting anything or writing an audit entry. The frontend adds a Sensitivity panel to the title view with debounced sliders that call the endpoint on change and render the recomputed badge and metrics, clearly labeled as a non-persisted scenario preview.

Two invariants anchor the design: the recompute path never mutates state (no DB write, no audit entry, no model-version change), and a scenario with all multipliers equal to 1.0 reproduces the title's persisted recommendation and metrics (the scenario math reuses the existing domain functions without altering thresholds or recommendation logic).

## Glossary

- **What_If_Endpoint**: The stateless backend endpoint `POST /api/v1/valuation/{title_id}/what-if` that recomputes a scorecard over scaled inputs and returns it without persisting.
- **Scenario_Recompute**: The pure recompute routine (a new domain helper or a non-persisting engine method, decided in design) that applies scenario multipliers to a title's base valuation inputs, runs the four guardrail checks, and calls the existing recommendation logic.
- **Scenario_Multipliers**: The three scalar inputs to a scenario: Cost_Multiplier, Viewership_Multiplier, and Churn_Multiplier.
- **Cost_Multiplier**: A positive scalar that scales the normalized acquisition cost in USD. A value above 1 raises cost (raising CPVH, lowering the LTV-to-cost multiple); below 1 lowers cost.
- **Viewership_Multiplier**: A positive scalar representing a bear/base/bull viewership assumption that scales projected viewing hours (lowering CPVH) and advertising impressions proportionally (raising advertising LTV value).
- **Churn_Multiplier**: A positive scalar that scales the modeled churn-reduction percentage used by the churn-mitigation guardrail.
- **Scorecard**: The computed result set: recommendation status, CPVH, LTV-to-cost multiple, churn-reduction percentage, payback-horizon months, explanation, and deal-support fields.
- **Recommendation_Status**: One of GREENLIGHT, NEGOTIATE_HARD, or PASS, produced by the existing `determine_recommendation` function.
- **Guardrail_Metrics**: The four scorecard metrics: CPVH, LTV-to-cost multiple, churn-reduction percentage, and payback-horizon months.
- **Persisted_Scorecard**: The scorecard the persisting valuation path (`Guardrails_Engine.evaluate`) stored for the title, read from `financial_projections`.
- **Base_Inputs**: The title's modeled valuation inputs (`ValuationInputs`) sourced from the active `title_versions` snapshot by the input provider, before any scenario scaling.
- **Multiplier_Bounds**: The validated inclusive numeric range each Scenario_Multiplier must fall within; values outside the range or non-positive are rejected.
- **Sensitivity_Panel**: The frontend component on the title evaluation view that presents the scenario sliders and renders the recomputed Scorecard.
- **Scenario_Preview_Label**: The ASCII-only UI text that marks the rendered Scorecard as a non-persisted scenario, worded "Scenario preview - not saved".
- **Debounce_Interval**: The quiet period after the last slider change before the Sensitivity_Panel issues a What_If_Endpoint request.
- **Identity_Scenario**: A scenario in which Cost_Multiplier, Viewership_Multiplier, and Churn_Multiplier are all exactly 1.0.

## Requirements

### Requirement 1: Stateless what-if recompute endpoint

**User Story:** As a content buyer, I want to request a recomputed scorecard for a title under scenario multipliers without changing any saved data, so that I can explore acquisition outcomes safely during a live negotiation.

#### Acceptance Criteria

1. WHEN a What_If_Endpoint request is received with a known title identifier and valid Scenario_Multipliers, THE What_If_Endpoint SHALL return a Scorecard computed over the scaled Base_Inputs.
2. WHEN the What_If_Endpoint returns a Scorecard, THE What_If_Endpoint SHALL include Recommendation_Status, CPVH, LTV-to-cost multiple, churn-reduction percentage, payback-horizon months, the explanation, and the deal-support fields.
3. IF the title identifier does not correspond to an existing title, THEN THE What_If_Endpoint SHALL return a not-found error response and SHALL return no Scorecard.
4. THE What_If_Endpoint SHALL serialize each Decimal-valued field of the Scorecard as a JSON string.
5. WHERE the caller supplies no Churn_Multiplier, THE What_If_Endpoint SHALL treat the Churn_Multiplier as 1.0.

### Requirement 2: No-persistence invariant

**User Story:** As a CFO, I want certainty that running what-if scenarios never alters the official record, so that exploratory analysis cannot corrupt audited valuations.

#### Acceptance Criteria

1. WHEN the What_If_Endpoint processes a request, THE What_If_Endpoint SHALL leave every stored financial-projection record unchanged.
2. WHEN the What_If_Endpoint processes a request, THE What_If_Endpoint SHALL create no audit entry.
3. WHEN the What_If_Endpoint processes a request, THE What_If_Endpoint SHALL leave the title's stored model-version stamp unchanged.
4. WHEN the Scenario_Recompute executes, THE Scenario_Recompute SHALL complete without invoking the persistence routine or the audit routine of the valuation path.

### Requirement 3: Identity scenario reproduces the persisted result

**User Story:** As a content buyer, I want the baseline scenario to match the official scorecard exactly, so that I trust the sensitivity tool reflects the real evaluation.

#### Acceptance Criteria

1. WHEN the What_If_Endpoint evaluates an Identity_Scenario for a title that has a Persisted_Scorecard, THE What_If_Endpoint SHALL return the same Recommendation_Status as the Persisted_Scorecard.
2. WHEN the What_If_Endpoint evaluates an Identity_Scenario for a title that has a Persisted_Scorecard, THE What_If_Endpoint SHALL return the same CPVH, LTV-to-cost multiple, churn-reduction percentage, and payback-horizon months as the Persisted_Scorecard.
3. THE Scenario_Recompute SHALL apply the same guardrail thresholds that the persisting valuation path applies.
4. THE Scenario_Recompute SHALL determine Recommendation_Status using the same recommendation logic that the persisting valuation path applies.

### Requirement 4: Bounded and validated scenario multipliers

**User Story:** As a content buyer, I want absurd or invalid slider values rejected, so that scenario results stay within a defensible modeling range.

#### Acceptance Criteria

1. IF a submitted Cost_Multiplier, Viewership_Multiplier, or Churn_Multiplier is less than or equal to zero, THEN THE What_If_Endpoint SHALL return a validation error response and SHALL return no Scorecard.
2. IF a submitted Scenario_Multiplier falls outside its Multiplier_Bounds, THEN THE What_If_Endpoint SHALL return a validation error response and SHALL return no Scorecard.
3. WHEN a submitted Scenario_Multiplier is within its Multiplier_Bounds, THE What_If_Endpoint SHALL accept the Scenario_Multiplier and compute a Scorecard.
4. THE What_If_Endpoint SHALL define Multiplier_Bounds that include 1.0 for every Scenario_Multiplier.

### Requirement 5: Scenario scaling of valuation inputs

**User Story:** As a content buyer, I want the sliders to move cost, viewership, and churn in the modeled direction, so that the recomputed metrics reflect the economics of each assumption.

#### Acceptance Criteria

1. WHEN the Scenario_Recompute applies a Cost_Multiplier, THE Scenario_Recompute SHALL scale the normalized acquisition cost in USD by the Cost_Multiplier before running the CPVH check and the LTV-to-cost check.
2. WHEN the Scenario_Recompute applies a Viewership_Multiplier, THE Scenario_Recompute SHALL scale the projected viewing hours by the Viewership_Multiplier before running the CPVH check.
3. WHEN the Scenario_Recompute applies a Viewership_Multiplier, THE Scenario_Recompute SHALL scale the advertising impressions by the Viewership_Multiplier before running the LTV-to-cost check.
4. WHEN the Scenario_Recompute applies a Churn_Multiplier, THE Scenario_Recompute SHALL scale the modeled churn-reduction percentage by the Churn_Multiplier before running the churn-mitigation check.
5. THE Scenario_Recompute SHALL leave the Base_Inputs value sourced from the title snapshot unchanged after computing a Scorecard.

### Requirement 6: Sensitivity panel on the title view

**User Story:** As an executive, I want a sliders panel on the title evaluation view, so that I can adjust cost, viewership, and churn assumptions directly where I read the recommendation.

#### Acceptance Criteria

1. WHERE a title evaluation view is displayed, THE Sensitivity_Panel SHALL present a cost-percentage slider, a viewership bear/base/bull slider, and a churn-percentage slider.
2. THE Sensitivity_Panel SHALL render every user-facing string using ASCII-only characters.
3. WHEN the Sensitivity_Panel renders a slider, THE Sensitivity_Panel SHALL constrain the slider range to the Multiplier_Bounds of the corresponding Scenario_Multiplier.
4. WHEN the Sensitivity_Panel initializes, THE Sensitivity_Panel SHALL set every slider to the Identity_Scenario value of 1.0.

### Requirement 7: Debounced live recompute from the panel

**User Story:** As an executive, I want results to update shortly after I stop dragging, so that I see live feedback without overwhelming the service with requests.

#### Acceptance Criteria

1. WHEN a slider value changes, THE Sensitivity_Panel SHALL wait for the Debounce_Interval to elapse with no further change before issuing a What_If_Endpoint request.
2. WHEN the Debounce_Interval elapses after the last slider change, THE Sensitivity_Panel SHALL issue a What_If_Endpoint request carrying the current Scenario_Multipliers.
3. WHEN a What_If_Endpoint response arrives, THE Sensitivity_Panel SHALL render the returned Recommendation_Status on the recommendation badge and the returned four Guardrail_Metrics.

### Requirement 8: Non-persisted scenario labeling

**User Story:** As an executive, I want the recomputed values clearly marked as unofficial, so that I never mistake a scenario preview for the saved decision.

#### Acceptance Criteria

1. WHEN the Sensitivity_Panel displays a recomputed Scorecard, THE Sensitivity_Panel SHALL display the Scenario_Preview_Label text "Scenario preview - not saved".
2. THE Sensitivity_Panel SHALL render the Scenario_Preview_Label using ASCII-only characters.

### Requirement 9: Defensive numeric coercion in the panel

**User Story:** As an executive, I want the panel to render metrics reliably regardless of serialization format, so that the preview never breaks on string-encoded numbers.

#### Acceptance Criteria

1. WHEN the Sensitivity_Panel receives a Guardrail_Metric value encoded as a JSON string, THE Sensitivity_Panel SHALL coerce the value to a number before formatting it for display.
2. IF a received Guardrail_Metric value cannot be coerced to a finite number, THEN THE Sensitivity_Panel SHALL display a placeholder in place of the metric value and SHALL continue rendering the remaining metrics.
