import { cn } from "@/lib/utils";
import type { DashboardKpis } from "@/lib/types";

/**
 * KpiCards (R14.1).
 *
 * Renders the four executive KPI header cards for the Executive Command
 * Dashboard: active pipeline valuation, average LTV-to-Cost multiple, portfolio
 * risk exposure index, and model prediction accuracy rate. Each figure is `null`
 * when the pipeline has no data to compute it, in which case a dash placeholder
 * is shown rather than a misleading zero.
 */

/** Format a USD figure compactly (e.g. `$12.4M`), or a dash when unavailable. */
function formatUsd(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Format an LTV multiple as e.g. `3.2×`, or a dash when unavailable. */
function formatMultiple(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(2)}×`;
}

/** Format a 0–1 ratio as a percentage (e.g. `87%`), or a dash when unavailable. */
function formatPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(value);
}

interface KpiCardProps {
  label: string;
  value: string;
  hint: string;
}

/** A single KPI card: large value with a label and a short descriptive hint. */
function KpiCard({ label, value, hint }: KpiCardProps) {
  return (
    <div className="rounded-lg border bg-background p-5 shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight">
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

export interface KpiCardsProps {
  kpis: DashboardKpis;
  className?: string;
}

export function KpiCards({ kpis, className }: KpiCardsProps) {
  return (
    <section
      aria-label="Portfolio key performance indicators"
      className={cn(
        "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4",
        className,
      )}
    >
      <KpiCard
        label="Active Pipeline Valuation"
        value={formatUsd(kpis.active_pipeline_valuation_usd)}
        hint="Normalized acquisition cost (USD)"
      />
      <KpiCard
        label="Avg LTV-to-Cost"
        value={formatMultiple(kpis.avg_ltv_to_cost)}
        hint="Across valued titles"
      />
      <KpiCard
        label="Portfolio Risk Exposure"
        value={formatPercent(kpis.portfolio_risk_exposure)}
        hint="Share of at-risk titles"
      />
      <KpiCard
        label="Model Accuracy"
        value={formatPercent(kpis.model_accuracy_rate)}
        hint="Prediction accuracy rate"
      />
    </section>
  );
}
