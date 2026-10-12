"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import type { BacktestAuditRequest, GroundTruthMetricInput } from "@/lib/types";

/**
 * GroundTruthForm (R16.1).
 *
 * Left-pane input controls for the Backtesting & Calibration Studio. The analyst
 * supplies the historical title identifier and the observed actual outcomes for
 * the audited metrics (CPVH and the LTV-to-cost multiple), then submits them to
 * `POST /backtest/audit` (R11.1). The parent owns the request lifecycle; this
 * component only gathers, validates, and shapes the {@link BacktestAuditRequest}.
 *
 * Only metrics the analyst actually fills in are included — a blank field is
 * omitted rather than sent as zero, since a genuine zero actual is excluded from
 * MAPE server-side (R11.7) and should be entered explicitly.
 */

/** The audited metrics surfaced in the form, matching the design (CPVH + LTV). */
const AUDITED_METRICS: { key: string; label: string; hint: string }[] = [
  { key: "cpvh", label: "Actual CPVH", hint: "Cost per viewing hour (USD)" },
  {
    key: "ltv_to_cost_multiple",
    label: "Actual LTV-to-Cost multiple",
    hint: "Realized lifetime-value-to-cost ratio",
  },
];

export interface GroundTruthFormProps {
  /** Submit the shaped ground-truth request; resolves when the audit returns. */
  onSubmit: (request: BacktestAuditRequest) => void | Promise<void>;
  /** True while an audit request is in flight; disables the controls. */
  submitting?: boolean;
  className?: string;
}

export function GroundTruthForm({
  onSubmit,
  submitting = false,
  className,
}: GroundTruthFormProps) {
  const [titleId, setTitleId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  function setMetric(key: string, raw: string) {
    setValues((prev) => ({ ...prev, [key]: raw }));
  }

  function buildMetrics(): GroundTruthMetricInput[] | { error: string } {
    const metrics: GroundTruthMetricInput[] = [];
    for (const { key, label } of AUDITED_METRICS) {
      const raw = (values[key] ?? "").trim();
      if (raw === "") {
        continue;
      }
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) {
        return { error: `${label} must be a number.` };
      }
      metrics.push({ metric_name: key, actual_value: parsed });
    }
    if (metrics.length === 0) {
      return { error: "Enter at least one observed actual value." };
    }
    return metrics;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const trimmedId = titleId.trim();
    if (trimmedId === "") {
      setError("A historical title identifier is required.");
      return;
    }

    const result = buildMetrics();
    if ("error" in result) {
      setError(result.error);
      return;
    }

    await onSubmit({ title_id: trimmedId, metrics: result });
  }

  const inputClass =
    "w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
    "focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50";

  return (
    <form
      onSubmit={handleSubmit}
      className={cn("flex flex-col gap-5", className)}
      aria-labelledby="ground-truth-heading"
    >
      <div>
        <h2 id="ground-truth-heading" className="text-lg font-semibold">
          Ground Truth
        </h2>
        <p className="text-sm text-muted-foreground">
          Enter the observed outcomes for a historical title to audit prediction
          accuracy.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="gt-title-id" className="text-sm font-medium">
          Historical title ID
        </label>
        <input
          id="gt-title-id"
          type="text"
          inputMode="text"
          autoComplete="off"
          placeholder="e.g. 3f1c…"
          value={titleId}
          disabled={submitting}
          onChange={(event) => setTitleId(event.target.value)}
          className={inputClass}
        />
      </div>

      {AUDITED_METRICS.map(({ key, label, hint }) => (
        <div key={key} className="flex flex-col gap-1.5">
          <label htmlFor={`gt-${key}`} className="text-sm font-medium">
            {label}
          </label>
          <input
            id={`gt-${key}`}
            type="number"
            step="any"
            inputMode="decimal"
            placeholder={hint}
            value={values[key] ?? ""}
            disabled={submitting}
            onChange={(event) => setMetric(key, event.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-muted-foreground">{hint}</span>
        </div>
      ))}

      {error ? (
        <p role="alert" className="text-sm font-medium text-red-600">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={submitting}
        className={cn(
          "inline-flex items-center justify-center rounded-md bg-primary px-4 py-2",
          "text-sm font-semibold text-primary-foreground",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        {submitting ? "Running audit…" : "Run audit"}
      </button>
    </form>
  );
}
