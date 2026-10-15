import Link from "next/link";

import { AppShell } from "@/components/layout/top-nav";

export const metadata = { title: "Home" };

const ENTRIES: { href: string; title: string; blurb: string; cta: string }[] = [
  {
    href: "/dashboard",
    title: "Executive Dashboard",
    blurb: "Portfolio health at a glance - KPIs and every title in the pipeline with its recommendation badge.",
    cta: "View the pipeline",
  },
  {
    href: "/studio",
    title: "Asset Studio",
    blurb: "Enter one title and get an instant greenlight scorecard. The fastest way to see the engine work.",
    cta: "Value an asset",
  },
  {
    href: "/backtest",
    title: "Backtest Studio",
    blurb: "Compare past predictions to real outcomes, measure accuracy, and recalibrate the model.",
    cta: "Open the studio",
  },
  {
    href: "/guide",
    title: "How It Works",
    blurb: "A plain-English guide: the pipeline, the four guardrails, worked examples, and a full glossary.",
    cta: "Read the guide",
  },
];

export default function HomePage() {
  return (
    <AppShell>
      <section className="relative mb-10 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50 p-8 sm:p-12">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-32 left-1/3 h-72 w-72 rounded-full bg-sky-500/5 blur-3xl" aria-hidden />
        <span className="relative inline-flex items-center gap-1.5 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px] shadow-emerald-400" aria-hidden />
          OTT Greenlight Intelligence Engine
        </span>
        <h1 className="relative mt-4 max-w-3xl text-3xl font-bold tracking-tight sm:text-4xl">
          Decide which titles to buy, haggle, or pass -{" "}
          <span className="text-emerald-400">with the numbers to back it up.</span>
        </h1>
        <p className="relative mt-3 max-w-2xl text-slate-400">
          CineROI AI runs every candidate title through four financial guardrails
          and returns a defensible GREENLIGHT / NEGOTIATE HARD / PASS
          recommendation, with the full reasoning and an executive scorecard.
        </p>
        <div className="relative mt-6 flex flex-wrap gap-3">
          <Link
            href="/studio"
            className="inline-flex items-center rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-bold text-emerald-950 shadow-lg shadow-emerald-900/30 transition hover:bg-emerald-400 hover:shadow-emerald-800/40"
          >
            Value an asset
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center rounded-lg border border-slate-700 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
          >
            View the dashboard
          </Link>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {ENTRIES.map((e) => (
          <Link
            key={e.href}
            href={e.href}
            className="group relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60 p-6 transition-all hover:-translate-y-0.5 hover:border-emerald-600/60 hover:bg-slate-900 hover:shadow-lg hover:shadow-emerald-950/30"
          >
            <h2 className="text-lg font-semibold text-slate-100">{e.title}</h2>
            <p className="mt-1.5 text-sm text-slate-400">{e.blurb}</p>
            <span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-400">
              {e.cta}
              <span className="transition-transform group-hover:translate-x-0.5">&rarr;</span>
            </span>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}