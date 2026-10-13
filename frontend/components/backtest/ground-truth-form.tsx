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
 * Each selectable option is labeled with the title name AND a short identifier
 * suffix so duplicate names remain distinguishable. The predicted ("previous")
 * values are shown read-only beside the actual-value inputs: the predicted
 * LTV-to-cost comes from the stored valuation and is shown as soon as a title is
 * selected; the predicted CPVH is only known after the audit returns, so the page
 * passes it in once available.
 *
 * Only metrics the analyst actually fills in are included - a blank field is
 * omitted rather than sent as zero, since a genuine zero actual is excluded from
 * MAPE server-side (R11.7) and should be entered explicitly.
 */

/** The audited metrics surfaced in the form, matching the design (CPVH + LTV). */
const AUDITED_METRICS: {
  /** Local field key / predicted-value selector in this form. */
  key: "cpvh" | "ltv_to_cost_multiple";
  /** Canonical metric name the backend audit pairs with its prediction. */
  metricName: "cpvh" | "ltv_to_cost";
  label: string;
  hint: string;
}[] = [
  {
    key: "cpvh",
    metricName: "cpvh",
    label: "Actual CPVH",
    hint: "Cost per viewing hour (USD)",
  },
  {
    key: "ltv_to_cost_multiple",
    metricName: "ltv_to_cost",
    label: "Actual LTV-to-Cost multiple",
    hint: "Realized lifetime-value-to-cost ratio",
  },
];

/** Shorten a title id for the option label so duplicate names stay distinct. */
function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

/** Format a predicted value for the read-only field, or a dash when unknown. */
function formatPredicted(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : String(value);
}

export interface GroundTruthFormProps {
  /** Auditable titles to list in the selector (recommendation_status != null). */
  titles: AuditableTitleOption[];
  /** Load lifecycle for the title list; drives selector enable + placeholder. */
  titlesStatus: TitlesLoadStatus;
  /**
   * Predicted CPVH for the audited title, known only after the audit returns.
   * Null/undefined renders the read-only CPVH field as "pending until audit".
   */
  predictedCpvh?: number | null;
  /** Submit the shaped ground-truth request; resolves when the audit returns. */
  onSubmit: (request: BacktestAuditRequest) => void | Promise<void>;
  /** True while an audit request is in flight; disables the controls. */
  submitting?: boolean;
  className?: string;
}

export function GroundTruthForm({
  titles,
  titlesStatus,
  predictedCpvh,
  onSubmit,
  submitting = false,
  className,
}: GroundTruthFormProps) {
  const [selectedTitleId, setSelectedTitleId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const selectedTitle = titles.find((t) => t.title_id === selectedTitleId) ?? null;

  function setMetric(key: string, raw: string) {
    setValues((prev) => ({ ...prev, [key]: raw }));
  }

  function buildMetrics(): GroundTruthMetricInput[] | { error: string } {
    const metrics: GroundTruthMetricInput[] = [];
    for (const { key, metricName, label } of AUDITED_METRICS) {
      const raw = (values[key] ?? "").trim();
      if (raw === "") {
        continue;
      }
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) {
        return { error: `${label} must be a number.` };
      }
      metrics.push({ metric_name: metricName, actual_value: parsed });
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
  const readOnlyClass =
    "w-full rounded-md border border-border bg-muted/40 px-3 py-2 text-sm " +
    "text-muted-foreground";

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

  /** The read-only "previous" (predicted) value for a given audited metric. */
  function predictedFor(key: "cpvh" | "ltv_to_cost_multiple"): string {
    if (!selectedTitle) {
      return "Select a title";
    }
    if (key === "ltv_to_cost_multiple") {
      return formatPredicted(selectedTitle.ltv_to_cost_multiple);
    }
    // CPVH is only known once the audit has run.
    return predictedCpvh === null || predictedCpvh === undefined
      ? "Available after audit"
      : formatPredicted(predictedCpvh);
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
              {`${title.title_name} (${shortId(title.title_id)})`}
            </option>
          ))}
        </select>
        {selectedTitle ? (
          <span className="text-xs text-muted-foreground">
            ID: {selectedTitle.title_id}
          </span>
        ) : isEmpty ? (
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
          <div className="flex items-center gap-2">
            <label
              htmlFor={`gt-${key}-predicted`}
              className="text-xs text-muted-foreground"
            >
              Predicted
            </label>
            <input
              id={`gt-${key}-predicted`}
              type="text"
              readOnly
              aria-readonly="true"
              tabIndex={-1}
              value={predictedFor(key)}
              className={readOnlyClass}
            />
          </div>
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