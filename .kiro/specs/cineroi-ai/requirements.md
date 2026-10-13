# Requirements Document

## Introduction

CineROI AI (formally "The OTT Enterprise High-ROI Content Acquisition, Licensing, Greenlighting & Historical Backtesting Intelligence Engine") is an internal decision-support system for OTT programming executives, content buyers, and data science teams. The system ingests content manifests (CSV batches, PDF script summaries, JSON pitch decks), extracts semantic metadata vectors through NLP embeddings, evaluates each title against quantitative financial guardrails (CPVH, LTV-to-Cost multiple, churn mitigation, payback horizon), and produces greenlight recommendations. A historical backtesting module compares predicted outcomes against ground-truth data, computes predictive variance (MAPE), and auto-calibrates feature-extraction weights.

The platform is delivered as a monorepo containing a FastAPI backend, a Next.js frontend, PostgreSQL 16+ with the pgvector extension, migration scripts, and Docker-based deployment orchestration.

This document captures the functional and non-functional requirements for the system in EARS format, organized by capability area: data ingestion and feature extraction, financial guardrails valuation, historical backtesting and calibration, market telemetry, REST API surface, frontend experiences, data persistence, and deployment. Requirements 1-30 define the core platform. Requirements 31-36 capture the decision-support and operational enhancements added after the core platform shipped: title-to-title comparable-titles matching, the market-telemetry card on the title page, dashboard filtering/search with shareable view state, the human-managed deal-stage acquisition lifecycle, responsive tablet layout, and demo/operational integrity (self-consistent seed data, exchange-rate fallback, and a one-command demo reset). (Three earlier enhancement waves - Deal Decision Support, What-If Sensitivity, and the demo-friendly Backtest Studio - are specified in their own sibling spec folders and are not duplicated here.)

## Glossary

- **CineROI_System**: The complete decision-support platform, including backend, frontend, and database.
- **Ingestion_Service**: The backend component that accepts batch manifests and triggers feature extraction.
- **Feature_Extraction_Engine**: The backend component that parses source documents and generates metadata vectors (narrative DNA, affective tone, talent pedigree, production scale).
- **Vector_Search_Engine**: The pgvector-backed component that computes cosine similarity between title vectors and subscriber cluster preference vectors.
- **Guardrails_Engine**: The quantitative financial engine that evaluates CPVH, LTV-to-Cost multiple, churn mitigation threshold, and payback horizon to produce a recommendation status.
- **Backtesting_Module**: The backend component that audits predictions against historical ground truth and computes variance.
- **Calibration_Controller**: The component that computes and applies auto-tuning weight offsets for feature-extraction parameters.
- **Telemetry_Connector**: The modular async connector framework that polls external social sentiment, chart-velocity, and licensing-inflation sources.
- **API_Service**: The FastAPI REST interface exposing system operations to the frontend and external callers.
- **Dashboard_UI**: The Next.js Executive Command Dashboard at `/dashboard`.
- **Title_Evaluation_UI**: The Next.js Deep-Dive Title Evaluation View at `/titles/[id]`.
- **Backtest_Studio_UI**: The Next.js Historical Backtesting & Calibration Studio at `/backtest`.
- **CPVH**: Cost-Per-Viewing-Hour = Total Acquisition Cost or Budget / Projected Viewing Hours.
- **LTV_to_Cost_Multiple**: ((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) / Total Acquisition Cost.
- **Churn_Mitigation_Threshold**: The modeled cohort monthly churn reduction percentage.
- **Payback_Horizon**: The number of months until a title reaches positive contribution margin.
- **MAPE**: Mean Absolute Percentage Error = (1/n) x sum(|(Actual - Predicted)/Actual|) x 100.
- **Recommendation_Status**: One of GREENLIGHT, NEGOTIATE_HARD, or PASS.
- **Asset_Type**: One of ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, or CO_PRODUCTION.
- **Premium_Original**: A title whose Asset_Type is ORIGINAL_SERIES, ORIGINAL_FILM, or CO_PRODUCTION.
- **Library_Filler**: A title whose Asset_Type is LICENSED_LIBRARY.
- **Narrative_DNA**: A 1536-dimension embedding vector representing tropes, themes, and pacing of a title.
- **Affective_Tone_Score**: A structured score of primary and secondary emotional triggers for a title.
- **Ground_Truth_Record**: A historical record of actual observed outcomes for a title stored in the historical_ground_truth table.
- **Auth_Service**: The component that authenticates users and issues/validates sessions and API credentials.
- **RBAC_Service**: The component that enforces role-based permissions across system operations.
- **Approval_Workflow**: The multi-tier sign-off process governing high-budget greenlight decisions and recommendation overrides.
- **User_Role**: One of DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER, or CFO.
- **Audit_Log_Service**: The component that records an immutable trail of state-changing actions with actor, timestamp, and before/after values.
- **Task_Queue**: The asynchronous background worker system (e.g., Celery with Redis or RabbitMQ) that executes long-running ingestion, extraction, and audit jobs.
- **Job_Status**: One of PENDING, PROCESSING, COMPLETED, or FAILED.
- **Model_Version**: An identifier capturing the active feature-extraction weight set and guardrail parameters at the time a valuation is produced.
- **License_Terms**: The contract structure for a title, including license duration, exclusivity, windowing rules, and milestone payment schedule.
- **Base_Currency**: The system's canonical reporting currency (United States dollars) into which all territorial costs are normalized.
- **Comparable_Titles**: The ranked set of titles most similar to a given title by Narrative_DNA cosine similarity (title-to-title, as opposed to the title-to-subscriber-cluster match of the Vector_Search_Engine). Surfaced as the "Top 3 historical comps" on the Title_Evaluation_UI.
- **Market_Telemetry_Card**: The Title_Evaluation_UI panel that surfaces the cached Market_Telemetry (social sentiment, chart velocity, licensing inflation) for the title's genre and primary target territory.
- **Primary_Territory**: The first entry of a title's target_territories list, used as the territory key for the Market_Telemetry_Card lookup.
- **Deal_Stage**: The human-managed position of a title in the acquisition pipeline, one of {SCREENING, EVALUATED, IN_NEGOTIATION, APPROVED, CLOSED_WON, CLOSED_LOST, PASSED}, independent of the AI Recommendation_Status.
- **Deal_Stage_Lifecycle**: The state machine governing legal Deal_Stage transitions (forward one step along the pipeline, an abandon-to-PASSED escape from any live stage, and APPROVED to CLOSED_WON/CLOSED_LOST), with terminal stages that admit no further transition.
- **Terminal_Deal_Stage**: A Deal_Stage with no outgoing transitions: CLOSED_WON, CLOSED_LOST, or PASSED.
- **Dashboard_View_State**: The dashboard grid's free-text title search, recommendation filter, deal-stage filter, and sort column/direction, mirrored into the URL query string so the view is shareable and survives reload.
- **Demo_Reset**: The one-command script that truncates the demo-mutable tables and re-applies the pristine seed so a demo can be re-run from a clean slate.
- **Asset_Studio_UI**: The Next.js title-intake and instant-evaluation surface at `/studio`, with a Single Asset tab, a Batch Slate tab, and a pitch-PDF drop zone.
- **Instant_Evaluation**: The synchronous single-title path `POST /api/v1/titles/quick-evaluate` that creates a title plus its active version, runs the Guardrails_Engine inline, and returns a full scorecard without the async ingest job.
- **Pitch_Auto_Fill**: The best-effort extraction path `POST /api/v1/titles/parse-pitch` that reads a pitch/script PDF and returns candidate Asset_Studio_UI field values for the user to review before submission.
- **Shorthand_Amount**: Analyst budget shorthand the cost field accepts (for example `12 Cr`, `3 Lakh`, `1.5M`, `500k`), expanded to a full number with a live preview before submission.

## Requirements

### Requirement 1: Batch Content Ingestion

**User Story:** As a content buyer, I want to ingest batches of content manifests in multiple formats, so that candidate titles enter the valuation pipeline without manual data entry.

#### Acceptance Criteria

1. WHEN a request to `POST /api/v1/titles/ingest` is received containing a CSV manifest of up to 10,000 data rows, THE Ingestion_Service SHALL create exactly one title record per valid data row in the titles table.
2. WHEN a request to `POST /api/v1/titles/ingest` is received containing a JSON pitch deck, THE Ingestion_Service SHALL create exactly one title record per parsed title object in the payload.
3. WHEN a request to `POST /api/v1/titles/ingest` is received containing a PDF script summary, THE Ingestion_Service SHALL extract the text content and create a corresponding title record.
4. IF a request to `POST /api/v1/titles/ingest` is received with a payload format that is not CSV, JSON, or PDF, THEN THE Ingestion_Service SHALL reject the request without creating any title record and return an error identifying the unsupported format.
5. IF a CSV manifest contains more than 10,000 data rows, THEN THE Ingestion_Service SHALL reject the request without creating any title record and return an error indicating that the row limit was exceeded.
6. WHEN a title record is successfully created during ingestion, THE Ingestion_Service SHALL trigger the Feature_Extraction_Engine for that title record.
7. IF an ingested record is missing a required field (title_name or acquisition_cost_or_budget), THEN THE Ingestion_Service SHALL reject that record without creating a title record for it, continue processing the remaining records, and return a descriptive error identifying the missing field.
8. IF an ingested record specifies an acquisition_cost_or_budget outside the range 0.01 to 999999999.99, OR specifies an asset_type value outside the set {ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, CO_PRODUCTION}, THEN THE Ingestion_Service SHALL reject that record without creating a title record for it, continue processing the remaining records, and return a descriptive error identifying the invalid value.
9. WHEN a batch ingestion request completes, THE Ingestion_Service SHALL return a summary reporting the count of accepted records and the count of rejected records.
10. WHEN the Ingestion_Service returns a batch summary, THE sum of accepted records and rejected records SHALL equal the total number of records submitted in the batch.

### Requirement 2: Feature Extraction and Vector Generation

**User Story:** As a data scientist, I want source documents parsed into semantic metadata vectors, so that each title has a quantified multidimensional profile for similarity matching.

#### Acceptance Criteria

1. WHEN the Feature_Extraction_Engine processes a title with at least one non-empty source document (logline, pitch deck, or manifest content), THE Feature_Extraction_Engine SHALL generate a Narrative_DNA vector containing exactly 1536 dimensions, where each dimension is a numeric value within the range -1.0 to 1.0.
2. IF a title has no non-empty source document available when processing begins, THEN THE Feature_Extraction_Engine SHALL record an extraction-failure status for that title and return an error message indicating that no source content was available.
3. WHEN the Feature_Extraction_Engine processes a title, THE Feature_Extraction_Engine SHALL generate an Affective_Tone_Score that identifies exactly one primary emotional trigger and exactly one secondary emotional trigger, each selected from a predefined set of emotional trigger categories.
4. WHEN the Feature_Extraction_Engine processes a title, THE Feature_Extraction_Engine SHALL compute a talent_pedigree_score as a numeric value bounded between 0.0 and 10.0 inclusive, rounded to 2 decimal places.
5. WHEN the Feature_Extraction_Engine processes a title, THE Feature_Extraction_Engine SHALL compute a production_scale_metric as a numeric value bounded between 0.0 and 10.0 inclusive, rounded to 2 decimal places.
6. WHEN the Feature_Extraction_Engine completes extraction for a title, THE Feature_Extraction_Engine SHALL persist the generated Narrative_DNA vector, Affective_Tone_Score, talent_pedigree_score, and production_scale_metric to the metadata_vectors table linked to the title_id as a single atomic operation.
7. IF persistence of the generated vectors and scores to the metadata_vectors table fails, THEN THE Feature_Extraction_Engine SHALL roll back any partial writes for that title, record an extraction-failure status, and return an error message indicating the persistence failure.
8. IF document parsing fails for a title, THEN THE Feature_Extraction_Engine SHALL record an extraction-failure status for that title, retain any previously persisted data for that title_id unchanged, and return an error message indicating the cause of the parsing failure.

### Requirement 3: Subscriber Preference Similarity Matching

**User Story:** As a programming executive, I want each title scored for similarity against subscriber cluster preferences, so that I can judge audience fit before acquisition.

#### Acceptance Criteria

1. WHEN a title has a persisted Narrative_DNA vector, THE Vector_Search_Engine SHALL compute cosine similarity between the title vector and subscriber cluster preference vectors using pgvector.
2. THE Vector_Search_Engine SHALL return similarity results ranked in descending order of cosine similarity score.
3. IF no subscriber cluster preference vectors exist, THEN THE Vector_Search_Engine SHALL return an empty similarity result set with a status indicating that no reference clusters are available.

### Requirement 4: Cost-Per-Viewing-Hour Guardrail

**User Story:** As a content buyer, I want each title evaluated against a CPVH ceiling, so that overpriced acquisitions are flagged automatically.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine evaluates a title with projected_viewing_hours greater than zero, THE Guardrails_Engine SHALL compute CPVH as acquisition_cost_or_budget divided by projected_viewing_hours, rounded to four decimal places.
2. WHERE a title is a Premium_Original, THE Guardrails_Engine SHALL apply a CPVH ceiling of 0.18 United States dollars.
3. WHERE a title is a Library_Filler, THE Guardrails_Engine SHALL apply a CPVH ceiling of 0.05 United States dollars.
4. IF a title does not match any defined title classification, THEN THE Guardrails_Engine SHALL mark the CPVH check as failed and return an error indicating that no applicable CPVH ceiling exists for the title.
5. IF projected_viewing_hours for a title is zero, THEN THE Guardrails_Engine SHALL mark the CPVH check as failed, return a descriptive error indicating that CPVH cannot be computed, and SHALL NOT persist a calculated_cpvh value for that title.
6. WHEN the computed CPVH for a title is strictly greater than the applicable ceiling, THE Guardrails_Engine SHALL record a CPVH guardrail breach for that title.
7. WHEN the computed CPVH for a title is less than or equal to the applicable ceiling, THE Guardrails_Engine SHALL record the CPVH check as passed for that title.
8. WHEN the Guardrails_Engine computes a CPVH value for a title, THE Guardrails_Engine SHALL persist the calculated_cpvh value to the financial_projections table before returning the evaluation result.

### Requirement 5: LTV-to-Cost Multiple Guardrail

**User Story:** As a programming executive, I want the long-term-value-to-cost ratio enforced, so that acquisitions deliver sufficient portfolio return.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine evaluates a title, THE Guardrails_Engine SHALL compute the LTV_to_Cost_Multiple as ((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) divided by acquisition_cost_or_budget.
2. THE Guardrails_Engine SHALL evaluate the LTV_to_Cost_Multiple against a minimum threshold of 3.2 over a 12-to-24-month window.
3. WHEN the computed LTV_to_Cost_Multiple for a title is below 3.2, THE Guardrails_Engine SHALL record an LTV-to-Cost guardrail breach for that title.
4. WHEN the Guardrails_Engine computes the LTV_to_Cost_Multiple for a title, THE Guardrails_Engine SHALL persist the ltv_to_cost_multiple value to the financial_projections table.

### Requirement 6: Churn Mitigation Guardrail

**User Story:** As a data scientist, I want the modeled churn reduction enforced against a threshold, so that only titles that measurably retain subscribers advance.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine evaluates a title, THE Guardrails_Engine SHALL compute the modeled cohort monthly churn reduction percentage for that title.
2. THE Guardrails_Engine SHALL evaluate the modeled churn reduction percentage against a minimum Churn_Mitigation_Threshold of 1.5 percent.
3. WHEN the modeled churn reduction percentage for a title is below 1.5 percent, THE Guardrails_Engine SHALL record a churn-mitigation guardrail breach for that title.

### Requirement 7: Payback Horizon Guardrail

**User Story:** As a content buyer, I want the payback timeline evaluated, so that capital is recovered within an acceptable window.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine evaluates a title, THE Guardrails_Engine SHALL compute the payback_horizon_months as the number of months until the title reaches positive contribution margin.
2. THE Guardrails_Engine SHALL evaluate payback_horizon_months against a target window of 9 to 12 months inclusive.
3. WHEN payback_horizon_months for a title exceeds 12, THE Guardrails_Engine SHALL record a payback-horizon guardrail breach for that title.
4. WHEN the Guardrails_Engine computes payback_horizon_months for a title, THE Guardrails_Engine SHALL persist the payback_horizon_months value to the financial_projections table.

### Requirement 8: Recommendation Status Determination

**User Story:** As a programming executive, I want each title assigned a clear recommendation, so that I can make greenlight decisions quickly.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine completes all guardrail checks for a title and the total count of breaches equals zero, THE Guardrails_Engine SHALL set the Recommendation_Status to GREENLIGHT.
2. WHEN the Guardrails_Engine completes all guardrail checks for a title and the breach count is one or more AND every breach is classified as correctable through renegotiated cost (projected metrics return within their target windows when cost is reduced to the minimum viable value), THE Guardrails_Engine SHALL set the Recommendation_Status to NEGOTIATE_HARD.
3. WHEN the Guardrails_Engine completes all guardrail checks for a title and at least one breach is classified as non-correctable (the breached metric cannot return within its target window under any permitted cost adjustment), THE Guardrails_Engine SHALL set the Recommendation_Status to PASS.
4. IF the Guardrails_Engine cannot classify a breach as either correctable or non-correctable due to missing or invalid input data, THEN THE Guardrails_Engine SHALL set the Recommendation_Status to PASS and record an indicator identifying the title as unclassifiable.
5. WHEN the Guardrails_Engine determines a Recommendation_Status for a title, THE Guardrails_Engine SHALL assign exactly one value from the set {GREENLIGHT, NEGOTIATE_HARD, PASS}.
6. WHEN the Guardrails_Engine assigns a Recommendation_Status to a title, THE Guardrails_Engine SHALL persist the recommendation_status value to the financial_projections table within 5 seconds of completing the guardrail checks.
7. IF persisting the recommendation_status value to the financial_projections table fails, THEN THE Guardrails_Engine SHALL retry up to 3 times and, if all retries fail, return an error indication identifying the affected title while preserving the previously stored recommendation_status value.

### Requirement 9: Valuation Calculation Endpoint

**User Story:** As a frontend application, I want to trigger a full valuation for a title, so that current financial scores and recommendations are produced on demand.

#### Acceptance Criteria

1. WHEN a request to `POST /api/v1/valuation/calculate` is received for a title, THE API_Service SHALL invoke the Guardrails_Engine for that title.
2. WHEN the Guardrails_Engine completes a valuation, THE API_Service SHALL return the calculated CPVH, LTV_to_Cost_Multiple, and Recommendation_Status in the response.
3. IF the valuation request references a title_id that does not exist, THEN THE API_Service SHALL return a not-found error identifying the missing title_id.

### Requirement 10: Valuation Retrieval Endpoint

**User Story:** As a programming executive, I want to retrieve a complete financial scorecard for a title, so that I can review the full basis for a recommendation.

#### Acceptance Criteria

1. WHEN a request to `GET /api/v1/valuation/{title_id}` is received, THE API_Service SHALL return the complete financial projection scorecard for the specified title.
2. WHEN a request to `GET /api/v1/valuation/{title_id}` is received, THE API_Service SHALL include the strategic metadata vector breakdown for the specified title in the response.
3. IF the requested title_id does not exist, THEN THE API_Service SHALL return a not-found error identifying the missing title_id.

### Requirement 11: Historical Backtest Audit

**User Story:** As a data scientist, I want predictions compared against actual historical outcomes, so that model accuracy is quantified.

#### Acceptance Criteria

1. WHEN a request to `POST /api/v1/backtest/audit` is received with a valid Ground_Truth_Record, THE Backtesting_Module SHALL persist the actual outcomes to the historical_ground_truth table and return confirmation identifying the persisted record within 5 seconds.
2. IF a request to `POST /api/v1/backtest/audit` is received with a Ground_Truth_Record that is missing required fields or contains a non-numeric actual value for an audited metric, THEN THE Backtesting_Module SHALL reject the request without persisting any data and return an error response indicating which field or value is invalid.
3. WHERE a title has is_historical set to TRUE, THE Backtesting_Module SHALL retrieve the corresponding Ground_Truth_Record for audit comparison, matching on the title identifier.
4. IF a title has is_historical set to TRUE but no corresponding Ground_Truth_Record exists, THEN THE Backtesting_Module SHALL exclude the title from the audit and return an error response indicating that ground truth data is unavailable for the title.
5. WHEN the Backtesting_Module audits a title, THE Backtesting_Module SHALL compute MAPE as (1/n) x sum(|(Actual - Predicted)/Actual|) x 100 across the n audited metrics that have a non-zero actual value, expressed as a percentage rounded to 2 decimal places.
6. WHEN the Backtesting_Module completes an audit, THE API_Service SHALL return an audit scorecard reporting, for each audited metric, the predicted value, the actual value, and the computed MAPE within 10 seconds of audit completion.
7. IF a Ground_Truth_Record contains an actual value of zero for a metric used in MAPE, THEN THE Backtesting_Module SHALL exclude that metric from the MAPE computation and report the excluded metric in the audit scorecard.
8. IF all audited metrics for a title are excluded from the MAPE computation, THEN THE Backtesting_Module SHALL report a null MAPE value in the audit scorecard and indicate that no metrics were eligible for computation.

### Requirement 12: Auto-Calibration of Feature Weights

**User Story:** As a data scientist, I want feature-extraction weights adjusted automatically when audit error is high, so that model accuracy improves over successive backtests.

#### Acceptance Criteria

1. WHEN an audit produces a Mean Absolute Percentage Error greater than 10 percent, THE Calibration_Controller SHALL compute weight-adjustment offsets for all feature-extraction parameters, where each offset is a numeric value within the range -1.00 to 1.00, within 5 seconds of audit completion.
2. WHEN the Calibration_Controller computes weight-adjustment offsets, THE Calibration_Controller SHALL re-weight the talent pedigree weight and the narrative trope alignment weight such that both resulting weights remain within the range 0.00 to 1.00 inclusive and sum to 1.00.
3. WHEN a user applies calibration through the Calibration_Controller, THE Calibration_Controller SHALL update the active feature-extraction weights with the computed offsets and retain the updated weights so they are in effect for subsequent backtests.
4. IF applying a computed offset would move any feature-extraction weight outside the range 0.00 to 1.00 inclusive, THEN THE Calibration_Controller SHALL reject the calibration, retain the prior weights unchanged, and return an error indicating that the adjustment is out of range.
5. WHEN an audit produces a Mean Absolute Percentage Error of 10 percent or less, THE Calibration_Controller SHALL report that no calibration adjustment is required and retain the active feature-extraction weights unchanged.

### Requirement 13: Market Telemetry Ingestion and Retrieval

**User Story:** As a programming executive, I want live market inflation and sentiment data by genre and territory, so that valuations reflect current market conditions.

#### Acceptance Criteria

1. THE Telemetry_Connector SHALL poll external social sentiment, chart-velocity, and licensing-inflation sources asynchronously.
2. WHEN the Telemetry_Connector retrieves telemetry data, THE Telemetry_Connector SHALL persist the social_sentiment_index, chart_velocity_score, and licensing_inflation_multiplier to the market_telemetry_cache table keyed by genre_tag and territory.
3. WHEN a request to `GET /api/v1/market/telemetry` is received, THE API_Service SHALL return the cached market inflation indices and social sentiment scores filtered by the requested genre and territory.
4. IF an external telemetry source is unavailable during a poll, THEN THE Telemetry_Connector SHALL retain the last cached values and record the source as unavailable.

### Requirement 14: Executive Command Dashboard

**User Story:** As a programming executive, I want a command dashboard summarizing the pipeline, so that I can assess portfolio health at a glance.

#### Acceptance Criteria

1. WHEN the Dashboard_UI loads, THE Dashboard_UI SHALL display KPI header cards for active pipeline valuation, average LTV-to-Cost multiple, portfolio risk exposure index, and model prediction accuracy rate.
2. WHEN the Dashboard_UI loads, THE Dashboard_UI SHALL display a master asset data grid listing title name, asset type, asking price, CPVH status, LTV multiple, and recommendation badge for each title.
3. THE Dashboard_UI SHALL render the recommendation badge as GREENLIGHT, NEGOTIATE HARD, or PASS according to the title Recommendation_Status.
4. WHEN a user selects a sortable column header in the master asset data grid, THE Dashboard_UI SHALL reorder the grid rows according to the selected column.
5. WHEN a user selects a title row in the master asset data grid, THE Dashboard_UI SHALL navigate to the Title_Evaluation_UI for that title.

### Requirement 15: Deep-Dive Title Evaluation View

**User Story:** As a content buyer, I want a detailed per-title evaluation view, so that I can analyze the metadata profile, financials, and negotiation leverage.

#### Acceptance Criteria

1. WHEN the Title_Evaluation_UI loads for a title, THE Title_Evaluation_UI SHALL render a radar chart of the Narrative DNA, Affective Tone, Talent Pedigree, and Production Scale dimensions.
2. WHEN the Title_Evaluation_UI loads for a title, THE Title_Evaluation_UI SHALL render a financial breakdown accordion containing CPVH ceiling checks, churn mitigation impact curves, and a payback timeline bar chart.
3. WHEN the Title_Evaluation_UI loads for a title, THE Title_Evaluation_UI SHALL render a negotiation leverage panel listing contractual safeguards.
4. IF the requested title has no completed valuation, THEN THE Title_Evaluation_UI SHALL display a message indicating that valuation is pending.

### Requirement 16: Historical Backtesting and Calibration Studio

**User Story:** As a data scientist, I want a studio to enter ground-truth data and compare predictions, so that I can audit and recalibrate the model.

#### Acceptance Criteria

1. WHEN the Backtest_Studio_UI loads, THE Backtest_Studio_UI SHALL render a split-pane layout with historical ground-truth input controls on the left pane.
2. WHEN a user submits ground-truth metrics in the left pane, THE Backtest_Studio_UI SHALL render side-by-side comparative variance charts for Predicted versus Actual CPVH and LTV multiples in the right pane.
3. WHEN a user selects the Model Calibration Controller control, THE Backtest_Studio_UI SHALL request application of the auto-tuning offsets based on the historical MAPE.
4. WHEN calibration is applied through the Backtest_Studio_UI, THE Backtest_Studio_UI SHALL display confirmation of the applied weight offsets.

### Requirement 17: Relational Data Persistence and Integrity

**User Story:** As a data engineer, I want a well-structured relational schema with referential integrity, so that data remains consistent across the system.

#### Acceptance Criteria

1. THE CineROI_System SHALL persist title records in a titles table using title_id as a UUID primary key.
2. THE CineROI_System SHALL enforce a foreign-key relationship from metadata_vectors, financial_projections, and historical_ground_truth to the titles table on title_id.
3. THE CineROI_System SHALL store target_territories as JSONB country codes in the titles table.
4. THE CineROI_System SHALL constrain asset_type to the enumerated set {ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, CO_PRODUCTION}.
5. THE CineROI_System SHALL constrain recommendation_status to the enumerated set {GREENLIGHT, NEGOTIATE_HARD, PASS}.
6. THE CineROI_System SHALL enable the pgvector extension to support VECTOR(1536) storage in the metadata_vectors table.
7. THE CineROI_System SHALL provide database initialization scripts that create the full schema and load mock seed data.

### Requirement 18: Monorepo Structure and Deployment

**User Story:** As a developer, I want a complete monorepo with deployment orchestration, so that the full stack can be provisioned reproducibly.

#### Acceptance Criteria

1. THE CineROI_System SHALL provide a monorepo containing a `/backend` FastAPI service, a `/frontend` Next.js application, and a `/database` directory of migration scripts.
2. THE CineROI_System SHALL provide a docker-compose configuration that orchestrates PostgreSQL with pgvector, the FastAPI backend, and the Next.js frontend.
3. THE CineROI_System SHALL provide a README that documents setup, environment configuration, and run instructions.
4. WHEN the docker-compose configuration is started, THE CineROI_System SHALL initialize the PostgreSQL database using the provided initialization scripts.

### Requirement 19: Authentication and Session Security

**User Story:** As a security administrator, I want all users and service callers authenticated, so that only authorized identities access the platform and its decision data.

#### Acceptance Criteria

1. WHEN a user initiates login, THE Auth_Service SHALL authenticate the user through an SSO identity provider using OIDC or SAML.
2. WHEN authentication succeeds, THE Auth_Service SHALL issue a session bound to the authenticated identity.
3. IF a request to a protected endpoint is received without a valid session or API credential, THEN THE Auth_Service SHALL reject the request and return a descriptive authentication error.
4. WHILE a session remains idle for 30 minutes, THE Auth_Service SHALL expire the session and require re-authentication on the next request.
5. WHEN an internal service-to-service call is made, THE Auth_Service SHALL authenticate the calling service using an API credential before the call is processed.
6. IF a request presents an expired or revoked session or API credential, THEN THE Auth_Service SHALL reject the request and return a descriptive error identifying the credential as expired or revoked.

### Requirement 20: Role-Based Access Control and Executive Approval Workflow

**User Story:** As a Chief Content Officer, I want role-based permissions and multi-tier sign-off on high-value decisions, so that greenlight authority and overrides are properly governed and auditable.

#### Acceptance Criteria

1. THE RBAC_Service SHALL assign each user exactly one User_Role from the set {DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER, CFO} and enforce the permission scope defined for that role on every system operation.
2. IF a user whose User_Role is not CONTENT_BUYER, CHIEF_CONTENT_OFFICER, or CFO attempts to override a Recommendation_Status, THEN THE RBAC_Service SHALL reject the override and return an authorization error.
3. WHERE a GREENLIGHT decision has an acquisition_cost_or_budget greater than 25000000 United States dollars, THE Approval_Workflow SHALL require sign-off from both a CHIEF_CONTENT_OFFICER and a CFO before the decision is finalized.
4. WHEN an approval, rejection, or override is submitted, THE Approval_Workflow SHALL record the action with the actor identity and a timestamp.
5. IF any required approval for a decision has not been recorded, THEN THE Approval_Workflow SHALL prevent that decision from being finalized and return a status indicating which approvals remain outstanding.

### Requirement 21: Multi-Currency and Territorial Cost Normalization

**User Story:** As a content buyer, I want multi-territory costs normalized into a base currency, so that financial guardrails compare titles consistently across markets.

#### Acceptance Criteria

1. WHEN a title acquisition cost is ingested, THE CineROI_System SHALL capture the cost in its native currency, supporting at minimum INR, USD, EUR, and GBP.
2. WHEN the Guardrails_Engine evaluates a title, THE Guardrails_Engine SHALL convert the acquisition cost into Base_Currency using a dated exchange rate before computing financial guardrails.
3. WHEN the Guardrails_Engine computes the LTV_to_Cost_Multiple, THE Guardrails_Engine SHALL apply territory-specific CPM and LTV weighting for each target territory.
4. WHEN a cost is normalized into Base_Currency, THE CineROI_System SHALL record the exchange rate value and the rate date used for the normalization.
5. IF an exchange rate for a required currency and rate date is unavailable, THEN THE Guardrails_Engine SHALL reject the valuation without persisting normalized values and return a descriptive error identifying the unavailable exchange rate.

### Requirement 22: Licensing Structure and Windowing Terms

**User Story:** As a content buyer, I want contract windowing and payment structures modeled, so that valuations reflect real licensing economics rather than a flat lump sum.

#### Acceptance Criteria

1. WHEN a title is ingested, THE CineROI_System SHALL capture License_Terms including license duration in months, an exclusivity flag, windowing rules, holdbacks, and a milestone-based payment schedule.
2. WHEN the Guardrails_Engine computes payback_horizon_months for a title, THE Guardrails_Engine SHALL use the milestone-based payment schedule rather than a single lump-sum disbursement.
3. WHEN the Guardrails_Engine projects value for a title, THE Guardrails_Engine SHALL distinguish exclusive windows from non-exclusive windows in the projected value.
4. IF the sum of windowing periods for a title exceeds the total license duration, THEN THE CineROI_System SHALL reject the License_Terms and return a descriptive error indicating that windowing exceeds the license duration.

### Requirement 23: Asynchronous Background Job Processing

**User Story:** As a data scientist, I want heavy computations run asynchronously, so that large batch ingests and audits do not block or time out HTTP requests.

#### Acceptance Criteria

1. WHEN a batch ingestion, vector generation, or backtest audit operation is requested, THE API_Service SHALL dispatch the operation to the Task_Queue rather than executing it inline within the HTTP request.
2. WHEN an operation is dispatched to the Task_Queue, THE API_Service SHALL return a job identifier in the response before the operation completes.
3. WHEN a job executes, THE Task_Queue SHALL track its Job_Status through the states PENDING, PROCESSING, and either COMPLETED or FAILED.
4. WHEN a request to retrieve job status by job identifier is received, THE API_Service SHALL return the current Job_Status for that job identifier.
5. IF a job transitions to FAILED, THEN THE Task_Queue SHALL record a failure reason associated with that job identifier.
6. WHEN a job reaches a terminal Job_Status of COMPLETED or FAILED, THE CineROI_System SHALL send a webhook notification reporting the job identifier and its terminal status.

### Requirement 24: Script and Pitch Version Control

**User Story:** As a content buyer, I want iterative script and pitch submissions versioned, so that revised drafts are tracked without losing prior evaluations.

#### Acceptance Criteria

1. WHEN a new submission is ingested for an existing title, THE CineROI_System SHALL store the submission as a versioned child of the original title rather than overwriting the original.
2. WHEN a versioned submission is created, THE CineROI_System SHALL assign an incrementing version identifier to that submission.
3. WHEN a new version is created, THE CineROI_System SHALL retain the metadata vector profile of all prior versions unchanged.
4. THE CineROI_System SHALL designate exactly one version per title as the active version used for Dashboard_UI display and valuation.
5. WHEN a request for a title's evaluation history is received, THE API_Service SHALL return the evaluation records across all versions of that title.

### Requirement 25: Audit Logging and Data Lineage

**User Story:** As a compliance officer, I want an immutable audit trail of state-changing actions, so that every decision input and change is traceable.

#### Acceptance Criteria

1. WHEN a state-changing operation (ingest, valuation, override, approval, or calibration) is performed, THE Audit_Log_Service SHALL record the actor identity, a timestamp, the action, and the before and after values.
2. THE Audit_Log_Service SHALL store audit entries as append-only records that cannot be updated or deleted.
3. WHEN a valuation is produced, THE Audit_Log_Service SHALL associate the valuation with the Model_Version in effect at the time of production.
4. WHEN a request for the lineage of a given title or decision is received, THE API_Service SHALL return the complete ordered set of audit entries for that title or decision.

### Requirement 26: Model Versioning and Reproducibility

**User Story:** As a data scientist, I want each valuation tied to a model version, so that past recommendations remain reproducible after calibration changes weights.

#### Acceptance Criteria

1. WHEN feature-extraction weights or guardrail parameters change, THE CineROI_System SHALL assign a new Model_Version identifier capturing the changed parameter set.
2. WHEN the Guardrails_Engine produces a valuation, THE Guardrails_Engine SHALL stamp the valuation with the Model_Version used to produce the valuation.
3. THE CineROI_System SHALL retain all historical Model_Version definitions so that a prior valuation can be reproduced from its stamped Model_Version.
4. WHEN the Calibration_Controller applies calibration as defined in Requirement 12, THE Calibration_Controller SHALL create a new Model_Version rather than mutating the existing Model_Version in place.

### Requirement 27: Concurrency Control and Idempotency

**User Story:** As a platform engineer, I want concurrent and duplicate operations handled safely, so that data remains consistent under simultaneous use.

#### Acceptance Criteria

1. WHEN an ingestion request includes an idempotency key that matches a previously processed request, THE Ingestion_Service SHALL return the original result and SHALL NOT create duplicate records.
2. IF a valuation update is submitted against a stale version of a title record, THEN THE API_Service SHALL reject the update using optimistic locking and return a conflict error.
3. WHEN two or more valuations of the same title execute concurrently, THE Guardrails_Engine SHALL complete the valuations without producing corrupted or partially written data.
4. WHEN a webhook delivery is received more than once for the same event, THE CineROI_System SHALL process the delivery idempotently so that repeated deliveries produce no additional effect.

### Requirement 28: Data Retention, Confidentiality, and PII Protection

**User Story:** As a security administrator, I want sensitive content and deal data protected and retained per policy, so that confidential material is safeguarded and compliant.

#### Acceptance Criteria

1. THE CineROI_System SHALL encrypt sensitive data, including unreleased scripts, deal terms, and PII, at rest.
2. WHEN a user requests a confidential record, THE RBAC_Service SHALL scope access to that record by the user's User_Role and authorized territory or business unit.
3. WHERE a configurable retention period for a record has elapsed, THE CineROI_System SHALL purge or archive the eligible record according to the configured policy.
4. IF a user whose User_Role is not authorized for a secret or confidential field requests that field, THEN THE RBAC_Service SHALL withhold the field value and return an authorization indication for that field.

### Requirement 29: Observability, SLAs, and Failure Handling

**User Story:** As a platform operator, I want observability and defined processing SLAs, so that the system's health and job throughput are monitored and failures are recoverable.

#### Acceptance Criteria

1. WHEN an API request is handled or a background job executes, THE CineROI_System SHALL emit metrics and structured logs for that request or job.
2. IF a background job's processing time exceeds its defined SLA of 15 minutes, THEN THE CineROI_System SHALL raise an alert identifying the job.
3. WHEN a job fails after exhausting its configured retries, THE Task_Queue SHALL route the job to a dead-letter queue for inspection.
4. WHEN a request to the health endpoint is received, THE API_Service SHALL report the status of the database, the Task_Queue, and the Telemetry_Connector.
5. WHEN an operator requests retry of a dead-lettered job after remediation, THE Task_Queue SHALL re-dispatch the job for processing.

### Requirement 30: Recommendation Explainability

**User Story:** As a programming executive, I want each recommendation to explain its basis, so that I understand and can justify overriding a PASS or NEGOTIATE_HARD.

#### Acceptance Criteria

1. WHEN the Guardrails_Engine produces a Recommendation_Status, THE Guardrails_Engine SHALL report which guardrail checks passed and which were breached.
2. WHEN a guardrail check is breached, THE Guardrails_Engine SHALL report the computed value, the applicable threshold, and the magnitude of the shortfall for that check.
3. WHEN the Recommendation_Status is PASS or NEGOTIATE_HARD, THE Guardrails_Engine SHALL identify the dominant contributing factor driving the status.
4. WHEN a valuation is retrieved through `GET /api/v1/valuation/{title_id}`, THE API_Service SHALL include the recommendation explanation in the response and THE Title_Evaluation_UI SHALL surface the explanation.

### Requirement 31: Comparable Titles (Top 3 Historical Comps)

**User Story:** As a content buyer, I want to see the titles most similar to the one I am evaluating, so that I can sanity-check a valuation against the closest precedents in the catalog.

#### Acceptance Criteria

1. WHEN a request to `GET /api/v1/valuation/{title_id}/comps` is received for a title that has a persisted Narrative_DNA vector, THE API_Service SHALL return up to three other titles ranked in descending order of Narrative_DNA cosine similarity to that title, excluding the title itself.
2. WHEN comparable titles are returned, THE API_Service SHALL include, for each comparable, its title identifier, title name, genre tag, latest Recommendation_Status (null when the comparable has no computed valuation), and the cosine similarity score.
3. IF the requested title has no persisted Narrative_DNA vector, THEN THE API_Service SHALL return a result indicating comparables could not be computed (found = false) with an empty comparables list, rather than an error.
4. IF the requested title_id does not exist, THEN THE API_Service SHALL return a not-found error identifying the missing title_id.
5. WHEN a title has more than one persisted Narrative_DNA vector (re-extractions), THE API_Service SHALL rank each other title by its single closest vector so no comparable title appears more than once.
6. WHEN the Title_Evaluation_UI loads for a title, THE Title_Evaluation_UI SHALL render a "Top 3 historical comps" panel listing each comparable with its name, recommendation badge, and similarity, linking each to that comparable's evaluation; AND SHALL render a graceful empty state when no comparable is available.

### Requirement 32: Market Telemetry Card on Title Evaluation

**User Story:** As a programming executive, I want the live market signals for a title's genre and territory shown on its evaluation, so that I can see the external context the valuation's territory weighting reflects.

#### Acceptance Criteria

1. WHEN a request to `GET /api/v1/valuation/{title_id}` is received, THE API_Service SHALL include the title's genre tag and Primary_Territory in the scorecard response.
2. WHEN the Title_Evaluation_UI has loaded a title's scorecard with a genre tag and Primary_Territory, THE Title_Evaluation_UI SHALL request `GET /api/v1/market/telemetry` for that genre and territory and render a Market_Telemetry_Card showing the social sentiment index, chart velocity score, and licensing inflation multiplier.
3. IF the telemetry source for the pair was unavailable on its most recent poll (source_available = false), THEN THE Market_Telemetry_Card SHALL display the retained values together with a staleness indication.
4. IF no telemetry has ever been cached for the pair (found = false), THEN THE Market_Telemetry_Card SHALL display a "not yet polled" empty state rather than an error.
5. IF the title has no genre tag or no Primary_Territory, THEN THE Title_Evaluation_UI SHALL omit the Market_Telemetry_Card rather than issue a telemetry request.

### Requirement 33: Dashboard Filtering, Search, and Shareable View State

**User Story:** As a programming executive, I want to search and filter the pipeline grid and share or bookmark a filtered view, so that I can quickly find titles and send a colleague the exact same view.

#### Acceptance Criteria

1. WHEN a user types in the dashboard title search box, THE Dashboard_UI SHALL restrict the grid to titles whose name contains the entered text, case-insensitively.
2. WHEN a user selects a recommendation filter or a deal-stage filter, THE Dashboard_UI SHALL restrict the grid to titles matching the selected Recommendation_Status or Deal_Stage respectively.
3. WHEN a user changes the search text, either filter, or the sort column/direction, THE Dashboard_UI SHALL reflect the resulting Dashboard_View_State in the page URL query string.
4. WHEN the dashboard is opened with a URL carrying view-state query parameters, THE Dashboard_UI SHALL initialize the grid's search, filters, and sort from those parameters so the same filtered, sorted view is reproduced.
5. WHEN the active filters match no titles, THE Dashboard_UI SHALL display a no-match state with a control to clear the filters, while leaving the underlying pipeline unchanged.
6. WHEN view-state query parameters change, THE Dashboard_UI SHALL replace rather than append browser history so repeated filtering does not flood the back button.

### Requirement 34: Deal-Stage Acquisition Lifecycle

**User Story:** As a content buyer, I want to track where each title sits in our acquisition pipeline, independent of the AI's recommendation, so that the portfolio reflects the real state of each deal.

#### Acceptance Criteria

1. THE CineROI_System SHALL store a Deal_Stage for every title, constrained to the set {SCREENING, EVALUATED, IN_NEGOTIATION, APPROVED, CLOSED_WON, CLOSED_LOST, PASSED}, defaulting a newly ingested title to SCREENING.
2. WHEN a request to `GET /api/v1/titles/{title_id}/deal-stage` is received, THE API_Service SHALL return the title's current Deal_Stage and the set of stages it may legally transition to next.
3. WHEN a request to `PATCH /api/v1/titles/{title_id}/deal-stage` proposes a target stage that is a legal transition from the current stage, THE API_Service SHALL update the title's Deal_Stage, record an append-only audit entry capturing the before and after stage, and return the new stage with its allowed next stages.
4. IF a PATCH proposes a stage that is not a legal transition from the current stage (including a transition out of a Terminal_Deal_Stage or a no-op to the same stage), THEN THE API_Service SHALL reject the request without changing the Deal_Stage and return an error identifying the current stage and the allowed next stages.
5. IF a user whose User_Role is not CONTENT_BUYER, CHIEF_CONTENT_OFFICER, or CFO attempts a Deal_Stage transition, THEN THE RBAC_Service SHALL reject the request with an authorization error and leave the Deal_Stage unchanged.
6. WHEN the Dashboard_UI renders the master asset data grid, THE Dashboard_UI SHALL show each title's Deal_Stage as a sortable column and allow filtering the grid by Deal_Stage.
7. WHEN the Title_Evaluation_UI loads for a title, THE Title_Evaluation_UI SHALL render a deal-stage control showing the current stage and offering only the legal next stages; a title in a Terminal_Deal_Stage SHALL offer no transitions; and a user without permission SHALL see the stage read-only.
8. THE Deal_Stage_Lifecycle SHALL permit, from any live (non-terminal) stage, a transition to PASSED; a single forward step along SCREENING to EVALUATED to IN_NEGOTIATION to APPROVED; and from APPROVED a transition to CLOSED_WON or CLOSED_LOST.

### Requirement 35: Responsive Tablet Layout

**User Story:** As an executive reviewing deals on a tablet, I want the portal to be usable at tablet screen widths, so that I can review and act on titles away from my desk.

#### Acceptance Criteria

1. THE CineROI_System frontend SHALL declare a responsive viewport so pages scale to the device width.
2. WHERE a page is viewed at a tablet-class width (approximately 768 to 1024 pixels), THE Dashboard_UI, Title_Evaluation_UI, and Backtest_Studio_UI SHALL present their primary content without horizontal clipping of controls, stacking multi-column layouts as needed and allowing the data grid to scroll horizontally within its container.
3. WHEN interactive controls (the what-if sliders) are presented on a touch device, THE Title_Evaluation_UI SHALL render them with a touch-friendly hit area and SHALL NOT scroll the page while a slider is being dragged.
4. WHEN the metadata radar is rendered within a constrained (half-width) column, THE Title_Evaluation_UI SHALL keep the axis labels within the chart bounds (no clipping).

### Requirement 36: Demo and Operational Integrity

**User Story:** As a platform operator running demonstrations, I want the seeded data to be internally consistent, the valuation to tolerate a missing exact-date rate, and a one-command reset, so that demos are reproducible and recomputing a seeded title never contradicts its stored verdict.

#### Acceptance Criteria

1. THE CineROI_System seed data SHALL be internally consistent such that recomputing any seeded title through the Guardrails_Engine reproduces that title's stored Recommendation_Status and the stored payback_horizon_months.
2. WHEN the Guardrails_Engine normalizes a cost and no exchange rate exists for the exact required rate date, THE Guardrails_Engine SHALL fall back to the latest available dated rate for that currency pair rather than rejecting the valuation, and SHALL reject only when no rate for the currency pair exists at all (R21.5).
3. WHEN a valuation is recomputed for a title that already has a persisted financial projection, THE Guardrails_Engine SHALL update the existing projection under optimistic locking without error (an optimistic-locked update SHALL resolve the primary-key column from the model class, not from the repository instance), persisting the recomputed scorecard.
4. WHEN the Demo_Reset script is run against a running stack, THE CineROI_System SHALL truncate the demo-mutable tables (including the market telemetry cache) and re-apply the pristine seed, leaving exactly the seeded titles in the pipeline.
5. THE CineROI_System SHALL provide an in-portal "How It Works" guide that explains, in plain non-technical language with worked arithmetic drawn from the seeded titles, what each guardrail computes and how a Recommendation_Status is reached.
6. WHEN a request to `GET /api/v1/valuation/{title_id}/decision` is received, THE API_Service SHALL resolve the title to its latest decision (financial-projection) identifier that the sign-off and finalization endpoints key on, or return a not-found error when the title has no computed valuation.
7. WHERE the demo authentication bypass is enabled and the environment is not production, THE API_Service SHALL expose `POST /api/v1/decisions/{decision_id}/demo-sign-off` that records an executive approval attributed to the seeded user holding the requested role (CHIEF_CONTENT_OFFICER or CFO), so a single-identity demo session can clear a two-role high-budget sign-off gate; outside dev/demo this route SHALL be absent (return not-found).
### Requirement 37: Asset Studio - Instant Evaluation and Intake

**User Story:** As a content buyer, I want to evaluate a title the moment I enter it, bring in a whole slate at once, or let a pitch PDF fill the form, so that I can get a verdict without waiting on the batch pipeline or retyping a deck.

#### Acceptance Criteria

1. WHEN a request to `POST /api/v1/titles/quick-evaluate` is received with a title's details, THE API_Service SHALL create the title and its active version, invoke the Guardrails_Engine inline, and return a full scorecard (recommendation, the four guardrail outputs, explanation, metadata profile, and the Deal Decision Support fields) in the same response.
2. IF a quick-evaluate request omits projected viewing hours or supplies a non-positive value, THEN THE API_Service SHALL estimate projected viewing hours from the title's budget and pedigree so CPVH can still be computed.
3. WHEN a quick-evaluate request supplies a non-USD native currency, THE Guardrails_Engine SHALL normalize the cost using the dated exchange rate for the rate date, falling back to the latest available rate for that currency pair when the exact date is absent (R21.5, R36.2).
4. WHEN a request to `POST /api/v1/titles/parse-pitch` is received with a PDF, THE API_Service SHALL return best-effort candidate values for the title name, synopsis, genre, budget, and currency for the user to review, and SHALL NOT create a title or submit a valuation from the parse step.
5. WHEN the Asset_Studio_UI cost field receives a Shorthand_Amount, THE Asset_Studio_UI SHALL display a live preview of the fully expanded numeric amount before the valuation is run.
6. WHEN the Asset_Studio_UI Batch Slate tab is used to upload or paste a CSV or JSON slate, THE Asset_Studio_UI SHALL submit it through the asynchronous batch ingestion path (R1, R23) and report the accepted and rejected counts with a reason per rejected row.
7. WHEN the Asset_Studio_UI runs an Instant_Evaluation, THE Asset_Studio_UI SHALL render the returned scorecard and offer a link to the title's full deep-dive evaluation.