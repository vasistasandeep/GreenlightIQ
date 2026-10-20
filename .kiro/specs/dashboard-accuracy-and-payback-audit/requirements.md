# Requirements Document

## Introduction

CineROI AI (FastAPI backend + Next.js frontend, Dockerized) exposes an Executive
Command Dashboard and a Backtesting & Calibration Studio. This spec covers two
small, related enhancements to the accuracy/backtesting surfaces. The product's
core value is honest numbers, so both enhancements are constrained to never
fabricate or proxy accuracy onto an executive view.

**Enhancement 1 — Dashboard "Model Accuracy" card.** Today
`GET /api/v1/dashboard/summary` (`backend/app/api/dashboard.py`) hard-codes
`model_accuracy_rate=None`, so the "Model Accuracy" KPI card
(`frontend/components/dashboard/kpi-cards.tsx`) always renders a dash. The card
must display a real "verdict-match rate" — the share of audited titles whose
predicted recommendation matched the actual (ground-truth-derived) outcome,
higher is better — and must stay blank (`null`) whenever no honest basis exists.

A design-affecting data nuance must be resolved here. A true per-title
"verdict match" does not exist today:

- The **offline harness** (`backend/app/engines/backtest_harness.py`) computes a
  dataset-level `verdict_match_rate` because each dataset row carries an
  `expected_recommendation` label. This is PROXY/SYNTHETIC accuracy over a
  committed dataset, explicitly labeled `proxy_accuracy` in that module, not
  live-pipeline accuracy.
- The **per-title audit path** (`POST /api/v1/backtest/audit`,
  `backend/app/engines/backtesting.py`) persists raw ground-truth metric values
  (`cpvh`, `ltv_to_cost`, `churn_reduction`, `payback_horizon`) to
  `historical_ground_truth` and returns a MAPE, but it does **not** store or
  compute an "actual recommendation" per title. There is no per-title
  verdict-match today.

Two options were considered for the single source of truth:

- **Option (a) — per-title audit-derived verdict match (SELECTED).** For each
  title that has ground truth, recompute an "actual" recommendation from that
  title's ACTUAL ground-truth metric values and compare it against the title's
  stored PREDICTED `recommendation_status`. The dashboard figure is the match
  rate across the titles where this comparison can be honestly made, and stays
  `null` when there are none. This reflects the live pipeline (the same
  projections the dashboard already renders) and reuses existing persisted data.
- **Option (b) — surface the harness `verdict_match_rate` (REJECTED).** This is
  dataset-level PROXY accuracy over a synthetic committed dataset, not
  live-pipeline accuracy. Placing it unqualified on the executive dashboard
  would misrepresent proxy accuracy as real model accuracy and violates the
  demo-honesty posture. Rejected for the dashboard number.

Option (a) carries an honesty constraint confirmed against the code: the
recommendation rule (`app.domain.recommendation.determine_recommendation`)
consumes classified guardrail *checks* (thresholds + correctability), while
`historical_ground_truth` stores only raw actual metric values. The requirements
therefore scope the "actual" verdict strictly to titles whose stored ground
truth is sufficient to produce a classifiable actual verdict, and exclude every
title that is not — so the number is real, never inferred from absent data.

**Enhancement 2 — `payback_horizon` ground-truth input in Backtest Studio.** The
backend audit already scores four metrics via `PREDICTED_METRIC_FIELDS`
(`cpvh`, `ltv_to_cost`, `churn_reduction`, `payback_horizon`). The frontend
`GroundTruthForm` (`frontend/components/backtest/ground-truth-form.tsx`) exposes
only three, omitting `payback_horizon`, so an analyst cannot enter actual payback
and it never contributes to MAPE. The form must add an "Actual payback horizon
(months)" input that threads to the existing `POST /backtest/audit` metrics list
exactly like the other three, and display the read-only "Predicted" payback
(available on the stored projection as `payback_horizon_months`). The audit
endpoint already accepts the `payback_horizon` metric, so no backend audit
contract change is required for this enhancement.

**Enhancement 3 — demo ground-truth seed.** The seed generator
(`database/seed/generate_seed_sql.py`) emits no `historical_ground_truth` rows
today, so a fresh demo has zero ground truth and the accuracy card can never
light up. This enhancement seeds deterministic, honestly-labeled actual outcomes
for the existing historical title(s) so at least one Eligible_Audited_Title
exists on a clean boot, making the Model_Accuracy_Rate a real (not fabricated)
number during a demo. The seed is additive, idempotent, and clearly marked as
demo/illustrative data, never presented as production outcomes.

## Glossary
- **Dashboard_Service**: The backend handler for `GET /api/v1/dashboard/summary`
  in `backend/app/api/dashboard.py`, which builds the `{kpis, titles}` payload.
- **Model_Accuracy_Rate**: The nullable float KPI field `model_accuracy_rate` on
  the dashboard `kpis` object, rendered by the "Model Accuracy" card.
- **Verdict_Match_Rate**: The share, in the closed interval 0 to 1, of eligible
  audited titles whose Actual_Verdict equals the title's Predicted_Verdict.
- **Predicted_Verdict**: A title's stored `recommendation_status` on its latest
  `financial_projections` row (one of GREENLIGHT, NEGOTIATE_HARD, PASS).
- **Actual_Verdict**: The recommendation recomputed from a title's actual
  ground-truth metric values using the existing recommendation rule
  (`app.domain.recommendation.determine_recommendation`).
- **Ground_Truth_Store**: The `historical_ground_truth` table, holding raw actual
  metric values keyed by `title_id` and `metric_name`.
- **Eligible_Audited_Title**: A title that has at least one ground-truth metric
  in the Ground_Truth_Store AND for which the stored ground-truth metrics plus
  the title's own stored thresholds are sufficient to produce a classifiable
  Actual_Verdict.
- **Backtesting_Module**: `backend/app/engines/backtesting.py`, owning
  ground-truth persistence, the audit scorecard, MAPE, and `PREDICTED_METRIC_FIELDS`.
- **Backtest_Harness**: The offline `backend/app/engines/backtest_harness.py`
  measurement substrate that computes a dataset-level, proxy `verdict_match_rate`.
- **Ground_Truth_Form**: The frontend input component
  `frontend/components/backtest/ground-truth-form.tsx`.
- **Auditable_Title_Option**: The option shape in
  `frontend/lib/backtest/select-auditable-titles.ts` the Backtest Studio page
  passes to the Ground_Truth_Form.
- **Title_Summary**: One master-grid row in the dashboard payload (`TitleSummary`
  in both `backend/app/api/dashboard.py` and `frontend/lib/types.ts`).
- **MAPE**: Mean Absolute Percentage Error, computed by
  `app.domain.mape.compute_mape`, which excludes zero-actual metrics.
- **Predicted_Payback**: The stored predicted payback horizon in whole months,
  `payback_horizon_months` on the latest `financial_projections` row.

- **Seed_Generator**: `database/seed/generate_seed_sql.py`, the deterministic
  generator that emits `02_seed_data.sql` (titles, projections, and related
  rows) applied on first boot by `database/seed/seed.py`.
- **Demo_Ground_Truth**: additive, deterministic, demo-labeled
  `historical_ground_truth` rows seeded for existing historical title(s) so a
  clean boot has at least one Eligible_Audited_Title.

## Requirements
### Requirement 1: Honest source of truth for the dashboard accuracy number

**User Story:** As a portfolio executive, I want the "Model Accuracy" card to
reflect how often the live pipeline's recommendations matched real outcomes, so
that I can trust it as a measure of model quality rather than a synthetic proxy.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL derive Model_Accuracy_Rate from the per-title
   audit path (option a), computed as the Verdict_Match_Rate over
   Eligible_Audited_Titles.
2. THE Dashboard_Service SHALL compute each Actual_Verdict from a title's actual
   ground-truth metric values using the existing recommendation rule in
   `app.domain.recommendation`, rather than defining a new recommendation rule.
3. THE Dashboard_Service SHALL compare each title's Actual_Verdict against that
   title's stored Predicted_Verdict (`recommendation_status`) to decide a match.
4. THE Dashboard_Service SHALL exclude the Backtest_Harness dataset-level
   `verdict_match_rate` from the Model_Accuracy_Rate figure.
5. WHERE no live-pipeline basis exists for a verdict comparison, THE
   Dashboard_Service SHALL NOT substitute the Backtest_Harness proxy figure.

### Requirement 2: Eligibility and blank-until-measured behavior

**User Story:** As a portfolio executive, I want the accuracy card to stay blank
until there is a real basis, so that an empty or thin dataset never shows a
fabricated score.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL treat a title as an Eligible_Audited_Title only
   when the title has at least one ground-truth metric in the Ground_Truth_Store
   AND the stored ground-truth metrics plus the title's own stored thresholds are
   sufficient to produce a classifiable Actual_Verdict.
2. IF a title has no ground-truth metrics in the Ground_Truth_Store, THEN THE
   Dashboard_Service SHALL exclude that title from the Model_Accuracy_Rate
   computation.
3. IF a title's stored ground truth is insufficient to classify an Actual_Verdict,
   THEN THE Dashboard_Service SHALL exclude that title from the
   Model_Accuracy_Rate computation.
4. IF the count of Eligible_Audited_Titles is zero, THEN THE Dashboard_Service
   SHALL set Model_Accuracy_Rate to `null`.
5. WHEN at least one Eligible_Audited_Title exists, THE Dashboard_Service SHALL
   set Model_Accuracy_Rate to the fraction of Eligible_Audited_Titles whose
   Actual_Verdict equals their Predicted_Verdict, expressed as a float in the
   closed interval 0 to 1 where a higher value indicates higher accuracy.
6. THE Dashboard_Service SHALL NOT emit a zero Model_Accuracy_Rate to stand in
   for "not yet measured"; absence of a basis is represented by `null`.

### Requirement 3: Deterministic and reproducible accuracy figure

**User Story:** As an engineer, I want the dashboard accuracy number to be
deterministic, so that the same persisted data always yields the same figure and
it can be covered by tests.

#### Acceptance Criteria

1. WHEN the Ground_Truth_Store, the titles, and their latest
   `financial_projections` rows are unchanged, THE Dashboard_Service SHALL return
   the same Model_Accuracy_Rate value on repeated requests.
2. THE Dashboard_Service SHALL compute Model_Accuracy_Rate as a pure function of
   persisted title, latest-projection, and ground-truth data, consulting no
   wall-clock time, random source, or request ordering.
3. THE Dashboard_Service SHALL round Model_Accuracy_Rate to a fixed, documented
   number of decimal places so the emitted value is stable across runs.

### Requirement 4: Dashboard response contract is preserved

**User Story:** As a frontend developer, I want the dashboard response shape to
stay stable, so that enabling the accuracy figure does not break existing
consumers.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL keep `model_accuracy_rate` as a nullable float
   field on the `kpis` object of the `GET /api/v1/dashboard/summary` response.
2. THE Dashboard_Service SHALL leave the three existing KPI figures
   (`active_pipeline_valuation_usd`, `avg_ltv_to_cost`,
   `portfolio_risk_exposure`) unchanged in value and semantics.
3. THE Dashboard_Service SHALL preserve the existing `{kpis, titles}` response
   structure and the existing field names and types on each Title_Summary row.
4. WHERE additional per-title data is needed to support the Backtest Studio
   payback display, THE Dashboard_Service SHALL add it as a new optional,
   nullable field rather than removing, renaming, or retyping any existing field.

### Requirement 5: Accuracy computation stays consistent with the codebase

**User Story:** As a maintainer, I want the accuracy computation to match the
existing backend conventions, so that it integrates cleanly without new
dependencies.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL compute Model_Accuracy_Rate using the Python
   standard library and existing project domain modules, introducing no new
   third-party dependency.
2. THE Dashboard_Service SHALL perform its data access through the existing async
   repository layer and remain an `async` handler consistent with the current
   `GET /api/v1/dashboard/summary` implementation.
3. THE Dashboard_Service SHALL reuse the existing recommendation rule and the
   existing `PREDICTED_METRIC_FIELDS` metric vocabulary rather than duplicating
   recommendation or metric-mapping logic.

### Requirement 6: Backend test coverage for the accuracy figure

**User Story:** As an engineer, I want tests for the accuracy figure, so that its
honesty and determinism are guarded against regressions.

#### Acceptance Criteria

1. THE project SHALL include pytest coverage asserting Model_Accuracy_Rate is
   `null` WHEN there are zero Eligible_Audited_Titles.
2. THE project SHALL include pytest coverage asserting Model_Accuracy_Rate equals
   the expected fraction for a fixed set of titles whose Predicted_Verdict and
   Actual_Verdict are known.
3. THE project SHALL include pytest coverage asserting a title without sufficient
   ground truth is excluded from the computation rather than counted as a match
   or a miss.
4. THE project SHALL include pytest coverage asserting the three existing KPI
   figures are unchanged by the accuracy enhancement.

### Requirement 7: Actual payback horizon input in the Backtest Studio

**User Story:** As a backtesting analyst, I want to enter the actual payback
horizon alongside the other actuals, so that realized payback contributes to the
MAPE scorecard.

#### Acceptance Criteria

1. THE Ground_Truth_Form SHALL present an "Actual payback horizon (months)" input
   alongside the existing CPVH, LTV-to-cost, and churn-reduction inputs.
2. WHEN an analyst enters a value in the payback input and submits, THE
   Ground_Truth_Form SHALL include a metric with `metric_name` `payback_horizon`
   and the entered numeric value in the `POST /backtest/audit` metrics list.
3. WHILE the payback input is left blank, THE Ground_Truth_Form SHALL omit the
   `payback_horizon` metric from the request rather than send a value of zero.
4. IF the payback input contains a non-numeric value on submit, THEN THE
   Ground_Truth_Form SHALL block submission and display a validation message
   identifying the payback field.
5. THE Ground_Truth_Form SHALL thread the payback value through the same request
   shaping used for the existing three metrics, requiring no change to the
   `POST /backtest/audit` request or response contract.

### Requirement 8: Predicted payback is displayed read-only

**User Story:** As a backtesting analyst, I want to see the model's predicted
payback next to the actual input, so that I can compare prediction against
observation before submitting.

#### Acceptance Criteria

1. WHEN a title with a stored Predicted_Payback is selected, THE Ground_Truth_Form
   SHALL display that Predicted_Payback value in a read-only field beside the
   actual payback input.
2. WHERE the selected title's Predicted_Payback is absent, THE Ground_Truth_Form
   SHALL display a non-numeric placeholder consistent with the form's existing
   read-only "Predicted" fields rather than display zero.
3. THE Dashboard_Service SHALL expose `payback_horizon_months` on each
   Title_Summary row so the Predicted_Payback is available to the
   Auditable_Title_Option and the Ground_Truth_Form.
4. THE Auditable_Title_Option SHALL carry the predicted payback value from the
   Title_Summary through to the Ground_Truth_Form, preserving input order of the
   title list.

### Requirement 9: Demo-honesty posture is preserved end to end

**User Story:** As a product owner, I want both surfaces to remain honest, so that
no screen shows a number that is fabricated, zero-filled, or a mislabeled proxy.

#### Acceptance Criteria

1. THE Dashboard_Service SHALL render the Model_Accuracy_Rate as "not yet
   measured" (a `null`-driven dash in the card) rather than a fabricated value
   whenever no Eligible_Audited_Title exists.
2. WHERE the available basis for Model_Accuracy_Rate is limited or proxy in
   nature, THE Dashboard_Service SHALL NOT present it as unqualified live-pipeline
   accuracy on the executive dashboard.
3. THE Ground_Truth_Form SHALL exclude a blank actual payback from the submission
   so that only analyst-entered actuals contribute to MAPE, consistent with the
   server-side rule that a genuine zero actual is excluded from MAPE.

### Requirement 10: Frontend test coverage for the payback input

**User Story:** As a frontend engineer, I want tests for the payback input and
predicted display, so that the threading and omission behavior are guarded.

#### Acceptance Criteria

1. THE project SHALL include vitest coverage asserting that entering an actual
   payback value adds a `payback_horizon` metric to the submitted request.
2. THE project SHALL include vitest coverage asserting that a blank payback input
   omits the `payback_horizon` metric from the submitted request.
3. THE project SHALL include vitest coverage asserting the read-only predicted
   payback renders the title's Predicted_Payback value when present and a
   non-numeric placeholder when absent.
4. THE project SHALL include vitest coverage asserting a non-numeric payback entry
   blocks submission with a field-identifying validation message.

### Requirement 11: Scope boundary

**User Story:** As a reviewer, I want the change tightly scoped to these two
enhancements, so that unrelated behavior is not altered.

#### Acceptance Criteria

1. THE project SHALL limit changes to the dashboard accuracy figure
   (Enhancement 1), the Backtest Studio payback input and predicted display
   (Enhancement 2), and the demo ground-truth seed (Enhancement 3).
2. THE project SHALL leave the Backtest_Harness proxy accuracy computation, the
   existing MAPE arithmetic, and the `POST /backtest/audit` persistence behavior
   unchanged.
3. THE project SHALL leave the existing three dashboard KPIs, the master grid
   rows' existing fields, and all unrelated endpoints unchanged.

### Requirement 12: Deterministic demo ground-truth seed

**User Story:** As a presenter, I want the Model_Accuracy_Rate card to show a
real number on a freshly booted demo, so that I can demonstrate backtested
accuracy without manually entering ground truth first.

#### Acceptance Criteria

1. THE Seed_Generator SHALL emit Demo_Ground_Truth rows into
   `historical_ground_truth` for at least one existing historical title, such
   that at least one Eligible_Audited_Title exists immediately after a clean
   seed.
2. THE Seed_Generator SHALL produce Demo_Ground_Truth deterministically, so that
   regenerating the seed yields byte-identical `historical_ground_truth` INSERT
   statements.
3. THE Demo_Ground_Truth rows SHALL be additive and idempotent on re-seed,
   consistent with the existing seed's `ON CONFLICT`/deterministic-primary-key
   convention, so re-running the seed never duplicates or errors.
4. THE Demo_Ground_Truth actual metric values SHALL be drawn only from the
   metric vocabulary the audit scores (`PREDICTED_METRIC_FIELDS`:
   `cpvh`, `ltv_to_cost`, `churn_reduction`, `payback_horizon`) and SHALL be
   plausible relative to the seeded predictions, not degenerate placeholders.
5. THE Demo_Ground_Truth SHALL be labeled as demo/illustrative data in the seed
   source so it is never represented as real production outcomes, preserving the
   demo-honesty posture.
6. THE Seed_Generator SHALL leave every other seeded entity (titles,
   projections, model versions, the five verdict-preserving churn tolerances)
   unchanged.
7. THE project SHALL include coverage asserting that, after the demo seed, the
   Dashboard_Service returns a non-null Model_Accuracy_Rate derived from at least
   one Eligible_Audited_Title.
