import { TrendingUp, Layers, ShieldAlert, Target } from "lucide-react";

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

type Accent = "emerald" | "sky" | "amber" | "violet";

const ACCENT: Record<Accent, { ring: string; icon: string; glow: string }> = {
  emerald: { ring: "border-emerald-500/20", icon: "bg-emerald-500/15 text-emerald-400", glow: "from-emerald-500/10" },
  sky: { ring: "border-sky-500/20", icon: "bg-sky-500/15 text-sky-400", glow: "from-sky-500/10" },
  amber: { ring: "border-amber-500/20", icon: "bg-amber-500/15 text-amber-400", glow: "from-amber-500/10" },
  violet: { ring: "border-violet-500/20", icon: "bg-violet-500/15 text-violet-400", glow: "from-violet-500/10" },
};

interface KpiCardProps {
  label: string;
  value: string;
  hint: string;
  accent: Accent;
  icon: React.ReactNode;
}

/** A single KPI card: an accented icon, large value, label, and a short hint. */
function KpiCard({ label, value, hint, accent, icon }: KpiCardProps) {
  const a = ACCENT[accent];
  return (
    <div
      data-kpi-card
      className={cn(
        "group relative overflow-hidden rounded-xl border bg-slate-900/70 p-5 transition-colors hover:bg-slate-900",
        a.ring,
      )}
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-0 bg-gradient-to-br to-transparent opacity-60",
          a.glow,
        )}
        aria-hidden
      />
      <div className="relative flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <span className={cn("inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", a.icon)} aria-hidden>
          {icon}
        </span>
      </div>
      <p className="relative mt-3 text-3xl font-semibold tabular-nums tracking-tight text-slate-50">
        {value}
      </p>
      <p className="relative mt-1 text-xs text-muted-foreground">{hint}</p>
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
        accent="emerald"
        icon={<Layers className="h-5 w-5" aria-hidden />}
      />
      <KpiCard
        label="Avg LTV-to-Cost"
        value={formatMultiple(kpis.avg_ltv_to_cost)}
        hint="Across valued titles"
        accent="sky"
        icon={<TrendingUp className="h-5 w-5" aria-hidden />}
      />
      <KpiCard
        label="Portfolio Risk Exposure"
        value={formatPercent(kpis.portfolio_risk_exposure)}
        hint="Share of at-risk titles"
        accent="amber"
        icon={<ShieldAlert className="h-5 w-5" aria-hidden />}
      />
      <KpiCard
        label="Model Accuracy"
        value={formatPercent(kpis.model_accuracy_rate)}
        hint="Prediction accuracy rate"
        accent="violet"
        icon={<Target className="h-5 w-5" aria-hidden />}
      />
    </section>
  );
}
