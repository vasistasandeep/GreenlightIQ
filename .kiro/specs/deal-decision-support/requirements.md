# Requirements Document

## Introduction

CineROI AI is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend) whose Guardrails_Engine evaluates each candidate title against four quantitative guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon) and produces a greenlight recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured explanation.

An enterprise UX audit found the per-title scorecard too opaque for executives making multi-million-dollar acquisition decisions. This feature, **Deal Decision Support**, adds three tightly related capabilities on top of the Guardrails_Engine's existing outputs. All three render on both decision surfaces that already show a valuation scorecard: the title evaluation view (`frontend/app/titles/[id]/`) and the Asset Studio instant scorecard (`frontend/app/studio/`).

1. **Negotiation Playbook** — When a decision is NEGOTIATE_HARD or PASS driven by a correctable breach (CPVH too high, or LTV-to-cost too low), present a concrete target purchase ceiling in USD, the implied discount versus the current ask, and plain-language counter-proposal levers keyed to which guardrail breached and its correctable classification.
2. **LTV-to-Cost Attribution Breakdown** — Decompose the opaque LTV-to-cost multiple into the SVOD subscription-value contribution and the AVOD ad-yield contribution the engine already computes internally, alongside the total modeled value, the normalized cost, and the resulting multiple.
3. **Absolute Churn Cohort Numbers** — Alongside the churn-reduction percentage, present the absolute cohort impact (approximate retained subscribers) derived from the modeled cohort size, clearly labeled as a derived/modeled figure.

The scope is strictly limited to **surfacing and composing data the engine already computes** (or deriving honest figures from existing modeled inputs) and rendering it. This feature MUST NOT change recommendation thresholds or the core guardrail math.

### Grounding (verified against the current codebase)

- `backend/app/engines/guardrails.py` computes the LTV-to-Cost multiple via `compute_ltv_to_cost(churn_reduction_value, ltv, watch_time_elasticity, cpm, ad_impressions, cost_usd)`; the subscription value (`churn_reduction_value * ltv`) and advertising value (`watch_time_elasticity * cpm * ad_impressions`) sub-components are computed inside `app/domain/ltv.py` but are **not** carried on `ValuationResult` today.
- `app/domain/cpvh.py` exposes `cpvh_ceiling(asset_type)` and `cpvh_breaches(cpvh, ceiling)`. The quick-evaluate path (`app/api/quick_evaluate.py`) already derives `target_purchase_ceiling_usd` via a private `_target_ceiling(result)` helper; that logic is local to the router and is **not** a reusable pure domain function.
- `QuickEvaluateResponse` carries `recommendation_status`, `explanation`, `metadata_profile`, `target_purchase_ceiling_usd`, `normalized_cost_usd`, and the four guardrail outputs. `ValuationScorecardResponse` (`GET /valuation/{title_id}`) carries the persisted guardrail outputs and `explanation` but does **not** carry `target_purchase_ceiling_usd`, an LTV attribution split, or an absolute cohort figure.
- The `Explanation` carries per-guardrail checks with `name`, `computed_value`, `threshold`, `passed`, `breached`, `shortfall_magnitude`, and `correctable`.
- `ValuationInputs` carries `churn_reduction_pct` but does **not** carry an absolute modeled cohort size today.
- Decimal values are serialized as JSON strings over the wire; the frontend coerces defensively (`num()` / `toNumber()`).
- Backend tests use pytest + hypothesis (property tests over pure domain functions); frontend tests use vitest + Testing Library. The title view already has a `NegotiationLeverage` component and a `FinancialAccordion`; the studio view already has a `ValuationReport` that renders a target-purchase-ceiling banner.

## Glossary

- **Deal_Decision_Support**: The feature described by this document: Negotiation Playbook, LTV-to-Cost attribution breakdown, and absolute churn cohort numbers, rendered on the title evaluation and Asset Studio scorecards.
- **Guardrails_Engine**: The existing financial engine (`backend/app/engines/guardrails.py`) that evaluates the four guardrails and emits a `ValuationResult` containing the recommendation status and `Explanation`.
- **Negotiation_Helper**: The new pure domain module that computes the target purchase ceiling and implied discount for cost-correctable guardrail breaches.
- **Attribution_Helper**: The new pure domain module that decomposes the LTV-to-Cost numerator into its subscription-value and advertising-value components.
- **Cohort_Helper**: The new pure domain module that derives the absolute retained-subscriber cohort impact from the modeled cohort size and churn-reduction percentage.
- **Target_Purchase_Ceiling**: The maximum normalized acquisition cost in USD at which every cost-correctable breached guardrail (CPVH, LTV-to-Cost) would pass; the binding (smallest) per-guardrail ceiling.
- **Implied_Discount_Pct**: `(current_ask_usd - target_purchase_ceiling_usd) / current_ask_usd * 100`, the percentage reduction from the current normalized ask to the target ceiling.
- **Counter_Proposal_Lever**: A plain-language, rule-based negotiation suggestion keyed to a specific breached guardrail and its correctable classification.
- **Subscription_Value_Contribution**: The SVOD portion of the LTV-to-Cost numerator = `churn_reduction_value * ltv` (territory-weighted LTV), expressed in USD.
- **Advertising_Value_Contribution**: The AVOD portion of the LTV-to-Cost numerator = `watch_time_elasticity * cpm * ad_impressions` (territory-weighted CPM), expressed in USD.
- **Total_Modeled_Value**: The full LTV-to-Cost numerator = Subscription_Value_Contribution + Advertising_Value_Contribution, expressed in USD.
- **Modeled_Cohort_Size**: The modeled count of addressable subscribers from which the churn-reduction percentage is applied; sourced from a modeled input or derived from existing modeled inputs.
- **Retained_Subscribers**: The absolute cohort impact = `Modeled_Cohort_Size * (churn_reduction_pct / 100)`, rounded to a whole number of subscribers.
- **Derived_Figure**: Any figure not persisted as a direct engine output, labeled as derived/modeled in the response and the UI, consistent with existing modeled-placeholder labeling.
- **Title_Evaluation_View**: The Next.js title evaluation surface at `frontend/app/titles/[id]/` and its `_components`.
- **Asset_Studio_View**: The Next.js Asset Studio instant-scorecard surface at `frontend/app/studio/` and its `_components`.
- **ValuationResult**: The `TypedDict` returned by `Guardrails_Engine.evaluate`.
- **Valuation_Scorecard_Response**: The response model `ValuationScorecardResponse` for `GET /valuation/{title_id}`.
- **Quick_Evaluate_Response**: The response model `QuickEvaluateResponse` for `POST /api/v1/titles/quick-evaluate`.

## Requirements

### Requirement 1: Negotiation target purchase ceiling computation

**User Story:** As a content buyer, I want the system to compute the exact price at which a correctably breached guardrail would pass, so that I know the ceiling to negotiate the seller down to.

#### Acceptance Criteria

1. WHEN the Negotiation_Helper is given the normalized cost in USD and the computed CPVH value and its ceiling for a breached, correctable CPVH check, THE Negotiation_Helper SHALL return the CPVH-implied ceiling as `normalized_cost_usd * (cpvh_ceiling / computed_cpvh)`.
2. WHEN the Negotiation_Helper is given the normalized cost in USD and the computed LTV-to-Cost multiple and its threshold for a breached, correctable LTV-to-Cost check, THE Negotiation_Helper SHALL return the LTV-implied ceiling as `normalized_cost_usd * (computed_multiple / threshold)`.
3. WHEN more than one cost-correctable guardrail is breached, THE Negotiation_Helper SHALL return the smallest per-guardrail ceiling as the Target_Purchase_Ceiling.
4. WHERE no cost-correctable guardrail is breached, THE Negotiation_Helper SHALL return null for the Target_Purchase_Ceiling.
5. IF the normalized cost in USD is less than or equal to zero, THEN THE Negotiation_Helper SHALL return null for the Target_Purchase_Ceiling.
6. WHEN the Negotiation_Helper returns a Target_Purchase_Ceiling, THE Negotiation_Helper SHALL round the value to a whole number of United States dollars.
7. THE Negotiation_Helper SHALL compute every monetary value using decimal arithmetic without introducing binary-floating-point representation error.

### Requirement 2: Implied discount computation

**User Story:** As a content buyer, I want to see the discount percentage the target ceiling represents versus the current ask, so that I can frame the counter-offer to the seller.

#### Acceptance Criteria

1. WHEN the Negotiation_Helper is given a current ask in USD greater than zero and a Target_Purchase_Ceiling, THE Negotiation_Helper SHALL return the Implied_Discount_Pct as `(current_ask_usd - target_purchase_ceiling_usd) / current_ask_usd * 100`.
2. WHERE the Target_Purchase_Ceiling is greater than or equal to the current ask in USD, THE Negotiation_Helper SHALL return an Implied_Discount_Pct of zero.
3. IF the current ask in USD is less than or equal to zero, THEN THE Negotiation_Helper SHALL return null for the Implied_Discount_Pct.
4. WHEN the Negotiation_Helper returns an Implied_Discount_Pct, THE Negotiation_Helper SHALL round the value to one decimal place.

### Requirement 3: Counter-proposal levers

**User Story:** As a content buyer, I want plain-language negotiation levers tied to the specific guardrail that breached, so that I have concrete talking points for the counter-proposal.

#### Acceptance Criteria

1. WHEN a decision is NEGOTIATE_HARD or PASS and at least one guardrail check is breached, THE Deal_Decision_Support SHALL return one Counter_Proposal_Lever per breached guardrail check.
2. WHERE a breached guardrail check has a correctable classification of true, THE Deal_Decision_Support SHALL return a Counter_Proposal_Lever describing a cost or terms action that moves the check within its threshold.
3. WHERE a breached guardrail check has a correctable classification of false, THE Deal_Decision_Support SHALL return a Counter_Proposal_Lever describing a non-cost structural action keyed to that guardrail.
4. THE Deal_Decision_Support SHALL key each Counter_Proposal_Lever to the breached guardrail by its `name` value of CPVH, LTV_TO_COST, CHURN_MITIGATION, or PAYBACK_HORIZON.
5. WHERE a decision is GREENLIGHT, THE Deal_Decision_Support SHALL return an empty list of Counter_Proposal_Levers.

### Requirement 4: Negotiation Playbook in backend responses

**User Story:** As a frontend developer, I want the negotiation target ceiling, implied discount, and levers available in the scorecard responses, so that both decision surfaces can render the playbook from one contract.

#### Acceptance Criteria

1. THE Quick_Evaluate_Response SHALL carry a `target_purchase_ceiling_usd` field computed through the Negotiation_Helper.
2. THE Quick_Evaluate_Response SHALL carry an `implied_discount_pct` field computed through the Negotiation_Helper from the normalized cost and the Target_Purchase_Ceiling.
3. THE Valuation_Scorecard_Response SHALL carry a `target_purchase_ceiling_usd` field and an `implied_discount_pct` field computed through the Negotiation_Helper.
4. THE Quick_Evaluate_Response and THE Valuation_Scorecard_Response SHALL each carry a `counter_proposal_levers` field containing the Counter_Proposal_Levers for the decision.
5. WHERE a cost-correctable guardrail ceiling cannot be computed for a title, THE Quick_Evaluate_Response and THE Valuation_Scorecard_Response SHALL serialize `target_purchase_ceiling_usd` and `implied_discount_pct` as null.
6. THE Quick_Evaluate_Response and THE Valuation_Scorecard_Response SHALL serialize every monetary and percentage value in the Negotiation Playbook as a JSON string.

### Requirement 5: LTV-to-Cost attribution split computation

**User Story:** As a data analyst, I want the LTV-to-Cost multiple decomposed into its subscription and advertising components, so that I can see which value driver supports the number.

#### Acceptance Criteria

1. WHEN the Attribution_Helper is given the churn-reduction value and the territory-weighted LTV, THE Attribution_Helper SHALL return the Subscription_Value_Contribution as `churn_reduction_value * ltv`.
2. WHEN the Attribution_Helper is given the watch-time elasticity, the territory-weighted CPM, and the ad impressions, THE Attribution_Helper SHALL return the Advertising_Value_Contribution as `watch_time_elasticity * cpm * ad_impressions`.
3. WHEN the Attribution_Helper computes both contributions, THE Attribution_Helper SHALL return the Total_Modeled_Value as the sum of the Subscription_Value_Contribution and the Advertising_Value_Contribution.
4. WHEN the Attribution_Helper is given a non-zero normalized cost in USD, THE Attribution_Helper SHALL return a resulting multiple equal to `Total_Modeled_Value / normalized_cost_usd`.
5. THE resulting multiple returned by the Attribution_Helper SHALL equal the LTV-to-Cost multiple computed by the existing `compute_ltv_to_cost` function for the same inputs.
6. THE Attribution_Helper SHALL compute every value using decimal arithmetic without introducing binary-floating-point representation error.

### Requirement 6: LTV-to-Cost attribution in engine output and responses

**User Story:** As an executive, I want the subscription and advertising value split surfaced in the scorecard responses, so that both decision surfaces can explain the LTV-to-cost number.

#### Acceptance Criteria

1. THE Guardrails_Engine SHALL carry the Subscription_Value_Contribution, the Advertising_Value_Contribution, and the Total_Modeled_Value on the ValuationResult it returns.
2. THE Guardrails_Engine SHALL compute the LTV-to-Cost attribution components from the same territory-weighted CPM and LTV used to compute the LTV-to-Cost multiple.
3. THE Valuation_Scorecard_Response and THE Quick_Evaluate_Response SHALL each carry an `ltv_attribution` object containing the Subscription_Value_Contribution, the Advertising_Value_Contribution, the Total_Modeled_Value, the normalized cost in USD, and the resulting multiple.
4. THE Valuation_Scorecard_Response and THE Quick_Evaluate_Response SHALL serialize every monetary value in the `ltv_attribution` object as a JSON string.
5. IF the LTV-to-Cost multiple cannot be computed for a title, THEN THE Valuation_Scorecard_Response and THE Quick_Evaluate_Response SHALL serialize `ltv_attribution` as null.

### Requirement 7: Absolute churn cohort computation

**User Story:** As an executive, I want the churn-reduction percentage expressed as an approximate number of retained subscribers, so that I can judge the absolute retention impact of the acquisition.

#### Acceptance Criteria

1. WHEN the Cohort_Helper is given a Modeled_Cohort_Size and a churn-reduction percentage, THE Cohort_Helper SHALL return the Retained_Subscribers as `Modeled_Cohort_Size * (churn_reduction_pct / 100)`.
2. WHEN the Cohort_Helper returns a Retained_Subscribers value, THE Cohort_Helper SHALL round the value to a whole number of subscribers.
3. IF the Modeled_Cohort_Size is less than or equal to zero, THEN THE Cohort_Helper SHALL return null for the Retained_Subscribers.
4. IF the churn-reduction percentage is less than or equal to zero, THEN THE Cohort_Helper SHALL return a Retained_Subscribers value of zero.
5. THE Cohort_Helper SHALL compute every value using decimal arithmetic without introducing binary-floating-point representation error.

### Requirement 8: Absolute churn cohort in engine output and responses

**User Story:** As a frontend developer, I want the absolute cohort figure and its cohort size available in the scorecard responses, so that both decision surfaces can render retained subscribers next to the percentage.

#### Acceptance Criteria

1. THE Guardrails_Engine SHALL obtain a Modeled_Cohort_Size from the modeled-inputs provider or derive it from existing modeled inputs.
2. THE Guardrails_Engine SHALL carry the Modeled_Cohort_Size and the Retained_Subscribers on the ValuationResult it returns.
3. THE Valuation_Scorecard_Response and THE Quick_Evaluate_Response SHALL each carry a `churn_cohort` object containing the churn-reduction percentage, the Modeled_Cohort_Size, and the Retained_Subscribers.
4. THE `churn_cohort` object SHALL carry a flag identifying the Modeled_Cohort_Size and the Retained_Subscribers as a Derived_Figure.
5. IF no Modeled_Cohort_Size is available for a title, THEN THE Valuation_Scorecard_Response and THE Quick_Evaluate_Response SHALL serialize the Modeled_Cohort_Size and the Retained_Subscribers within `churn_cohort` as null while still carrying the churn-reduction percentage.

### Requirement 9: Negotiation Playbook rendering on both decision surfaces

**User Story:** As a content buyer, I want the negotiation playbook on both the title evaluation view and the Asset Studio scorecard, so that I get the same guidance regardless of how I reached the title.

#### Acceptance Criteria

1. WHERE a decision is NEGOTIATE_HARD or PASS and a Target_Purchase_Ceiling is present, THE Title_Evaluation_View SHALL display the Target_Purchase_Ceiling in USD and the Implied_Discount_Pct.
2. WHERE a decision is NEGOTIATE_HARD or PASS and a Target_Purchase_Ceiling is present, THE Asset_Studio_View SHALL display the Target_Purchase_Ceiling in USD and the Implied_Discount_Pct.
3. WHEN Counter_Proposal_Levers are present in the response, THE Title_Evaluation_View SHALL display each Counter_Proposal_Lever labeled by its guardrail.
4. WHEN Counter_Proposal_Levers are present in the response, THE Asset_Studio_View SHALL display each Counter_Proposal_Lever labeled by its guardrail.
5. WHERE a decision is GREENLIGHT, THE Title_Evaluation_View and THE Asset_Studio_View SHALL omit the negotiation target ceiling and implied discount.
6. WHEN a Negotiation Playbook monetary or percentage value arrives as a JSON string, THE Title_Evaluation_View and THE Asset_Studio_View SHALL coerce the value to a number before formatting it for display.

### Requirement 10: LTV-to-Cost attribution rendering on both decision surfaces

**User Story:** As an executive, I want the subscription-versus-advertising value split shown on both scorecards, so that I understand what drives the LTV-to-cost multiple.

#### Acceptance Criteria

1. WHEN an `ltv_attribution` object is present in the response, THE Title_Evaluation_View SHALL display the Subscription_Value_Contribution, the Advertising_Value_Contribution, the Total_Modeled_Value, the normalized cost in USD, and the resulting multiple.
2. WHEN an `ltv_attribution` object is present in the response, THE Asset_Studio_View SHALL display the Subscription_Value_Contribution, the Advertising_Value_Contribution, the Total_Modeled_Value, the normalized cost in USD, and the resulting multiple.
3. WHERE the `ltv_attribution` object is null, THE Title_Evaluation_View and THE Asset_Studio_View SHALL display the LTV-to-Cost multiple without the attribution breakdown.
4. WHEN an LTV attribution monetary value arrives as a JSON string, THE Title_Evaluation_View and THE Asset_Studio_View SHALL coerce the value to a number before formatting it for display.

### Requirement 11: Absolute churn cohort rendering on both decision surfaces

**User Story:** As an executive, I want the retained-subscriber count shown next to the churn percentage on both scorecards, so that I can read the absolute retention impact.

#### Acceptance Criteria

1. WHEN a `churn_cohort` object carries a non-null Retained_Subscribers value, THE Title_Evaluation_View SHALL display the Retained_Subscribers alongside the churn-reduction percentage.
2. WHEN a `churn_cohort` object carries a non-null Retained_Subscribers value, THE Asset_Studio_View SHALL display the Retained_Subscribers alongside the churn-reduction percentage.
3. WHERE a `churn_cohort` object identifies the Retained_Subscribers as a Derived_Figure, THE Title_Evaluation_View and THE Asset_Studio_View SHALL display a label marking the figure as derived or modeled.
4. WHERE the Retained_Subscribers value is null, THE Title_Evaluation_View and THE Asset_Studio_View SHALL display the churn-reduction percentage without the absolute cohort figure.

### Requirement 12: Scope preservation

**User Story:** As a data analyst, I want this feature to leave the recommendation logic untouched, so that greenlight decisions remain comparable to prior valuations.

#### Acceptance Criteria

1. THE Deal_Decision_Support SHALL leave the CPVH ceilings, the LTV-to-Cost threshold, the churn-mitigation threshold, and the payback-horizon target window unchanged.
2. THE Deal_Decision_Support SHALL leave the recommendation status produced by the Guardrails_Engine for a title unchanged for inputs that produced that status before this feature.
3. THE Deal_Decision_Support SHALL derive every new figure from values the Guardrails_Engine already computes or from existing modeled inputs, without introducing new guardrail math.
