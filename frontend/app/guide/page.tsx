"use client";

import { useState } from "react";
import Link from "next/link";

/**
 * In-portal "How It Works" guide (`/guide`) - tabbed reference.
 *
 * Tabs: Overview | Guardrails | Worked Examples | Glossary. The Examples tab
 * walks three real titles (one per verdict) end to end with the actual numbers
 * the engine produces, so a first-time reader can see exactly how a verdict is
 * reached. Client component for the tab interaction; all content is static.
 */

type TabId = "overview" | "guardrails" | "examples" | "glossary";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "guardrails", label: "The 4 Guardrails" },
  { id: "examples", label: "Worked Examples" },
  { id: "glossary", label: "Glossary" },
];

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
const GLOSSARY: { term: string; def: string }[] = [
  { term: "CPVH", def: "Cost-Per-Viewing-Hour = Acquisition Cost / Projected Viewing Hours. The core efficiency guardrail - what you pay per hour watched." },
  { term: "LTV-to-Cost Multiple", def: "((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) / Acquisition Cost. Return per dollar spent." },
  { term: "Churn Mitigation", def: "The modeled monthly cohort churn-reduction percentage a title delivers. Must be at least 1.5%." },
  { term: "Payback Horizon", def: "Months until a title reaches positive contribution margin. Target 9-12 months." },
  { term: "MAPE", def: "Mean Absolute Percentage Error = (1/n) x sum(|(Actual - Predicted)/Actual|) x 100. How far predictions were from reality in backtesting." },
  { term: "Recommendation Status", def: "The verdict: GREENLIGHT, NEGOTIATE HARD, or PASS." },
  { term: "Correctable breach", def: "A failed check that renegotiating the price down would fix (e.g. too-high CPVH). Leads to NEGOTIATE HARD, not PASS." },
  { term: "Non-correctable breach", def: "A failed check that no price change can fix (e.g. weak churn impact). Any one of these forces a PASS." },
  { term: "Asset Type", def: "ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, or CO_PRODUCTION." },
  { term: "Premium Original", def: "ORIGINAL_SERIES / ORIGINAL_FILM / CO_PRODUCTION. CPVH ceiling 0.18 USD." },
  { term: "Library Filler", def: "LICENSED_LIBRARY. CPVH ceiling 0.05 USD (cheaper content, stricter per-hour cap)." },
  { term: "Narrative DNA", def: "A 1536-dimension embedding of a title's tropes, themes, and pacing." },
  { term: "Affective Tone Score", def: "A title's primary and secondary emotional triggers." },
  { term: "Ground Truth Record", def: "The actual observed outcome for a historical title, used to backtest predictions." },
  { term: "Approval Workflow", def: "Multi-tier executive sign-off: a GREENLIGHT over $25M needs both the CCO and the CFO to approve before it is final." },
  { term: "User Role", def: "DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER, or CFO. One per user." },
  { term: "Audit Log", def: "An append-only trail of every state-changing action with who/when/before/after." },
  { term: "Task Queue", def: "The async worker system (Celery + Redis) that runs long jobs: ingestion, extraction, audits, telemetry." },
  { term: "Model Version", def: "An immutable snapshot of the active weights and parameters, stamped on each valuation so it stays reproducible." },
  { term: "License Terms", def: "A title's contract: duration, exclusivity, windowing rules, and milestone payment schedule." },
  { term: "Base Currency", def: "USD - all territorial costs are normalized into USD before any comparison." },
  { term: "Market Telemetry", def: "Live external signals (social sentiment, chart velocity, licensing inflation) by genre and territory that nudge valuations." },
];

// --------------------------------------------------------------------------- //
// Tab bodies
// --------------------------------------------------------------------------- //
function OverviewTab() {
  return (
    <div className="space-y-8">
      <div className="space-y-3 text-sm leading-relaxed text-slate-300">
        <p>
          Think of CineROI AI as a disciplined gatekeeper for buying TV and film
          content. You give it a title and its deal terms; it answers one
          question with evidence: <span className="font-medium text-slate-100">should we buy this, haggle, or walk away?</span>
        </p>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">The journey of one title</h3>
        <ol className="ml-4 list-decimal space-y-2 text-sm text-slate-300 marker:text-emerald-400">
          <li><span className="font-medium text-slate-100">Ingest</span> - a title comes in, in bulk (CSV/JSON/PDF) or one at a time in the Asset Studio.</li>
          <li><span className="font-medium text-slate-100">Understand it</span> - the system reads the material into a numeric profile: Narrative DNA, emotional tone, talent pedigree, production scale.</li>
          <li><span className="font-medium text-slate-100">Match the audience</span> - it compares the title to what subscriber groups actually like.</li>
          <li><span className="font-medium text-slate-100">Run the money checks</span> - four financial guardrails (next tab), all in USD.</li>
          <li><span className="font-medium text-slate-100">Decide</span> - GREENLIGHT, NEGOTIATE HARD, or PASS, with the reasoning spelled out.</li>
          <li><span className="font-medium text-slate-100">Keep itself honest</span> - it later checks predictions against real outcomes and re-tunes.</li>
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
          <Card title="Dashboard">Portfolio at a glance - KPIs and a sortable grid of every title with its badge.</Card>
          <Card title="Asset Studio">Type in one title and get an instant scorecard. Best place to see the whole thing work.</Card>
          <Card title="Title Evaluation">Deep dive on a single title: radar, financial breakdown, and the full explanation.</Card>
          <Card title="Backtest Studio">Feed in real outcomes, see how accurate past predictions were, and re-tune the model.</Card>
        </div>
      </div>
    </div>
  );
}

function GuardrailsTab() {
  return (
    <div className="space-y-6">
      <p className="text-sm leading-relaxed text-slate-300">
        Four checks decide the money question. Each has a plain-English meaning,
        a formula, and a line it must not cross. All amounts are converted to USD
        first, so a title bought in rupees and one bought in euros are judged on
        the same scale.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Card title="1. CPVH - Cost per Viewing Hour">
          <span className="text-slate-300">Plain English:</span> how much are we paying for each hour someone watches? Cheaper per hour is better.
          <Formula>CPVH = Acquisition Cost / Projected Viewing Hours</Formula>
          <p className="mt-2">Must stay at or below <span className="text-emerald-300">0.18 USD</span> (premium) or <span className="text-emerald-300">0.05 USD</span> (library). Over the line = breach.</p>
        </Card>
        <Card title="2. LTV-to-Cost Multiple">
          <span className="text-slate-300">Plain English:</span> for every dollar we spend, how many dollars of long-term value come back?
          <Formula>((Churn Value x LTV) + (Elasticity x CPM x Impressions)) / Cost</Formula>
          <p className="mt-2">Must be <span className="text-emerald-300">3.2x or higher</span>. Below = breach.</p>
        </Card>
        <Card title="3. Churn Mitigation">
          <span className="text-slate-300">Plain English:</span> does having this title stop people from cancelling?
          <Formula>Modeled monthly cohort churn reduction %</Formula>
          <p className="mt-2">Must be <span className="text-emerald-300">at least 1.5%</span>. Below = breach. (A price cut can&apos;t fix weak retention - so this breach is non-correctable.)</p>
        </Card>
        <Card title="4. Payback Horizon">
          <span className="text-slate-300">Plain English:</span> how many months until the title pays for itself?
          <Formula>Months until cumulative margin turns positive</Formula>
          <p className="mt-2">Target <span className="text-emerald-300">9-12 months</span>. Over 12 = breach.</p>
        </Card>
      </div>
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
        <span className="font-medium text-slate-100">Why &quot;correctable&quot; matters:</span>{" "}
        CPVH and LTV both depend on price - pay less and they improve, so breaking
        them only means &quot;negotiate.&quot; Weak churn or an unfixable payback can&apos;t
        be solved by paying less, so those breaks mean &quot;pass.&quot;
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

function ExamplesTab() {
  return (
    <div className="space-y-6">
      <p className="text-sm leading-relaxed text-slate-300">
        Three real titles, run through the actual engine. Each shows every check,
        the number it produced, the line it had to clear, and why the final
        verdict came out the way it did. These are the exact figures the Asset
        Studio returns - try them yourself with the matching presets.
      </p>

      <ExampleBlock
        title="The Bengaluru Syndicate"
        subtitle="Original Series &bull; $1.25M &bull; pedigree 7.5"
        verdict="GREENLIGHT"
        cost="$1,250,000"
        checks={[
          { label: "CPVH", plain: "Cost per viewing hour is well under the 0.18 ceiling.", math: "0.1598 <= 0.18", verdict: "pass" },
          { label: "LTV-to-Cost", plain: "Returns 4.25x per dollar - comfortably above the 3.2x hurdle.", math: "4.25x >= 3.2x", verdict: "pass" },
          { label: "Churn Mitigation", plain: "Retains subscribers at 2.5%, above the 1.5% floor.", math: "2.5% >= 1.5%", verdict: "pass" },
          { label: "Payback Horizon", plain: "Pays for itself in 9 months, inside the 9-12 target.", math: "9 <= 12", verdict: "pass" },
        ]}
        takeaway="All four checks pass, so the engine says buy it as proposed. No breaches, no caveats."
      />

      <ExampleBlock
        title="Vintage Reruns Vol. 7"
        subtitle="Licensed Library &bull; EUR 1.2M (-> $1.308M) &bull; pedigree 4.0"
        verdict="NEGOTIATE HARD"
        cost="$1,308,000 (converted from EUR)"
        checks={[
          { label: "CPVH", plain: "Very cheap per hour - well under the stricter 0.05 library ceiling.", math: "0.0436 <= 0.05", verdict: "pass" },
          { label: "LTV-to-Cost", plain: "Just misses the 3.2x hurdle - the one thing holding it back.", math: "3.19x < 3.2x", verdict: "breach" },
          { label: "Churn Mitigation", plain: "Retention impact clears the floor.", math: "1.8% >= 1.5%", verdict: "pass" },
          { label: "Payback Horizon", plain: "Recovers in 10 months, inside target.", math: "10 <= 12", verdict: "pass" },
        ]}
        ceiling="~$1,305,000"
        takeaway="Only the LTV check fails, and it fails because of price - pay a little less and it clears. The engine's dominant factor is LTV-to-Cost, so the message to the buyer is: this is worth having, go negotiate the price down."
      />

      <ExampleBlock
        title="Overpriced Epic"
        subtitle="Original Film &bull; $80M &bull; pedigree 2.0"
        verdict="PASS"
        cost="$80,000,000"
        checks={[
          { label: "CPVH", plain: "Massively overpriced per hour - more than 4x the ceiling.", math: "0.80 > 0.18", verdict: "breach" },
          { label: "LTV-to-Cost", plain: "Below the 3.2x hurdle.", math: "3.04x < 3.2x", verdict: "breach" },
          { label: "Churn Mitigation", plain: "Weak retention impact - below the 1.5% floor, and no price cut can fix that.", math: "1.4% < 1.5%", verdict: "breach" },
          { label: "Payback Horizon", plain: "Still recovers within the window.", math: "11 <= 12", verdict: "pass" },
        ]}
        takeaway="Three checks fail. The CPVH and LTV breaches are about price, but the churn breach is NOT - a weak retention effect can't be fixed by paying less. One non-correctable breach is enough to force a PASS. Dominant factor: CPVH. Walk away."
      />

      <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 p-4 text-sm text-slate-300">
        <span className="font-medium text-emerald-300">Try it live: </span>
        open the <Link href="/studio" className="text-emerald-400 underline">Asset Studio</Link>,
        click a preset (Bengaluru, Apex Horizon, or Vintage Reruns), and press
        &quot;RUN ROI VALUATION&quot; to watch these numbers appear on the scorecard.
      </div>
    </div>
  );
}

function GlossaryTab() {
  return (
    <dl className="divide-y divide-slate-800 rounded-lg border border-slate-800 bg-slate-900/40">
      {GLOSSARY.map((g) => (
        <div key={g.term} className="grid grid-cols-1 gap-1 p-4 sm:grid-cols-[220px_1fr] sm:gap-4">
          <dt className="font-semibold text-emerald-300">{g.term}</dt>
          <dd className="text-sm text-slate-400">{g.def}</dd>
        </div>
      ))}
    </dl>
  );
}

// --------------------------------------------------------------------------- //
// Page
// --------------------------------------------------------------------------- //
export default function GuidePage() {
  const [tab, setTab] = useState<TabId>("overview");

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100">
      <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/80 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <span className="text-lg font-bold tracking-tight">CineROI AI</span>
          <span className="hidden text-xs uppercase tracking-widest text-emerald-400 sm:inline">
            How It Works
          </span>
        </div>
        <nav className="flex items-center gap-2 text-sm">
          <Link href="/dashboard" className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:border-emerald-500 hover:text-emerald-300">Dashboard</Link>
          <Link href="/studio" className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:border-emerald-500 hover:text-emerald-300">Asset Studio</Link>
        </nav>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight">How CineROI AI Works</h1>
          <p className="mt-2 max-w-2xl text-slate-400">
            A plain-English guide to the whole platform - what it does, how it
            decides, and worked examples with real numbers.
          </p>
        </div>

        {/* Tabs */}
        <div role="tablist" aria-label="Guide sections" className="mb-8 flex flex-wrap gap-1 rounded-lg border border-slate-800 bg-slate-900/60 p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={
                "rounded-md px-4 py-2 text-sm font-medium transition-colors " +
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
          {tab === "guardrails" ? <GuardrailsTab /> : null}
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