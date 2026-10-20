"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { TopNav } from "@/components/layout/top-nav";

/**
 * In-portal "How It Works" guide (`/guide`) - tabbed reference.
 *
 * Tabs: Overview | Guardrails | Worked Examples | Glossary. The Examples tab
 * walks three real titles (one per verdict) end to end with the actual numbers
 * the engine produces, so a first-time reader can see exactly how a verdict is
 * reached. Client component for the tab interaction; all content is static.
 */

type TabId = "overview" | "features" | "guardrails" | "calculations" | "examples" | "glossary";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "features", label: "Features & How-To" },
  { id: "guardrails", label: "The 4 Guardrails" },
  { id: "calculations", label: "How Numbers Are Calculated" },
  { id: "examples", label: "Worked Examples" },
  { id: "glossary", label: "Glossary" },
];

// --------------------------------------------------------------------------- //
// End-to-end walkthrough video
// --------------------------------------------------------------------------- //
// To publish the walkthrough, drop an MP4 into frontend/public (e.g.
// public/walkthrough.mp4) and set WALKTHROUGH_VIDEO_SRC to its public path
// ("/walkthrough.mp4"). Optionally add a poster image the same way. While the
// source is empty the section renders a tidy "coming soon" placeholder, so the
// guide looks intentional with or without a video. Keep it a DEMO walkthrough
// caption (honest: the app runs on sample data).
const WALKTHROUGH_VIDEO_SRC = ""; // e.g. "/walkthrough.mp4"
const WALKTHROUGH_VIDEO_POSTER = ""; // e.g. "/walkthrough-poster.png"

// The chapters the walkthrough covers, shown beside the player as a quick map of
// the end-to-end flow (also useful as a shot list when recording the video).
const WALKTHROUGH_CHAPTERS: { step: string; detail: string }[] = [
  { step: "Enter a title", detail: "Type one in the Asset Studio (or click a preset) and run it." },
  { step: "See the four checks", detail: "CPVH, LTV-to-Cost, churn, and payback, each value vs its line." },
  { step: "Read the verdict", detail: "GREENLIGHT, NEGOTIATE HARD, or PASS, with the reason spelled out." },
  { step: "Act on it", detail: "Use the negotiation target, what-if sliders, or export the memo." },
];

function WalkthroughVideo() {
  const hasVideo = WALKTHROUGH_VIDEO_SRC !== "";
  return (
    <section
      aria-labelledby="walkthrough-heading"
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-5"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="walkthrough-heading" className="text-lg font-semibold text-slate-100">
          Watch the 2-minute walkthrough
        </h3>
        <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
          Demo &middot; sample data
        </span>
      </div>
      <p className="mb-4 text-sm text-slate-400">
        One title taken end to end: enter it, watch the four money checks, read the
        verdict, and act on it. No finance background needed.
      </p>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.6fr_1fr]">
        {/* Player (or placeholder) */}
        <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
          {hasVideo ? (
            <video
              controls
              preload="metadata"
              playsInline
              poster={WALKTHROUGH_VIDEO_POSTER || undefined}
              className="aspect-video w-full bg-black"
            >
              <source src={WALKTHROUGH_VIDEO_SRC} type="video/mp4" />
              Your browser does not support the video tag. You can still follow the
              step-by-step guide in the tabs above.
            </video>
          ) : (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-slate-900 to-slate-950 text-center">
              <span
                aria-hidden
                className="flex h-14 w-14 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-slate-500"
              >
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor" aria-hidden>
                  <path d="M8 5v14l11-7z" />
                </svg>
              </span>
              <p className="text-sm font-medium text-slate-300">Walkthrough video coming soon</p>
              <p className="max-w-xs px-6 text-xs text-slate-500">
                In the meantime, the step-by-step guide below and the Worked Examples
                tab cover the same end-to-end flow.
              </p>
            </div>
          )}
        </div>

        {/* Chapters / what the video covers */}
        <ol className="flex flex-col gap-3">
          {WALKTHROUGH_CHAPTERS.map((c, i) => (
            <li key={c.step} className="flex gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-xs font-bold text-emerald-300"
              >
                {i + 1}
              </span>
              <div>
                <p className="text-sm font-medium text-slate-200">{c.step}</p>
                <p className="text-xs text-slate-500">{c.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Small presentational helpers
// --------------------------------------------------------------------------- //
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-1.5 font-semibold text-slate-100">{title}</h3>
      <div className="text-sm text-slate-400">{children}</div>
    </div>
  );
}

function Formula({ children }: { children: React.ReactNode }) {
  return (
    <code className="mt-1 block rounded-md border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-emerald-300">
      {children}
    </code>
  );
}

function Verdict({ kind }: { kind: "GREENLIGHT" | "NEGOTIATE HARD" | "PASS" }) {
  const cls =
    kind === "GREENLIGHT"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-700/50"
      : kind === "NEGOTIATE HARD"
        ? "bg-amber-500/15 text-amber-300 border-amber-700/50"
        : "bg-rose-500/15 text-rose-300 border-rose-700/50";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-bold ${cls}`}>
      {kind}
    </span>
  );
}

/** A single check row inside a worked example. */
function CheckLine({
  label,
  plain,
  math,
  verdict,
}: {
  label: string;
  plain: string;
  math: string;
  verdict: "pass" | "breach";
}) {
  return (
    <div className="flex flex-col gap-1 border-b border-slate-800 py-2.5 last:border-b-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={verdict === "pass" ? "text-emerald-400" : "text-rose-400"}>
            {verdict === "pass" ? "PASS" : "BREACH"}
          </span>
          <span className="font-medium text-slate-100">{label}</span>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">{plain}</p>
      </div>
      <code className="shrink-0 font-mono text-xs text-slate-300">{math}</code>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Glossary data (exact to the system's requirements glossary)
// --------------------------------------------------------------------------- //
type GlossaryEntry = { term: string; def: string };
type GlossaryGroup = {
  group: string;
  /** Short slug for the jump/filter chips and the section anchor id. */
  id: string;
  /** One-line purpose shown under the group header for quick orientation. */
  blurb: string;
  items: GlossaryEntry[];
};

const GLOSSARY: GlossaryGroup[] = [
  {
    group: "The Verdict",
    id: "verdict",
    blurb: "The three possible answers and how a breach decides between them.",
    items: [
      { term: "Recommendation Status", def: "The final verdict for a title: GREENLIGHT, NEGOTIATE HARD, or PASS. Shown as the big banner on the scorecard." },
      { term: "GREENLIGHT", def: "All four guardrails pass. Acquire the title as proposed." },
      { term: "NEGOTIATE HARD", def: "One or more guardrails fail, but every failure is correctable by lowering the price. There is a price at which it clears - go negotiate." },
      { term: "PASS", def: "At least one failure cannot be fixed by any price change (e.g. weak retention). Walk away." },
      { term: "Correctable breach", def: "A failed check that renegotiating the price down would fix (CPVH, LTV, payback all improve as cost falls). Leads to NEGOTIATE HARD." },
      { term: "Non-correctable breach", def: "A failed check no price change can fix (e.g. churn impact). A single one forces PASS." },
      { term: "Dominant Factor", def: "The single breached check with the largest normalized shortfall - the headline reason behind a NEGOTIATE HARD or PASS. Shown in the Explainability panel." },
      { term: "Unclassifiable", def: "A breach the engine could not classify as correctable or not (missing/invalid data). Treated conservatively as PASS and flagged." },
    ],
  },
  {
    group: "The Four Guardrails",
    id: "guardrails",
    blurb: "The four money checks every title must clear, and their thresholds.",
    items: [
      { term: "CPVH", def: "Cost-Per-Viewing-Hour = Acquisition Cost / Projected Viewing Hours. What you pay per hour watched. Lower is better." },
      { term: "CPVH Ceiling", def: "The maximum allowed CPVH: 0.18 USD for premium originals, 0.05 USD for library titles. Over it = breach." },
      { term: "LTV-to-Cost Multiple", def: "((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) / Acquisition Cost. Dollars of value returned per dollar spent." },
      { term: "LTV Hurdle", def: "The minimum acceptable LTV-to-Cost multiple: 3.2x over a 12-24 month window. Below it = breach." },
      { term: "Churn Mitigation", def: "The monthly cohort churn-reduction percentage a title delivers. Calculated by an additive model from the title's features (asset type, pedigree, production scale, exclusivity, market buzz) - or supplied directly, in which case it is used exactly. Must be at least 1.5%. The model coefficients are illustrative, tuned to the demo titles." },
      { term: "Churn Mitigation Threshold", def: "The 1.5% minimum churn reduction a title must clear." },
      { term: "Borderline Sensitivity", def: "A flag shown when the churn number lands within 0.05% of the 1.5% hurdle (the 1.45%-1.55% band). Informational only - it never changes the verdict." },
      { term: "Payback Horizon", def: "Months until a title reaches positive contribution margin (pays for itself). Target 9-12; over 12 = breach." },
      { term: "Guardrail", def: "One of the four quantitative financial checks a title must pass to be greenlit." },
      { term: "Breach", def: "A guardrail check whose value crosses its threshold in the wrong direction (a fail)." },
      { term: "Threshold / Ceiling", def: "The line a guardrail must not cross. CPVH has a ceiling (max); LTV, churn, payback have floors/windows." },
      { term: "Shortfall Magnitude", def: "How far past its threshold a breached check landed, normalized so breaches are comparable across guardrails." },
    ],
  },
  {
    group: "What You Enter",
    id: "inputs",
    blurb: "The fields you fill in to evaluate a title in the Asset Studio.",
    items: [
      { term: "Title Name", def: "The name of the content being evaluated (e.g. 'The Bengaluru Syndicate'). Required." },
      { term: "Asset Type", def: "The content category: ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, or CO_PRODUCTION. Sets the CPVH ceiling." },
      { term: "Cost & Currency / Asking Price", def: "The acquisition cost or production budget and its native currency. Range 0.01 to 999,999,999.99; normalized to USD before any check." },
      { term: "Native Currency", def: "The currency the deal is quoted in: USD, INR, EUR, or GBP. Converted to USD using a dated exchange rate." },
      { term: "Target Territories", def: "The regions the title will be distributed in (India, North America, Europe, SE Asia, Global). Drives territory-weighted CPM/LTV." },
      { term: "Logline / Synopsis", def: "The narrative premise. Feeds feature extraction (Narrative DNA, affective tone). Required." },
      { term: "Genre & Tags", def: "The genre classification, chosen from a dropdown (a custom value still works). Drives market-telemetry lookups AND a per-genre churn-affinity weight: serialized/returning formats (crime, drama, thriller, reality) retain subscribers more than one-and-done formats. An unlisted genre uses a neutral weight." },
      { term: "Content Format", def: "The OTT consumption format (live sports, live event, reality/competition, scripted series, film, library), chosen from a dropdown. Adds an extra churn lift for live/appointment formats the asset type cannot express - a live match is far stickier than a one-and-done film. Zero lift for formats the asset type already covers." },
      { term: "Projected Viewing Hours", def: "Estimated total hours audiences will watch, entered with a unit (hours / minutes / seconds) that is normalized to hours. Optional - if blank the engine estimates it. Drives CPVH." },
      { term: "Talent Pedigree", def: "A 0-10 score of cast/creator strength. Higher pedigree raises modeled value and recovers cost sooner." },
      { term: "License (months) / License Duration", def: "How long the content is licensed for. Bounds the windowing rules and the milestone schedule." },
      { term: "Exclusive SVOD", def: "Whether the license is exclusive (only this platform) vs non-exclusive. Exclusive windows command a premium value." },
      { term: "Quick Presets", def: "One-click sample titles (Bengaluru, Apex Horizon, Vintage Reruns) that fill the form so you can run a valuation instantly." },
      { term: "Production Scale Metric", def: "A 0-10 measure of production ambition/budget scale, derived during feature extraction." },
    ],
  },
  {
    group: "Reading the Scorecard",
    id: "scorecard",
    blurb: "Everything on the valuation report: the checks, charts, and panels.",
    items: [
      { term: "Executive Scorecard", def: "The right-hand valuation report: banner, four checks, explainability, governance, radar, and payback chart." },
      { term: "Four Quantitative Checks", def: "The CPVH / LTV / Churn / Payback results panel, each showing computed value vs threshold and PASS/BREACH." },
      { term: "Explainability", def: "The plain-reason panel: the dominant factor and any breached checks behind the recommendation." },
      { term: "Target Purchase Ceiling", def: "The highest price at which the cost-sensitive checks still pass - your renegotiation target. Derived guidance." },
      { term: "Metadata Vector Profile", def: "The radar chart of a title's qualitative dimensions on a 0-10 scale." },
      { term: "Narrative DNA", def: "A 1536-dimension embedding of a title's tropes, themes, and pacing. Shown as one radar axis." },
      { term: "Affective Tone Score", def: "A title's primary and secondary emotional triggers. A radar axis." },
      { term: "Cultural Portability", def: "How well a title travels across the selected territories. A radar axis derived from the territory spread." },
      { term: "Cumulative Payback Projection", def: "The bar chart showing cumulative contribution margin by month; it crosses zero at the break-even month." },
      { term: "Break-Even Month", def: "The month cumulative margin turns positive - i.e. the payback horizon." },
      { term: "Normalized Cost (USD)", def: "The acquisition cost converted into USD, used for every comparison and the $25M governance threshold." },
    ],
  },
  {
    group: "Governance & Trust",
    id: "governance",
    blurb: "Sign-off gates, roles, and the audit trail that make a decision defensible.",
    items: [
      { term: "Governance Panel", def: "The scorecard section showing whether executive sign-off is required and which approvals are outstanding." },
      { term: "Approval Workflow", def: "Multi-tier executive sign-off: a GREENLIGHT whose normalized cost exceeds $25M needs both CCO and CFO approval before it is final." },
      { term: "High-Budget Threshold", def: "$25,000,000 USD. A GREENLIGHT above this triggers the CCO + CFO approval gate." },
      { term: "PENDING (sign-off)", def: "A required approver (CCO or CFO) who has not yet approved. The decision cannot finalize until all are cleared." },
      { term: "User Role", def: "DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER (CCO), or CFO. Each user holds exactly one." },
      { term: "CCO", def: "Chief Content Officer. One of the two required sign-offs on a high-budget greenlight." },
      { term: "CFO", def: "Chief Financial Officer. The second required sign-off on a high-budget greenlight." },
      { term: "RBAC", def: "Role-Based Access Control - what each role may do; overrides are reserved for decision-making roles." },
      { term: "Override", def: "A manual change to a title's recommendation status by an authorized role; always recorded in the audit log." },
      { term: "Audit Log", def: "An append-only, tamper-evident trail of every state-changing action with actor, time, and before/after values." },
      { term: "Confidential Scoping", def: "Hiding confidential fields (scripts, deal terms, PII) from roles/territories not cleared to see them." },
      { term: "SSO", def: "Single Sign-On via OIDC/SAML - how users authenticate. Sessions expire after 30 minutes idle." },
    ],
  },
  {
    group: "Accuracy & the Model",
    id: "model",
    blurb: "How the system measures and tunes its own accuracy over time.",
    items: [
      { term: "Backtesting", def: "Comparing past predictions against actual observed outcomes to measure how accurate the model has been." },
      { term: "Ground Truth Record", def: "The actual observed outcome for a historical title, entered in the Backtest Studio to score predictions." },
      { term: "Actual Payback Horizon", def: "One of the four observed outcomes entered in the Backtest Studio (alongside actual CPVH, LTV-to-Cost, and churn reduction): the real number of months the title took to pay for itself. Left blank it is simply omitted from the accuracy scoring." },
      { term: "MAPE", def: "Mean Absolute Percentage Error = (1/n) x sum(|(Actual - Predicted)/Actual|) x 100. The per-metric backtest accuracy; lower is better." },
      { term: "Model Accuracy (Verdict-Match Rate)", def: "The dashboard KPI card: the share of audited titles whose predicted verdict (GREENLIGHT / NEGOTIATE HARD / PASS) matched the verdict recomputed from the actual observed outcomes. Higher is better. It stays blank until at least one title has enough ground truth to judge, so it is never a fabricated number." },
      { term: "Calibration", def: "Auto-tuning the model's feature weights when MAPE exceeds 10%, so future predictions improve." },
      { term: "Model Version", def: "An immutable snapshot of the active weights and parameters stamped on each valuation, so any past result is reproducible." },
      { term: "Weight Offsets", def: "The adjustments applied to feature weights during calibration (each within -1.00 to 1.00)." },
      { term: "Variance Chart", def: "The Backtest Studio chart comparing Predicted vs Actual values side by side." },
      { term: "Feature Extraction", def: "Turning a title's source material into its numeric profile (Narrative DNA, tone, pedigree, production scale)." },
      { term: "Content Evaluation Models", def: "Small, transparent, versioned models that produce the engine's inputs (viewing hours, churn, watch-time elasticity, ad-load receptivity) from a title's features, each with a point-by-point breakdown. They never change the thresholds or the verdict." },
      { term: "PROXY / illustrative badge", def: "A label shown wherever a value is modeled or proxy-trained rather than measured. It means the number is illustrative, and any accuracy behind it is proxy accuracy, not real-world accuracy." },
      { term: "SUPPLIED > FITTED > FALLBACK", def: "The strict order used to resolve each modeled input: a value you type in wins; otherwise a fitted model if one is active; otherwise a deterministic illustrative fallback. No fitted model is active by default." },
      { term: "False Greenlight Rate", def: "The share of predicted GREENLIGHTs whose expected verdict was NEGOTIATE HARD or PASS - a capital-loss error, tracked as the primary risk metric when scoring a model." },
    ],
  },
  {
    group: "Under the Hood",
    id: "platform",
    blurb: "Platform plumbing: currencies, licensing, telemetry, and async jobs.",
    items: [
      { term: "Premium Original", def: "ORIGINAL_SERIES / ORIGINAL_FILM / CO_PRODUCTION. CPVH ceiling 0.18 USD." },
      { term: "Library Filler", def: "LICENSED_LIBRARY. CPVH ceiling 0.05 USD (cheaper content, stricter per-hour cap)." },
      { term: "Base Currency", def: "USD - the single currency all territorial costs are normalized into before comparison." },
      { term: "Exchange Rate", def: "A dated native-currency-to-USD rate used to normalize cost. Missing rate = the valuation is rejected." },
      { term: "License Terms", def: "A title's contract: license duration, exclusivity, windowing rules, and milestone payment schedule." },
      { term: "Windowing Rules", def: "The ordered release windows within a license (exclusive vs non-exclusive); their total cannot exceed the license duration." },
      { term: "Milestone Schedule", def: "The staged payment plan for an acquisition; drives the payback-horizon calculation." },
      { term: "Market Telemetry", def: "Live external signals (social sentiment, chart velocity, licensing inflation) by genre and territory that nudge valuations." },
      { term: "Subscriber Cluster", def: "A cohort of subscribers with a shared preference vector; titles are matched against these for audience fit." },
      { term: "Similarity Match", def: "pgvector cosine-similarity ranking of a title's Narrative DNA against subscriber-cohort preferences." },
      { term: "Ingestion", def: "Bringing titles into the pipeline - in bulk (CSV/JSON/PDF, up to 10,000 rows) or one at a time in the Studio." },
      { term: "Task Queue", def: "The async worker system (Celery + Redis) that runs long jobs: ingestion, extraction, audits, telemetry." },
      { term: "Job Status", def: "The lifecycle of an async job: PENDING, PROCESSING, COMPLETED, or FAILED." },
      { term: "Idempotency Key", def: "A key that makes a repeated ingestion request return the original result instead of creating duplicates." },
    ],
  },
  {
    group: "Acting on the Verdict",
    id: "decision-support",
    blurb: "Negotiation, what-if, and export tools for turning a verdict into action.",
    items: [
      { term: "Negotiation Playbook", def: "On a NEGOTIATE HARD / PASS title, the panel that gives a target purchase ceiling, the implied discount vs the ask, and per-guardrail counter-proposal talking points." },
      { term: "Target Purchase Ceiling", def: "The highest price at which every cost-correctable guardrail would pass - the number to negotiate the seller down to." },
      { term: "Implied Discount", def: "How far below the current ask the target ceiling sits, as a percentage - the size of the cut to ask for." },
      { term: "Counter-Proposal Lever", def: "A plain-language negotiation suggestion tied to a specific breached guardrail, marked correctable (fixable by price) or structural (needs a terms change)." },
      { term: "LTV Attribution", def: "The split of the LTV-to-Cost numerator into SVOD subscription value (retention) vs AVOD ad-yield value (advertising), so the multiple is not a black box." },
      { term: "Retained Subscribers", def: "The absolute churn impact - roughly how many subscribers a title keeps - shown next to the churn percentage. A modeled estimate." },
      { term: "What-If Sensitivity", def: "Sliders on the title page that recompute the verdict under alternate cost / viewership / churn assumptions. A preview only - never saved." },
      { term: "Scenario Preview", def: "A what-if result; clearly labeled 'not saved' because it never changes the stored record." },
      { term: "Greenlight Memo", def: "A one-page printable executive brief (scorecard, checks, playbook, sign-off block) exported from the title page via the browser's Save-as-PDF." },
      { term: "Model Version Catalog", def: "The Backtest Studio list of every immutable model version with its weights and date, where an authorized user can roll back to a prior version." },
      { term: "Rollback", def: "Re-activating a previous model version. Versions are immutable, so rollback just flips which one is active; recorded in the audit log." },
      { term: "Batch Slate Ingestion", def: "Uploading a CSV/JSON catalog of titles in one go via the Asset Studio's Batch Slate tab, processed asynchronously with an accepted/rejected summary." },
      { term: "Pitch Auto-Fill", def: "Dropping a pitch/script PDF on the Asset Studio form to pre-fill the title, synopsis, genre, and budget for review - best-effort, never auto-submitted." },
      { term: "Shorthand Amount", def: "Analyst budget shorthand the cost field accepts: 12 Cr, 3 Lakh, 1.5M, 500k - expanded to a full number with a live preview." },
    ],
  },
];

const GLOSSARY_COUNT = GLOSSARY.reduce((n, g) => n + g.items.length, 0);

// --------------------------------------------------------------------------- //
// Tab bodies
// --------------------------------------------------------------------------- //
function OverviewTab() {
  return (
    <div className="space-y-8">
      <WalkthroughVideo />

      <div className="space-y-3 text-sm leading-relaxed text-slate-300">
        <p>
          <span className="font-medium text-slate-100">In one sentence:</span> CineROI AI
          is a credit check for content deals. You hand it a title and the price
          on the table; it hands back a clear answer, backed by numbers anyone
          can follow.
        </p>
        <p>
          Every title gets exactly one of three answers to the question
          {" "}<span className="font-medium text-slate-100">&quot;should we buy this, haggle, or walk away?&quot;</span>
          There is no jargon you need to know to read the result - the system
          spells out, in dollars and plain sentences, why it landed where it did.
          This guide shows you the whole thing with real titles and real math.
        </p>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">The journey of one title</h3>
        <ol className="ml-4 list-decimal space-y-2 text-sm text-slate-300 marker:text-emerald-400">
          <li><span className="font-medium text-slate-100">Ingest</span> - a title comes in: one at a time in the Asset Studio, a whole slate via CSV/JSON, or by dropping a pitch PDF that auto-fills the form.</li>
          <li><span className="font-medium text-slate-100">Understand it</span> - the system reads the script and deal to size up the story, the mood, the strength of the cast, and the scale of the production.</li>
          <li><span className="font-medium text-slate-100">Match the audience</span> - it checks how well the title fits what our different subscriber groups actually like to watch.</li>
          <li><span className="font-medium text-slate-100">Run the money checks</span> - the four checks on the next tab, all in US dollars so every deal is judged the same way.</li>
          <li><span className="font-medium text-slate-100">Decide</span> - GREENLIGHT, NEGOTIATE HARD, or PASS, with the reasoning spelled out.</li>
          <li><span className="font-medium text-slate-100">Keep itself honest</span> - later, it compares what it predicted to what actually happened, and tunes itself to get better.</li>
        </ol>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">The three answers</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-emerald-800/50 bg-emerald-500/10 p-4">
            <Verdict kind="GREENLIGHT" />
            <p className="mt-2 text-xs text-slate-400">All checks pass. Buy it as proposed.</p>
          </div>
          <div className="rounded-lg border border-amber-800/50 bg-amber-500/10 p-4">
            <Verdict kind="NEGOTIATE HARD" />
            <p className="mt-2 text-xs text-slate-400">Good title, wrong price. There is a lower price at which it clears - go haggle.</p>
          </div>
          <div className="rounded-lg border border-rose-800/50 bg-rose-500/10 p-4">
            <Verdict kind="PASS" />
            <p className="mt-2 text-xs text-slate-400">A problem no price can fix. Walk away.</p>
          </div>
        </div>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Where you do things in the portal</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Card title="Dashboard">The whole portfolio at a glance - headline numbers up top and a sortable list of every title with its verdict. Search and filter to find anything fast.</Card>
          <Card title="Asset Studio">Where you evaluate a title - type one in, upload a whole catalog at once, or drop a pitch PDF and let it fill the form. Press one button to get the verdict.</Card>
          <Card title="Title page">The full story on one title - the four checks, a price to negotiate to, &quot;what if&quot; sliders to test scenarios, the deal-stage tracker, the full history, and a one-page PDF to take to a meeting.</Card>
          <Card title="Backtest Studio">Where we check how accurate the system has been (predicted vs what really happened), tune it up when needed, and record the executive sign-offs big deals require.</Card>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          New here? The <span className="text-emerald-400">Features &amp; How-To</span> tab has a step-by-step recipe for every one of these.
        </p>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Common questions</h3>
        <div className="space-y-2">
          {[
            ["Why did my title get a PASS?", "Because at least one failure can't be fixed by paying less - almost always that it doesn't keep subscribers from cancelling. The title page spells out the single biggest reason in plain words."],
            ["What's the difference between NEGOTIATE HARD and PASS?", "NEGOTIATE HARD means the only problems are price problems - there's a lower price where the deal works, so go haggle. PASS means something is wrong that no discount can fix, so there's no deal to be had."],
            ["What counts as a good cost-per-hour?", "The lower the better. The limit is $0.18 per hour for premium originals and $0.05 per hour for cheaper library titles. For example, a title that costs $42M and is watched 250M hours is $0.168/hour - just under the line."],
            ["Why do some greenlights need two executives to approve?", "Only the big ones. Any 'buy' decision above $25M needs sign-off from both the Chief Content Officer and the CFO before it's final - a second pair of eyes on a large commitment."],
            ["What if I don't know the viewing hours?", "Leave it blank. The system estimates how many hours a title will be watched from its budget and talent, so it can still work out the cost-per-hour."],
            ["Are these real numbers?", "The decision math - the four checks, the final verdict, the accuracy tracking, and the approvals - is the real engine. In this demo, the 'read the script' part and a few modeled inputs use fixed stand-in values so the whole thing runs on a laptop with no outside services."],
            ["Can the rules (the lines titles must clear) be changed?", "They're part of a saved 'model version.' When the model is re-tuned it saves a brand-new version rather than editing the old one, so every past decision can always be reproduced exactly as it was made."],
            ["How do I know what price to negotiate to?", "Open any NEGOTIATE HARD title. The Negotiation Playbook gives you a target price to aim for, how big a discount that is versus the asking price, and talking points for each thing that's holding the deal back."],
            ["Can I test 'what if the price or audience were different'?", "Yes. The title page has sliders for cost, viewership, and subscriber impact. Drag them and the verdict recalculates live. It's a sandbox - it never changes the saved record. (Set every slider back to 100% to see the official result.)"],
            ["Can I bring in a whole catalog at once?", "Yes. The Asset Studio has a Batch Slate tab that takes a spreadsheet or file of many titles in one upload. You can also drop a single pitch PDF and it fills the form for you to review."],
            ["How do I get a one-pager for a committee meeting?", "On any title page, click 'Export Greenlight Memo (PDF).' It opens a clean, print-ready one-page brief - the verdict, the four checks, the negotiation target, and a sign-off box - that you can save as a PDF."],
            ["Can someone overrule the system, and is that tracked?", "Yes - a Content Buyer, CCO, or CFO can override the verdict when their judgment should win. They must type a reason, and the change is recorded permanently in the title's history, which anyone can review."],
          ].map(([q, a]) => (
            <details key={q} className="group rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <summary className="cursor-pointer list-none font-medium text-slate-100 marker:content-none">
                <span className="mr-2 text-emerald-400 group-open:hidden">+</span>
                <span className="mr-2 hidden text-emerald-400 group-open:inline">-</span>
                {q}
              </summary>
              <p className="mt-2 pl-5 text-sm text-slate-400">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

/** One guardrail explained for a non-financial reader: rule + a real worked number. */
function GuardrailExplainer({
  n,
  name,
  question,
  formula,
  line,
  worked,
  result,
  resultOk,
}: {
  n: number;
  name: string;
  question: string;
  formula: string;
  line: React.ReactNode;
  worked: React.ReactNode;
  result: string;
  resultOk: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h3 className="text-base font-semibold text-slate-100">
        Guardrail {n}: {name}
      </h3>
      <p className="mt-1 text-sm text-slate-300">
        <span className="font-medium text-slate-100">The question it answers: </span>
        {question}
      </p>
      <p className="mt-2 text-sm text-slate-400">
        <span className="font-medium text-slate-300">The rule: </span>
        {line}
      </p>
      <Formula>{formula}</Formula>
      <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Worked with a real title
        </p>
        <div className="mt-1 text-sm text-slate-300">{worked}</div>
        <p className={"mt-2 text-sm font-medium " + (resultOk ? "text-emerald-300" : "text-rose-300")}>
          {resultOk ? "PASS - " : "BREACH - "}
          {result}
        </p>
      </div>
    </div>
  );
}

function GuardrailsTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm leading-relaxed text-slate-300">
        <p>
          Think of it like a bank running four checks before approving a loan.
          Before we commit money to a title, the engine runs four money checks.
          A title has to clear all four to get a straight &quot;yes.&quot; Each check
          below shows the plain question it answers, the one line it must not
          cross, and the <span className="font-medium text-slate-100">actual arithmetic</span> from
          a real title in the system - so you can see exactly where the number
          comes from.
        </p>
        <p className="mt-2 text-slate-400">
          Every amount is first converted to US dollars, so a title bought in
          rupees and one bought in euros are judged on the very same scale.
        </p>
      </div>

      <GuardrailExplainer
        n={1}
        name="Cost per Viewing Hour (CPVH)"
        question="How much are we paying for each hour an audience actually watches? Cheaper per hour is better value."
        formula="CPVH  =  Cost (in USD)  /  Projected Viewing Hours"
        line={<>Stay at or below <span className="text-emerald-300">$0.18 per hour</span> for premium originals, or <span className="text-emerald-300">$0.05 per hour</span> for cheaper library titles. Go over the line and it&apos;s a breach.</>}
        worked={
          <>
            <span className="font-medium text-slate-100">Aurora Protocol</span> cost
            {" "}<span className="text-slate-100">$42,000,000</span> and is expected to be
            watched for <span className="text-slate-100">250,000,000</span> hours.
            <div className="mt-1 font-mono text-xs text-emerald-300">
              $42,000,000 &divide; 250,000,000 hours = $0.168 per hour
            </div>
          </>
        }
        result="$0.168 is just under the $0.18 ceiling. Good value per hour."
        resultOk={true}
      />

      <GuardrailExplainer
        n={2}
        name="Return on Spend (LTV-to-Cost)"
        question="For every $1 we put in, how many dollars of value come back over the title's life? Higher is better."
        formula="Return  =  Total modeled value  /  Cost (in USD)"
        line={<>Must return at least <span className="text-emerald-300">$3.20 for every $1 spent</span> (written &quot;3.2x&quot;). Below that is a breach.</>}
        worked={
          <>
            <span className="font-medium text-slate-100">The Ledger</span> cost
            {" "}<span className="text-slate-100">$9,500,000</span>. Its modeled value
            (subscribers it keeps + advertising it earns) works out to about
            {" "}<span className="text-slate-100">$27,550,000</span>.
            <div className="mt-1 font-mono text-xs text-rose-300">
              $27,550,000 &divide; $9,500,000 = 2.9x
            </div>
          </>
        }
        result="2.9x is below the 3.2x hurdle. It would clear if the price were lower - so this breach is fixable by negotiating."
        resultOk={false}
      />

      <GuardrailExplainer
        n={3}
        name="Keeps Subscribers (Churn Mitigation)"
        question="Does having this title stop people from cancelling their subscription?"
        formula="Churn % = base rate + asset type + pedigree + production scale + exclusivity + market buzz + genre affinity + content format"
        line={
          <>
            The churn number is <span className="text-slate-100">calculated</span> by adding up
            small contributions from the title&apos;s features (illustrative coefficients, tuned
            to the demo titles) - unless a buyer types a known figure, which is then used
            exactly. It must keep at least{" "}
            <span className="text-emerald-300">1.5% of subscribers</span> from cancelling each
            month; below that is a breach. If it lands within 0.05% of the 1.5% line, the
            scorecard shows a &quot;Borderline Sensitivity&quot; note (it never changes the
            verdict).
          </>
        }
        worked={
          <>
            <span className="font-medium text-slate-100">Vintage Reruns Vol. 7</span> is a cheap
            library title with low pedigree and no exclusivity, so the model lands at only
            {" "}<span className="text-slate-100">0.81%</span> a month.
            <div className="mt-1 font-mono text-xs text-rose-300">
              0.81% &lt; 1.5% required
            </div>
          </>
        }
        result="0.81% misses the 1.5% floor. Important: paying less does NOT make a title more loved - so this breach can't be fixed by negotiating. One of these forces a PASS."
        resultOk={false}
      />

      <GuardrailExplainer
        n={4}
        name="Pays for Itself in Time (Payback Horizon)"
        question="How many months until the title earns back what we paid for it?"
        formula="Payback  =  first month the running total turns positive"
        line={<>Target <span className="text-emerald-300">9 to 12 months</span>. Longer than 12 months is a breach.</>}
        worked={
          <>
            <span className="font-medium text-slate-100">Aurora Protocol</span> earns back
            its cost by <span className="text-slate-100">month 11</span>.
            <div className="mt-1 font-mono text-xs text-emerald-300">
              11 months &le; 12-month limit
            </div>
          </>
        }
        result="Month 11 is inside the 9-12 month window."
        resultOk={true}
      />

      <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 p-4 text-sm text-slate-300">
        <p className="font-medium text-emerald-300">The one idea that drives every verdict: can a lower price fix it?</p>
        <p className="mt-2">
          Three of the four checks - cost per hour, return on spend, and payback -
          all get <span className="font-medium text-slate-100">better when we pay less</span>. So if
          only those fail, the title isn&apos;t bad - the price is wrong. That&apos;s a
          <span className="font-medium text-amber-300"> NEGOTIATE HARD</span>.
        </p>
        <p className="mt-2">
          But &quot;keeps subscribers&quot; is about how good the title is, not its price.
          No discount makes a show more binge-worthy. So if that one fails, no
          deal works and the answer is <span className="font-medium text-rose-300">PASS</span>.
        </p>
      </div>
    </div>
  );
}

function ExampleBlock({
  title,
  subtitle,
  verdict,
  cost,
  checks,
  takeaway,
  ceiling,
  governance,
}: {
  title: string;
  subtitle: string;
  verdict: "GREENLIGHT" | "NEGOTIATE HARD" | "PASS";
  cost: string;
  checks: { label: string; plain: string; math: string; verdict: "pass" | "breach" }[];
  takeaway: string;
  ceiling?: string;
  governance?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        <Verdict kind={verdict} />
      </div>
      <p className="mb-3 text-sm text-slate-400">
        <span className="text-slate-500">Normalized cost:</span> {cost}
      </p>
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4">
        {checks.map((c) => (
          <CheckLine key={c.label} {...c} />
        ))}
      </div>
      {ceiling ? (
        <p className="mt-3 text-sm text-slate-400">
          <span className="text-slate-500">Suggested purchase ceiling:</span>{" "}
          <span className="text-emerald-300">{ceiling}</span> - the most you could pay and still clear the cost-sensitive checks.
        </p>
      ) : null}
      {governance ? (
        <p className="mt-1 text-sm text-amber-300">{governance}</p>
      ) : null}
      <div className="mt-3 rounded-md border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-200">
        <span className="font-semibold">The takeaway: </span>{takeaway}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// How Numbers Are Calculated tab
// --------------------------------------------------------------------------- //

/** A calculation block: the formula, the rule/threshold, and a worked number. */
function CalcBlock({
  title,
  formula,
  rule,
  worked,
}: {
  title: string;
  formula: string;
  rule?: React.ReactNode;
  worked?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      <Formula>{formula}</Formula>
      {rule ? <p className="mt-2 text-sm text-slate-400">{rule}</p> : null}
      {worked ? (
        <div className="mt-2 rounded-md border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-300">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Worked:{" "}
          </span>
          {worked}
        </div>
      ) : null}
    </div>
  );
}

function CalculationsTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm leading-relaxed text-slate-300">
        <p>
          This is the exact math behind every number you see. It helps to think of it as
          two layers.
        </p>
        <p className="mt-2">
          <span className="font-medium text-slate-100">Layer A - the drivers:</span> a
          title&apos;s modeled economics (its lifetime value, how many subscribers it keeps,
          its ad potential, its payment schedule). For ingested titles these come from the
          submitted deal; in the Asset Studio they are derived from what you type; in
          production a financial-modeling pipeline and an NLP model supply them.
        </p>
        <p className="mt-2">
          <span className="font-medium text-slate-100">Layer B - the verdict math:</span>{" "}
          the fixed formulas below that turn those drivers into the four checks and the
          final answer. This layer never changes - the same arithmetic runs every time.
        </p>
      </div>

      <SectionHead note="Done once, up front, so every deal is judged on the same scale.">
        Step 1 - Convert the cost to US dollars
      </SectionHead>
      <CalcBlock
        title="Currency normalization"
        formula="Normalized cost (USD) = native cost x exchange rate"
        rule={<>Uses the dated rate; if the exact date is missing it falls back to the latest available rate. Rounded to 2 decimals.</>}
        worked={<>Vintage Reruns: EUR 1,200,000 x 1.09 = <span className="text-emerald-300">$1,308,000</span>.</>}
      />

      <SectionHead note="The four checks. A title must clear all four for a straight GREENLIGHT.">
        Step 2 - The four guardrails
      </SectionHead>
      <CalcBlock
        title="1. Cost per Viewing Hour (CPVH)"
        formula="CPVH = Cost (USD) / Projected Viewing Hours"
        rule={<>Must be at or below <span className="text-emerald-300">$0.18/hour</span> (premium) or <span className="text-emerald-300">$0.05/hour</span> (library). Over the line = breach. Correctable by a lower price.</>}
        worked={<>Aurora: 42,000,000 / 250,000,000 = <span className="text-emerald-300">$0.168</span> (PASS). The Ledger: 9,500,000 / 40,000,000 = <span className="text-rose-300">$0.2375</span> (BREACH).</>}
      />
      <CalcBlock
        title="2. Return on Spend (LTV-to-Cost)"
        formula="Multiple = ( (Churn Value x LTV) + (Elasticity x CPM x Ad Impressions) ) / Cost"
        rule={<>The first bracket is subscription value, the second is advertising value; their sum is the total modeled value. CPM and LTV are first weighted by the title&apos;s territories (see Step 3). Must be <span className="text-emerald-300">3.2x or higher</span>. Correctable by a lower price.</>}
        worked={<>The Ledger: total value approx $27,550,000; 27,550,000 / 9,500,000 = <span className="text-rose-300">2.9x</span> (BREACH, below 3.2x).</>}
      />
      <CalcBlock
        title="3. Keeps Subscribers (Churn Mitigation)"
        formula="Churn % = base rate + asset type + pedigree + production scale + exclusivity + market buzz + genre affinity + content format"
        rule={<>The monthly churn-reduction % is <span className="text-slate-100">calculated</span> by adding small, explained contributions from the title&apos;s features, then capped between 0.10% and 5.00% (illustrative coefficients, tuned to the demo titles). A title with no market-buzz data or an unlisted genre uses a neutral default rather than zero, so a data gap never unfairly forces a PASS. A buyer can instead <span className="text-slate-100">supply</span> a known figure, which is used exactly. Must be at least <span className="text-emerald-300">1.5%</span>; below = breach. A number within 0.05% of 1.5% shows a borderline note (it never changes the verdict). <span className="text-rose-300">Not correctable</span> - no price change makes a title stickier, so one churn breach forces a PASS.</>}
        worked={<>Vintage Reruns: model-computed 0.81% &lt; 1.5% -&gt; <span className="text-rose-300">BREACH</span> (non-correctable). The Ledger: 1.60% &ge; 1.5% -&gt; PASS.</>}
      />
      <CalcBlock
        title="4. Pays for Itself (Payback Horizon)"
        formula="First month where (monthly margin x month) - cost paid so far turns positive"
        rule={<>Walked month-by-month over the real milestone payment schedule, not a lump sum. Target <span className="text-emerald-300">9-12 months</span>; over 12 = breach. Correctable by a lower price.</>}
        worked={<>Aurora: 11 months (PASS). The Ledger: 15 months (BREACH, over 12).</>}
      />

      <SectionHead note="Market conditions nudge the return math up or down by territory.">
        Step 3 - Territory weighting (feeds the return check)
      </SectionHead>
      <CalcBlock
        title="Per-territory multipliers, then averaged"
        formula="cpm_weight = avg(licensing inflation);  ltv_weight = avg(1 + chart velocity / 100)"
        rule={<>For each target territory the title&apos;s genre telemetry gives a CPM multiplier and an LTV multiplier; they are averaged across territories. A territory with no data contributes a neutral 1. Then weighted CPM = CPM x cpm_weight and weighted LTV = LTV x ltv_weight.</>}
      />

      <SectionHead note="How the four results combine into one answer.">
        Step 4 - The verdict and the headline reason
      </SectionHead>
      <CalcBlock
        title="Shortfall magnitude (ranks breaches on one scale)"
        formula="Shortfall = | value - threshold | / threshold"
        rule={<>Computed for each breached check so they are comparable. The breach with the largest shortfall is the <span className="text-slate-100">dominant factor</span> headlined on a PASS or NEGOTIATE HARD.</>}
        worked={<>The Ledger CPVH: |0.2375 - 0.18| / 0.18 = <span className="text-slate-100">0.319</span>.</>}
      />
      <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 p-4 text-sm text-slate-300">
        <p className="font-medium text-emerald-300">The verdict rule</p>
        <ul className="mt-2 ml-4 list-disc space-y-1 text-slate-400 marker:text-emerald-400">
          <li><span className="text-emerald-300">GREENLIGHT</span> - zero breaches.</li>
          <li><span className="text-amber-300">NEGOTIATE HARD</span> - one or more breaches, and every one is correctable (a lower price fixes it).</li>
          <li><span className="text-rose-300">PASS</span> - at least one breach is non-correctable (churn), or the data was too incomplete to classify.</li>
        </ul>
      </div>

      <SectionHead note="For a NEGOTIATE HARD, the exact price to aim for.">
        Step 5 - The negotiation target
      </SectionHead>
      <CalcBlock
        title="Target purchase ceiling and implied discount"
        formula="CPVH ceiling = cost x (0.18 / CPVH);  LTV ceiling = cost x (multiple / 3.2);  target = the smaller one"
        rule={<>The highest price at which the price-driven checks would pass is the smaller of the two ceilings. The implied discount is (ask - target) / ask x 100.</>}
        worked={<>The Ledger: CPVH ceiling 9,500,000 x (0.18/0.2375) = <span className="text-emerald-300">$7,200,000</span>; LTV ceiling 9,500,000 x (2.9/3.2) = $8,609,375; the binding target is <span className="text-emerald-300">$7,200,000</span>, a <span className="text-emerald-300">24.2%</span> discount off the $9.5M ask.</>}
      />

      <SectionHead note="Extra context figures shown on the scorecard.">
        Supporting numbers
      </SectionHead>
      <CalcBlock
        title="Retained subscribers (a modeled estimate)"
        formula="Retained = modeled cohort size x (churn % / 100)"
        rule={<>The modeled cohort size, when not supplied, is one modeled subscriber per whole USD of cost. Always labeled as a derived figure; it never affects the verdict.</>}
      />
      <CalcBlock
        title="Model accuracy (MAPE) and self-tuning"
        formula="MAPE = average of | (actual - predicted) / actual | x 100"
        rule={<>The backtest accuracy metric; pairs with a zero actual are excluded. Lower is better. Above 10% triggers calibration, which re-tunes the two feature weights (they always sum to 1.00) and forks a new, immutable model version so past decisions stay reproducible.</>}
      />
      <CalcBlock
        title="Estimated viewing hours (Asset Studio, when left blank)"
        formula="hours = cost / ( ceiling x (0.70 + pedigree/10 x 0.25) )"
        rule={<>Only used when you do not supply viewing hours. It targets a cost-per-hour at 70-95% of the ceiling (stronger titles higher), so a quality title is not failed just for a missing input. The seeded demo titles use real stored hours, not this estimate.</>}
        worked={<>$10M premium original, pedigree 8: target CPVH 0.18 x 0.90 = 0.162; hours = 10,000,000 / 0.162 approx 61.7M.</>}
      />

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-500">
        Every figure uses exact decimal arithmetic (no floating-point drift). CPVH rounds to
        4 decimals, money to 2, the discount to 1, and MAPE to 2. For the full technical
        reference see the Calculations Reference document in the repository.
      </div>
    </div>
  );
}

/** A single numbered arithmetic step in the step-by-step walkthrough. */
function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-slate-800 py-3 last:border-b-0">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-xs font-bold text-emerald-950">
        {n}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-100">{title}</p>
        <div className="mt-1 text-sm text-slate-400">{children}</div>
      </div>
    </div>
  );
}

function WalkthroughTheLedger() {
  return (
    <div className="rounded-xl border border-amber-800/40 bg-amber-500/[0.04] p-5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-slate-100">
          Follow the money, one step at a time: The Ledger
        </h3>
        <Verdict kind="NEGOTIATE HARD" />
      </div>
      <p className="mb-4 text-sm text-slate-400">
        Here is one real title taken from the raw deal all the way to the final
        answer, with every number shown. Nothing is hidden - if you can read a
        bank statement, you can read this.
      </p>

      <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-4">
        <Step n={1} title="Start with the deal on the table">
          We are offered <span className="text-slate-100">The Ledger</span>, an original
          film, for <span className="text-slate-100">$9,500,000</span>. We expect it to be
          watched for <span className="text-slate-100">40,000,000</span> hours. It is a
          US-dollar deal, so no currency conversion is needed (the amount is already
          what we compare on).
        </Step>

        <Step n={2} title="Check 1 - what are we paying per hour watched?">
          Divide the cost by the hours:
          <div className="mt-1 font-mono text-xs text-slate-300">
            $9,500,000 &divide; 40,000,000 hours = <span className="text-rose-300">$0.2375 per hour</span>
          </div>
          The ceiling for a premium original is $0.18/hour. $0.2375 is over it, so this
          check <span className="text-rose-300">fails</span> - but it&apos;s a price problem:
          pay less, and the per-hour cost drops.
        </Step>

        <Step n={3} title="Check 2 - how many dollars come back per dollar spent?">
          The engine totals the value the title creates (subscribers it keeps plus
          advertising it earns): about <span className="text-slate-100">$27,550,000</span>. Divide by cost:
          <div className="mt-1 font-mono text-xs text-slate-300">
            $27,550,000 &divide; $9,500,000 = <span className="text-rose-300">2.9x</span>
          </div>
          The hurdle is 3.2x. 2.9x is under it, so this check
          <span className="text-rose-300"> fails</span> - again a price problem, because a
          smaller cost makes the same value go further.
        </Step>

        <Step n={4} title="Check 3 - does it keep subscribers from cancelling?">
          The Ledger is modeled to cut monthly cancellations by
          {" "}<span className="text-slate-100">1.6%</span>. The floor is 1.5%.
          <div className="mt-1 font-mono text-xs text-emerald-300">
            1.6% &ge; 1.5% required -&gt; PASS
          </div>
          This is the check a discount can&apos;t influence - and it passes, which is what
          keeps the title alive.
        </Step>

        <Step n={5} title="Check 4 - how long until it pays for itself?">
          At its current price it earns back the cost in
          {" "}<span className="text-slate-100">15 months</span>. The limit is 12.
          <div className="mt-1 font-mono text-xs text-rose-300">
            15 months &gt; 12-month limit -&gt; fails
          </div>
          Still a price problem: a cheaper title pays back sooner.
        </Step>

        <Step n={6} title="Add it up into one answer">
          Three checks failed, one passed. But look at WHICH failed: cost-per-hour,
          return, and payback are <span className="text-slate-100">all fixable by paying less</span>.
          The one check that a discount can&apos;t fix - keeping subscribers - passed. So
          this isn&apos;t a bad title; it&apos;s a <span className="font-medium text-amber-300">good title at the wrong price</span>.
          The verdict is <span className="font-medium text-amber-300">NEGOTIATE HARD</span>.
        </Step>

        <Step n={7} title="Get the price to aim for">
          The engine does the math in reverse to find the highest price at which all the
          price-driven checks would pass: <span className="text-emerald-300">$7,200,000</span>.
          <div className="mt-1 font-mono text-xs text-slate-300">
            ($9,500,000 - $7,200,000) &divide; $9,500,000 = ~24% discount to ask for
          </div>
          The buyer walks into the room with a target: negotiate the seller down to about
          $7.2M (roughly a 24% cut) and the deal clears.
        </Step>
      </div>
    </div>
  );
}

function ExamplesTab() {
  return (
    <div className="space-y-6">
      <p className="text-sm leading-relaxed text-slate-300">
        First, one title walked through end to end with every calculation shown.
        Then three real titles - one of each possible answer - with the exact
        figures the system produces. You can open any of these in the dashboard
        and see the same numbers.
      </p>

      <WalkthroughTheLedger />

      <div className="pt-2">
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-emerald-400">
          One of each answer, with real numbers
        </h3>
        <p className="mb-4 text-sm text-slate-400">
          Every row shows the title&apos;s number, the line it had to clear, and whether
          it passed. These are live figures from the seeded demo titles.
        </p>
      </div>

      <ExampleBlock
        title="Aurora Protocol"
        subtitle="Original Series - $42,000,000 - watched 250,000,000 hours"
        verdict="GREENLIGHT"
        cost="$42,000,000 (US dollars, no conversion)"
        checks={[
          { label: "Cost per hour", plain: "$42,000,000 / 250,000,000 hours = $0.168/hour, just under the $0.18 ceiling.", math: "$0.168 <= $0.18", verdict: "pass" },
          { label: "Return on spend", plain: "Returns $3.80 of value for every $1 spent - above the 3.2x hurdle.", math: "3.8x >= 3.2x", verdict: "pass" },
          { label: "Keeps subscribers", plain: "Cuts monthly cancellations by 2.1%, above the 1.5% floor.", math: "2.1% >= 1.5%", verdict: "pass" },
          { label: "Pays for itself", plain: "Earns its cost back by month 11, inside the 9-12 target.", math: "11 <= 12", verdict: "pass" },
        ]}
        governance="Because this is a GREENLIGHT above $25M, it also needs sign-off from BOTH the Chief Content Officer and the CFO before it is final."
        takeaway="All four checks pass, so the engine says acquire it as proposed. The only extra step is the dual executive sign-off that any greenlight over $25M requires."
      />

      <ExampleBlock
        title="The Ledger"
        subtitle="Original Film - $9,500,000 - watched 40,000,000 hours"
        verdict="NEGOTIATE HARD"
        cost="$9,500,000 (US dollars, no conversion)"
        checks={[
          { label: "Cost per hour", plain: "$9,500,000 / 40,000,000 hours = $0.2375/hour, over the $0.18 ceiling. Fixable by paying less.", math: "$0.2375 > $0.18", verdict: "breach" },
          { label: "Return on spend", plain: "Returns 2.9x, just under the 3.2x hurdle. Fixable by paying less.", math: "2.9x < 3.2x", verdict: "breach" },
          { label: "Keeps subscribers", plain: "Cuts cancellations by 1.6%, clearing the 1.5% floor.", math: "1.6% >= 1.5%", verdict: "pass" },
          { label: "Pays for itself", plain: "Takes 15 months at this price, over the 12-month limit. Fixable by paying less.", math: "15 > 12", verdict: "breach" },
        ]}
        ceiling="$7,200,000 (about a 24% discount off the $9.5M ask)"
        takeaway="Three checks fail, but every failure is a price problem - and the one check a discount can't fix (keeping subscribers) passes. So it's a good title at the wrong price: negotiate the seller down toward $7.2M and it clears."
      />

      <ExampleBlock
        title="Vintage Reruns Vol. 7"
        subtitle="Licensed Library - EUR 1,200,000 - watched 60,000,000 hours"
        verdict="PASS"
        cost="$1,308,000 (converted: EUR 1,200,000 x 1.09)"
        checks={[
          { label: "Cost per hour", plain: "$1,308,000 / 60,000,000 hours = $0.0218/hour, well under the stricter $0.05 library ceiling.", math: "$0.0218 <= $0.05", verdict: "pass" },
          { label: "Return on spend", plain: "Returns a strong 4.1x per dollar.", math: "4.1x >= 3.2x", verdict: "pass" },
          { label: "Keeps subscribers", plain: "Only cuts cancellations by 0.9%, below the 1.5% floor - and no price cut can change how sticky a title is.", math: "0.9% < 1.5%", verdict: "breach" },
          { label: "Pays for itself", plain: "Earns back in 8 months, well inside the window.", math: "8 <= 12", verdict: "pass" },
        ]}
        takeaway="Three checks pass and it's dirt cheap per hour - but the one failure is the one that matters most: it does not keep subscribers. That cannot be fixed by paying less, so there is no price at which this becomes a good deal. The answer is PASS - walk away."
      />

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
        <p className="font-medium text-slate-100">Notice the pattern across all three:</p>
        <ul className="mt-2 ml-4 list-disc space-y-1 text-slate-400 marker:text-emerald-400">
          <li><span className="text-emerald-300">GREENLIGHT</span> - all four checks pass.</li>
          <li><span className="text-amber-300">NEGOTIATE HARD</span> - some checks fail, but every failure is a price problem, so a lower price fixes it.</li>
          <li><span className="text-rose-300">PASS</span> - at least one failure is NOT about price (it does not keep subscribers), so no deal works.</li>
        </ul>
      </div>

      <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 p-4 text-sm text-slate-300">
        <span className="font-medium text-emerald-300">See it live: </span>
        open the <Link href="/dashboard" className="text-emerald-400 underline">Dashboard</Link>,
        click any of these titles, and the scorecard shows the very same numbers you
        just read.
      </div>
    </div>
  );
}
// --------------------------------------------------------------------------- //
// Features & How-To tab
// --------------------------------------------------------------------------- //

/** A numbered how-to with a heading, "when to use it", and ordered steps. */
function HowTo({
  title,
  where,
  what,
  steps,
  tip,
}: {
  title: string;
  where: string;
  what: string;
  steps: React.ReactNode[];
  tip?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-100">{title}</h3>
        <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
          {where}
        </span>
      </div>
      <p className="mb-3 text-sm text-slate-400">{what}</p>
      <ol className="ml-4 list-decimal space-y-1.5 text-sm text-slate-300 marker:text-emerald-400">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
      {tip ? (
        <p className="mt-3 rounded-md border border-emerald-800/40 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-200">
          <span className="font-semibold">Tip: </span>
          {tip}
        </p>
      ) : null}
    </div>
  );
}

function SectionHead({ children, note }: { children: React.ReactNode; note?: string }) {
  return (
    <div className="pt-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-emerald-400">
        {children}
      </h2>
      {note ? <p className="mt-1 text-sm text-slate-400">{note}</p> : null}
    </div>
  );
}

function FeaturesTab() {
  return (
    <div className="space-y-6">
      <p className="text-sm leading-relaxed text-slate-300">
        Every feature in the portal, as a simple &quot;I want to... here is how&quot;
        recipe. Four areas: the <span className="text-slate-100">Dashboard</span>,
        the <span className="text-slate-100">Asset Studio</span> (evaluate titles),
        the <span className="text-slate-100">Title page</span> (deep dive +
        decisions), and the <span className="text-slate-100">Backtest Studio</span>
        (accuracy + the model). You can start anywhere from the top navigation
        bar; the logo always returns to Home.
      </p>

      <SectionHead note="Your portfolio at a glance.">On the Dashboard</SectionHead>
      <HowTo
        title="See every title and its verdict"
        where="Dashboard"
        what="The command dashboard shows four KPI cards and a sortable grid of every title with its recommendation badge."
        steps={[
          <>Open <Link href="/dashboard" className="text-emerald-400 underline">Dashboard</Link> from the top nav.</>,
          <>Read the KPI cards: pipeline value, average LTV-to-Cost, risk exposure, and model accuracy.</>,
          <>Click any column header to sort (e.g. by LTV multiple or CPVH status).</>,
          <>Click a row to open that title&apos;s full evaluation.</>,
        ]}
        tip={<>Status badges use an icon + color + border (check / scale / X), so the verdict is readable even if you are color-blind.</>}
      />

      <SectionHead note="Turn a title and its deal terms into an instant executive scorecard.">
        In the Asset Studio
      </SectionHead>
      <HowTo
        title="Evaluate a single title"
        where="Asset Studio - Single Asset tab"
        what="Type one title's details and get a full scorecard - recommendation, four checks, radar, and payback - in seconds."
        steps={[
          <>Open <Link href="/studio" className="text-emerald-400 underline">Asset Studio</Link>; the Single Asset tab is selected by default.</>,
          <>Fill in Title, Asset Type, Cost &amp; Currency, and a Synopsis (the rest is optional).</>,
          <>Press <span className="font-medium text-slate-100">RUN ROI VALUATION</span>. The scorecard appears on the right.</>,
          <>Click <span className="font-medium text-slate-100">View Full Deep-Dive Analysis</span> to open the title page.</>,
        ]}
        tip={<>Not sure what to type? Click a Quick Preset to fill the whole form with a sample title and run it instantly.</>}
      />
      <HowTo
        title="Enter the budget in shorthand (Cr / Lakh / M / k)"
        where="Asset Studio - Cost field"
        what="The cost box understands analyst shorthand, so you never miscount zeros."
        steps={[
          <>In the Cost field, type amounts like <code className="text-emerald-300">12 Cr</code>, <code className="text-emerald-300">1.5M</code>, <code className="text-emerald-300">500k</code>, or <code className="text-emerald-300">3 Lakh</code>.</>,
          <>A live preview under the box shows the full number (e.g. &quot;120,000,000 USD&quot;) so you can confirm it.</>,
          <>Pick the matching currency (USD / INR / EUR / GBP); everything is normalized to USD before any check.</>,
        ]}
        tip={<>Plain numbers with commas work too - &quot;1,200,000&quot; is fine.</>}
      />
      <HowTo
        title="Auto-fill the form from a pitch / script PDF"
        where="Asset Studio - Drop-zone"
        what="Drop a pitch deck and the system reads the title, synopsis, genre, and budget for you to review."
        steps={[
          <>At the top of the Single Asset form, click the <span className="font-medium text-slate-100">&quot;Drop a script / pitch PDF&quot;</span> box and choose a PDF.</>,
          <>Wait a moment while it reads the document; recognized fields pre-fill automatically.</>,
          <>Review and edit every pre-filled field - nothing is submitted for you.</>,
          <>Press RUN ROI VALUATION when it looks right.</>,
        ]}
        tip={<>It is best-effort: a messy deck may fill only some fields. A short note tells you exactly what was pre-filled.</>}
      />
      <HowTo
        title="Ingest a whole slate at once (CSV / JSON)"
        where="Asset Studio - Batch Slate tab"
        what="Bring in a catalog of titles from a festival or a studio in one upload instead of typing them one by one."
        steps={[
          <>In the Asset Studio, switch to the <span className="font-medium text-slate-100">Batch Slate</span> tab.</>,
          <>New to the format? Click <span className="font-medium text-slate-100">Download CSV template</span> to get a ready-made file with the header row, every allowed value as a comment hint, and three example titles. Fill in your rows and remove the examples.</>,
          <>Choose the format (CSV or JSON), then upload a file or paste the contents. Each row needs at least a title name and a cost.</>,
          <>Press <span className="font-medium text-slate-100">Ingest slate</span>. A live indicator tracks the background job.</>,
          <>When it finishes, read the summary: how many rows were accepted vs rejected, with a reason per rejected row.</>,
        ]}
        tip={<>Rejected rows never block the batch - accepted + rejected always equals what you submitted.</>}
      />
      <HowTo
        title="Ask the chat assistant (data + how-to)"
        where="Any page - the chat button, bottom-right"
        what="A read-only assistant that explains your data and how to use the portal. It only reports what the platform already shows and never changes a decision."
        steps={[
          <>Click the chat button in the bottom-right corner of any page.</>,
          <>Ask a data question (e.g. <span className="font-medium text-slate-100">&quot;why did The Ledger get NEGOTIATE HARD?&quot;</span>) or a how-to/concept question (e.g. <span className="font-medium text-slate-100">&quot;how do I upload a slate?&quot;</span>, <span className="font-medium text-slate-100">&quot;what is CPVH?&quot;</span>).</>,
          <>On a title page it answers about that title automatically; elsewhere it uses the portfolio or your named title.</>,
          <>Each answer lists its sources (title scorecard, portfolio, or a help topic) so you can see it is grounded, not guessed.</>,
        ]}
        tip={<>It cannot override, greenlight, or change any number - those stay on the audited governance controls. If it does not have the answer, it says so rather than inventing one.</>}
      />

      <SectionHead note="Everything you can do on a single title's page.">
        On the Title page
      </SectionHead>
      <HowTo
        title="Read the full breakdown"
        where="Title page"
        what="The deep-dive page lays out the verdict, the metadata radar, the financial breakdown, and the plain-English explanation."
        steps={[
          <>Open a title from the Dashboard grid or the Studio&apos;s &quot;deep-dive&quot; link.</>,
          <>See the recommendation badge up top, then the radar (narrative / tone / pedigree / scale).</>,
          <>Expand the Financial Breakdown for CPVH, the LTV-to-Cost attribution split, churn, and the payback chart.</>,
          <>Read the Explanation panel for the dominant factor behind the verdict.</>,
        ]}
      />
      <HowTo
        title="Understand WHY the LTV multiple is what it is"
        where="Title page - Financial Breakdown"
        what="The opaque multiple is broken into the two value drivers behind it."
        steps={[
          <>Open the Financial Breakdown section.</>,
          <>Under LTV-to-Cost, read the attribution: <span className="text-slate-100">SVOD subscription value</span> (retention) vs <span className="text-slate-100">AVOD ad-yield value</span> (advertising).</>,
          <>The two add up to the total modeled value, divided by cost to give the multiple.</>,
        ]}
      />
      <HowTo
        title="Get a concrete negotiation target"
        where="Title page - Negotiation Playbook"
        what="When a title is NEGOTIATE HARD or PASS, the playbook tells you the exact price to aim for and gives talking points."
        steps={[
          <>Scroll to the <span className="font-medium text-slate-100">Negotiation Playbook</span> panel (shown for non-GREENLIGHT titles).</>,
          <>Read the <span className="text-slate-100">target purchase ceiling</span> (the price at which the deal clears) and the implied discount vs the current ask.</>,
          <>Use the per-guardrail counter-proposal levers as talking points, labeled correctable (price) or structural.</>,
        ]}
      />
      <HowTo
        title="Stress-test with What-If sliders"
        where="Title page - What-if sensitivity"
        what="Drag sliders to see how the verdict would change under different cost, viewership, or churn assumptions - without saving anything."
        steps={[
          <>Find the <span className="font-medium text-slate-100">What-if sensitivity</span> panel.</>,
          <>Drag the Cost, Viewership (bear/base/bull), or Churn sliders.</>,
          <>Watch the recommendation badge and the four metrics recompute live after you stop dragging.</>,
          <>Everything here is a <span className="text-slate-100">scenario preview - not saved</span>; the real record is untouched.</>,
        ]}
        tip={<>Set every slider to 100% to reproduce the official saved scorecard exactly.</>}
      />
      <HowTo
        title="Model a deal in the What-If Explorer"
        where="Title page - What-If Explorer tab"
        what="A read-only sandbox to set exact figures - acquisition cost, viewing hours, CPM, LTV, churn %, and even the guardrail thresholds - and watch the verdict recompute against the saved Baseline. Nothing is saved."
        steps={[
          <>Open a title and switch to the <span className="font-medium text-slate-100">What-If Explorer</span> tab.</>,
          <>Type exact values on the left (e.g. a seller&apos;s asking price in dollars, or a higher CPM). Each field shows the Baseline; blank means &quot;use Baseline&quot;.</>,
          <>Not sure what a field does? Hover the small <span className="font-medium text-slate-100">i</span> beside its label for what it is and how raising or lowering it moves the verdict.</>,
          <>Watch the right panel: each guardrail shows Baseline &rarr; Scenario with a PASS/BREACH badge, and a callout appears if the verdict would flip.</>,
          <>Try a preset - <span className="font-medium text-slate-100">Bear</span>, <span className="font-medium text-slate-100">Bull</span>, or <span className="font-medium text-slate-100">Target deal</span> (sets cost to the price that clears all correctable guardrails).</>,
          <>Click <span className="font-medium text-slate-100">Copy scenario link</span> to share the exact scenario - it lives in the URL, nothing is stored.</>,
        ]}
        tip={<>It is a sandbox: it never changes the saved scorecard, forks no model version, and is excluded from the Greenlight Memo. Thresholds you relax here are exploration only.</>}
      />
      <HowTo
        title="Override the recommendation (with a reason)"
        where="Title page - Override"
        what="An authorized executive can change the verdict when judgment should trump the model - the reason is logged forever."
        steps={[
          <>Click <span className="font-medium text-slate-100">Override recommendation</span>.</>,
          <>Pick the new status and type a mandatory business justification.</>,
          <>Press <span className="font-medium text-slate-100">Record override</span>. The verdict updates and the change is written to the audit log.</>,
        ]}
        tip={<>Only decision-making roles may override; others get a clear &quot;not permitted&quot; message.</>}
      />
      <HowTo
        title="Trace the full history (Audit Lineage)"
        where="Title page - Audit history"
        what="Compliance and legal can see every action taken on a decision, in order."
        steps={[
          <>Expand the <span className="font-medium text-slate-100">Audit history &amp; lineage</span> section.</>,
          <>Read the chronological timeline: valuation runs, overrides, and sign-offs, each with a before to after change where relevant.</>,
        ]}
      />
      <HowTo
        title="Export a Greenlight Memo (PDF)"
        where="Title page - Export"
        what="Produce a clean one-pager to take into an Investment / Greenlight Committee meeting."
        steps={[
          <>Click <span className="font-medium text-slate-100">Export Greenlight Memo (PDF)</span>.</>,
          <>Your browser&apos;s print dialog opens with a paper-friendly brief: financial summary, guardrail checks, negotiation playbook, and a sign-off block.</>,
          <>Choose &quot;Save as PDF&quot; (or print). The app chrome is hidden - only the memo prints.</>,
        ]}
      />

      <SectionHead note="High-budget greenlights need two executives to sign off.">
        Executive sign-off
      </SectionHead>
      <HowTo
        title="Clear a high-budget sign-off gate"
        where="Backtest Studio - Executive Sign-Off"
        what="A GREENLIGHT above $25M requires both the Chief Content Officer and the CFO to approve before it is final."
        steps={[
          <>Run an audit on a title in the <Link href="/backtest" className="text-emerald-400 underline">Backtest Studio</Link>; the Executive Sign-Off panel shows the required roles.</>,
          <>If sign-off is required, each outstanding role shows an <span className="font-medium text-slate-100">Approve as...</span> button.</>,
          <>Record each approval; once both CCO and CFO are in, the gate flips to <span className="text-emerald-300">Ready to finalize</span>.</>,
        ]}
        tip={<>Non-high-budget decisions show &quot;No sign-off required&quot; and are clear to finalize immediately.</>}
      />

      <SectionHead note="Measure the model's accuracy and keep it honest.">
        In the Backtest Studio
      </SectionHead>
      <HowTo
        title="Audit a prediction against reality"
        where="Backtest Studio"
        what="Enter what actually happened for a historical title and see how close the prediction was."
        steps={[
          <>Open <Link href="/backtest" className="text-emerald-400 underline">Backtest Studio</Link>.</>,
          <>Pick a title from the <span className="font-medium text-slate-100">Historical title</span> dropdown (titles with a stored prediction; the ID is shown to tell duplicates apart).</>,
          <>Enter the actual outcomes - CPVH, LTV-to-Cost, churn reduction, and payback horizon (months); the predicted values show read-only beside each, and any field left blank is skipped.</>,
          <>Press <span className="font-medium text-slate-100">Run audit</span> to see Predicted vs Actual and the overall Prediction Error (MAPE - lower is better).</>,
        ]}
      />
      <HowTo
        title="Re-tune the model (calibration)"
        where="Backtest Studio - Model Calibration"
        what="When accuracy drifts, auto-tune the feature weights - which forks a new immutable model version."
        steps={[
          <>After an audit, press <span className="font-medium text-slate-100">Request auto-tuning</span>.</>,
          <>If the error is above tolerance, the engine applies weight offsets and activates a new model version; otherwise it reports no change needed.</>,
          <>Read the applied offsets and the new version id in the result.</>,
        ]}
      />
      <HowTo
        title="Roll back to a prior model version"
        where="Backtest Studio - Model Version Catalog"
        what="If a calibration underperforms, re-activate a previous version. History is immutable, so nothing is lost."
        steps={[
          <>Find the <span className="font-medium text-slate-100">Model Version Catalog</span> panel: the active version plus every prior one with its weights and date.</>,
          <>On any non-active version, click <span className="font-medium text-slate-100">Roll back to this</span>.</>,
          <>The catalog refreshes with that version now active; the change is recorded in the audit log.</>,
        ]}
      />

      <SectionHead note="A self-running interactive deck that walks anyone through the product.">
        Share &amp; present
      </SectionHead>
      <HowTo
        title="Share the interactive overview deck"
        where="Anywhere - a browser link"
        what="A single self-contained HTML deck (12 slides) that tells the whole story: the problem, the credit-check analogy, a draggable live verdict, the four guardrails, the AI stack, and a button into this portal. No install, no login."
        steps={[
          <>Send the public link: <a href="https://vasistasandeep.github.io/GreenlightIQ" target="_blank" rel="noopener" className="text-emerald-400 underline">vasistasandeep.github.io/GreenlightIQ</a>. It opens fully interactive in any browser.</>,
          <>Navigate with the bottom bar (Home / prev / next / click any dot to jump) or the arrow keys; press <span className="font-medium text-slate-100">F</span> for full screen.</>,
          <>On the <span className="font-medium text-slate-100">Verdict Machine</span> slide, drag the acquisition price and watch the four checks and the verdict flip live.</>,
          <>The deck uses illustrative sample-slate figures - it is a demo, not production data.</>,
        ]}
        tip={<>The deck&apos;s &quot;Open the live demo portal&quot; button is off by default so a shared copy never links to a dead address. To light it up for a live demo, set <code className="text-emerald-300">PORTAL_URL</code> near the top of the deck&apos;s inline script to where the portal is reachable (a deployment, <code className="text-emerald-300">http://localhost:3000</code>, or a current ngrok URL), then push.</>}
      />
      <SectionHead note="How the engine's inputs are modeled - and why some numbers wear a PROXY badge.">
        Behind the scenes: the modeling layer
      </SectionHead>
      <HowTo
        title="Understand the Content Evaluation models (and the PROXY badge)"
        where="Title page - financial breakdown & valuation report"
        what="Some inputs the engine uses - projected viewing hours, churn, watch-time elasticity, ad-load receptivity - are produced by small, transparent models from a title's features, each shown as a point-by-point breakdown just like churn. Where a value is modeled or proxy-trained, it carries a PROXY / illustrative badge."
        steps={[
          <>Open any title&apos;s deep-dive and expand the <span className="font-medium text-slate-100">financial breakdown</span>. Alongside the churn breakdown you may see viewing-hours and engagement breakdown cards.</>,
          <>Each card lists the per-feature contributions that add up to the final number, so a modeled input is never a black box.</>,
          <>A <span className="font-medium text-slate-100">PROXY / illustrative</span> badge marks any value that came from a modeled or proxy-trained source rather than a measured real-world outcome.</>,
          <>Read the badge literally: it means the figure is illustrative, and any accuracy behind it is <span className="font-medium text-slate-100">proxy accuracy, not real-world accuracy</span>.</>,
        ]}
        tip={<>The models only produce the engine&apos;s <em>inputs</em>. The four guardrails, the verdict rule, and the governance gates are unchanged - and by default no fitted model is active, so the demo verdicts are exactly as described elsewhere in this guide. A value you type in always wins over any model (SUPPLIED &gt; FITTED &gt; FALLBACK).</>}
      />
      <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 p-4 text-sm text-slate-300">
        <span className="font-medium text-emerald-300">Fastest way to learn the app: </span>
        open the <Link href="/studio" className="text-emerald-400 underline">Asset Studio</Link>,
        click a preset, run a valuation, then click into the title&apos;s deep-dive
        and try the What-if sliders and the Greenlight Memo export.
      </div>
    </div>
  );
}

// Display order for the glossary groups: follows a user's journey through the
// product (what you enter -> how it is judged -> the answer -> what to do ->
// trust -> under the hood) rather than the internal data order.
const GLOSSARY_ORDER = [
  "inputs",
  "guardrails",
  "verdict",
  "scorecard",
  "decision-support",
  "governance",
  "model",
  "platform",
] as const;

const GLOSSARY_ORDERED: GlossaryGroup[] = [...GLOSSARY].sort(
  (a, b) => GLOSSARY_ORDER.indexOf(a.id as (typeof GLOSSARY_ORDER)[number]) -
    GLOSSARY_ORDER.indexOf(b.id as (typeof GLOSSARY_ORDER)[number]),
);

/** Render a definition/term with the matched query substring highlighted. */
function highlight(text: string, q: string): React.ReactNode {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark className="rounded bg-emerald-500/25 px-0.5 text-emerald-200">
        {text.slice(i, i + q.length)}
      </mark>
      {text.slice(i + q.length)}
    </>
  );
}

function GlossaryTab() {
  const [query, setQuery] = useState("");
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const q = query.trim().toLowerCase();

  // Apply the text filter, then the optional single-group filter.
  const groups = GLOSSARY_ORDERED.map((g) => ({
    ...g,
    items: q
      ? g.items.filter(
          (it) =>
            it.term.toLowerCase().includes(q) || it.def.toLowerCase().includes(q),
        )
      : g.items,
  }))
    .filter((g) => g.items.length > 0)
    .filter((g) => (activeGroup ? g.id === activeGroup : true));

  const shown = groups.reduce((n, g) => n + g.items.length, 0);

  // Jump to a group's anchor (and clear any single-group filter so it is visible).
  function jumpTo(id: string) {
    setActiveGroup((cur) => (cur === id ? null : id));
  }

  return (
    <div className="space-y-5">
      {/* Search + live count */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search terms (e.g. CPVH, governance, payback)..."
          aria-label="Search glossary terms"
          className="min-h-[44px] w-full max-w-sm rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 sm:min-h-0"
        />
        <span className="text-xs text-slate-500" role="status" aria-live="polite">
          {q || activeGroup ? `${shown} of ${GLOSSARY_COUNT} terms` : `${GLOSSARY_COUNT} terms in ${GLOSSARY_ORDERED.length} groups`}
        </span>
      </div>

      {/* Category chips: jump to / filter by a single group. */}
      <div className="flex flex-wrap gap-2" aria-label="Glossary categories">
        <button
          type="button"
          onClick={() => setActiveGroup(null)}
          aria-pressed={activeGroup === null}
          className={
            "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
            (activeGroup === null
              ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300"
              : "border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200")
          }
        >
          All
        </button>
        {GLOSSARY_ORDERED.map((g) => (
          <button
            key={g.id}
            type="button"
            onClick={() => jumpTo(g.id)}
            aria-pressed={activeGroup === g.id}
            className={
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
              (activeGroup === g.id
                ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300"
                : "border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200")
            }
          >
            {g.group}
          </button>
        ))}
      </div>

      {groups.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
          No terms match &ldquo;{query}&rdquo;.
        </p>
      ) : (
        groups.map((g) => (
          <section key={g.id} id={`glossary-${g.id}`} className="scroll-mt-20">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-emerald-400">
                {g.group}
              </h3>
              <span className="shrink-0 text-xs text-slate-600">
                {g.items.length} {g.items.length === 1 ? "term" : "terms"}
              </span>
            </div>
            <p className="mb-3 text-xs text-slate-500">{g.blurb}</p>
            <dl className="divide-y divide-slate-800 rounded-lg border border-slate-800 bg-slate-900/40">
              {g.items.map((it) => (
                <div key={it.term} className="grid grid-cols-1 gap-1 p-4 sm:grid-cols-[220px_1fr] sm:gap-4">
                  <dt className="font-semibold text-slate-100">{highlight(it.term, q)}</dt>
                  <dd className="text-sm text-slate-400">{highlight(it.def, q)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Page
// --------------------------------------------------------------------------- //
export default function GuidePage() {
  const [tab, setTab] = useState<TabId>("overview");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const isFirstTabEffect = useRef(true);
  const activeIndex = TABS.findIndex((t) => t.id === tab);

  // Keep the selected tab centered in the mobile scroll strip; skip the initial
  // mount so there is no jarring horizontal slide on first load.
  useEffect(() => {
    if (isFirstTabEffect.current) {
      isFirstTabEffect.current = false;
      return;
    }
    tabRefs.current[activeIndex]?.scrollIntoView({
      behavior: "smooth",
      inline: "center",
      block: "nearest",
    });
  }, [activeIndex]);

  // Roving arrow-key navigation (ArrowLeft/Right with wrap-around).
  function onTabKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    else return;
    e.preventDefault();
    setTab(TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100">
      <TopNav />

      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight">How CineROI AI Works</h1>
          <p className="mt-2 max-w-2xl text-slate-400">
            A plain-English guide for anyone - no finance or tech background
            needed. What it does, how it decides, and the real math behind every
            verdict, worked out step by step.
          </p>
        </div>

        {/* Tabs */}
        <div
          role="tablist"
          aria-label="Guide sections"
          className="mb-8 flex gap-2 overflow-x-auto scroll-smooth rounded-lg border border-slate-800 bg-slate-900/60 p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden snap-x sm:gap-1"
        >
          {TABS.map((t, i) => (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              role="tab"
              aria-selected={tab === t.id}
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => setTab(t.id)}
              onKeyDown={(e) => onTabKeyDown(e, i)}
              className={
                "flex-shrink-0 snap-start whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-colors sm:px-3 " +
                (tab === t.id
                  ? "bg-emerald-500 text-emerald-950"
                  : "text-slate-300 hover:bg-slate-800")
              }
            >
              {t.label}
            </button>
          ))}
        </div>

        <div role="tabpanel">
          {tab === "overview" ? <OverviewTab /> : null}
          {tab === "features" ? <FeaturesTab /> : null}
          {tab === "guardrails" ? <GuardrailsTab /> : null}
          {tab === "calculations" ? <CalculationsTab /> : null}
          {tab === "examples" ? <ExamplesTab /> : null}
          {tab === "glossary" ? <GlossaryTab /> : null}
        </div>

        <footer className="mt-12 border-t border-slate-800 pt-6 text-xs text-slate-500">
          <p>
            Note: in demo mode the Narrative DNA embedding and modeled financial
            drivers are deterministic placeholders so the stack runs with no
            external dependencies. The guardrail math, recommendation logic,
            backtesting, and governance are genuine working logic.
          </p>
        </footer>
      </div>
    </div>
  );
}