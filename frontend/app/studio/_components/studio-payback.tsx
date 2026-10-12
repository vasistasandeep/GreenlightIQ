"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import { num } from "./helpers";

/**
 * Cumulative Payback Projection. Projects linear cost recovery across the
 * payback horizon: cumulative margin crosses zero at the break-even month.
 */
export function StudioPayback({
  normalizedCostUsd,
  paybackMonths,
}: {
  normalizedCostUsd: number | string | null;
  paybackMonths: number | null;
}) {
  const cost = num(normalizedCostUsd);
  const horizon = paybackMonths && paybackMonths > 0 ? paybackMonths : null;

  if (cost === null || horizon === null) {
    return (
      <p className="py-10 text-center text-sm text-slate-500">
        Payback projection unavailable until the horizon is computed.
      </p>
    );
  }

  const months = Math.min(horizon, 12);
  const perMonth = cost / horizon;
  // Cumulative contribution: starts at -cost, recovers perMonth each month.
  const data = Array.from({ length: 12 }, (_, i) => {
    const month = i + 1;
    const cumulative = perMonth * month - cost;
    return { month, cumulative: Math.round(cumulative) };
  });

  return (
    <div className="h-64 w-full" role="img" aria-label="Cumulative payback projection">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            width={48}
            tickFormatter={(v: number) =>
              new Intl.NumberFormat("en-US", { notation: "compact" }).format(v)
            }
          />
          <ReferenceLine y={0} stroke="#475569" />
          <Bar dataKey="cumulative" radius={[2, 2, 0, 0]}>
            {data.map((d) => (
              <Cell
                key={d.month}
                fill={d.cumulative >= 0 ? "#10b981" : "#334155"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}