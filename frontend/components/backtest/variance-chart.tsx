"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";
import type { AuditMetric } from "@/lib/types";

/**
 * VarianceChart (R16.2).
 *
 * Right-pane variance visualization rendered after a ground-truth submission.
 * For each audited metric (CPVH and the LTV-to-cost multiple) it draws the
 * Predicted and Actual values side by side so an executive can read the gap at a
 * glance. Excluded pairs (zero actual, R11.7) are annotated so the viewer knows
 * why a bar may be absent from the MAPE.
 */

/** Human-friendly labels for the metric keys the backend emits. */
const METRIC_LABELS: Record<string, string> = {
  cpvh: "CPVH",
  ltv_to_cost: "LTV-to-Cost",
  ltv_to_cost_multiple: "LTV-to-Cost",
};

function labelFor(metric: string): string {
  return METRIC_LABELS[metric] ?? metric;
}

interface VarianceDatum {
  metric: string;
  label: string;
  predicted: number;
  actual: number;
  excluded: boolean;
}

export interface VarianceChartProps {
  /** The scorecard rows comparing predicted vs actual for each metric. */
  metrics: AuditMetric[];
  className?: string;
}

export function VarianceChart({ metrics, className }: VarianceChartProps) {
  const data: VarianceDatum[] = metrics.map((row) => ({
    metric: row.metric,
    label: labelFor(row.metric),
    // Decimal values arrive as strings over the wire; coerce for the chart.
    predicted: Number(row.predicted),
    actual: Number(row.actual),
    excluded: row.excluded,
  }));

  if (data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No metrics to compare for this title.
      </p>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <h3 className="text-base font-semibold">Predicted vs Actual</h3>
      <div className="h-72 w-full" role="img" aria-label="Predicted versus actual variance by metric">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip
              formatter={(value: number, name: string) => [value, name]}
              labelFormatter={(label: string) => `Metric: ${label}`}
            />
            <Legend />
            <Bar dataKey="predicted" name="Predicted" fill="hsl(222.2 47.4% 55%)" radius={[2, 2, 0, 0]} />
            <Bar dataKey="actual" name="Actual" fill="hsl(142 71% 45%)" radius={[2, 2, 0, 0]}>
              {data.map((entry) => (
                <Cell
                  key={entry.metric}
                  fillOpacity={entry.excluded ? 0.35 : 1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {data.some((d) => d.excluded) ? (
        <p className="text-xs text-muted-foreground">
          Faded bars mark metrics with a zero actual, excluded from the MAPE
          calculation.
        </p>
      ) : null}
    </div>
  );
}
