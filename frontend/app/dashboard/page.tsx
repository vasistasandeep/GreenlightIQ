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
    <main className="container space-y-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Executive Command Dashboard
        </h1>
        <p className="text-sm text-muted-foreground">
          Portfolio health at a glance across the active acquisition pipeline.
        </p>
      </header>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          {error}
        </div>
      ) : null}

      <KpiCards kpis={summary.kpis} />

      <section aria-label="Pipeline asset grid" className="space-y-3">
        <h2 className="text-lg font-medium">Pipeline Assets</h2>
        <AssetDataGrid titles={summary.titles} />
      </section>
    </main>
  );
}
