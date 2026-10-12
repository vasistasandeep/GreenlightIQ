# Requirements Document

## Introduction

The Backtesting & Calibration Studio (`/backtest`) lets an analyst submit observed
ground-truth outcomes for a historical title and compare predicted vs actual via
an audit scorecard. In its current form the studio is confusing and fragile for a
demo user:

- The ground-truth form accepts a free-typed "Historical title ID" string. The
  backend schema (`BacktestAuditRequest.title_id`) requires a `uuid.UUID`, so a
  plain name such as "Maharani" is rejected by request-shape validation
  (`422 VALIDATION_FAILED`) before the handler runs.
- The audit is only meaningful for a title that ALREADY has a stored prediction
  (the audit compares predicted vs actual). An arbitrary name can never succeed
  regardless of format, so inviting free text is misleading.
- When any backend rejection occurs the page surfaces the raw envelope message
  (e.g. "Request validation failed.") with no guidance about what went wrong or
  how to fix it, because the page only reads `err.envelope?.message` and ignores
  the structured `error_code`.

This feature makes the studio understandable and resilient for a demo user by
replacing free-text title entry with a selection of titles that are actually
auditable (a title with a stored prediction), and by translating backend
rejections into readable, actionable messages. The scope is strictly a
demo-support UX fix: the audit math, the ground-truth validation rules, and the
calibration flow are unchanged.

Ground truth established from the current codebase:
- `GET /dashboard/summary` already returns every pipeline title with `title_id`,
  `title_name`, `asset_type`, `recommendation_status`, and
  `ltv_to_cost_multiple`. A title has a stored prediction when it carries a
  non-null `recommendation_status`. The typed client already exposes
  `api.getDashboardSummary()`.
- The shared error envelope exposes `error_code`: `VALIDATION_FAILED` (422,
  request-shape), `GROUND_TRUTH_INVALID` (422), `GROUND_TRUTH_MISSING` (404),
  and `TITLE_NOT_FOUND` (404).

## Glossary

- **Backtest_Studio**: The `/backtest` page (`frontend/app/backtest/page.tsx`)
  that owns the audit request lifecycle and renders the studio panes.
- **Ground_Truth_Form**: The left-pane input component
  (`frontend/components/backtest/ground-truth-form.tsx`) that collects the
  audited title selection and the observed actual metric values and shapes a
  `BacktestAuditRequest`.
- **Title_Selector**: The control, introduced by this feature, that lets the
  user choose an auditable title instead of typing a free-text identifier.
- **Auditable_Title**: A pipeline title that carries a stored prediction — a
  title whose `recommendation_status` from `GET /dashboard/summary` is non-null.
- **Dashboard_Summary_Endpoint**: `GET /dashboard/summary`, the existing
  read-only aggregate that lists pipeline titles and their valuation outcome.
- **Audit_Request**: The `BacktestAuditRequest` payload posted to
  `POST /api/v1/backtest/audit`, carrying `title_id` (UUID) and one or more
  observed `metrics`.
- **Error_Envelope**: The backend error contract `{ error_code, message,
  details }` carried on an `ApiError` as `err.envelope`.
- **Error_Message_Mapper**: The logic, introduced by this feature, that maps an
  `Error_Envelope` (keyed on `error_code` and HTTP status) to a readable,
  actionable message for the user.
- **Demo_User**: An operator exercising the application in a demo context,
  without prior knowledge of internal title identifiers.

## Requirements

### Requirement 1: Select an auditable title instead of typing one

**User Story:** As a demo user, I want to choose the title to audit from a list
of titles that already have a stored prediction, so that I never have to guess
or type an internal identifier and I only submit audits that can succeed.

#### Acceptance Criteria

1. WHEN the Backtest_Studio renders the Ground_Truth_Form, THE Ground_Truth_Form SHALL present a Title_Selector that lists the available Auditable_Titles for selection instead of a free-text identifier input.
2. WHEN the Title_Selector is populated, THE Ground_Truth_Form SHALL display each selectable option with the Auditable_Title name so a Demo_User can recognize it without knowing the identifier.
3. WHEN a Demo_User selects an Auditable_Title in the Title_Selector, THE Ground_Truth_Form SHALL set the Audit_Request `title_id` to the selected Auditable_Title's `title_id`.
4. WHILE no Auditable_Title is selected, THE Ground_Truth_Form SHALL keep the audit submission control disabled.
5. WHEN a Demo_User submits the Ground_Truth_Form with a selected Auditable_Title and at least one observed actual value, THE Ground_Truth_Form SHALL emit an Audit_Request whose `title_id` is the selected Auditable_Title's identifier and whose `metrics` contain only the filled-in actual values.

### Requirement 2: Determine auditable titles from existing data

**User Story:** As a demo user, I want the title choices to come from the titles
the system actually knows about, so that the choices are real and current.

#### Acceptance Criteria

1. WHEN the Backtest_Studio initializes, THE Backtest_Studio SHALL request the title list from the Dashboard_Summary_Endpoint.
2. WHEN the Dashboard_Summary_Endpoint returns the title list, THE Backtest_Studio SHALL treat a title as an Auditable_Title WHERE that title's `recommendation_status` is non-null.
3. WHEN the Backtest_Studio has resolved the Auditable_Titles, THE Backtest_Studio SHALL provide those Auditable_Titles to the Ground_Truth_Form for selection.
4. WHEN the Dashboard_Summary_Endpoint returns titles but none are Auditable_Titles, THE Ground_Truth_Form SHALL display a message stating that no titles with a stored prediction are available to audit.
5. IF the request to the Dashboard_Summary_Endpoint fails, THEN THE Backtest_Studio SHALL display a readable message indicating the auditable titles could not be loaded and SHALL keep the audit submission control disabled.

### Requirement 3: Translate backend rejections into actionable messages

**User Story:** As a demo user, I want a clear explanation when an audit is
rejected, so that I understand what went wrong and what to do next instead of
seeing a raw technical error.

#### Acceptance Criteria

1. IF an Audit_Request is rejected with an Error_Envelope whose `error_code` is `VALIDATION_FAILED`, THEN THE Backtest_Studio SHALL display a message stating that the selected title identifier is invalid or missing and that an auditable title must be selected.
2. IF an Audit_Request is rejected with an Error_Envelope whose HTTP status is 404 and whose `error_code` is `TITLE_NOT_FOUND`, THEN THE Backtest_Studio SHALL display a message stating that the selected title no longer exists in the system.
3. IF an Audit_Request is rejected with an Error_Envelope whose HTTP status is 404 and whose `error_code` is `GROUND_TRUTH_MISSING`, THEN THE Backtest_Studio SHALL display a message stating that the selected title has no stored prediction to audit against.
4. IF an Audit_Request is rejected with an Error_Envelope whose `error_code` is `GROUND_TRUTH_INVALID`, THEN THE Backtest_Studio SHALL display a message stating that the entered actual values are invalid and must be numeric.
5. IF an Audit_Request is rejected with an Error_Envelope whose `error_code` matches none of the mapped codes, THEN THE Backtest_Studio SHALL display the Error_Envelope `message` WHERE the Error_Envelope carries a message, and SHALL otherwise display a generic failure message.
6. WHEN the Error_Message_Mapper produces a user-facing message, THE Error_Message_Mapper SHALL compose that message from ASCII characters only.

### Requirement 4: Preserve existing studio behavior and theme

**User Story:** As a demo user, I want the studio to keep working and looking the
way it does today, so that the fix does not break the audit, calibration, or
sign-off flows.

#### Acceptance Criteria

1. WHEN an Audit_Request succeeds, THE Backtest_Studio SHALL render the predicted-vs-actual variance scorecard and the overall MAPE exactly as it does today.
2. WHEN an Audit_Request succeeds, THE Backtest_Studio SHALL enable the calibration control for the audited title exactly as it does today.
3. THE Ground_Truth_Form SHALL continue to collect the observed CPVH and LTV-to-cost actual values and omit any blank metric field from the Audit_Request.
4. THE Ground_Truth_Form SHALL present the Title_Selector and surrounding controls using the existing dark AppShell theme styling.
5. THE Backtest_Studio SHALL leave the audit computation, the ground-truth validation rules, and the calibration flow unchanged.

### Requirement 5: Keep the change demo-safe

**User Story:** As a maintainer, I want this demo-support fix to avoid weakening
production safety, so that enabling the demo flow does not create a security or
data-integrity regression.

#### Acceptance Criteria

1. THE feature SHALL source the Title_Selector data from endpoints that already exist in the backend WHERE such an endpoint already satisfies the need.
2. WHERE a new backend endpoint is introduced for the Title_Selector, THE new endpoint SHALL preserve the existing authentication and authorization guards without weakening production safety.
3. THE feature SHALL leave the dev-only authentication bypass behavior unchanged.
