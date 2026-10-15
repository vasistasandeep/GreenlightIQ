"use client";

import { useState } from "react";
import Link from "next/link";

import { TopNav } from "@/components/layout/top-nav";

import { ApiError, api } from "@/lib/api-client";
import type { QuickEvaluateRequest, QuickEvaluateResponse } from "@/lib/types";
import { AssetForm } from "./_components/asset-form";
import { ValuationReport } from "./_components/valuation-report";
import { BatchIngest } from "./_components/batch-ingest";

/**
 * Asset Studio (`/studio`) - manual asset ingestion + instant ROI valuation.
 *
 * A dark executive workspace: the left pane captures a single asset's metadata
 * and deal terms; "RUN ROI VALUATION" submits to POST /titles/quick-evaluate,
 * which creates the title, runs the Guardrails_Engine, and returns the scorecard
 * rendered in place on the right.
 */
export default function AssetStudioPage() {
  const [tab, setTab] = useState<"single" | "batch">("single");
  const [result, setResult] = useState<QuickEvaluateResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(payload: QuickEvaluateRequest) {
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.quickEvaluate(payload);
      setResult(res);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.envelope?.message ?? err.message
          : "Could not reach the valuation engine.";
      setError(message);
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100">
      <TopNav />

      <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-[380px_1fr]">
        {/* Left: input panel */}
        <aside className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="mb-4 flex gap-2" role="tablist" aria-label="Ingestion mode">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "single"}
              onClick={() => setTab("single")}
              className={
                "flex-1 rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-wide transition " +
                (tab === "single" ? "bg-emerald-500 text-emerald-950 shadow-sm" : "bg-slate-800 text-slate-400 hover:text-slate-200")
              }
            >
              Single Asset
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "batch"}
              onClick={() => setTab("batch")}
              className={
                "flex-1 rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-wide transition " +
                (tab === "batch" ? "bg-emerald-500 text-emerald-950 shadow-sm" : "bg-slate-800 text-slate-400 hover:text-slate-200")
              }
            >
              Batch Slate
            </button>
          </div>
          {tab === "single" ? (
            <AssetForm onSubmit={handleSubmit} submitting={submitting} />
          ) : (
            <BatchIngest />
          )}
        </aside>

        {/* Right: valuation report */}
        <main>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Valuation Report &amp; ROI Forecast
          </h2>

          {error ? (
            <div
              role="alert"
              className="rounded-xl border border-rose-800 bg-rose-950/40 px-5 py-4 text-sm text-rose-300"
            >
              {error}
            </div>
          ) : null}

          {submitting ? (
            <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-6 py-10 text-slate-300">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
              Deconstructing Narrative DNA &amp; Running Guardrails...
            </div>
          ) : result ? (
            <>
              <ValuationReport result={result} />
              <div className="mt-5">
                <Link
                  href={`/titles/${result.title_id}`}
                  className="inline-flex items-center rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-emerald-300 hover:bg-slate-700"
                >
                  View Full Deep-Dive Analysis &rarr;
                </Link>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center">
              <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-slate-800/80 text-slate-500" aria-hidden>
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 3v18h18" />
                  <path d="M7 14l4-4 3 3 5-6" />
                </svg>
              </span>
              <p className="max-w-xs text-sm text-slate-400">
                Enter an asset on the left and run the valuation to see the instant
                executive scorecard.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}