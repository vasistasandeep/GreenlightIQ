"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import type { BacktestAuditRequest, GroundTruthMetricInput } from "@/lib/types";
import type {
  AuditableTitleOption,
  TitlesLoadStatus,
} from "@/lib/backtest/select-auditable-titles";

/**
 * GroundTruthForm (R16.1).
 *
 * Left-pane input controls for the Backtesting & Calibration Studio. The analyst
 * picks a historical title that already has a stored prediction (an Auditable
 * Title, supplied by the page from `GET /dashboard/summary`) and enters the
 * observed actual outcomes for the audited metrics (CPVH and the LTV-to-cost
 * multiple), then submits them to `POST /backtest/audit` (R11.1). The parent owns
 * the request lifecycle and the title-list fetch; this component only gathers,
 * validates, and shapes the {@link BacktestAuditRequest}.
 *
 * Replacing the former free-text identifier input with a selector means a demo
 * user never types an internal UUID and can only submit audits that can succeed
 * (an audit compares predicted vs actual, so a title without a prediction is not
 * selectable).
 *
 * Only metrics the analyst actually fills in are included - a blank field is
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
  /** Auditable titles to list in the selector (recommendation_status != null). */
  titles: AuditableTitleOption[];
  /** Load lifecycle for the title list; drives selector enable + placeholder. */
  titlesStatus: TitlesLoadStatus;
  /** Submit the shaped ground-truth request; resolves when the audit returns. */
  onSubmit: (request: BacktestAuditRequest) => void | Promise<void>;
  /** True while an audit request is in flight; disables the controls. */
  submitting?: boolean;
  className?: string;
}

export function GroundTruthForm({
  titles,
  titlesStatus,
  onSubmit,
  submitting = false,
  className,
}: GroundTruthFormProps) {
  const [selectedTitleId, setSelectedTitleId] = useState("");
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

    if (selectedTitleId === "") {
      setError("Select a historical title to audit.");
      return;
    }

    const result = buildMetrics();
    if ("error" in result) {
      setError(result.error);
      return;
    }

    await onSubmit({ title_id: selectedTitleId, metrics: result });
  }

  const controlClass =
    "w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
    "focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50";

  const titlesLoaded = titlesStatus === "loaded";
  const isEmpty = titlesStatus === "empty";
  const selectorDisabled = submitting || !titlesLoaded;
  const submitDisabled = submitting || !titlesLoaded || selectedTitleId === "";

  let placeholderLabel = "Select a title...";
  if (titlesStatus === "loading") {
    placeholderLabel = "Loading titles...";
  } else if (titlesStatus === "error") {
    placeholderLabel = "Titles unavailable";
  } else if (isEmpty) {
    placeholderLabel = "No auditable titles";
  }

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
          Pick a historical title with a stored prediction, then enter the
          observed outcomes to audit prediction accuracy.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="gt-title-id" className="text-sm font-medium">
          Historical title
        </label>
        <select
          id="gt-title-id"
          value={selectedTitleId}
          disabled={selectorDisabled}
          onChange={(event) => setSelectedTitleId(event.target.value)}
          className={controlClass}
        >
          <option value="" disabled>
            {placeholderLabel}
          </option>
          {titles.map((title) => (
            <option key={title.title_id} value={title.title_id}>
              {title.title_name}
            </option>
          ))}
        </select>
        {isEmpty ? (
          <span className="text-xs text-amber-600">
            No titles with a stored prediction are available to audit.
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">
            Only titles that already have a prediction can be audited.
          </span>
        )}
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
            className={controlClass}
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
        disabled={submitDisabled}
        className={cn(
          "inline-flex items-center justify-center rounded-md bg-primary px-4 py-2",
          "text-sm font-semibold text-primary-foreground",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        {submitting ? "Running audit..." : "Run audit"}
      </button>
    </form>
  );
}