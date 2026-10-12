"use client";

/**
 * PaybackTimeline (R15.2).
 *
 * A Recharts bar chart of cumulative recovery of the normalized acquisition cost
 * across the payback horizon. The backend scorecard carries the total
 * `payback_horizon_months` and the `normalized_cost_usd`; from these we project a
 * linear month-by-month recovery curve so the executive can see when the
 * investment is recouped. When the horizon is unknown the chart is suppressed.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatUsd, toNumber } from "./format";

/** Cap the number of rendered bars so very long horizons stay legible. */
const MAX_BARS = 36;

export interface PaybackPoint {
  month: number;
  recovered: number;
}

/** Project a linear cumulative-recovery curve across the horizon (R15.2). */
export function buildPaybackSeries(
  horizonMonths: number | null,
  normalizedCostUsd: number | null,
): PaybackPoint[] {
  if (!horizonMonths || horizonMonths <= 0 || normalizedCostUsd === null) {
    return [];
  }
  const months = Math.min(horizonMonths, MAX_BARS);
  const perMonth = normalizedCostUsd / horizonMonths;
  return Array.from({ length: months }, (_, i) => {
    const month = i + 1;
    return { month, recovered: Math.min(perMonth * month, normalizedCostUsd) };
  });
}

export interface PaybackTimelineProps {
  paybackHorizonMonths: number | null;
  normalizedCostUsd: number | string | null;
}

export function PaybackTimeline({
  paybackHorizonMonths,
  normalizedCostUsd,
}: PaybackTimelineProps) {
  const cost = toNumber(normalizedCostUsd);
  const series = buildPaybackSeries(paybackHorizonMonths, cost);

  if (series.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        A payback timeline is not available until the payback horizon is computed.
      </p>
    );
  }

  const truncated =
    paybackHorizonMonths !== null && paybackHorizonMonths > MAX_BARS;

  return (
    <div>
      <div
        className="h-56 w-full"
        role="img"
        aria-label="Cumulative cost-recovery timeline"
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11 }}
              label={{ value: "Month", position: "insideBottom", offset: -2, fontSize: 11 }}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              width={72}
              tickFormatter={(v: number) =>
                new Intl.NumberFormat("en-US", {
                  notation: "compact",
                  maximumFractionDigits: 1,
                }).format(v)
              }
            />
            <Tooltip
              formatter={(value: number | string) =>
                [formatUsd(Number(value)), "Recovered"] as [string, string]
              }
              labelFormatter={(label) => `Month ${label}`}
            />
            <Bar dataKey="recovered" fill="hsl(222.2 47.4% 11.2%)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Projected linear recovery of {formatUsd(cost)} across{" "}
        {paybackHorizonMonths} month{paybackHorizonMonths === 1 ? "" : "s"}.
        {truncated ? ` Showing the first ${MAX_BARS} months.` : ""}
      </p>
    </div>
  );
}
