"use client";

/**
 * SensitivityPanel (What-If Sensitivity).
 *
 * Lets an executive drag cost, viewership, and churn sliders and see the
 * recommendation and the four guardrail metrics recompute live, WITHOUT changing
 * any saved record. Calls the stateless `POST /valuation/{id}/what-if` endpoint
 * (debounced) and renders a clearly-labeled non-persisted preview.
 *
 * Excluded from the Greenlight Memo print via the `no-print` class.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { MULTIPLIER_BOUNDS, type ValuationScorecard } from "@/lib/types";
import { RecommendationBadge } from "@/components/recommendation-badge";
import { formatMultiple, formatNumber, formatPercent, toNumber } from "./format";

const DEBOUNCE_MS = 400;
const VIEWERSHIP_STOPS = [
  { label: "Bear", value: 0.5 },
  { label: "Base", value: 1.0 },
  { label: "Bull", value: 2.0 },
];

export interface SensitivityPanelProps {
  titleId: string;
}

export function SensitivityPanel({ titleId }: SensitivityPanelProps) {
  const [cost, setCost] = useState(1.0);
  const [viewership, setViewership] = useState(1.0);
  const [churn, setChurn] = useState(1.0);
  const [preview, setPreview] = useState<ValuationScorecard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.whatIf(titleId, {
          cost_multiplier: cost,
          viewership_multiplier: viewership,
          churn_multiplier: churn,
        });
        // Ignore a stale response superseded by a newer request.
        if (id === requestId.current) {
          setPreview(result);
        }
      } catch {
        if (id === requestId.current) {
          setError("Could not compute this scenario. Please try again.");
        }
      } finally {
        if (id === requestId.current) {
          setLoading(false);
        }
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [titleId, cost, viewership, churn]);

  const metric = (value: number | string | null | undefined, fmt: (v: number | string | null | undefined) => string) =>
    toNumber(value) === null ? "-" : fmt(value);

  return (
    <section
      aria-labelledby="sensitivity-heading"
      className="no-print rounded-lg border bg-background p-5 shadow-sm"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="sensitivity-heading" className="text-lg font-semibold">
          What-if sensitivity
        </h2>
        <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs font-medium text-slate-300">
          Scenario preview - not saved
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">
            Cost: {Math.round(cost * 100)}%
          </span>
          <input
            type="range"
            aria-label="Cost multiplier"
            min={MULTIPLIER_BOUNDS.min}
            max={MULTIPLIER_BOUNDS.max}
            step={0.05}
            value={cost}
            onChange={(e) => setCost(Number(e.target.value))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">
            Viewership:{" "}
            {VIEWERSHIP_STOPS.find((s) => s.value === viewership)?.label ??
              `${Math.round(viewership * 100)}%`}
          </span>
          <input
            type="range"
            aria-label="Viewership multiplier"
            min={MULTIPLIER_BOUNDS.min}
            max={MULTIPLIER_BOUNDS.max}
            step={0.05}
            value={viewership}
            onChange={(e) => setViewership(Number(e.target.value))}
            list="viewership-stops"
          />
          <datalist id="viewership-stops">
            {VIEWERSHIP_STOPS.map((s) => (
              <option key={s.label} value={s.value} label={s.label} />
            ))}
          </datalist>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">
            Churn: {Math.round(churn * 100)}%
          </span>
          <input
            type="range"
            aria-label="Churn multiplier"
            min={MULTIPLIER_BOUNDS.min}
            max={MULTIPLIER_BOUNDS.max}
            step={0.05}
            value={churn}
            onChange={(e) => setChurn(Number(e.target.value))}
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 border-t pt-4">
        {error ? (
          <p role="alert" className="text-sm font-medium text-red-500">
            {error}
          </p>
        ) : preview ? (
          <>
            <RecommendationBadge
              status={preview.recommendation_status}
              className="text-sm"
            />
            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div className="flex items-baseline gap-1.5">
                <dt className="text-muted-foreground">CPVH</dt>
                <dd className="font-medium tabular-nums">
                  {metric(preview.calculated_cpvh, formatNumber)}
                </dd>
              </div>
              <div className="flex items-baseline gap-1.5">
                <dt className="text-muted-foreground">LTV-to-Cost</dt>
                <dd className="font-medium tabular-nums">
                  {metric(preview.ltv_to_cost_multiple, formatMultiple)}
                </dd>
              </div>
              <div className="flex items-baseline gap-1.5">
                <dt className="text-muted-foreground">Churn</dt>
                <dd className="font-medium tabular-nums">
                  {metric(preview.churn_reduction_pct, formatPercent)}
                </dd>
              </div>
              <div className="flex items-baseline gap-1.5">
                <dt className="text-muted-foreground">Payback</dt>
                <dd className="font-medium tabular-nums">
                  {preview.payback_horizon_months ?? "-"} mo
                </dd>
              </div>
            </dl>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {loading ? "Computing scenario..." : "Adjust a slider to preview a scenario."}
          </p>
        )}
      </div>
    </section>
  );
}