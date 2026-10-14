# CineROI AI - Calculations Reference

> The exact, authoritative definition of **every number the platform computes** - the
> inputs it starts from, the formulas it applies, the thresholds it compares against, the
> rounding it uses, and worked examples with real figures. Taken directly from the
> implementation. Use this alongside the main knowledge base.

---

## 0. How to Read This: Two Layers of Computation

Every verdict is produced in two distinct layers. Keeping them separate removes almost all
confusion about "where a number comes from."

### Layer A - Modeled Inputs (the drivers)
A set of financial drivers that describe a title's modeled economics:

- `ltv` - lifetime value contribution (subscription side)
- `churn_reduction_value` - a scalar multiplied into LTV (subscription term)
- `watch_time_elasticity`, `cpm`, `ad_impressions` - the advertising-side drivers
- `churn_reduction_pct` - modeled monthly % of subscribers retained; calculated by the churn
  model from the title's features (or supplied explicitly), see Section 6
- `monthly_margin` and `milestone_schedule` - the cash-flow drivers for payback
- plus the title's own stored facts: `acquisition_cost_or_budget`, `native_currency`,
  `projected_viewing_hours`, `asset_type`, `target_territories`, `talent_pedigree_score`.

**Where these drivers come from (by path):**

- **Ingested / seeded titles:** read from the title's active `title_versions` *source
  snapshot* (the as-submitted manifest captured at ingestion) by
  `SnapshotValuationInputProvider`. Missing fields get conservative defaults
  (e.g. `watch_time_elasticity` defaults to 1, others to 0).
- **Asset Studio instant evaluation (quick-evaluate):** the form captures business facts
  (cost, pedigree, exclusivity, synopsis); the modeled drivers are *derived* from those
  facts by `_modeled_inputs(...)` so an instant scorecard is meaningful without a full
  financial-modeling pipeline (see Section 9).
- **In production:** this layer is where a real financial-modeling pipeline and the real
  NLP embedding model plug in. The engine depends on the *interface*
  (`ValuationInputProvider` and `EmbeddingProvider`), so swapping in production models
  changes the drivers without touching any of the formulas in Layer B. In the current
  demo build these providers are deterministic so the stack runs offline.

### Layer B - Deterministic Guardrail Math (the verdict)
Pure, exact arithmetic over the Layer-A drivers. These formulas never change between demo
and production: the four guardrails, the recommendation logic, MAPE, currency
normalization, territory weighting, negotiation ceilings, attribution, and cohort numbers.
Everything in Sections 1-8 and 10-11 below is Layer B and is covered by property-based
tests. All of it uses Python `Decimal` for exact precision (no binary-float error).

**One-line summary:** Layer A says *what the title's economics are*; Layer B says *whether
that passes the platform's financial discipline, and what to do about it*.

---

## 1. The Metadata Profile (Feature Extraction)

Produced by the Feature Extraction Engine for each title and stored in `metadata_vectors`.
Four artifacts:

### 1.1 Narrative DNA (1536-dimension embedding)
- **What:** a 1536-number vector representing the title's tropes/themes/pacing; every
  component in `[-1.0, 1.0]`.
- **How (production):** produced by an injected `EmbeddingProvider` - the slot a real NLP
  embedding model fills.
- **How (demo build):** `DeterministicEmbeddingProvider` expands a SHA-256 digest of the
  source text into 1536 numbers: for each 32-byte digest block it maps each byte `b` to
  `(b / 127.5) - 1.0` (which lands in `[-1.0, 1.0]`), salting the digest with a block
  counter until 1536 values are produced. Deterministic (same text -> same vector),
  reproducible, offline. It is a stand-in, not a semantic embedding.
- **Used by:** the Top-3 comps and audience-fit similarity (cosine over these vectors).

### 1.2 Affective Tone (primary + secondary emotional trigger)
- **What:** exactly one primary and one distinct secondary trigger from a fixed set of 10:
  SUSPENSE, JOY, FEAR, NOSTALGIA, AWE, GRIEF, ROMANCE, HUMOR, TENSION, HOPE.
- **How (demo build):** from a SHA-256 digest of the text, `primary = digest[0] % 10`;
  `secondary = (primary + 1 + (digest[1] % 9)) % 10` (guarantees secondary != primary).

### 1.3 Talent Pedigree Score and 1.4 Production Scale Metric
- **What:** two scores, each in `[0.0, 10.0]`, 2 decimals.
- **How (demo build):** derive a stable signal in `[0,1]` from the text -
  `signal = (digest[0] << 8 | digest[1]) / 65535` using a facet-specific salt
  ("talent" or "production"); then `score = clamp(signal x weight x 10, 0, 10)` rounded to
  2 dp, where `weight` is the active model version's `talent_pedigree_weight` (for pedigree)
  or `narrative_trope_weight` (for production scale). Those weights sum to 1.00 and are what
  calibration tunes.

> Note: in the demo these are deterministic placeholders; in production the embedding model
> and modeling pipeline supply richer values. The guardrail math below is identical either
> way.
---

## 2. Currency Normalization (every cost first)

Before any guardrail runs, the native cost is converted to USD.

- **Formula:** `normalized_cost_usd = acquisition_cost x exchange_rate`, rounded HALF_UP to
  2 decimals.
- **Rate selection:** use the dated `exchange_rates` row for the required date; if the exact
  date is missing, fall back to the **latest available** rate for that currency pair. Reject
  the valuation only if the currency pair has no rate at all
  (`EXCHANGE_RATE_UNAVAILABLE`, HTTP 422).
- **Recorded:** the rate value, the rate date, and the `exchange_rate_id` are persisted with
  the projection so the normalization is reproducible.
- **Worked example (Vintage Reruns):** EUR 1,200,000 x 1.09 = **$1,308,000.00**.
- **Seeded demo rates (as of 2024-01-02):** USD->USD 1.00, INR->USD 0.012, EUR->USD 1.09,
  GBP->USD 1.27.

---

## 3. Territory Weighting (applied to CPM and LTV)

The LTV-to-Cost math weights the advertising CPM and the subscription LTV by the title's
target territories, using each territory's cached market telemetry.

For each target territory with telemetry for the title's genre:
- `cpm_multiplier  = licensing_inflation_multiplier`  (defaults to 1 when absent)
- `ltv_multiplier  = 1 + (chart_velocity_score / 100)` (a 0 score is neutral, = 1)

Then blend across all target territories with an equal-weight mean:
- `cpm_weight = mean(cpm_multiplier over territories)`
- `ltv_weight = mean(ltv_multiplier over territories)`

A territory with no telemetry contributes a neutral `1`. With no territories at all, both
weights are `1` (identity). These weights are applied as:
- `weighted_cpm = cpm x cpm_weight`
- `weighted_ltv = ltv x ltv_weight`

> This is why the seed back-fills each title's drivers by *dividing out* these weights: it
> keeps the stored verdict identical while a live recompute still reproduces it.

---

## 4. Guardrail 1 - Cost per Viewing Hour (CPVH)

- **Formula:** `CPVH = normalized_cost_usd / projected_viewing_hours`, rounded HALF_UP to
  **4 decimals**. Requires viewing hours > 0 (zero hours -> check fails, no CPVH persisted).
- **Ceiling (threshold):** `$0.18` for a Premium_Original (ORIGINAL_SERIES, ORIGINAL_FILM,
  CO_PRODUCTION); `$0.05` for a Library_Filler (LICENSED_LIBRARY). No matching
  classification -> check fails (no applicable ceiling).
- **Breach test:** breach if and only if `CPVH > ceiling` (strictly). `CPVH <= ceiling`
  passes.
- **Correctable:** yes - a lower cost lowers CPVH.
- **Worked example (Aurora Protocol):** `42,000,000 / 250,000,000 = 0.1680`.
  `0.1680 <= 0.18` -> PASS.
- **Worked example (The Ledger):** `9,500,000 / 40,000,000 = 0.2375`.
  `0.2375 > 0.18` -> BREACH (correctable).

---

## 5. Guardrail 2 - Return on Spend (LTV-to-Cost Multiple)

- **Formula:**
  `multiple = ((churn_reduction_value x weighted_ltv) + (watch_time_elasticity x weighted_cpm x ad_impressions)) / normalized_cost_usd`
  - the first term is the **subscription (SVOD)** value; the second is the **advertising
    (AVOD)** value; their sum is the **total modeled value**.
  - `weighted_ltv` and `weighted_cpm` are the territory-weighted values from Section 3.
- **Threshold:** `3.2` (i.e. $3.20 of value per $1). Over a 12-24 month window.
- **Breach test:** breach if and only if `multiple < 3.2` (strictly). `multiple = 3.2`
  passes.
- **Correctable:** yes - dividing the same numerator by a smaller cost raises the multiple.
- **Worked example (The Ledger):** total modeled value approx $27,550,000;
  `27,550,000 / 9,500,000 = 2.9x`. `2.9 < 3.2` -> BREACH (correctable).

### 5.1 LTV Attribution (the breakdown shown in the UI)
Same operand order as the multiple, so it agrees by construction:
- `subscription_value = churn_reduction_value x weighted_ltv`
- `advertising_value  = watch_time_elasticity x weighted_cpm x ad_impressions`
- `total_modeled_value = subscription_value + advertising_value`
- `multiple = total_modeled_value / normalized_cost_usd`

---

## 6. Guardrail 3 - Churn Mitigation

### 6.0 How the churn number is produced (the Churn_Mitigation_Model)

`churn_reduction_pct` - the modeled monthly cohort churn-reduction percentage - is no longer
a hard-coded Layer-A literal. It is **CALCULATED** by a transparent, deterministic, additive
model from a title's observable features, *unless* an explicit value is **SUPPLIED** (then it
is used exactly). The math lives in the pure domain module `backend/app/domain/churn.py` and
is covered by property-based tests.

- **Additive formula (CALCULATED path):**
  `churn% = intercept + asset_offset + pedigree_weight x pedigree + scale_weight x production_scale + exclusivity_lift (if exclusive) + telemetry_weight x telemetry_heat`
  then **clamped to [0.10, 5.00]** and rounded to **2 decimals HALF_UP**. All feature weights
  are non-negative.
- Each numeric feature is first clamped to its valid domain: pedigree and production scale to
  `[0, 10]`, telemetry heat to `[0, 100]`.
- `telemetry_heat` is the mean, over the title's target territories that have a cached reading
  for the title's genre, of `social_sentiment_index x 100` (converting the stored 0-1 index to
  a 0-100 scale), rounded to 2 dp HALF_UP. Territories with no reading are excluded; a title
  with no readings at all has a missing telemetry heat.

> **Illustrative coefficients.** The default coefficients below are *tuned to the five demo
> titles, not fitted to real subscriber-outcome data.* They are deliberately simple and
> explainable, not a trained model.

#### Default coefficients

| Parameter | Value |
|---|---|
| intercept (base platform rate) | 0.15 |
| asset offset - ORIGINAL_SERIES | 0.35 |
| asset offset - CO_PRODUCTION | 0.45 |
| asset offset - ORIGINAL_FILM | 0.20 |
| asset offset - LICENSED_LIBRARY | 0.00 |
| pedigree_weight (per point) | 0.09 |
| scale_weight (per point) | 0.03 |
| exclusivity_lift (if exclusive) | 0.25 |
| telemetry_weight (per point of heat) | 0.005 |
| output clamp bounds | [0.10, 5.00] |

#### Feature sources and precedence

Each feature is resolved from **explicit snapshot facts first**, then from stored data:

- **pedigree / production scale / exclusivity:** the title's explicit snapshot facts
  (`talent_pedigree_score`, `production_scale_metric`, `is_exclusive`) when present; otherwise
  the title's latest SUCCESS metadata vector (pedigree, production scale) and the title's
  license terms (exclusivity).
- **asset type:** read from the title row.
- **telemetry heat:** computed from `market_telemetry_cache` by the mean-x100 rule above.
- A **missing** numeric feature contributes **0** and is flagged in the result's
  `missing_features` list (the method stays CALCULATED). An unknown asset type applies a zero
  offset and is flagged. Unknown exclusivity is treated as not exclusive.

#### Supplied value wins

- A finite numeric `churn_reduction_pct` supplied in the title deal snapshot or the
  quick-evaluate payload is used **exactly as given - no clamp, no re-round** - and the method
  is **SUPPLIED** (a supplied `0` counts as supplied). A blank / null / non-numeric /
  non-finite supplied value is treated as "not supplied" and falls through to CALCULATED. A
  legacy snapshot that already carries a churn value continues to report SUPPLIED until it is
  reseeded without one.
- The quick-evaluate request accepts an optional `churn_reduction_pct` in `[0, 100]`; when
  present it is SUPPLIED, otherwise the Asset Studio path is CALCULATED.

#### Borderline sensitivity flag

- When the resolved churn (CALCULATED or SUPPLIED) lies in the inclusive band `[1.45, 1.55]`,
  the result is flagged borderline with the message
  **"Borderline Sensitivity: within 0.05% of the 1.50% hurdle"**. The flag is informational
  only - it never changes the pass/breach result, the dominant factor, or the recommendation.

#### Parameter storage and versioning

- The coefficients live in the active model version's `guardrail_params["churn_model"]`
  (JSONB - no migration). They are versioned with the model, and carried forward **unchanged**
  when calibration forks a new version (calibration never re-fits churn). If
  `guardrail_params["churn_model"]` is absent or structurally invalid, the engine falls back
  to the built-in defaults and records `params_source = DEFAULTS`.

#### Persisted explanation (the `churn_model` object)

The persisted `financial_projections.explanation` carries a `churn_model` object:
`churn_method` (CALCULATED | SUPPLIED), `is_borderline`, `params_source`
(MODEL_VERSION | DEFAULTS), `model_version_id`, `missing_features`, and `churn_breakdown` (the
per-feature points: `base_platform_rate`, `asset_cadence`, `talent_pedigree_contribution`,
`production_scale_contribution`, `exclusivity_lift`, `market_telemetry_heat`, plus a
`bounds_adjustment` entry when clamping/rounding changed the value so the entries always sum to
the final value). When SUPPLIED, `churn_breakdown` is null and `missing_features` is empty.

### 6.1 The churn guardrail check (unchanged)

- **Value:** the resolved `churn_reduction_pct` from the model above (CALCULATED or SUPPLIED).
- **Threshold:** `1.5` percent.
- **Breach test:** breach if and only if `churn_reduction_pct < 1.5` (strictly).
- **Correctable:** **NO.** This is the one structural check - no price change affects it, so
  a single churn breach forces a PASS.
- **Worked example (Vintage Reruns):** model-computed `0.88 < 1.5` -> BREACH (non-correctable).

---

## 7. Guardrail 4 - Payback Horizon

- **What:** the first month at which cumulative contribution turns strictly positive, walked
  over the milestone payment schedule (not a lump sum).
- **Algorithm:** for each month m (starting at 1):
  - `cumulative_outflow = sum of milestone amounts disbursed through month m`
    (milestones at month <= 0 are treated as disbursed by month 1)
  - `cumulative_contribution = (monthly_margin x m) - cumulative_outflow`
  - return the first m where `cumulative_contribution > 0`.
  - `monthly_margin` must be > 0 or no finite payback exists (PaybackComputationError -> an
    unclassifiable breach -> conservative PASS).
- **Target window:** 9 to 12 months inclusive.
- **Breach test:** breach if and only if `months > 12` (strictly). (The 9-month lower bound
  is the stated target; the hard breach line is > 12.)
- **Correctable:** yes - a cheaper title pays back sooner.
- **Worked example (Aurora Protocol):** payback = 11 months. `11 <= 12` -> PASS.
- **Worked example (The Ledger):** payback = 15 months. `15 > 12` -> BREACH (correctable).
---

## 8. Shortfall Magnitude and the Verdict

### 8.1 Normalized shortfall (per breached check)
Used to rank breaches on a common axis so the dominant factor is comparable across
guardrails of different scales.

- **Formula:** `shortfall = |distance| / |threshold|` (falls back to `|distance|` if the
  threshold is 0), where `distance` is how far past the line the value landed:
  - CPVH: `distance = cpvh - ceiling`
  - LTV: `distance = 3.2 - multiple`
  - Churn: `distance = 1.5 - churn_pct`
  - Payback: `distance = months - 12`
- Only breached checks carry a shortfall; passing checks report `None`.
- **Worked example (The Ledger CPVH):** `|0.2375 - 0.18| / 0.18 = 0.0575 / 0.18 = 0.3194`.

### 8.2 Dominant factor
The breached check with the **largest** normalized shortfall (ties broken by input order;
a known magnitude always beats an unknown one). Reported for any PASS or NEGOTIATE HARD.

### 8.3 Recommendation Status (the final verdict)
Count the breaches, then:
- **0 breaches** -> GREENLIGHT.
- **>=1 breach, and at least one is unclassifiable** (`correctable` is unknown due to
  missing/invalid data) -> PASS, with an `unclassifiable` flag.
- **>=1 breach, and at least one is non-correctable** (`correctable = False`, i.e. churn)
  -> PASS.
- **>=1 breach, every breach correctable** -> NEGOTIATE HARD.

Exactly one of {GREENLIGHT, NEGOTIATE_HARD, PASS} is always returned. The engine marks CPVH,
LTV, and payback breaches `correctable = True`; a churn breach `correctable = False`.

---

## 9. Negotiation Playbook Math (for NEGOTIATE HARD / PASS)

Algebraic rearrangements of the CPVH and LTV checks - the price at which each breached,
cost-correctable guardrail would *just* pass.

- **CPVH-implied ceiling:** `cost x (cpvh_ceiling / computed_cpvh)` (requires computed CPVH
  > 0). At this cost, CPVH equals its ceiling.
- **LTV-implied ceiling:** `cost x (computed_multiple / 3.2)` (requires threshold > 0). At
  this cost, the multiple equals 3.2.
- **Target purchase ceiling:** the **smallest (binding)** of the per-guardrail ceilings over
  all breached, cost-correctable CPVH/LTV checks, rounded to whole USD. `None` when cost <= 0
  or no cost-correctable CPVH/LTV breach exists. (Churn and payback do not yield a closed-form
  cost ceiling; they are addressed by levers only.)
- **Implied discount %:** `(current_ask - ceiling) / current_ask x 100`, rounded to 1 dp;
  `0` when the ceiling is at or above the ask (never negative); `None` when ask <= 0.
- **Worked example (The Ledger):**
  - CPVH ceiling: `9,500,000 x (0.18 / 0.2375) = $7,200,000`.
  - LTV ceiling: `9,500,000 x (2.9 / 3.2) = $8,609,375`.
  - Binding (smallest) = **$7,200,000**.
  - Implied discount: `(9,500,000 - 7,200,000) / 9,500,000 x 100 = 24.2%`.
- **Counter-proposal levers:** one plain-language message per breached check, keyed by
  guardrail name and whether it is correctable (price/terms message) or structural.

---

## 10. Absolute Churn Cohort (derived, display only)

- **Modeled cohort size:** when not supplied, derived as `floor(normalized_cost_usd)` - one
  modeled addressable subscriber per whole USD of cost. A transparent placeholder; never
  feeds a guardrail.
- **Retained subscribers:** `round(modeled_cohort_size x (churn_reduction_pct / 100))` to a
  whole number. `None` when size <= 0; `0` when pct <= 0 and size > 0.
- Both are flagged as derived/modeled figures wherever they surface.

---

## 11. MAPE (backtest accuracy) and Calibration

### 11.1 MAPE (Mean Absolute Percentage Error)
- **Formula:** `MAPE = (1/n) x sum(|(actual - predicted) / actual|) x 100` over the eligible
  pairs, rounded HALF_UP to 2 dp.
- **Eligibility:** a pair whose actual value is 0 is excluded (its term is undefined) and
  reported as excluded. If every pair is excluded, MAPE is `None` with a
  `NO_ELIGIBLE_METRICS` indicator.
- Lower is better; a MAPE above 10% triggers calibration.

### 11.2 Calibration weight offsets
- Each offset must be within `[-1.00, 1.00]`; otherwise rejected.
- Offsets apply to the two coupled feature weights (`talent_pedigree_weight`,
  `narrative_trope_weight`): `adjusted = quantize(active_weight + offset)` to 2 dp. If either
  adjusted weight < 0, reject (prior weights retained).
- Normalize so the pair sums to exactly 1.00:
  `talent = quantize(adjusted_talent / (adjusted_talent + adjusted_narrative))`;
  `narrative = quantize(1.00 - talent)`. Both must land in `[0.00, 1.00]`.
- A successful calibration **forks a new immutable model version**; it never edits weights in
  place, so past valuations stay reproducible.

---

## 12. Projected Viewing Hours - When Estimated (Asset Studio only)

Viewing hours is normally a stored input on the title. It is only *estimated* in the Asset
Studio quick-evaluate path when the user leaves it blank or enters a non-positive value. The
estimate is engineered so CPVH lands safely under the ceiling (so a title is not failed for a
missing input):

- `ceiling = 0.05 if LICENSED_LIBRARY else 0.18`
- `pedigree = talent_pedigree_score (default 5)`
- `target_cpvh = ceiling x (0.70 + (pedigree / 10) x 0.25)`  (i.e. 70%-95% of the ceiling)
- `estimated_hours = round(cost / target_cpvh)` to a whole number
- **Worked example:** $10,000,000 premium original, pedigree 8:
  `target_cpvh = 0.18 x (0.70 + 0.8 x 0.25) = 0.162`; `hours = 10,000,000 / 0.162 = 61,728,395`;
  the resulting CPVH is approx $0.162, just under $0.18.

> For the five seeded demo titles, viewing hours are real stored inputs (e.g. Aurora's
> 250,000,000), not estimated.

---

## 13. Instant-Evaluation Modeled Drivers (Asset Studio quick-evaluate)

When you run a title in the Asset Studio, the form's business facts are turned into the
Layer-A drivers so the instant scorecard is meaningful. These derivations are demo
conveniences (a real financial-modeling pipeline would replace them); the Layer-B formulas
above then consume them unchanged.

- `quality = talent_pedigree_score / 10` (default pedigree 5 -> 0.5)
- `target_multiple = 2.6 + quality x 2.2`  (ranges 2.6 .. 4.8; higher pedigree -> higher)
- `numerator = target_multiple x cost`; split ~85% subscription, ~15% advertising:
  - `ltv = 0.85 x numerator`, `churn_reduction_value = 1` (so the SVOD term is just LTV)
  - `watch_time_elasticity = 1.0`, `cpm = 12.0`,
    `ad_impressions = (0.15 x numerator) / (1.0 x 12.0)`
- `churn_reduction_pct` is no longer derived by a placeholder formula here. It now comes from
  the shared Churn_Mitigation_Model (Section 6): **SUPPLIED** when the form provides a value,
  otherwise **CALCULATED** from the title's features. The production-scale feature fed to the
  model is derived with the same shared helper that feeds the metadata radar, so the explained
  model input equals the production scale shown on the radar.
- `target_payback = round(11 - quality x 4)` months (ranges 7 .. 11; higher pedigree -> sooner)
- `monthly_margin = round(cost / target_payback, 2)`; a single milestone of the full cost at
  month 1, so cumulative contribution dips to -cost then climbs by `monthly_margin`/month and
  crosses zero at `target_payback`.

---

## 14. Seed Back-Fill (why demo recompute matches the stored verdict)

For the shipped demo titles, the stored scorecard and a live recompute agree exactly because
the seed generator engineers the drivers:

- **Payback:** a single month-1 milestone of the full normalized cost, with
  `monthly_margin = normalized_cost / (payback_target - 0.5)`. The milestone walk then crosses
  zero at exactly `payback_target` months.
- **Territory weighting:** the drivers are divided by the resulting `ltv_weight` /
  `cpm_weight` so that applying the weights reproduces the intended LTV multiple.
- **Churn** is no longer a seed literal: the seed generator imports the Churn_Mitigation_Model
  (Section 6) and computes each title's `churn_reduction_pct` from its seeded features
  (pedigree / production scale / exclusivity / asset type / telemetry heat), so the stored
  value equals a live recompute. The illustrative coefficients are tuned so the five titles
  keep their verdicts: 3 GREENLIGHT (Aurora 2.11%, Monsoon 1.76%, Echoes 1.96%), 1 NEGOTIATE
  HARD (The Ledger 1.62%), 1 PASS (Vintage Reruns 0.88%, the only churn breach).

---

## 15. Quick Reference - Thresholds and Rounding

| Quantity | Formula / rule | Threshold | Rounding |
|---|---|---|---|
| Normalized cost | cost x rate | - | 2 dp HALF_UP |
| CPVH | cost_usd / viewing_hours | <= 0.18 premium / <= 0.05 library | 4 dp HALF_UP |
| LTV-to-Cost | (churn_val x wLTV + elast x wCPM x impr) / cost | >= 3.2 | exact (string) |
| Churn mitigation | calculated by the churn model (or supplied) | >= 1.5% | 2 dp HALF_UP, clamp [0.10, 5.00] (supplied used exactly) |
| Payback | first month cumulative contribution > 0 | <= 12 months | integer month |
| Shortfall | \|distance\| / \|threshold\| | - | exact |
| Target ceiling | min(cost x ceiling/cpvh, cost x mult/3.2) | - | whole USD HALF_UP |
| Implied discount | (ask - ceiling) / ask x 100 | - | 1 dp HALF_UP |
| Retained subs | cohort x (pct/100) | - | whole number |
| MAPE | mean(\|(act-pred)/act\|) x 100 | calibrate > 10% | 2 dp HALF_UP |
| Calibration weights | offset in [-1,1]; pair sums to 1.00 | [0,1] each | 2 dp HALF_UP |

All arithmetic uses Decimal; monetary and percentage values serialize as JSON strings over
the wire and are coerced defensively on the frontend.

*End of calculations reference. Formulas and thresholds are taken from the implementation
(`backend/app/domain/` and `backend/app/engines/guardrails.py`).*