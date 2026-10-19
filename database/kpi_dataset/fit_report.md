# Content_Eval fit report (viewing-hours v1)

- Changed model: `viewing_hours`
- Fit dataset version: `kpi-test-dataset-v1`
- Candidate version label: `fitted-viewing-hours-v1`
- Dominant label type: `SYNTHETIC`

> PROXY ACCURACY: every measured row is PROXY/SYNTHETIC. All numbers below are proxy accuracy, **not** real-world accuracy.

## Fit (training split)

- Objective: `wape_log`  | converged: False | iterations: 10000 | train rows: 41
- Intercept: `16.5222671862`
- Fitted betas (non-negative):
  - `production_scale` = 0.0929389309
  - `log_vote_count` = 0.1116790420
  - `franchise_flag` = 0.7986520846
- Train metrics: train_log_mae=0.447641, train_wape=0.363439

## Measurement (held-out test split)

- Rows scored (test): 19  | temporal cutoff: 2019  | label types: {'PROXY': 2, 'SYNTHETIC': 17}

### Viewing-hours accuracy (PROXY)

| metric | baseline | candidate |
| --- | --- | --- |
| MAPE % | 99.03 | 32.57 |
| WAPE | 0.9883 | 0.3899 |
| Log-MAE | 4.8121 | 0.4236 |
| eligible/scored | 19/19 | 19/19 |

### Verdict scoring (PROXY; False_Greenlight_Rate is the primary risk metric)

| metric | baseline | candidate | delta |
| --- | --- | --- | --- |
| False_Greenlight_Rate | 0.0000 | 0.0000 | 0.0000 |
| False_Pass_Rate | 0.0526 | 0.0526 | - |
| Verdict_Match_Rate | 0.9474 | 0.9474 | 0.0000 |

### Output_KPI deltas (candidate - baseline; PROXY indices)

| KPI | delta |
| --- | --- |
| active_pipeline_valuation | 0.00 |
| avg_ltv_to_cost | 0.00 |
| model_prediction_accuracy | 0.0000 |
| portfolio_risk_exposure | 0.0000 |

## Decision

- Regression check: no regression
- `auto_activate`: True
- Recommendation: candidate did not regress; activation is an explicit manual decision (this script never auto-activates)

This script measures only; it never changes the seed or writes a `model_versions` row. Activating the fitted version is a separate, explicit governance decision.
