import Link from "next/link";

/**
 * In-portal "How It Works" guide (`/guide`).
 *
 * A single self-contained reference page explaining the end-to-end platform:
 * the pipeline, the four financial guardrails and their formulas, the
 * recommendation logic, the portal views, governance/security, and a glossary.
 * Static server component - no data fetching, matches the dark portal theme.
 */

export const metadata = {
  title: "How It Works - CineROI AI",
};

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20 border-t border-slate-800 pt-8">
      <h2 className="mb-4 text-xl font-semibold tracking-tight text-slate-100">
        {title}
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-slate-300">
        {children}
      </div>
    </section>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
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

const GLOSSARY: { term: string; def: string }[] = [
  { term: "CPVH", def: "Cost-Per-Viewing-Hour = Total Acquisition Cost or Budget / Projected Viewing Hours. The core efficiency guardrail." },
  { term: "LTV-to-Cost Multiple", def: "((Churn Reduction Value x LTV) + (Watch-Time Elasticity x CPM x Ad Impressions)) / Total Acquisition Cost. Portfolio return per dollar spent." },
  { term: "Churn Mitigation Threshold", def: "The modeled cohort monthly churn-reduction percentage a title must deliver (minimum 1.5%)." },
  { term: "Payback Horizon", def: "The number of months until a title reaches positive contribution margin. Target window 9-12 months." },
  { term: "MAPE", def: "Mean Absolute Percentage Error = (1/n) x sum(|(Actual - Predicted)/Actual|) x 100. Measures prediction accuracy in backtesting." },
  { term: "Recommendation Status", def: "The verdict for a title: GREENLIGHT, NEGOTIATE HARD, or PASS." },
  { term: "Asset Type", def: "ORIGINAL_SERIES, ORIGINAL_FILM, LICENSED_LIBRARY, or CO_PRODUCTION." },
  { term: "Premium Original", def: "A title whose asset type is ORIGINAL_SERIES, ORIGINAL_FILM, or CO_PRODUCTION. CPVH ceiling 0.18 USD." },
  { term: "Library Filler", def: "A title whose asset type is LICENSED_LIBRARY. CPVH ceiling 0.05 USD." },
  { term: "Narrative DNA", def: "A 1536-dimension embedding vector representing a title's tropes, themes, and pacing." },
  { term: "Affective Tone Score", def: "A structured score of a title's primary and secondary emotional triggers." },
  { term: "Ground Truth Record", def: "A historical record of actual observed outcomes for a title, used in backtesting." },
  { term: "Approval Workflow", def: "Multi-tier executive sign-off governing high-budget greenlights (CCO + CFO when a GREENLIGHT exceeds $25M)." },
  { term: "User Role", def: "DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER, or CFO. Each user holds exactly one." },
  { term: "Audit Log", def: "An immutable, append-only trail of state-changing actions with actor, timestamp, and before/after values." },
  { term: "Task Queue", def: "The async worker system (Celery + Redis) that runs long jobs: ingestion, extraction, audits, telemetry." },
  { term: "Job Status", def: "PENDING, PROCESSING, COMPLETED, or FAILED - the lifecycle of an async job." },
  { term: "Model Version", def: "An immutable snapshot of the active feature weights and guardrail parameters stamped on each valuation for reproducibility." },
  { term: "License Terms", def: "A title's contract structure: duration, exclusivity, windowing rules, and milestone payment schedule." },
  { term: "Base Currency", def: "USD - the canonical reporting currency all territorial costs are normalized into before comparison." },
  { term: "Market Telemetry", def: "Live external signals (social sentiment, chart velocity, licensing inflation) by genre and territory that adjust valuations." },
];

export default function GuidePage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100">
      {/* Top bar */}
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
        {/* Hero */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">
            How CineROI AI Works
          </h1>
          <p className="mt-2 max-w-2xl text-slate-400">
            An internal decision-support platform for OTT content acquisition. It
            turns a candidate title into a defensible{" "}
            <span className="text-emerald-400">GREENLIGHT</span> /{" "}
            <span className="text-amber-400">NEGOTIATE HARD</span> /{" "}
            <span className="text-rose-400">PASS</span> recommendation, backed by
            quantitative financial guardrails, historical backtesting, and
            executive governance.
          </p>
        </div>

        {/* On-this-page nav */}
        <nav className="mb-10 flex flex-wrap gap-2 text-xs">
          {[
            ["pipeline", "The Pipeline"],
            ["guardrails", "The Four Guardrails"],
            ["recommendation", "Recommendation Logic"],
            ["views", "Portal Views"],
            ["backtesting", "Backtesting & Calibration"],
            ["governance", "Governance & Security"],
            ["glossary", "Glossary"],
          ].map(([id, label]) => (
            <a key={id} href={`#${id}`} className="rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1 text-slate-300 hover:border-emerald-500 hover:text-emerald-300">
              {label}
            </a>
          ))}
        </nav>

        <div className="space-y-10">
          <Section id="pipeline" title="1. The Pipeline">
            <p>
              Every candidate title flows through the same six stages. Heavy work
              (ingestion, extraction, audits) runs asynchronously on a worker
              fleet; interactive reads and single-title valuations run instantly.
            </p>
            <ol className="ml-4 list-decimal space-y-2 marker:text-emerald-400">
              <li><span className="font-medium text-slate-100">Ingest</span> - submit titles in bulk (CSV up to 10,000 rows, JSON pitch decks, PDF scripts) or one at a time in the Asset Studio.</li>
              <li><span className="font-medium text-slate-100">Feature Extraction</span> - parse source material into a 1536-dim Narrative DNA embedding, affective tone, talent pedigree, and production scale.</li>
              <li><span className="font-medium text-slate-100">Similarity Match</span> - score the title against subscriber-cohort preference vectors with pgvector cosine similarity.</li>
              <li><span className="font-medium text-slate-100">Guardrails</span> - normalize cost to USD, then run the four financial checks.</li>
              <li><span className="font-medium text-slate-100">Recommendation</span> - derive GREENLIGHT / NEGOTIATE HARD / PASS with a full explanation.</li>
              <li><span className="font-medium text-slate-100">Backtest</span> - compare past predictions to actuals, measure MAPE, and auto-recalibrate the model.</li>
            </ol>
          </Section>

          <Section id="guardrails" title="2. The Four Financial Guardrails">
            <p>
              These are deterministic calculations - the platform&apos;s most
              rigorously tested asset. All monetary comparisons happen in USD
              after dated normalization, so multi-territory deals are judged on
              one axis.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Card title="CPVH - Cost per Viewing Hour">
                Efficiency: is the title priced sensibly per hour watched?
                <Formula>CPVH = Acquisition Cost / Projected Viewing Hours</Formula>
                <p className="mt-2">Ceiling: <span className="text-emerald-300">0.18 USD</span> premium original, <span className="text-emerald-300">0.05 USD</span> library. Breach when strictly above the ceiling.</p>
              </Card>
              <Card title="LTV-to-Cost Multiple">
                Portfolio return per dollar spent.
                <Formula>((Churn Value x LTV) + (Elasticity x CPM x Impressions)) / Cost</Formula>
                <p className="mt-2">Hurdle: <span className="text-emerald-300">&ge; 3.2x</span> over a 12-24 month window. Breach when below.</p>
              </Card>
              <Card title="Churn Mitigation">
                Does the title measurably retain subscribers?
                <Formula>Modeled monthly cohort churn reduction %</Formula>
                <p className="mt-2">Threshold: <span className="text-emerald-300">&ge; 1.5%</span>. Breach when below.</p>
              </Card>
              <Card title="Payback Horizon">
                How fast is the capital recovered?
                <Formula>Months until cumulative contribution margin turns positive</Formula>
                <p className="mt-2">Target: <span className="text-emerald-300">9-12 months</span>. Breach when above 12.</p>
              </Card>
            </div>
          </Section>

          <Section id="recommendation" title="3. Recommendation Logic">
            <p>Each title gets exactly one verdict, derived from the guardrail breaches:</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-emerald-800/50 bg-emerald-500/10 p-4">
                <div className="font-bold text-emerald-300">GREENLIGHT</div>
                <p className="mt-1 text-xs text-slate-400">Zero guardrail breaches. Acquire as proposed.</p>
              </div>
              <div className="rounded-lg border border-amber-800/50 bg-amber-500/10 p-4">
                <div className="font-bold text-amber-300">NEGOTIATE HARD</div>
                <p className="mt-1 text-xs text-slate-400">Breaches exist but are all correctable by renegotiating cost down. There is a price at which it clears.</p>
              </div>
              <div className="rounded-lg border border-rose-800/50 bg-rose-500/10 p-4">
                <div className="font-bold text-rose-300">PASS</div>
                <p className="mt-1 text-xs text-slate-400">At least one breach cannot be fixed by any permitted cost change. Walk away.</p>
              </div>
            </div>
            <p>
              Every recommendation ships with an <span className="font-medium text-slate-100">explanation</span>:
              each check&apos;s computed value vs its threshold, the shortfall
              magnitude, and the <span className="font-medium text-slate-100">dominant factor</span> driving the outcome.
            </p>
          </Section>

          <Section id="views" title="4. Portal Views">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Card title="Executive Command Dashboard (/dashboard)">
                Portfolio KPIs (pipeline valuation, avg LTV-to-Cost, risk exposure, model accuracy) and a sortable asset grid with recommendation badges. Click a row to drill in.
              </Card>
              <Card title="Asset Studio (/studio)">
                Enter a single asset&apos;s metadata and deal terms, run an instant ROI valuation, and get the executive scorecard - banner, four checks, explainability, governance, metadata radar, and payback projection.
              </Card>
              <Card title="Title Evaluation (/titles/[id])">
                Deep dive on one title: metadata radar, financial accordion (CPVH checks, churn curves, payback timeline), negotiation leverage, and the full explanation.
              </Card>
              <Card title="Backtest Studio (/backtest)">
                Enter ground-truth outcomes, see predicted-vs-actual variance charts, and recalibrate the model when accuracy drifts.
              </Card>
            </div>
          </Section>

          <Section id="backtesting" title="5. Backtesting & Calibration">
            <p>
              The platform keeps itself honest. For historical titles it compares
              each prediction to the actual observed outcome and computes{" "}
              <span className="font-medium text-slate-100">MAPE</span> (mean
              absolute percentage error). When MAPE exceeds 10%, the{" "}
              Calibration Controller computes weight-adjustment offsets and{" "}
              <span className="font-medium text-slate-100">forks a new immutable model version</span> -
              it never mutates weights in place, so every past valuation stays
              reproducible from its stamped version.
            </p>
          </Section>

          <Section id="governance" title="6. Governance & Security">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Card title="Authentication">SSO (OIDC/SAML), identity-bound sessions, 30-minute idle expiry, and service-to-service credentials.</Card>
              <Card title="Role-Based Access">One role per user. Overrides are reserved for decision-makers; confidential fields are scoped by role and authorized territory.</Card>
              <Card title="Executive Sign-Off">A GREENLIGHT whose normalized cost exceeds $25M requires both CCO and CFO approval before it can be finalized.</Card>
              <Card title="Audit & Reproducibility">Every state-changing action is written to an append-only audit log; model versions and title versions are immutable.</Card>
            </div>
          </Section>

          <Section id="glossary" title="7. Glossary">
            <dl className="divide-y divide-slate-800 rounded-lg border border-slate-800 bg-slate-900/40">
              {GLOSSARY.map((g) => (
                <div key={g.term} className="grid grid-cols-1 gap-1 p-4 sm:grid-cols-[200px_1fr] sm:gap-4">
                  <dt className="font-semibold text-emerald-300">{g.term}</dt>
                  <dd className="text-sm text-slate-400">{g.def}</dd>
                </div>
              ))}
            </dl>
          </Section>
        </div>

        <footer className="mt-12 border-t border-slate-800 pt-6 text-xs text-slate-500">
          <p>
            Note: in demo mode the Narrative DNA embedding and modeled financial
            drivers are deterministic placeholders so the stack runs with no
            external dependencies. The guardrail math, recommendation logic,
            backtesting, and governance are genuine working logic.
          </p>
          <div className="mt-3 flex gap-3">
            <Link href="/dashboard" className="text-emerald-400 hover:underline">Go to Dashboard</Link>
            <Link href="/studio" className="text-emerald-400 hover:underline">Open Asset Studio</Link>
          </div>
        </footer>
      </div>
    </div>
  );
}