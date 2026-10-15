import Link from "next/link";
import { Suspense } from "react";

import { AppShell } from "@/components/layout/top-nav";
import { api, ApiError } from "@/lib/api-client";
import type { DashboardSummary } from "@/lib/types";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { AssetDataGrid } from "@/components/dashboard/asset-data-grid";

/**
 * Executive Command Dashboard (R14).
 *
 * Server Component that fetches the dashboard summary (KPI figures + asset grid
 * rows) and renders the KPI header cards (R14.1) above the sortable master asset
 * data grid (R14.2, R14.4, R14.5). On a fetch failure it degrades to an inline
 * error notice while still presenting the page shell.
 */

// The pipeline summary is live operational data; never statically cache it.
export const dynamic = "force-dynamic";

/** Empty KPI figures used when the summary cannot be loaded. */
const EMPTY_SUMMARY: DashboardSummary = {
  kpis: {
    active_pipeline_valuation_usd: null,
    avg_ltv_to_cost: null,
    portfolio_risk_exposure: null,
    model_accuracy_rate: null,
  },
  titles: [],
};

interface LoadResult {
  summary: DashboardSummary;
  error: string | null;
}

/** Fetch the dashboard summary, degrading to an empty payload + message on failure. */
async function loadSummary(): Promise<LoadResult> {
  try {
    const summary = await api.getDashboardSummary({ cache: "no-store" });
    return { summary, error: null };
  } catch (err) {
    const message =
      err instanceof ApiError
        ? `Unable to load the pipeline (${err.message}).`
        : "Unable to reach the valuation service.";
    return { summary: EMPTY_SUMMARY, error: message };
  }
}

export default async function DashboardPage() {
  const { summary, error } = await loadSummary();

  return (
    <AppShell>
      <div className="space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Executive Command Dashboard
            </h1>
            <p className="text-sm text-muted-foreground">
              Portfolio health at a glance across the active acquisition pipeline.
            </p>
          </div>
          <Link
            href="/studio"
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 shadow-lg shadow-emerald-900/30 transition hover:bg-emerald-400"
          >
            + New Asset Valuation
          </Link>
        </header>

        {error ? (
          <div
            role="alert"
            className="rounded-lg border border-amber-700/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-300"
          >
            {error}
          </div>
        ) : null}

        <KpiCards kpis={summary.kpis} />

        <section aria-label="Pipeline asset grid" className="space-y-3">
          <h2 className="text-lg font-medium">Pipeline Assets</h2>
          {/* Suspense boundary: AssetDataGrid reads filter/sort state from the
              URL via useSearchParams, which requires a Suspense boundary. */}
          <Suspense fallback={null}>
            <AssetDataGrid titles={summary.titles} />
          </Suspense>
        </section>
      </div>
    </AppShell>
  );
}
