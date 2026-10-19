# CineROI AI - Complete Knowledge Base

> A single, self-contained reference to the entire CineROI AI platform: what it is, the
> business problem it solves, exactly how it decides, every feature and screen, the API
> surface, the data model, the architecture, the governance model, the demo data with
> real worked numbers, the testing strategy, and the full build history. This document is
> written to be read start-to-finish or queried piece by piece.

> For the exact formula, threshold, rounding, and worked example behind EVERY computed
> number (currency normalization, the four guardrails, territory weighting, shortfall,
> the verdict rule, negotiation ceilings, cohort, MAPE, calibration weights, viewing-hours
> estimation, and the demo driver derivations), see the companion document
> **CineROI_AI_Calculations_Reference.md**. The same content is in the in-portal guide
> under the "How Numbers Are Calculated" tab.

> For a picture-first, executive-friendly walkthrough of the architecture and the
> end-to-end data flow (the six services, the four processing stations, the two request
> journeys, and the self-calibration loop, with diagrams), see the companion document
> **CineROI_AI_Architecture_And_Data_Flow.md**.

---

## 1. Executive Summary (Read This First)

**In one sentence:** CineROI AI is a *credit check for content deals* - you give it a TV
or film title and the price on the table, and it returns a clear, evidence-backed answer
to one question: **should we buy this, haggle, or walk away?**

**The three possible answers (the Recommendation Status):**

- **GREENLIGHT** - all four money checks pass. Acquire the title as proposed.
- **NEGOTIATE HARD** - some checks fail, but *every* failure is a price problem, so there
  is a lower price at which the deal clears. Go negotiate.
- **PASS** - at least one failure is *not* about price (it cannot be fixed by paying
  less), so no deal works. Walk away.

**Who uses it:** OTT (streaming) programming executives, content buyers, data-science
teams, and finance (CFO) / content leadership (CCO) for sign-off on large deals.

**What makes it trustworthy:** the decision math is deterministic and explainable. Every
verdict shows which checks passed or breached, the computed value vs the threshold, the
dominant reason, and - for a NEGOTIATE HARD - a concrete target price to negotiate toward.
Every state-changing action is written to an append-only audit log. Every valuation is
stamped with the model version that produced it, so any past decision is reproducible.

**Delivery:** a Docker Compose monorepo - a Next.js (App Router) frontend, a FastAPI
(async) backend, PostgreSQL 16 with the pgvector extension, and a Celery worker fleet
backed by Redis. Heavy work (batch ingestion, feature extraction, backtest audits,
telemetry polling) runs asynchronously; interactive reads and single-title valuations run
synchronously.

**Demo-mode honesty note:** the decision math, recommendation logic, backtesting,
governance, and persistence are the real engine. In demo mode the Narrative DNA embedding
and a few modeled financial drivers are deterministic placeholders so the full stack runs
on a laptop with no external services.

---

## 2. The Business Problem

Streaming platforms spend enormous sums acquiring and commissioning content, often on gut
feel and inconsistent spreadsheets. Deals arrive in different currencies, with different
licensing structures, across different territories, and with wildly different audience
potential. Executives need a consistent, defensible way to answer "is this worth it, and
at what price?" fast enough to move on a deal, and auditable enough to defend a
multi-million-dollar commitment to a board.

CineROI AI standardizes that judgment:

- It **normalizes every deal to US dollars** so a title quoted in rupees and one quoted in
  euros are compared on the same axis.
- It runs **four quantitative guardrails** that encode the platform's financial discipline.
- It separates **"the price is wrong" (negotiable) from "the title is wrong" (pass)** so
  buyers know where there is a deal to be had.
- It governs big commitments with **dual executive sign-off** and an **immutable audit
  trail**.
- It keeps itself honest by **backtesting** predictions against real outcomes and
  **re-calibrating** when it drifts.

---

## 3. The Decision Model - The Four Guardrails (The Core)

Before any money is committed, the Guardrails Engine runs four checks. A title must clear
all four to earn a straight GREENLIGHT. Every monetary amount is converted to USD first
(using a dated exchange rate), so all titles are judged on one scale.

### 3.1 Guardrail 1 - Cost per Viewing Hour (CPVH)

- **Question:** How much are we paying for each hour an audience actually watches? Cheaper
  per hour is better value.
- **Formula:** `CPVH = Cost (USD) / Projected Viewing Hours` (rounded to 4 decimals).
- **The line:** at or below **$0.18 per hour** for premium originals
  (ORIGINAL_SERIES, ORIGINAL_FILM, CO_PRODUCTION); at or below **$0.05 per hour** for
  cheaper library titles (LICENSED_LIBRARY). Strictly over the line is a breach.
- **Worked example (Aurora Protocol):** cost $42,000,000, projected 250,000,000 hours.
  `42,000,000 / 250,000,000 = $0.168/hour`. $0.168 <= $0.18 -> PASS.
- **Correctable?** Yes. Paying less lowers CPVH, so a CPVH breach only means "negotiate."
- **Edge case:** if projected viewing hours is zero, CPVH cannot be computed; the check
  fails and no CPVH value is persisted.

### 3.2 Guardrail 2 - Return on Spend (LTV-to-Cost Multiple)

- **Question:** For every $1 we put in, how many dollars of value come back over the
  title's life? Higher is better.
- **Formula:** `((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) / Cost (USD)`.
  The numerator is the total modeled value: a subscription (SVOD) part plus an
  advertising (AVOD) part.
- **The line:** must return at least **$3.20 per $1 spent (3.2x)** over a 12-24 month
  window. Below 3.2x is a breach.
- **Worked example (The Ledger):** cost $9,500,000, total modeled value about
  $27,550,000. `27,550,000 / 9,500,000 = 2.9x`. 2.9x < 3.2x -> BREACH (correctable).
- **Correctable?** Yes. Dividing the same value by a smaller cost raises the multiple.

### 3.3 Guardrail 3 - Keeps Subscribers (Churn Mitigation)

- **Question:** Does having this title stop people from cancelling their subscription?
- **How the number is produced:** rather than a single hard-coded figure, the churn-reduction
  percentage is **calculated** by a transparent, additive model from the title's observable
  features. It starts from a small base platform rate and adds a contribution for the asset
  type, the talent pedigree, the production scale, exclusivity, and market buzz (telemetry) -
  each contribution explained point-by-point - then caps the result between 0.10% and 5.00%.
  If a buyer **supplies** a known churn figure directly, that value is used exactly and the
  model step is skipped.
- **Illustrative, not fitted:** the model's coefficients are tuned to the five demo titles for
  a coherent showcase; they are not fitted to real subscriber-outcome data.
- **Borderline flag:** when the number lands right on the line (within 0.05% of 1.5%, i.e. in
  the 1.45%-1.55% band), the scorecard shows an amber "Borderline Sensitivity" note so a
  reviewer knows the greenlight-vs-pass outcome hinges on a fragile input. The flag is
  informational and never changes the verdict.
- **How it is modeled:** an additive, transparent model sums a base rate, the asset cadence,
  talent pedigree, production scale, an exclusivity lift, market telemetry heat, and a
  per-genre affinity weight. A title with no market-telemetry data uses a neutral default
  (not zero), and an unlisted genre uses a neutral genre weight - so a data gap never
  unfairly pushes a title toward a PASS. A number typed directly by a buyer overrides the
  model exactly (SUPPLIED). The coefficients are illustrative, tuned to the demo titles.
  A separate **content format** signal (live sports, live events, reality) adds extra churn
  credit for OTT-native appointment formats the asset type cannot express - so a live cricket
  match is not scored like a one-and-done library title.
- **The line:** must keep at least **1.5% of subscribers** from cancelling each month.
  Below 1.5% is a breach.
- **Worked example (Vintage Reruns Vol. 7):** model-computed 0.81% reduction. 0.81% < 1.5% ->
  BREACH.
- **Correctable?** **NO.** Paying less does not make a title more loved. A churn breach is
  structural, and a single one forces a PASS.

### 3.4 Guardrail 4 - Pays for Itself in Time (Payback Horizon)

- **Question:** How many months until the title earns back what we paid for it?
- **Formula:** the first month at which cumulative contribution margin turns positive,
  walked month-by-month over the **milestone-based** payment schedule (not a single lump
  sum).
- **The line:** target **9 to 12 months**. Longer than 12 months is a breach.
- **Worked example (Aurora Protocol):** earns back by month 11. 11 <= 12 -> PASS.
- **Correctable?** Yes. A cheaper title pays back sooner.

### 3.5 How the Four Checks Become One Verdict

The single idea that drives every verdict: **can a lower price fix it?**

- Three checks - CPVH, return on spend, payback - all improve when you pay less. If only
  those fail, the title is good and the price is wrong -> **NEGOTIATE HARD**.
- The "keeps subscribers" check is about how good the title is, not its price. No discount
  fixes it. If that one fails -> **PASS**.

Formal rule:
- **0 breaches** -> GREENLIGHT.
- **1+ breaches, all correctable** -> NEGOTIATE HARD.
- **1+ non-correctable breach** (or any breach the engine cannot classify due to missing/
  invalid data) -> PASS (an unclassifiable breach is treated conservatively as PASS and
  flagged).

### 3.6 Explainability

Every recommendation reports: which checks passed and which breached; for each breach, the
computed value, the threshold, and the normalized shortfall magnitude; and the **dominant
factor** (the breached check with the largest normalized shortfall) that headlines a PASS
or NEGOTIATE HARD.

### 3.7 Deal Decision Support (built on top of the verdict)

- **Negotiation Playbook** - for a NEGOTIATE HARD / PASS driven by a correctable breach:
  a **target purchase ceiling** in USD (the highest price at which the cost-correctable
  checks would pass), the **implied discount** versus the current ask, and plain-language
  **counter-proposal levers** keyed to each breached guardrail (marked correctable vs
  structural).
- **LTV-to-Cost Attribution** - splits the opaque multiple into its SVOD subscription
  value and AVOD advertising value, alongside the total modeled value, the normalized
  cost, and the multiple, so the number is not a black box.
- **Absolute Churn Cohort** - alongside the churn percentage, an approximate count of
  retained subscribers, labeled as a modeled/derived figure.

---

## 4. Worked Examples With Real Numbers (The Seeded Demo Titles)

These are the five titles the demo ships with. The stored verdict, the live recompute, and
the dashboard badge all agree for every one (the seed is self-consistent).

### 4.1 Aurora Protocol - GREENLIGHT

- Original Series, cost **$42,000,000** (USD, no conversion), projected **250,000,000** hours.
- CPVH: `42,000,000 / 250,000,000 = $0.168` <= $0.18 -> PASS.
- Return: **3.8x** >= 3.2x -> PASS.
- Churn: **2.11%** >= 1.5% -> PASS.
- Payback: **11 months** <= 12 -> PASS.
- Verdict: **GREENLIGHT**. Because it is a GREENLIGHT above $25M, it also needs dual
  sign-off from both the CCO and the CFO before it is final.

### 4.2 The Ledger - NEGOTIATE HARD (the step-by-step walkthrough)

- Original Film, cost **$9,500,000** (USD), projected **40,000,000** hours.
- Step 1 - the deal: $9.5M for a film expected to be watched 40M hours.
- Step 2 - CPVH: `9,500,000 / 40,000,000 = $0.2375/hour`. Over the $0.18 ceiling -> BREACH
  (price problem).
- Step 3 - Return: total modeled value about $27,550,000. `27,550,000 / 9,500,000 = 2.9x`.
  Under 3.2x -> BREACH (price problem).
- Step 4 - Churn: **1.60%** >= 1.5% -> PASS (the check a discount cannot fix - and it passes).
- Step 5 - Payback: **15 months** > 12 -> BREACH (price problem).
- Step 6 - Verdict: three breaches, all price-fixable; the one non-correctable check
  passes -> **NEGOTIATE HARD**. Dominant factor: CPVH.
- Step 7 - the target: the engine solves for the highest price at which the price-driven
  checks pass: **$7,200,000** - about a **24% discount** off the $9.5M ask. The buyer's
  goal: negotiate toward $7.2M.

### 4.3 Vintage Reruns Vol. 7 - PASS

- Licensed Library, **EUR 1,200,000** -> normalized **$1,308,000** (EUR 1.2M x 1.09),
  projected **60,000,000** hours.
- CPVH: `1,308,000 / 60,000,000 = $0.0218` <= $0.05 (library ceiling) -> PASS.
- Return: **4.1x** >= 3.2x -> PASS.
- Churn: **0.81%** < 1.5% -> BREACH (non-correctable - no price fixes a title that does not
  retain subscribers).
- Payback: **8 months** <= 12 -> PASS.
- Verdict: **PASS**. Three checks pass and it is dirt cheap per hour, but the one failure
  is the one that matters: it does not keep subscribers. Walk away.

### 4.4 Monsoon Lanes - GREENLIGHT

- Co-Production, **INR 18,000,000** -> normalized ~**$216,000**, projected 140,000,000 hours.
- CPVH ~$0.0015, Return 3.35x, Churn 1.79%, Payback 12 months - all pass -> GREENLIGHT.

### 4.5 Echoes of 2019 - GREENLIGHT (historical, used for backtesting)

- Original Series, cost **$30,000,000** (USD), projected 180,000,000 hours.
- CPVH $0.1667, Return 3.5x, Churn 1.99%, Payback 10 months - all pass -> GREENLIGHT.

**Demo verdict spread:** 3 GREENLIGHT (Aurora, Monsoon, Echoes), 1 NEGOTIATE HARD
(The Ledger), 1 PASS (Vintage Reruns).

---

## 5. The Screens (Frontend Surfaces)

The portal is a Next.js App Router application with a shared dark theme and top navigation.
The logo returns to the landing page. Six route areas, plus a cross-cutting chat assistant:

### 5.1 Landing Page (`/`)
Entry point with navigation into the four working areas.

### 5.2 Executive Command Dashboard (`/dashboard`)
The whole portfolio at a glance.

- **KPI header cards:** active pipeline valuation (USD), average LTV-to-Cost multiple,
  portfolio risk exposure index, and model prediction accuracy rate.
- **Master asset data grid:** one row per title showing title name, asset type, asking
  price (native currency), CPVH status, LTV multiple, **deal stage**, and the
  recommendation badge. Status badges use icon + color + border (check / scale / X) so
  the verdict is readable without relying on color (accessibility).
- **Sortable columns** - clicking a header reorders rows; toggling re-selects direction.
- **Search and filters** - a free-text title search, a recommendation filter, and a
  deal-stage filter, with a visible "N of M" count and a no-match state with a clear
  control.
- **Shareable view state** - the search, both filters, and the sort column/direction are
  mirrored into the URL query string (`?q=`, `?rec=`, `?stage=`, `?sort=`, `?dir=`), so a
  filtered/sorted view is bookmarkable, survives reload, and can be shared by link.
- **Row click** navigates to that title's evaluation.

### 5.3 Asset Studio (`/studio`)
Where titles enter the pipeline and get an instant verdict.

- **Single Asset tab** - type a title's details (name, asset type, cost & currency,
  synopsis, optional pedigree/territories/viewing-hours) and press RUN ROI VALUATION to
  get a full scorecard instantly (synchronous quick-evaluate path).
- **Viewing-hours units** - the viewing-hours field takes a value plus a unit (hours /
  minutes / seconds) and is normalized to hours before the CPVH math, so you can type a
  figure in whatever unit you have (e.g. 1,000,000 sec). Blank = the engine estimates it.
- **Genre dropdown** - genre is chosen from a canonical list (a custom value still works)
  and drives both market-telemetry lookups and a per-genre churn-affinity weight.
- **Content Format dropdown** - the OTT consumption format (Live Sports, Live Event,
  Reality/Competition, Scripted Series, Film, Library, ...). Live/appointment formats add
  extra churn credit the asset type cannot express, so a live match is not scored like a
  one-and-done library title. Optional; unlisted/blank adds no extra churn.
- **Shorthand budgets** - the cost field accepts analyst shorthand like `12 Cr`,
  `3 Lakh`, `1.5M`, `500k`, with a live preview of the expanded number.
- **Quick Presets** - one-click sample titles that fill the form so you can run a
  valuation immediately.
- **Pitch PDF auto-fill (drop zone)** - drop a pitch/script PDF and the system reads the
  title, synopsis, genre, and budget into the form for review (best-effort; nothing is
  auto-submitted).
- **Batch Slate tab** - upload or paste a CSV/JSON catalog of titles in one go; it is
  processed asynchronously and returns an accepted/rejected summary with a reason per
  rejected row. A **Download CSV template** button provides a ready-made
  `cineroi-slate-template.csv` (header row + allowed-value comment hints + three example
  titles) so first-time users can start from the correct shape.
- **Instant scorecard** - the right pane renders the recommendation, the four checks, a
  metadata radar, and a payback chart, with a link to the full deep-dive.

### 5.4 Title Evaluation / Deep-Dive (`/titles/[id]`)
Everything about one title.

- **Deal-stage control** - shows where the title sits in the acquisition pipeline and
  offers only the legal next stages (see Section 7).
- **Metadata radar** - Narrative DNA, Affective Tone, Talent Pedigree, Production Scale on
  a shared 0-10 axis.
- **Top 3 historical comps** - the three titles most similar to this one by Narrative DNA,
  each linked, with its recommendation badge and an affinity percentage (see Section 6.1).
- **Market Telemetry card** - the live market signals (social sentiment, chart velocity,
  licensing inflation) for this title's genre and primary territory (see Section 6.2).
- **Financial breakdown accordion** - CPVH ceiling checks, the LTV-to-Cost attribution
  split (SVOD vs AVOD), churn mitigation, and a payback timeline bar chart.
- **Negotiation leverage / playbook** - for non-GREENLIGHT titles: the target purchase
  ceiling, implied discount, and counter-proposal levers.
- **Explanation panel** - passed/breached checks, computed vs threshold, shortfall, and
  the dominant factor.
- **What-if sensitivity** - sliders for cost, viewership (bear/base/bull), and churn that
  recompute the verdict live without saving anything (a preview; set all sliders to 100%
  to reproduce the official result).
- **Override** - an authorized executive can change the verdict with a mandatory written
  justification; the change is logged.
- **Audit history & lineage** - the chronological timeline of every action on the decision.
- **Export Greenlight Memo (PDF)** - a print-ready one-page executive brief (scorecard,
  checks, playbook, sign-off block) via the browser's Save-as-PDF.

### 5.5 Backtesting & Calibration Studio (`/backtest`)
Keeps the model honest.

- **Split-pane:** left pane is the ground-truth input form (pick a title that already has
  a stored prediction, enter the actual observed CPVH and LTV); right pane renders
  side-by-side Predicted vs Actual variance charts after submission, plus the overall
  prediction error (MAPE - lower is better).
- **Model Calibration Controller** - requests auto-tuning of the feature weights based on
  the historical MAPE; shows the applied weight offsets.
- **Model Version Catalog** - every immutable model version with its weights and date;
  an authorized user can roll back to a prior version.
- **Executive Sign-Off panel** - for a high-budget GREENLIGHT, shows the required roles
  (CCO + CFO) and which approvals are still outstanding; records sign-offs until the gate
  clears.

### 5.6 How It Works Guide (`/guide`)
An in-portal, plain-language guide written for non-technical executives. Tabs: Overview,
Features & How-To, The 4 Guardrails (each with real worked arithmetic), Worked Examples
(a step-by-step walkthrough of The Ledger plus one title per verdict), and a searchable
Glossary. Every number in the guide matches what the live app produces for the seeded
titles.

### 5.7 Data Chat Assistant - "CineROI Copilot" (floating widget, all pages)

A persistent chat button (bottom-right) opens **CineROI Copilot**, a read-only assistant
available on every page. It answers two kinds of question: data questions (a title's verdict,
guardrail checks, churn, the portfolio) and how-to/concept questions (how to upload a slate,
what CPVH means, how overrides work). It is **grounded** - it retrieves real records through
the existing repositories plus curated help snippets, and answers only from what it retrieved;
when it lacks the answer it says so rather than inventing one. On a title page it scopes to
that title automatically; elsewhere it resolves a named title (even a partial name) or falls
back to the portfolio. Every answer lists its **sources** (title scorecard, portfolio, or a
help topic) for traceability, and offers up to three **follow-up chips** - suggested next
questions that are question-aware, so clicking one never repeats what was just asked and the
conversation keeps advancing.

It is strictly **read-only**: it computes no number and takes no action. The deterministic
engine remains the sole source of every value, and any request to override, greenlight, or
change a number is redirected to the audited governance controls on the title page. It
inherits the same RBAC confidential-field scoping, so it never surfaces data a user could not
see directly.

The language model behind it is **swappable** behind a single `ChatProvider` interface,
selected by `CINEROI_CHAT_PROVIDER`:

- **mock** (default) - an in-process, no-key, no-network, deterministic provider that composes
  the answer from the grounded context. Instant and free; ideal for demos and CI.
- **ollama** - a local Ollama server (`CINEROI_CHAT_OLLAMA_MODEL`, e.g. `llama3.1:latest`),
  reached from the container via `host.docker.internal`. Keeps data on the host (no third-party
  egress). Local CPU inference can be slow; on a provider timeout the endpoint returns a clean
  error envelope and the widget shows a Retry.

A hosted provider (Bedrock / OpenAI / Anthropic) can be added later as another class behind the
same interface, with no change to the endpoint, the grounding, or the widget.

---

### 5.8 What-If Explorer (title page tab, read-only sandbox)

A dedicated **What-If Explorer** tab on each title page lets an analyst model a deal without touching the saved record. Unlike the simple what-if sliders, it accepts **direct values**: the acquisition cost in dollars, projected viewing hours, the churn-reduction %, the SVOD/AVOD drivers (LTV, churn value, CPM, ad impressions, watch-time elasticity), and even the four **guardrail thresholds** (LTV-to-Cost floor, churn hurdle, CPVH ceiling, payback window). The verdict and all four checks recompute live and are shown **Baseline vs Scenario** - each check with its value, threshold, and PASS/BREACH on both sides, a callout when the verdict would flip, and the SVOD/AVOD revenue split both ways.

It is a strict **read-only sandbox**: it persists nothing, writes no audit entry, forks no model version, and never changes the saved scorecard or the standard thresholds - so the platform's "every saved verdict is reproducible" guarantee is untouched. Direct overrides win over the coarse multipliers; a cost change scales the milestone schedule and monthly margin proportionally (in USD) so payback stays coherent, and a direct USD cost on a non-USD title is applied without FX distortion. Three one-click presets seed scenarios - Bear, Bull, and Target Deal (cost set to the negotiation ceiling that clears all correctable guardrails; disabled for already-GREENLIGHT or structural-PASS titles). The whole scenario is encoded sparsely in the URL as a shareable link (nothing stored), and the tab is excluded from the Greenlight Memo PDF.

The surface is designed to teach as you use it: every field shows its Baseline value inline (as the input placeholder) and carries a hover/focus **info tooltip** explaining what the field is and how raising or lowering it moves the verdict. Quick-scenario presets (Bear, Bull) do not just scale hidden multipliers - they fill the actual input fields with concrete numbers derived from the Baseline, so you can see exactly what each preset changed and then fine-tune from there.

---

### 5.9 Interactive Overview Deck (shareable presentation)

A standalone, self-contained HTML deck (`presentation/index.html`, with `presentation/SPEAKER_NOTES.md`) tells the whole CineROI AI story in 12 interactive slides: the business problem, the credit-check analogy, the four guardrails, a **draggable live Verdict Machine** (drag a sample title's acquisition price and watch the four checks and the verdict flip in real time, with the crossover faithful to the real engine), the "explainable AI" trust pillars, the AI stack (Perception / Decision / Conversational AI), the self-calibration loop, and a call-to-action slide that opens this portal. It carries a persistent nav bar (Home / prev / next / click-to-jump dots / counter), keyboard navigation, and an ambient motion layer, and it honors `prefers-reduced-motion`.

It is intended for sharing, not as a product surface: everything is inline (no assets), so it opens in any browser with no install or login, and it uses **illustrative sample-slate figures** rather than production data. It is published via GitHub Pages at `https://vasistasandeep.github.io/GreenlightIQ/presentation/` (push to `main` to update). The deck's "Open the live demo portal" button is **off by default** (its `PORTAL_URL` constant is empty) so a shared copy never links to a dead address; set `PORTAL_URL` to a reachable URL (a deployment, `http://localhost:3000`, or a current ngrok tunnel) to activate it for a live demo.

---

## 6. Enhancement Features In Detail
### 6.1 Top 3 Historical Comps (title-to-title similarity)
A title-to-title nearest-neighbour lookup over the 1536-dimension Narrative DNA embedding,
distinct from the audience-fit match (which compares a title to subscriber-cluster
preferences). The repository ranks other titles by pgvector cosine similarity
(`1 - (narrative_dna <=> query_vector)`), excludes the title itself, de-duplicates to the
single closest vector per neighbour, and resolves each neighbour's latest recommendation.
Endpoint: `GET /valuation/{title_id}/comps`. Returns `found=false` with an empty list when
the title has no embedding; 404 for a missing title.

*Implementation note:* at demo data volumes the pgvector IVFFlat index has near-empty
inverted lists and ordering by the bare `<=>` operator returns zero rows, so the query
orders by the derived `1 - distance` similarity expression to force an exact sequential
scan.

### 6.2 Market Telemetry Card
Surfaces the cached market telemetry (social sentiment index, chart velocity score,
licensing inflation multiplier) for the title's genre and primary territory - the same
signals the engine folds into territory-weighted CPM/LTV. The valuation scorecard carries
the title's genre and primary territory so the card can look telemetry up. States: live
data; a stale-source note when the last poll failed; a "not yet polled" empty state; and
nothing at all when the title has no genre/territory. The demo seeds the telemetry cache
and back-fills each title's modeled inputs so valuations are unchanged by the weighting.

### 6.3 Dashboard Filtering, Search, and Shareable View State
Covered in Section 5.2. The grid is a pure function of the URL: it reads its state from the
query string and writes changes back with history-replacing navigation.

### 6.4 What-If Sensitivity (stateless recompute)
A read-only endpoint `POST /valuation/{title_id}/what-if` applies bounded scenario
multipliers (cost, viewership, churn; each within [0.5, 2.0]) to a title's modeled inputs,
re-runs the *same* guardrail math, and returns a fresh scorecard without persisting
anything or writing an audit entry. An all-1.0 scenario reproduces the stored verdict.

### 6.5 Greenlight Memo (PDF)
A print-only one-pager composed from the scorecard, the four checks, the negotiation
playbook, and a sign-off block; the app chrome is hidden via print CSS so only the memo
prints.

---

## 7. Deal-Stage Acquisition Lifecycle

A human-managed pipeline stage, **independent of the AI recommendation**, that tracks where
a title sits in the acquisition process.

**The stages:** `SCREENING -> EVALUATED -> IN_NEGOTIATION -> APPROVED -> CLOSED_WON`, with
`CLOSED_LOST` and `PASSED` as the other terminal outcomes.

**The guarded transition rules (a state machine):**
- From any live (non-terminal) stage you may abandon to **PASSED**.
- A single forward step: SCREENING -> EVALUATED -> IN_NEGOTIATION -> APPROVED.
- From APPROVED you may go to **CLOSED_WON** or **CLOSED_LOST**.
- Terminal stages (CLOSED_WON, CLOSED_LOST, PASSED) have no outgoing transitions.
- No stage transitions to itself; illegal jumps (e.g. SCREENING straight to CLOSED_WON)
  are rejected.

**Endpoints:**
- `GET /titles/{id}/deal-stage` - current stage + the legal next stages.
- `PATCH /titles/{id}/deal-stage` - advance to a target stage. Gated to decision-making
  roles (Content Buyer / CCO / CFO); an unauthorized role gets 403; an illegal transition
  gets 422 with the allowed set; a successful move is persisted under optimistic locking
  and written to the audit log (before/after stage).

**UI:** a sortable Deal Stage column and a stage filter on the dashboard; a stage control
on the title page that offers only legal next stages, is read-only for users without
permission, and surfaces a clear message on a rejected move.

**Seeded stages (demo):** Aurora APPROVED, Monsoon IN_NEGOTIATION, The Ledger EVALUATED,
Vintage Reruns SCREENING, Echoes CLOSED_WON - a realistic spread across the pipeline.

---

## 8. Governance, Security, and Compliance

### 8.1 Roles (RBAC)
Each user holds exactly one role: **DATA_ANALYST**, **CONTENT_BUYER**,
**CHIEF_CONTENT_OFFICER (CCO)**, or **CFO**. Permissions are enforced per operation.

- Ingest and valuation: all roles.
- Override a recommendation, and change a deal stage: CONTENT_BUYER, CCO, CFO only.
- Executive sign-off (approve/reject): CCO and CFO.
- Calibrate the model: DATA_ANALYST, CCO, CFO.
- Read confidential fields: CONTENT_BUYER, CCO, CFO (analysts excluded; CONTENT_BUYER is
  further territory-scoped; executives are organization-wide).

### 8.2 Approval Workflow (high-budget gate)
A GREENLIGHT whose normalized cost exceeds **$25,000,000** requires sign-off from **both**
the CCO and the CFO before it can be finalized. The finalization endpoint reports which
required approvals remain outstanding and blocks finalization until all are cleared.
(A demo-only `demo-sign-off` endpoint, enabled only under the dev/demo auth bypass, lets a
single-identity demo session attribute approvals to the seeded role-holders so a two-role
gate can be cleared; it is absent in production.)

### 8.3 Authentication & Sessions
SSO via OIDC/SAML; sessions bound to the authenticated identity; 30-minute idle expiry;
service-to-service calls use API credentials; missing/expired/revoked credentials are
rejected with descriptive errors.

### 8.4 Audit Logging & Lineage
Every state-changing action (ingest, valuation, override, approval, calibration, deal-stage
transition) writes exactly one append-only audit entry capturing actor, timestamp, action,
and before/after values. Append-only is enforced in the database (revoked UPDATE/DELETE +
a mutation-blocking trigger). `GET /audit/lineage/{subject_id}` returns the full
chronological trail.

### 8.5 Model Versioning & Reproducibility
Every valuation is stamped with the model version active at the time. Calibration never
mutates weights in place - it forks a new immutable version. All historical versions are
retained, so any past valuation can be reproduced from its stamped version.

### 8.6 Data Protection
Sensitive data (unreleased scripts, deal terms, PII) is encrypted at rest; confidential
records/fields are scoped by role and authorized territory with field withholding;
configurable retention purges or archives eligible records.
---

## 9. Multi-Currency and Licensing Economics

### 9.1 Currency Normalization
Costs are captured in their native currency (at minimum INR, USD, EUR, GBP) and converted
to the Base Currency (USD) using a **dated** exchange rate before any guardrail runs. The
rate value and rate date are recorded with the projection. If no rate exists for the exact
required date, the engine **falls back to the latest available rate** for that currency
pair; it rejects the valuation only when the currency pair has no rate at all.

### 9.2 Territory Weighting
When computing the LTV-to-Cost multiple, the engine applies per-territory CPM and LTV
weighting derived from each target territory's cached market telemetry:
`cpm_weight = licensing_inflation_multiplier`, `ltv_weight = 1 + chart_velocity_score/100`.
A territory with no telemetry contributes a neutral weight of 1. Weights are averaged
(equal-weight mean) across the title's target territories.

### 9.3 Licensing & Windowing
Each title carries License Terms: license duration (months), an exclusivity flag,
windowing rules, holdbacks, and a milestone-based payment schedule. Payback uses the
milestone schedule, not a lump sum. Exclusive windows are valued separately from
non-exclusive windows. If the summed windowing periods exceed the license duration, the
terms are rejected.

---

## 10. Asynchronous Processing & Operations

- **Task queue:** Celery workers backed by Redis run `ingest_batch`, `extract_features`,
  `run_backtest_audit`, and `poll_telemetry` on dedicated queues.
- **Job lifecycle:** PENDING -> PROCESSING -> COMPLETED | FAILED, with a recorded failure
  reason on failure. `GET /jobs/{job_id}` returns status; `POST /jobs/{job_id}/retry`
  re-dispatches a dead-lettered job after remediation.
- **Dispatch pattern:** the API never does heavy work inline - it persists intent,
  enqueues a job, and returns a job id (202 Accepted) immediately.
- **Webhooks:** a terminal-status webhook fires with a per-event dedupe key so repeated
  deliveries are idempotent.
- **Observability & SLAs:** structured logs + metrics per request/job; an SLA alert if a
  job exceeds 15 minutes; exhausted-retry jobs route to a dead-letter queue;
  `GET /health` reports the status of the database, the task queue, and the telemetry
  connector.
- **Concurrency & idempotency:** ingestion honors an idempotency key (a replay returns the
  original result, no duplicates); valuation updates use optimistic locking (`row_version`)
  and reject a stale-version write with a conflict error; concurrent valuations never
  produce partial/corrupt rows.

---

## 11. REST API Surface (Reference)

All under `/api/v1`. Auth via session bearer token or service credential; errors use a
shared `{error_code, message, details}` envelope.

| Method & Path | Purpose |
|---|---|
| `POST /titles/ingest` | Dispatch a batch manifest (CSV/JSON/PDF, <= 10,000 rows) asynchronously; returns 202 + job id; honors `Idempotency-Key`. |
| `POST /titles/quick-evaluate` | Create one title + active version and return an instant full scorecard (synchronous). |
| `POST /titles/parse-pitch` | Best-effort extraction of fields from a pitch/script PDF for review (creates nothing). |
| `GET /titles/{id}/versions` | All versions of a title (evaluation history). |
| `GET /titles/{id}/deal-stage` | Current deal stage + allowed next stages. |
| `PATCH /titles/{id}/deal-stage` | Advance the deal stage (guarded transition; audited). |
| `POST /valuation/calculate` | Run a full valuation for a title (persists; audited). |
| `GET /valuation/{id}` | Full persisted scorecard + metadata breakdown + explanation + genre/primary territory. |
| `GET /valuation/{id}/comps` | Top 3 most similar titles by Narrative DNA. |
| `GET /valuation/{id}/decision` | Resolve a title to its latest decision (projection) id. |
| `POST /valuation/{id}/what-if` | Stateless scenario recompute (no persist, no audit). |
| `POST /backtest/audit` | Persist ground truth and return the audit scorecard (predicted vs actual + MAPE). |
| `POST /calibration/apply` | Apply auto-tuning offsets, forking a new model version. |
| `GET /market/telemetry?genre=&territory=` | Cached market telemetry for a genre/territory pair. |
| `GET /dashboard/summary` | KPI figures + the asset grid rows (includes deal stage). |
| `POST /decisions/{id}/override` | Override a recommendation with a justification (audited). |
| `POST /decisions/{id}/approve` / `reject` | Executive sign-off actions. |
| `GET /decisions/{id}/finalization` | Finalization gate + outstanding approvals. |
| `POST /decisions/{id}/demo-sign-off` | Dev/demo-only: attribute an approval to a seeded role-holder. |
| `GET /audit/lineage/{subject_id}` | Full chronological audit trail for a title/decision. |
| `GET /models/versions`, `GET /models/versions/{id}` | Model version catalog. |
| `POST /models/versions/{id}/activate` | Roll back / activate a model version. |
| `GET /jobs/{id}`, `POST /jobs/{id}/retry` | Async job status and dead-letter retry. |
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/session` | SSO session lifecycle. |
| `GET /health` | DB / task-queue / telemetry readiness. |

---

## 12. Data Model (PostgreSQL 16 + pgvector)

Core and expanded tables; UUID primary keys; foreign keys enforce referential integrity.

- **titles** - the central entity: `title_id` (UUID PK), `title_name`, `asset_type`
  (CHECK: ORIGINAL_SERIES | ORIGINAL_FILM | LICENSED_LIBRARY | CO_PRODUCTION),
  `acquisition_cost_or_budget` (range 0.01-999,999,999.99), `native_currency`,
  `target_territories` (JSONB country codes), `genre_tag`, `projected_viewing_hours`,
  `is_historical`, `deal_stage` (CHECK over the 7 stages, default SCREENING),
  `active_version_id`, `row_version` (optimistic lock), `created_by`, `created_at`.
- **metadata_vectors** - `narrative_dna` VECTOR(1536) with an IVFFlat cosine index,
  `affective_primary`/`affective_secondary`, `talent_pedigree_score` (0-10),
  `production_scale_metric` (0-10), `extraction_status`, FK to titles and title_versions.
- **financial_projections** - `calculated_cpvh`, `ltv_to_cost_multiple`,
  `churn_reduction_pct`, `payback_horizon_months`, `recommendation_status`
  (CHECK: GREENLIGHT | NEGOTIATE_HARD | PASS), `normalized_cost_usd`, `exchange_rate_id`,
  `model_version_id`, `explanation` (JSONB), `row_version`.
- **historical_ground_truth** - observed actual outcomes for historical titles (backtest).
- **market_telemetry_cache** - `(genre_tag, territory)` unique key; `social_sentiment_index`,
  `chart_velocity_score`, `licensing_inflation_multiplier`, `source_available`.
- **title_versions** - immutable per-title snapshots; one active per title; incrementing
  version number; `source_snapshot` encrypted at rest.
- **license_terms** - duration, exclusivity, windowing rules, holdbacks, milestone schedule
  (encrypted at rest).
- **exchange_rates** - dated native->USD rates; `(from, to, date)` unique.
- **model_versions** - immutable weight/parameter snapshots; exactly one active (partial
  unique index); `talent_pedigree_weight + narrative_trope_weight = 1.00` CHECK.
- **subscriber_clusters** - 1536-dim preference vectors for audience-fit matching
  (IVFFlat cosine index).
- **users / sessions** - one role per user; session lifecycle.
- **approval_workflows / approval_actions** - the high-budget sign-off state and the
  recorded approve/reject/override acts.
- **audit_log** - append-only (revoked UPDATE/DELETE + trigger); actor, action,
  before/after, model version, timestamp.
- **jobs** - async job lifecycle; `idempotency_key` unique; dead-letter flag.

**Migrations:** Alembic, `0001_core_tables` through `0004_deal_stage` (the last added the
`titles.deal_stage` column + CHECK). Deterministic seed data is generated by
`database/seed/generate_seed_sql.py` (byte-stable, idempotent, with a `--check` mode).

---

## 13. Architecture & Deployment

- **Monorepo:** `/backend` (FastAPI async), `/frontend` (Next.js App Router + TypeScript +
  Tailwind + Shadcn UI + Recharts), `/database` (Alembic migrations + seed), plus
  `docker-compose.yml`, `scripts/`, and a README.
- **Backend layers:** `app/api/` (routers), `app/engines/` (ingestion, feature_extraction,
  vector_search, guardrails, backtesting, calibration, telemetry, auth, rbac, approvals,
  audit, model_versioning), `app/domain/` (pure functions: cpvh, ltv, mape, currency,
  windowing, recommendation, negotiation, attribution, cohort, sensitivity, weights,
  deal_stage), `app/models/` (ORM), `app/schemas/` (Pydantic), `app/repositories/` (data
  access), `app/tasks/` (Celery).
- **Compose services:** `db` (PostgreSQL 16 + pgvector), `redis` (broker + result
  backend), `db-init` (one-shot: alembic upgrade + seed), `backend` (FastAPI/uvicorn),
  `worker` (Celery fleet), `frontend` (Next.js). A `pgdata` volume persists the database.
- **Single-origin portability:** the frontend calls the API same-origin and Next.js
  rewrites proxy `/api/*` and `/health` to the backend, so the app works behind one public
  URL (a tunnel, load balancer, or any host) with no hardcoded localhost.
- **Operational scripts:** `scripts/demo-up`, `demo-down`, and **`demo-reset`** (truncates
  the demo-mutable tables - including the telemetry cache - and re-applies the pristine
  seed so a demo can be re-run from a clean slate).
- **CI:** a GitHub Actions pipeline runs the backend suite, the frontend suite, and a
  docker smoke test.

---

## 14. Testing Strategy

- **Property-based tests (Hypothesis)** target the pure domain functions and deterministic
  engine orchestration - 47 named correctness properties (e.g. CPVH boundary, LTV formula,
  recommendation totality, MAPE zero-actual exclusion, currency round-trip, approval
  thresholds, audit append-only, deal-stage transition legality, optimistic-lock statement
  building, exchange-rate fallback, seed recompute consistency). Each runs 100+ generated
  examples and is tagged for traceability.
- **Unit tests** cover specific edge cases (no clusters, zero viewing hours, row-limit
  boundary at exactly 10,000/10,001, extraction failure, persist-failure rollback).
- **Integration tests** (real PostgreSQL + pgvector) cover schema constraints, atomic
  persistence, concurrency, async job flow, auth, telemetry caching, and encryption/
  retention.
- **DB-less regression** for the optimistic-lock fix builds the guarded UPDATE against a
  fake session and reproduces the original descriptor failure on pre-fix code.
- **Frontend tests** (Vitest + Testing Library) cover the dashboard grid (sorting, search,
  filters, URL hydration), the title-page panels (radar, comps, telemetry card, deal-stage
  control, what-if), and the backtest studio.
- **Deployment smoke test:** `docker compose up` initializes the DB, loads seed, brings
  services healthy, and `GET /health` reports component status.
- **Current totals (as of the latest commit):** backend ~223 passing (66 skipped locally
  without psycopg); frontend ~165 passing across ~24 files.
---

## 15. Build History (How the Platform Grew)

The platform was built in waves, each committed and verified. In rough order:

1. **Core platform** - full-stack decision-support engine: the four guardrails, the
   recommendation logic, feature extraction, ingestion, backtesting, calibration,
   telemetry, auth/RBAC/approvals, async jobs, currency, licensing, versioning, audit,
   the three core screens, and Docker deployment (Requirements 1-30).
2. **Demo population & backtest usability** - populated dashboard/title views; a
   demo-friendly backtest title selector with readable audit errors; calibration enabled
   in demo; ground-truth persistence and LTV scoring fixes.
3. **Asset Studio** - manual single-title ingest + instant ROI valuation, then demo
   refinements.
4. **How It Works guide** - the in-portal `/guide`, later expanded to a tabbed guide with
   worked examples, an exhaustive glossary/FAQ, and single-origin portability.
5. **Six UX/decision-support waves:**
   - Wave 1: colorblind-safe badges, empty states, label polish.
   - Wave 2: deal-support - negotiation playbook, LTV attribution, churn cohort.
   - Wave 3: Export Greenlight Memo (PDF one-pager).
   - Wave 4: what-if stateless sensitivity analysis with live recompute.
   - Wave 5: override-with-justification + the audit-lineage timeline.
   - Wave 6: shorthand currency input, model-version catalog + rollback, batch slate
     ingestion, and PDF pitch auto-fill.
6. **Readiness review enhancements (the most recent wave):**
   - FX fix: fall back to the latest available exchange rate; add the demo-reset script.
   - Top 3 historical comps via pgvector title-to-title similarity.
   - Market Telemetry card on the title page.
   - URL-driven filter/search/sort on the dashboard grid.
   - Deal-stage acquisition lifecycle with guarded transitions.
   - iPad/tablet responsive polish.
   - A bug fix: repaired the optimistic-locked update (recomputing a title that already
     had a projection used to 500) and made the seed verdicts self-consistent so a
     recompute always agrees with the stored verdict.
   - Rewrote the How It Works guide for executives with real worked math.
   - Folded all post-launch enhancements into the main spec (Requirements 31-37).

---

## 16. Specifications

The platform is specified under `.kiro/specs/`. The main spec `cineroi-ai` holds
Requirements 1-37 (EARS format), a design document (architecture, components, 47
correctness properties, testing strategy), and an implementation task plan with full
requirement traceability. Three sibling specs detail earlier enhancement waves in depth:
`deal-decision-support`, `what-if-sensitivity`, and `backtest-studio-demo-friendly`.

Requirement groups:
- **1-10:** ingestion, feature extraction, similarity, the four guardrails, recommendation,
  valuation endpoints.
- **11-18:** backtesting, calibration, telemetry, the three screens, persistence,
  deployment.
- **19-30:** auth, RBAC + approvals, multi-currency, licensing, async jobs, versioning,
  audit, model reproducibility, concurrency/idempotency, data protection, observability,
  explainability.
- **31-37 (post-launch):** comparable titles, market-telemetry card, dashboard filtering/
  shareable state, deal-stage lifecycle, responsive tablet layout, demo/operational
  integrity, and the Asset Studio instant-evaluation + intake surface.

---

## 17. Glossary

- **CPVH (Cost per Viewing Hour):** Cost (USD) / Projected Viewing Hours. Lower is better.
  Ceiling $0.18 (premium) or $0.05 (library).
- **LTV-to-Cost Multiple:** dollars of modeled value returned per dollar spent. Hurdle 3.2x.
- **Churn Mitigation:** modeled monthly % of subscribers a title keeps from cancelling,
  calculated by an additive model from the title's features (asset type, pedigree, production
  scale, exclusivity, market buzz) or supplied directly. Floor 1.5%. A breach here is
  non-correctable. The coefficients are illustrative, tuned to the demo titles.
- **Payback Horizon:** months until a title's cumulative margin turns positive. Target
  9-12; over 12 breaches.
- **Recommendation Status:** GREENLIGHT, NEGOTIATE_HARD, or PASS.
- **Correctable breach:** a failed check a lower price would fix (CPVH, LTV, payback) ->
  leads to NEGOTIATE HARD.
- **Non-correctable breach:** a failed check no price fixes (churn) -> forces PASS.
- **Dominant factor:** the breached check with the largest normalized shortfall.
- **Target Purchase Ceiling:** the highest price at which the cost-correctable checks pass -
  the negotiation target.
- **Implied Discount:** how far below the current ask the target ceiling sits, as a %.
- **Narrative DNA:** a 1536-dimension embedding of a title's tropes, themes, and pacing.
- **Affective Tone:** a title's primary and secondary emotional triggers.
- **Deal Stage:** the human acquisition-pipeline stage (SCREENING, EVALUATED,
  IN_NEGOTIATION, APPROVED, CLOSED_WON, CLOSED_LOST, PASSED), independent of the AI verdict.
- **Asset Type:** ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, or CO_PRODUCTION.
- **Premium Original:** ORIGINAL_SERIES / ORIGINAL_FILM / CO_PRODUCTION (CPVH ceiling 0.18).
- **Library Filler:** LICENSED_LIBRARY (CPVH ceiling 0.05).
- **Base Currency:** USD - the single currency all costs normalize into.
- **MAPE:** Mean Absolute Percentage Error = (1/n) x sum(|(Actual-Predicted)/Actual|) x 100.
  Lower is better; drives calibration above 10%.
- **Calibration:** auto-tuning feature weights when MAPE is high; forks a new model version.
- **Model Version:** an immutable snapshot of weights/parameters stamped on each valuation.
- **Approval Workflow:** dual CCO + CFO sign-off required for a GREENLIGHT above $25M.
- **Audit Log:** append-only, tamper-evident trail of every state-changing action.
- **Market Telemetry:** external signals (social sentiment, chart velocity, licensing
  inflation) by genre/territory that drive territory weighting.
- **What-If Sensitivity:** live, non-persisted recompute of the verdict under alternate
  cost/viewership/churn assumptions.
- **Idempotency Key:** makes a replayed ingestion return the original result, no duplicates.
- **Optimistic Locking:** a `row_version` guard that rejects a stale-version write.

---

## 18. Frequently Asked Questions

- **Why did a title get PASS?** At least one failure cannot be fixed by paying less -
  almost always that it does not keep subscribers (churn below 1.5%).
- **Difference between NEGOTIATE HARD and PASS?** NEGOTIATE HARD = only price problems, so
  a lower price clears it. PASS = a structural problem no discount fixes.
- **What is a good cost-per-hour?** At or below $0.18/hour (premium) or $0.05/hour
  (library). Lower is better.
- **Why do some greenlights need two executives?** Only GREENLIGHTs above $25M; large
  commitments require both CCO and CFO sign-off.
- **What if viewing hours are blank?** The engine estimates them from budget and pedigree
  so CPVH can still be computed.
- **Are the numbers real?** The decision math, recommendation logic, backtesting, and
  governance are the real engine; in demo mode the embedding and a few modeled drivers are
  deterministic placeholders so it runs with no external services.
- **Can the thresholds change?** They live in the active model version; calibration forks a
  new immutable version rather than editing in place, so past decisions stay reproducible.
- **How do I know the price to negotiate to?** The Negotiation Playbook on a NEGOTIATE HARD
  title gives a target purchase ceiling and the implied discount vs the ask.
- **Can I test scenarios?** Yes - the what-if sliders recompute the verdict live without
  changing the saved record.
- **Can I bring in a whole catalog?** Yes - the Asset Studio Batch Slate tab ingests a
  CSV/JSON slate; or drop a pitch PDF to auto-fill a single title.
- **One-pager for a committee?** Export Greenlight Memo (PDF) on the title page.
- **Who can override, and is it tracked?** Content Buyer / CCO / CFO, with a mandatory
  written justification, recorded permanently in the audit log.

---

*End of knowledge base. This document reflects the platform as of the latest commit on the
`main` branch. For the authoritative, machine-validated specification see
`.kiro/specs/cineroi-ai/` (requirements.md, design.md, tasks.md).*