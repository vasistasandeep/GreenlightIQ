"use client";

import { useState } from "react";
import Link from "next/link";

import { ApiError, api } from "@/lib/api-client";
import type { QuickEvaluateRequest, QuickEvaluateResponse } from "@/lib/types";
import { AssetForm } from "./_components/asset-form";
import { ValuationReport } from "./_components/valuation-report";

/**
 * Asset Studio (`/studio`) - manual asset ingestion + instant ROI valuation.
 *
 * A dark executive workspace: the left pane captures a single asset's metadata
 * and deal terms; "RUN ROI VALUATION" submits to POST /titles/quick-evaluate,
 * which creates the title, runs the Guardrails_Engine, and returns the scorecard
 * rendered in place on the right.
 */
export default function AssetStudioPage() {
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
      {/* Top bar */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/80 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <span className="text-lg font-bold tracking-tight">CineROI AI</span>
          <span className="hidden text-xs uppercase tracking-widest text-emerald-400 sm:inline">
            OTT Greenlight Intelligence Engine
          </span>
          <span className="flex items-center gap-1.5 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            Live
          </span>
        </div>
        <nav className="flex items-center gap-2">
          <Link
            href="/dashboard"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-emerald-500 hover:text-emerald-300"
          >
            Dashboard
          </Link>
        </nav>
      </header>

      <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-[380px_1fr]">
        {/* Left: input panel */}
        <aside className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Input New Asset
          </h2>
          <AssetForm onSubmit={handleSubmit} submitting={submitting} />
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
            <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center text-slate-500">
              Enter an asset on the left and run the valuation to see the instant
              executive scorecard.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}