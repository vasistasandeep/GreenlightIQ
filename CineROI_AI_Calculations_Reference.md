# CineROI AI - Calculations Reference

> The exact, authoritative definition of **every number the platform computes** - the
> inputs it starts from, the formulas it applies, the thresholds it compares against, the
> rounding it uses, and worked examples with real figures. Taken directly from the
> implementation. Use this alongside the main knowledge base.

> Companion documents: **CineROI_AI_Complete_Knowledge_Base.md** (what every feature and
> screen does, with the demo data and build history) and
> **CineROI_AI_Architecture_And_Data_Flow.md** (an executive, diagram-led walkthrough of
> the architecture and end-to-end data flow).

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
  `churn% = intercept + asset_offset + pedigree_weight x pedigree + scale_weight x production_scale + exclusivity_lift (if exclusive) + telemetry_weight x telemetry_heat + genre_weight + content_format_lift`
  then **clamped to [0.10, 5.00]** and rounded to **2 decimals HALF_UP**. All feature weights
  are non-negative.
- Each numeric feature is first clamped to its valid domain: pedigree and production scale to
  `[0, 10]`, telemetry heat to `[0, 100]`.
- `telemetry_heat` is the mean, over the title's target territories that have a cached reading
  for the title's genre, of `social_sentiment_index x 100` (converting the stored 0-1 index to
  a 0-100 scale), rounded to 2 dp HALF_UP. Territories with no reading are excluded. When a
  title has NO reading at all, the model uses a **neutral default of 50** (not 0) so a data gap
  does not unfairly push the title toward a PASS; the feature is reported as *assumed* (neutral),
  distinct from a genuinely missing feature.
- `genre_weight` is a per-genre coefficient (serialized/returning formats such as crime, drama,
  thriller, reality retain subscribers more than one-and-done formats such as documentary, kids,
  musical). An unknown or absent genre uses a **neutral default of 0.10** and is reported as
  *assumed*. The weights are stored under `guardrail_params["churn_model"]["genre_offsets"]`.
- `content_format_lift` is an **additive lift** for OTT-native appointment formats the four asset
  types cannot express. It is **0** for formats the asset type already captures (scripted series,
  films, library) and positive only for: **live sports 0.70**, **live events 0.50**, **reality/
  competition 0.45**. An unknown/absent format adds 0 (today's behavior). This is why a live
  cricket match stored as a LICENSED_LIBRARY asset still earns strong churn credit. Stored under
  `guardrail_params["churn_model"]["format_offsets"]`; the Asset Studio exposes a Content Format
  dropdown separate from Asset Type and Genre.
- Default coefficients: `intercept 0.03`; asset offsets ORIGINAL_SERIES 0.35 / CO_PRODUCTION 0.45
  / ORIGINAL_FILM 0.15 / LICENSED_LIBRARY 0.00; `pedigree_weight 0.09`; `scale_weight 0.03`;
  `exclusivity_lift 0.25`; `telemetry_weight 0.005`; `genre_default 0.10`; `telemetry_neutral 50`.
  These are Illustrative_Coefficients tuned to the five demo titles, not fitted to real data.

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
(MODEL_VERSION | DEFAULTS), `model_version_id`, `missing_features`, `assumed_features` (features that used a neutral default - a missing telemetry reading or an unlisted genre), and `churn_breakdown` (the
per-feature points: `base_platform_rate`, `asset_cadence`, `talent_pedigree_contribution`,
`production_scale_contribution`, `exclusivity_lift`, `market_telemetry_heat`, `genre_affinity`, `content_format`, plus a
`bounds_adjustment` entry when clamping/rounding changed the value so the entries always sum to
the final value). When SUPPLIED, `churn_breakdown` is null and `missing_features` is empty.

### 6.1 The churn guardrail check (unchanged)

- **Value:** the resolved `churn_reduction_pct` from the model above (CALCULATED or SUPPLIED).
- **Threshold:** `1.5` percent.
- **Breach test:** breach if and only if `churn_reduction_pct < 1.5` (strictly).
- **Correctable:** **NO.** This is the one structural check - no price change affects it, so
  a single churn breach forces a PASS.
- **Worked example (Vintage Reruns):** model-computed `0.81 < 1.5` -> BREACH (non-correctable).

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

The Asset Studio viewing-hours input is **unit-aware**: the buyer enters a value and picks a
unit (hours / minutes / seconds), and the quick-evaluate handler normalizes it to hours
(`minutes / 60`, `seconds / 3600`) before the CPVH math. A blank value still falls back to the
estimate above.

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
  keep their verdicts: 3 GREENLIGHT (Aurora 2.11%, Monsoon 1.79%, Echoes 1.99%), 1 NEGOTIATE
  HARD (The Ledger 1.60%), 1 PASS (Vintage Reruns 0.81%, the only churn breach).

---

## 15. Content Evaluation Models (the modeling-layer formulas)

> **Honesty gate.** Every formula and number in this section belongs to the *modeling layer*
> (the Content_Eval_System) that produces the engine's Layer-A inputs. The coefficients shipped
> today are **illustrative / PROXY**; where they are fitted at all, they are fitted against an
> **open-data or synthetic** truth sheet. **No fitted version is active by default**, so with the
> default seed every driver and verdict is byte-identical to the placeholder behavior in Sections
> 12-14. Any accuracy below is **proxy accuracy, not real-world accuracy.**

These models map a title's `Feature_Vector` to one Layer-A driver, each with a per-feature
breakdown that conserves to the final value (the same contract Section 6 describes for churn).
The math lives in pure stdlib modules (`backend/app/domain/viewing_hours.py`,
`engagement.py`, `fit.py`) and is property-tested.

### 15.1 Projected viewing hours - log-space model + Option-B hour breakdown

Viewing hours is heavy-tailed (a tentpole can be orders of magnitude above a library title),
so the model is **linear in log space** and **conserved and clamped in hour space**.

- **Predict (log space):**
  `y_log = intercept + sum_i(beta_i x x_i)` over non-negative-constrained feature weights,
  then `H_hat = exp(y_log) - 1` (the inverse of the `log(1 + H)` fit target).
- **Hour-space breakdown - base hours + marginal-lift share (Option B).** Because `exp(sum)`
  is multiplicative, a naive per-term log share would double-count the intercept and force a
  large negative adjustment. Instead:
  - Base platform hours: `H0 = exp(intercept) - 1`.
  - Total non-intercept log lift: `L = sum_i(beta_i x x_i)`.
  - Total feature lift in hours: `dH = H_hat - H0`.
  - Per feature: `hours_i = (beta_i x x_i / L) x dH` when `L > 0`, else `hours_i = 0`
    (the `L == 0` base-only case).
  - Breakdown entries: `{ base_platform_hours = H0, hours_i..., rounding_or_bounds_adjustment }`.
  By construction `H0 + sum_i(hours_i) == H_hat` before quantization, so the single trailing
  `rounding_or_bounds_adjustment` entry only ever carries a tiny +/-1-hour rounding or
  floor-clamp residual - never a structural offset. **The intercept term is never divided by
  `L`.**
- **Floor/clamp:** the output is clamped to a small positive `floor` so viewing hours never hit
  the CPVH null/zero path (Section 4); the clamp delta flows into the adjustment entry, so
  conservation still holds exactly.
- **Params:** `guardrail_params['content_eval']['viewing_hours'] = { intercept, betas{feature->weight>=0}, floor, objective:"wape_log" }`,
  parsed with a churn-style full fallback to illustrative defaults when absent/invalid.

### 15.2 Engagement models (additive, conserving)

- **Watch-time elasticity:** an additive model over engagement correlates (runtime, genre
  bingeability, serialization), bounded to its documented domain, with the same
  conserving-breakdown and fallback shape as churn: `value = intercept + sum_i(w_i x x_i)`,
  then clamp, with a single `bounds_adjustment` entry carrying the clamp/rounding residual so
  `sum(breakdown) == value`.
- **Ad-load receptivity:** a **unit-centered multiplier** (default `1.0`) that *scales* the
  configured CPM basis rather than inventing a dollar CPM - honoring the Platform_Rate
  boundary. The engine still multiplies by the configured `cpm`; the model supplies only the
  scalar.

### 15.3 Churn -> LTV link (opt-in, default off)

The modeled churn-reduction % and the LTV numerator's `churn_reduction_value` are distinct
fields today (Section 5.1, Section 13 pins `churn_reduction_value = 1`). The opt-in link makes
the modeled churn flow into LTV:

- `churn_reduction_value = Base_Retained_Cohort_Value x (Churn_Reduction_Pct / 100)`

where `Base_Retained_Cohort_Value` is a configured Platform_Rate. The link is gated by
`guardrail_params['content_eval']['link_churn_to_ltv']` (**default false**). When off - the
default - the current behavior is preserved exactly and the demo verdicts do not move. A
`SUPPLIED` `churn_reduction_value` still wins at the field level.

### 15.4 Deterministic fit (`fit.py`)

- Standard-library **non-negative least squares via projected coordinate descent**, with an
  **IRLS** wrapper for the log-space WAPE / Log-MAE objective used by viewing hours.
- **Zero-variance guard:** `denom = sum_n(w_n x x_nj^2)`; `if denom <= 1e-12: beta_j = 0;
  continue` - so a constant or sparse feature column never raises a divide-by-zero.
- Fixed iteration count, fixed tolerance, fixed seed, no wall-clock or environment dependence,
  no numpy/scipy - so fitted parameters are byte-identical across platforms. Non-negativity is
  projected after each coordinate update, preserving monotonicity/explainability.

### 15.5 Harness metrics (how a model is scored on the held-out split)

- **MAPE** (per input): `(1/n) x sum(|(actual - predicted) / actual|) x 100` over eligible
  rows, **excluding zero-actual** rows (matching Section 11.1).
- **WAPE** (viewing hours): `sum_i|actual_i - predicted_i| / sum_i|actual_i|` - a
  magnitude-weighted percentage error that is robust to the heavy tail. **Log-MAE:** the mean
  absolute residual in `log(1 + H)` space.
- **Verdict-match rate:** the fraction of titles whose predicted recommendation equals the
  expected recommendation.
- **False_Greenlight_Rate (FGR)** = (# titles predicted GREENLIGHT whose expected verdict was
  NEGOTIATE_HARD or PASS) / (# titles predicted GREENLIGHT). The capital-loss error - reported
  first as the **primary risk metric**.
- **False_Pass_Rate (FPR)** = (# titles predicted PASS or NEGOTIATE_HARD whose expected verdict
  was GREENLIGHT) / (# titles predicted PASS or NEGOTIATE_HARD). The opportunity-cost error.
- **Output_KPI deltas:** the change in each portfolio KPI (active pipeline valuation, average
  LTV-to-Cost, portfolio risk exposure, model prediction accuracy) between baseline and
  candidate over the same dataset, attributed to the single changed model.

A fitted version that scores worse than the active baseline on the held-out split is surfaced
but never auto-activated.

### 15.6 Illustrative first-fit numbers (PROXY - not real-world accuracy)

A first viewing-hours fit against `kpi-test-dataset-v1` (dominant Label_Type **SYNTHETIC**;
temporal cutoff 2019; 19 held-out test rows, label mix 17 SYNTHETIC / 2 PROXY) produced:

| metric (viewing hours, PROXY) | baseline | candidate |
|---|---|---|
| MAPE % | 99.03 | 32.57 |
| WAPE | 0.9883 | 0.3899 |
| Log-MAE | 4.8121 | 0.4236 |

| verdict metric (PROXY; FGR first) | baseline | candidate | delta |
|---|---|---|---|
| False_Greenlight_Rate | 0.0000 | 0.0000 | 0.0000 |
| False_Pass_Rate | 0.0526 | 0.0526 | - |
| Verdict_Match_Rate | 0.9474 | 0.9474 | 0.0000 |

All four Output_KPI deltas were 0.00. **These are proxy accuracy on synthetic/open-data labels,
not real-world accuracy**, and the candidate was measured only - activation is a separate,
explicit governance decision (this layer never auto-activates). Source: the committed
`database/kpi_dataset/fit_report.md`.

﻿---

## 16. Advanced Content-Eval Drivers (optional, default-off)

> **Default-off, inert when off.** These four drivers are each gated behind their own
> kill-switch (`CINEROI_ENABLE_COMPS`, `CINEROI_ENABLE_LINEAGE`, `CINEROI_ENABLE_MOMENTUM`,
> `CINEROI_ENABLE_MACRO_MODIFIERS`), all **false by default**. With every flag off (the
> shipped state) the drivers touch nothing - inputs, breakdowns, explanations, and verdicts
> are byte-identical to the behavior described in Sections 1-15 (proven by a demo-invariance
> guard). Each flag is independent. All coefficients below are DETERMINISTIC_FALLBACK
> **Illustrative_Coefficients** tuned for demo coherence, **not fitted to real data** - the
> same honesty framing as Section 15. The math lives in pure stdlib Decimal modules
> (`backend/app/domain/comps.py`, `lineage.py`, `momentum.py`, `macro_modifiers.py`,
> `driver_assembly.py`) and is property-tested.

### 16.1 Driver A - Comps_Engine (empirical anchor)

Anchors a title''s base viewing hours and base churn to the median of its budget-band
comparable historical titles, instead of the model''s constant intercept.

- **Retrieval:** nearest-neighbour historical titles of the same `asset_type`, ranked by
  Narrative_DNA pgvector cosine distance ascending, restricted to a normalized-USD
  **Budget_Band = `[0.65 x query_cost, 1.35 x query_cost]`** (factors `0.65` / `1.35`; the band
  is **never widened**), deterministic tie-break `(cosine_distance asc, title_id asc)`, target
  comp-set size **k = 5**.
- **Anchors:** `H_comps = median(projected_viewing_hours of the comp set)`;
  `C_comps = median(churn_pct of the comp set)`; `dispersion = IQR` of the hours.
- **Seeding:** a non-empty comp set seeds `base_hours_override = H_comps` into the viewing-hours
  model (replacing `H0 = exp(intercept) - 1`, Section 15.1) and `base_churn_override = C_comps`
  into the churn model''s base line (Section 6). Zero eligible comps ->
  `use_intercept_fallback` (the constant intercept is used, a no-op). A `SUPPLIED` field still
  wins over the anchor.

### 16.2 Driver B - Lineage_Decay (franchise floor + loyalty credit)

- **Franchise_Floor (hours):**
  `Franchise_Floor = parent_title_viewing_hours x (alpha_base_decay + beta_comp x parent_completion_rate)`
  with defaults `alpha_base_decay = 0.55`, `beta_comp = 0.35`; `parent_completion_rate` clamped
  `[0, 1]`. Applied as a **one-sided max** at the final assembly stage
  (`H7 = max(H6, Franchise_Floor)`) - it can only raise, never lower, the prediction. A sequel
  with missing parent data uses an assumed `parent_completion_rate = 0.70` (recorded as an
  assumed feature). Non-franchise (`is_franchise` false or `franchise_order <= 1`) -> floor 0.
- **delta_C_franchise (churn pct points):**
  `delta_C_franchise = clamp(gamma_base + delta_order x min(franchise_order - 1, 6), 0.15, 0.45)`
  with defaults `gamma_base = 0.15`, `delta_order = 0.05`, loyalty cap `6`. Non-decreasing in
  franchise order (2nd entry **+0.20**, saturating at **+0.45** by the 7th), added to the churn
  total **before** the `[0.10, 5.00]` clamp and the 1.5% hurdle, so it can legitimately lift a
  title across the hurdle while the clamp still bounds the result. Non-franchise -> credit 0.00.

### 16.3 Driver C - Momentum_Telemetry (stage-gated buzz multiplier)

Introduces a **Production_Stage** enum - `CONCEPT_SCRIPT`, `IN_PRODUCTION`, `FESTIVAL_PREVIEW`,
`ACQUISITION_READY` - distinct from the deal-stage pipeline.

- **Stage gating:** `CONCEPT_SCRIPT` / `IN_PRODUCTION` -> multiplier forced to the neutral
  **1.00** (`STAGE_EXCLUDED`; an unproduced pitch is never moved by buzz it cannot have yet).
  `FESTIVAL_PREVIEW` / `ACQUISITION_READY` -> compute below.
- **Composition:**
  `raw = 1 + w_v x norm(V_trailer) + w_e x E_norm + w_s x (S_velocity - 1)`, then
  `Momentum_Multiplier = clamp(raw, 1.00, momentum_multiplier_max)` where
  `norm(V_trailer) = clamp(V_trailer / baseline_v, 0, cap_v)`,
  `E_norm = clamp(E_ratio, 0, cap_e)`, `S_velocity` clamped `[0.50, 2.00]`. Defaults
  `w_v = 0.15`, `w_e = 0.20`, `w_s = 0.25`, `baseline_v = 1.0`, `cap_v = 2.00`, `cap_e = 1.00`,
  `momentum_multiplier_max = 1.50`.
- **Staleness / availability:** a governing telemetry reading older than the **14-day**
  staleness window -> `1.00` (`STALE`); source unavailable -> `1.00` (`UNAVAILABLE`).

### 16.4 Driver D - Macro_Modifiers (four market multipliers)

Four documented-domain lookups, each clamped, then multiplied into a single `product`. An
absent / unrecognized descriptor resolves to the neutral **1.00** (recorded as assumed). The
"premium modifiers never reduce the pre-modifier value" guarantee applies to `>= 1.00`
multipliers only; `PUBLIC_DOMAIN = 0.95` is the one intentional sub-neutral value.

- **Source_IP_Provenance** (clamp `[0.95, 1.25]`): `ORIGINAL_SCREENPLAY 1.00`,
  `BESTSELLER_BOOK 1.20`, `TRUE_CRIME_IP 1.25`, `WEBTOON_MANGA 1.15`, `PUBLIC_DOMAIN 0.95`.
- **Release_Window_Halo** (a new concept; does not touch `windowing.WindowType`):
  `DIRECT_TO_STREAMING 1.00`, `DAY_AND_DATE 1.10`, `THEATRICAL_30D 1.25`,
  `THEATRICAL_60D_PLUS 1.40`.
- **Calendar_Seasonality** (clamp `[0.80, 1.35]`): a per-release-month factor (e.g. Dec `1.30`,
  Nov `1.25`, Jan/Feb `0.90`); a NULL / out-of-range month -> neutral `1.00`.
- **Vernacular_TAM_Factor** (clamp `[1.00, 2.20]`): by vernacular track count - 1 track `1.00`,
  2 -> `1.40`, 3 -> `1.80`, 4+ saturates at `2.20`.

### 16.5 Assembly, schema, and provenance

- **Log-space assembler (`driver_assembly.py`):** composes the drivers in a seven-stage
  Attribution_Order, emitting one signed hour / churn-point line per driver so every delta is
  attributable; a single trailing adjustment line carries only the whole-unit quantization
  residual (same conserving contract as Sections 6 and 15.1).
- **Schema:** Alembic migration `0005` adds nine neutral-default columns to `titles`
  (`is_franchise`, `franchise_order`, `parent_title_viewing_hours`, `parent_completion_rate`,
  `production_stage`, `source_ip_provenance`, `release_window`, `release_month`,
  `vernacular_track_count`); the seed backfills them to neutral defaults so existing rows stay
  inert.
- **Versioning:** each driver''s illustrative coefficients ride in
  `model_versions.guardrail_params` under `comps` / `lineage` / `momentum` / `macro_modifiers`
  (exactly like the `churn_model` / `content_eval` blocks), carried forward unchanged on a
  calibration fork.

---

## 17. Quick Reference - Thresholds and Rounding

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
| Viewing hours (modeled, PROXY) | H = exp(intercept + sum beta_i x_i) - 1, clamp to floor | - | floor clamp; +/-1h adjustment |
| Churn -> LTV link (opt-in, off) | churn_val = Base_Retained_Cohort_Value x pct/100 | default off | exact |
| WAPE (viewing hours) | sum\|act-pred\| / sum\|act\| | lower is better | exact |
| FGR / FPR (verdict error) | false greenlights / false passes over the split | lower is better | exact |
| Comps anchor (driver, off) | median H / C over budget-band comps | band [0.65x, 1.35x], k=5 | medians; default off |
| Franchise floor (driver, off) | parent_hours x (0.55 + 0.35 x completion) | one-sided max | default off |
| Franchise credit (driver, off) | clamp(0.15 + 0.05 x min(order-1, 6), 0.15, 0.45) | added pre-hurdle | 2 dp; default off |
| Momentum mult (driver, off) | clamp(1 + 0.15 normV + 0.20 E + 0.25 (S-1), 1.00, 1.50) | stage-gated; 14-day stale -> 1.00 | default off |
| Macro modifiers (driver, off) | product of IP x window x season x vernacular | IP [0.95,1.25], season [0.80,1.35], vern [1.00,2.20] | default off |

All arithmetic uses Decimal; monetary and percentage values serialize as JSON strings over
the wire and are coerced defensively on the frontend.

*End of calculations reference. Formulas and thresholds are taken from the implementation
(`backend/app/domain/` and `backend/app/engines/guardrails.py`).*